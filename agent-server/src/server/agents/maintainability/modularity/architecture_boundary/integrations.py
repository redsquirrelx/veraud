"""Small, bounded declaration scan; no execution, endpoint testing or API audit."""

import ast
from collections import defaultdict
from urllib.parse import urlsplit

from .....services.repository_analysis.context import create_identifier
from .....services.repository_analysis.entrypoints import (
    python_import_aliases,
    resolve_python_name,
)
from .....services.repository_analysis.source_code import (
    Language,
    Parser,
    node_text,
    tree_sitter_javascript,
    tree_sitter_typescript,
)
from .schemas import (
    BoundaryInvestigation,
    IntegrationLink,
    IntegrationPoint,
    StructuralQuery,
    StructuralSignal,
)

METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def authority(url):
    parsed = urlsplit(url)
    host = parsed.hostname
    if host in {"127.0.0.1", "0.0.0.0", "::1"}:
        host = "localhost"
    try:
        port = parsed.port
    except ValueError:
        return None
    return f"{host}:{port or (443 if parsed.scheme in {'https', 'wss'} else 80)}" if host else None


def declarations(file, project, check):
    """Reuse the existing Python/JS parsers, retaining declarations and ranges only.

    Only literal module constants, known client factories and listen declarations
    are resolved. Shadowed/conflicting constants and dynamic wiring stay unknown.
    """
    clients, endpoints, bindings = [], [], []

    def point(kind, line, end, mechanism="http", url=None, method=None):
        return IntegrationPoint(id=create_identifier("integration_" + kind, file.id, line, method, url),
            file_id=file.id, path=file.path, project_id=project, start_line=line, end_line=end,
            content_hash=file.content_hash, mechanism=mechanism, route=urlsplit(url).path if url else None,
            method=method, authority=authority(url) if url else None)

    if file.language == "python":
        tree = ast.parse(file.content)
        aliases, values, sessions = python_import_aliases(tree), {}, {}
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

        def shadowed(node, name):
            while node in parents:
                node = parents[node]
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                        *([node.args.vararg] if node.args.vararg else []), *([node.args.kwarg] if node.args.kwarg else [])]
                    if any(argument.arg == name for argument in arguments):
                        return True
                    if any(isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store) and item.id == name for item in ast.walk(node)):
                        return True
            return False

        def literal(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, (str, int)):
                return node.value
            if isinstance(node, ast.Name):
                return values.get(node.id) if not shadowed(node, node.id) else None
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                left, right = literal(node.left), literal(node.right)
                if isinstance(left, str) and isinstance(right, str):
                    return left + right
            if isinstance(node, ast.JoinedStr):
                parts = [literal(part.value) if isinstance(part, ast.FormattedValue) else literal(part) for part in node.values]
                if all(isinstance(part, str) for part in parts):
                    return "".join(parts)
            return None

        def factory(node):
            return (isinstance(node, ast.Call) and not shadowed(node, ast.unparse(node.func).split(".", 1)[0])
                and resolve_python_name(node.func, aliases) in {
                    "httpx.Client", "httpx.AsyncClient", "aiohttp.ClientSession", "requests.Session"})

        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        value = literal(node.value)
                        values[target.id] = value if target.id not in values else None
                        if factory(node.value):
                            sessions[target.id] = next((literal(k.value) for k in node.value.keywords if k.arg == "base_url"), None)
        for node in ast.walk(tree):
            check()
            if not isinstance(node, ast.Call):
                continue
            name = resolve_python_name(node.func, aliases)
            raw_receiver = ast.unparse(node.func).split(".", 1)[0]
            receiver, _, method = name.rpartition(".")
            base, scoped_session = sessions.get(receiver), False
            ancestor = node
            while ancestor in parents:
                ancestor = parents[ancestor]
                if isinstance(ancestor, (ast.With, ast.AsyncWith)):
                    for item in ancestor.items:
                        if isinstance(item.optional_vars, ast.Name) and item.optional_vars.id == raw_receiver and factory(item.context_expr):
                            scoped_session = True
                            base = next((literal(k.value) for k in item.context_expr.keywords if k.arg == "base_url"), None)
                            break
                if scoped_session:
                    break
            if (shadowed(node, raw_receiver) and not scoped_session) or (raw_receiver in aliases and raw_receiver in values):
                continue
            keywords = {k.arg: literal(k.value) for k in node.keywords}
            if (name == "uvicorn.run" and isinstance(keywords.get("port"), int)
                    and ("host" not in keywords or isinstance(keywords["host"], str))):
                host = keywords.get("host") or "localhost"
                bindings.append(point("binding", node.lineno, node.end_lineno, url=f"http://{host}:{keywords['port']}"))
            if method in METHODS and (receiver in {"requests", "httpx", "aiohttp"} or receiver in sessions or scoped_session):
                url = literal(node.args[0]) if node.args else keywords.get("url")
                if isinstance(base, str) and isinstance(url, str) and not urlsplit(url).netloc:
                    url = base.rstrip("/") + "/" + url.lstrip("/")
                clients.append(point("client", node.lineno, node.end_lineno, url=url if isinstance(url, str) else None, method=method.upper()))
            elif name in {"websockets.connect", "grpc.insecure_channel", "grpc.secure_channel"}:
                url = literal(node.args[0]) if node.args else None
                clients.append(point("client", node.lineno, node.end_lineno,
                    mechanism="websocket" if name.startswith("websockets") else "rpc", url=url if isinstance(url, str) else None))
        return clients, endpoints, bindings

    content = file.content.encode("utf-8")
    grammar = tree_sitter_javascript.language() if file.language == "javascript" else (
        tree_sitter_typescript.language_tsx() if file.path.endswith(".tsx") else tree_sitter_typescript.language_typescript())
    tree = Parser(Language(grammar)).parse(content)
    if tree.root_node.has_error:
        raise ValueError("Incomplete syntax tree")
    values, imports, sessions, servers = {}, {}, {}, set()

    def walk(node):
        yield node
        for child in node.named_children:
            yield from walk(child)

    def text(node):
        return node_text(node, content) if node else ""

    def shadowed(node, name):
        parent = node.parent
        while parent:
            parameters = parent.child_by_field_name("parameters") or parent.child_by_field_name("parameter")
            if parameters and any(item.type == "identifier" and text(item) == name for item in walk(parameters)):
                return True
            if parent.type == "statement_block":
                for statement in parent.named_children:
                    if statement.type in {"lexical_declaration", "variable_declaration"} and any(
                            text(binding.child_by_field_name("name")) == name for binding in statement.named_children):
                        return True
            parent = parent.parent
        return False

    def literal(node):
        if node is None:
            return None
        if node.type == "string":
            try:
                return ast.literal_eval(text(node))
            except (SyntaxError, ValueError):
                return None
        if node.type == "number" and text(node).isdigit():
            return int(text(node))
        if node.type == "identifier":
            return values.get(text(node)) if not shadowed(node, text(node)) else None
        if node.type == "template_string":
            parts = []
            for child in node.named_children:
                value = text(child) if child.type == "string_fragment" else (
                    literal(child.named_children[0]) if child.type == "template_substitution" and child.named_children else None)
                if not isinstance(value, str):
                    return None
                parts.append(value)
            return "".join(parts)
        return None

    def properties(node):
        return {(literal(child.child_by_field_name("key")) or text(child.child_by_field_name("key"))): child.child_by_field_name("value")
            for child in node.named_children if child.type == "pair"} if node and node.type == "object" else {}

    def call(node):
        function = node.child_by_field_name("function") or node.child_by_field_name("constructor")
        args = node.child_by_field_name("arguments")
        return text(function), args.named_children if args else []

    for node in tree.root_node.named_children:
        if node.type == "import_statement":
            module = literal(node.child_by_field_name("source"))
            for child in node.named_children:
                if child.type == "import_clause":
                    for binding in child.named_children:
                        if binding.type == "identifier":
                            imports[text(binding)] = module
                        elif binding.type == "named_imports":
                            for specifier in binding.named_children:
                                imports[text(specifier.child_by_field_name("alias") or specifier.child_by_field_name("name"))] = module
        if node.type in {"function_declaration", "class_declaration"}:
            values[text(node.child_by_field_name("name"))] = None
        declaration = node.named_children[-1] if node.type == "export_statement" and node.named_children else node
        if declaration.type in {"lexical_declaration", "variable_declaration"}:
            for binding in declaration.named_children:
                name, value = text(binding.child_by_field_name("name")), binding.child_by_field_name("value")
                values[name] = literal(value) if name not in values else None
                if value and value.type == "call_expression":
                    function, args = call(value)
                    if function.endswith(".create") and imports.get(function.rpartition(".")[0]) == "axios":
                        sessions[name] = literal(properties(args[0]).get("baseURL")) if args else None
                    if imports.get(function) in {"express", "fastify"}:
                        servers.add(name)
    for node in walk(tree.root_node):
        check()
        if node.type not in {"call_expression", "new_expression"}:
            continue
        function, args = call(node)
        receiver, _, method = function.rpartition(".")
        if shadowed(node, receiver or function):
            continue
        if method == "listen" and receiver in servers and args and isinstance(literal(args[0]), int):
            bindings.append(point("binding", node.start_point[0] + 1, node.end_point[0] + 1, url=f"http://localhost:{literal(args[0])}"))
        if receiver in servers and method in METHODS and args and isinstance(literal(args[0]), str):
            endpoints.append(point("endpoint", node.start_point[0] + 1, node.end_point[0] + 1, url=literal(args[0]), method=method.upper()))
        network = function == "fetch" and "fetch" not in values and imports.get("fetch", "undici") in {"undici", "node-fetch"}
        network |= method in METHODS and (imports.get(receiver) == "axios" or receiver in sessions)
        if network:
            url = literal(args[0]) if args else None
            base = sessions.get(receiver)
            if isinstance(base, str) and isinstance(url, str) and not urlsplit(url).netloc:
                url = base.rstrip("/") + "/" + url.lstrip("/")
            options = properties(args[1]) if len(args) > 1 else {}
            http_method = (method.upper() if method in METHODS else literal(options.get("method")) if "method" in options
                else None if len(args) > 1 and args[1].type != "object" else "GET")
            clients.append(point("client", node.start_point[0] + 1, node.end_point[0] + 1,
                url=url if isinstance(url, str) else None, method=http_method.upper() if isinstance(http_method, str) else None))
        elif (node.type == "new_expression" and function == "WebSocket" and function not in values
                and imports.get(function, "ws") == "ws"):
            url = literal(args[0]) if args else None
            clients.append(point("client", node.start_point[0] + 1, node.end_point[0] + 1,
                mechanism="websocket", url=url if isinstance(url, str) else None))
    return clients, endpoints, bindings


def discover_integrations(snapshot, files, file_projects, seeds, config, check, character_limit):
    clients, endpoints, bindings = [], [], defaultdict(list)
    diagnostics = {"scanned_files": 0, "scanned_characters": 0, "scan_omitted_files": 0,
        "parse_failures": 0, "matched_clients": 0, "ambiguous_clients": 0, "unresolved_clients": 0}
    for entry in snapshot.entrypoints:
        if entry.kind == "http_endpoint" and entry.file_id in files and entry.route:
            file = files[entry.file_id]
            evidence = next((item for item in snapshot.evidence if item.id in entry.evidence_ids), None)
            if evidence and evidence.start_line:
                endpoints.append(IntegrationPoint(id=entry.id, indexed_entrypoint_id=entry.id,
                    file_id=file.id, path=file.path, project_id=file_projects[file.id],
                    start_line=evidence.start_line, end_line=evidence.end_line or evidence.start_line,
                    content_hash=file.content_hash, mechanism="http", route=entry.route, method=entry.http_method))
    buckets = defaultdict(list)
    network_files = {r.source_id for r in snapshot.relationships
        if r.specifier.split(".")[0] in {"httpx", "requests", "aiohttp", "axios", "express", "fastify", "uvicorn", "websockets", "grpc"}}
    for file in files.values():
        if file.language in {"python", "javascript", "typescript"}:
            buckets[file_projects[file.id]].append(file)
    ordered = []
    for bucket in buckets.values():
        bucket.sort(key=lambda file: (file.id not in network_files, file.size_bytes, file.path))
    while any(buckets.values()):
        for project in sorted(buckets):
            if buckets[project]:
                ordered.append(buckets[project].pop(0))
    cap = min(config.max_integration_scan_characters, character_limit)
    for file in ordered:
        check()
        if diagnostics["scanned_files"] >= config.max_integration_scan_files or diagnostics["scanned_characters"] + len(file.content) > cap:
            diagnostics["scan_omitted_files"] += 1
            continue
        diagnostics["scanned_files"] += 1
        diagnostics["scanned_characters"] += len(file.content)
        try:
            found, exposed, origins = declarations(file, file_projects[file.id], check)
        except (SyntaxError, ValueError, RecursionError):
            diagnostics["parse_failures"] += 1
            continue
        clients.extend(found)
        endpoints.extend(exposed)
        bindings[file_projects[file.id]].extend(origin for origin in origins if origin.authority)
    # Reuse indexed endpoint IDs when parser fallback sees the same declaration.
    endpoints = list({(point.file_id, point.route, point.method): point for point in reversed(endpoints)}.values())
    groups = defaultdict(list)
    for client in clients:
        check()
        matches = [endpoint for endpoint in endpoints if endpoint.project_id != client.project_id
            and client.route and client.method and endpoint.route == client.route and endpoint.method == client.method
            and endpoint.mechanism == client.mechanism]
        bound = [endpoint for endpoint in matches if client.authority
            and client.authority in {point.authority for point in bindings[endpoint.project_id]}]
        target_projects = {endpoint.project_id for endpoint in bound}
        strong = len(target_projects) == 1
        # A foreign authority must never be connected to a local endpoint only
        # because the path happens to match. Relative routes stay ambiguous.
        plausible = bound if bound else matches if not client.authority else []
        if client.file_id not in seeds and not any(endpoint.file_id in seeds for endpoint in plausible):
            continue
        basis = ("authority_route_method" if strong else "ambiguous_destination" if bound
            else "route_only_ambiguous" if plausible else "unresolved_target")
        target = next(iter(target_projects)) if strong else None
        diagnostics["matched_clients" if strong else "ambiguous_clients" if plausible else "unresolved_clients"] += 1
        link = IntegrationLink(id=create_identifier("integration_candidate", client.id, *(p.id for p in plausible)),
            client=client, endpoints=plausible[:6], target_project_id=target, match_basis=basis,
            binding_points=[point for project in target_projects for point in bindings[project] if point.authority == client.authority][:6],
            status="structural_candidate" if strong else "ambiguous")
        route_group = "/" + (client.route or "").strip("/").split("/")[0]
        key = (client.project_id, target, client.mechanism, client.authority, route_group if strong else client.file_id)
        groups[key].append(link)
    tasks = []
    for (source, target, mechanism, origin, _), links in groups.items():
        links = links[:6]
        paths = list(dict.fromkeys(point.path for link in links for point in [link.client, *link.endpoints, *link.binding_points]))
        projects = [source, *([target] if target else [])]
        tasks.append(BoundaryInvestigation(id=create_identifier("investigation_integration", snapshot.repository.snapshot_hash,
                *(link.id for link in links)), priority="medium" if target else "low", scope=paths,
            scope_kind="inter_application" if target else "integration_discovery", project_ids=projects,
            structural_signal=StructuralSignal(kind="integration", basis="corroborated" if target else "inferred",
                observed=[f"{len(links)} {mechanism} client declaration(s); origin={origin}; destination project={target}; match={links[0].match_basis}.",
                    "Methods, routes and code-level listener bindings are static observations, not a confirmed deployment connection."],
                inference="Investigate whether the integration follows an identifiable interface boundary; legitimate communication is not a defect. Unknown targets and route-only matches remain unresolved.",
                integration_links=links, entrypoint_ids=[p.indexed_entrypoint_id for link in links for p in link.endpoints if p.indexed_entrypoint_id]),
            question=f"Does the {mechanism} integration from {paths[0]} use the intended code-supported interface, or does it bypass an identifiable integration boundary?",
            evidence_needed=["Client construction, destination binding and exposed entrypoints",
                "Code declarations establishing the integration interface and allowed access paths",
                "Mount prefixes, dynamic configuration and legitimate alternative access paths"],
            investigation_strategy=[StructuralQuery(tool="find_symbols", arguments={"file_path": path, "limit": 10}) for path in paths[:3]],
            completion_condition="The integration boundary and access path are examined, or unresolved destination/wiring limitations are documented; functional API correctness and change impact are outside scope."))
    diagnostics["indexed_endpoints"] = sum(point.indexed_entrypoint_id is not None for point in endpoints)
    diagnostics["discovered_endpoints"] = len(endpoints)
    diagnostics["listener_bindings"] = sum(len(points) for points in bindings.values())
    diagnostics["generated_opportunities"] = len(tasks)
    diagnostics["by_project"] = [{"project_id": project,
        "client_declarations": sum(point.project_id == project for point in clients),
        "exposed_endpoints": sum(point.project_id == project for point in endpoints),
        "listener_bindings": len(bindings[project]),
        "integration_opportunities": sum(project in task.project_ids for task in tasks)}
        for project in sorted({file_projects[file.id] for file in files.values()})]
    return tasks, diagnostics
