"""Static framework, application and CLI entrypoints, with explicit evidence."""

import ast
import posixpath
import re

from .context import AnalysisContext, create_identifier
from .schemas import EntrypointRecord
from .source_code import node_text

HTTP_METHOD_NAMES = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options"}
)
APPLICATION_FACTORIES = frozenset(
    {
        "fastapi.FastAPI",
        "flask.Flask",
        "starlette.applications.Starlette",
        "typer.Typer",
    }
)


def python_import_aliases(syntax_tree: ast.AST) -> dict[str, str]:
    aliases = {}
    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Import):
            for imported_name in node.names:
                aliases[imported_name.asname or imported_name.name.split(".", 1)[0]] = (
                    imported_name.name
                    if imported_name.asname
                    else imported_name.name.split(".", 1)[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            for imported_name in node.names:
                aliases[imported_name.asname or imported_name.name] = (
                    f"{node.module}.{imported_name.name}"
                )
    return aliases


def resolve_python_name(expression: ast.AST, aliases: dict[str, str]) -> str:
    expression_name = ast.unparse(expression)
    first_name, separator, remaining = expression_name.partition(".")
    return aliases.get(first_name, first_name) + (
        separator + remaining if separator else ""
    )


def literal_string(expression: ast.AST | None) -> str | None:
    return (
        expression.value
        if isinstance(expression, ast.Constant) and isinstance(expression.value, str)
        else None
    )


def register_entrypoint(
    context, source_file, kind, name, target, start_line, end_line=None, **details
):
    evidence_id = context.add_evidence(
        source_file, "source_entrypoint", start_line, end_line or start_line
    )
    context.entrypoints.append(
        EntrypointRecord(
            id=create_identifier(
                "entrypoint",
                source_file.path,
                kind,
                name,
                start_line,
                details.get("http_method"),
            ),
            project_id=source_file.project_id,
            kind=kind,
            name=name,
            target=target,
            file_id=source_file.id,
            detection="observed",
            evidence_ids=(evidence_id,),
            **details,
        )
    )


def extract_python_entrypoints(context: AnalysisContext):
    for file_path, syntax_tree in context.python_trees.items():
        source_file = context.files[file_path]
        aliases = python_import_aliases(syntax_tree)
        router_names = set()
        for node in ast.walk(syntax_tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                if not isinstance(value, ast.Call):
                    continue
                constructor = resolve_python_name(value.func, aliases)
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    if constructor in APPLICATION_FACTORIES:
                        register_entrypoint(
                            context,
                            source_file,
                            "cli" if constructor == "typer.Typer" else "application",
                            target.id,
                            f"{file_path}:{target.id}",
                            node.lineno,
                            node.end_lineno,
                        )
                    if (
                        constructor in APPLICATION_FACTORIES
                        or constructor == "fastapi.APIRouter"
                    ):
                        router_names.add(target.id)
            if (
                isinstance(node, ast.If)
                and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__"
                and any(
                    literal_string(comparator) == "__main__"
                    for comparator in node.test.comparators
                )
                and any(isinstance(operator, ast.Eq) for operator in node.test.ops)
            ):
                register_entrypoint(
                    context,
                    source_file,
                    "application",
                    "__main__",
                    file_path,
                    node.lineno,
                    node.end_lineno,
                )
        for node in ast.walk(syntax_tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol = next(
                    (
                        candidate
                        for candidate in context.symbols
                        if candidate.file_id == source_file.id
                        and candidate.name == node.name
                        and candidate.start_line <= node.lineno <= candidate.end_line
                    ),
                    None,
                )
                for decorator in node.decorator_list:
                    decorator_function = (
                        decorator.func if isinstance(decorator, ast.Call) else decorator
                    )
                    decorator_name = resolve_python_name(decorator_function, aliases)
                    receiver, _, method_name = ast.unparse(
                        decorator_function
                    ).rpartition(".")
                    if receiver in router_names and method_name in HTTP_METHOD_NAMES | {
                        "route",
                        "api_route",
                    }:
                        route = (
                            literal_string(decorator.args[0])
                            if isinstance(decorator, ast.Call) and decorator.args
                            else None
                        )
                        methods = (
                            [method_name.upper()]
                            if method_name in HTTP_METHOD_NAMES
                            else ["GET"]
                        )
                        if isinstance(decorator, ast.Call):
                            for keyword in decorator.keywords:
                                if keyword.arg == "methods" and isinstance(
                                    keyword.value, (ast.List, ast.Tuple)
                                ):
                                    methods = [
                                        literal_string(element)
                                        for element in keyword.value.elts
                                        if literal_string(element)
                                    ]
                        for method in methods:
                            register_entrypoint(
                                context,
                                source_file,
                                "http_endpoint",
                                node.name,
                                f"{file_path}:{node.name}",
                                decorator.lineno,
                                decorator.end_lineno,
                                symbol_id=symbol.id if symbol else None,
                                http_method=method.upper(),
                                route=route,
                                limitations=(
                                    "Route is local to this router; mount prefixes are not composed.",
                                )
                                if route
                                else (
                                    "Route expression could not be resolved statically.",
                                ),
                            )
                    elif decorator_name in ("click.command", "click.group"):
                        register_entrypoint(
                            context,
                            source_file,
                            "cli",
                            node.name,
                            f"{file_path}:{node.name}",
                            decorator.lineno,
                            decorator.end_lineno,
                            symbol_id=symbol.id if symbol else None,
                        )
            elif (
                isinstance(node, ast.Call)
                and resolve_python_name(node.func, aliases)
                in ("django.urls.path", "django.urls.re_path")
                and len(node.args) >= 2
            ):
                route = literal_string(node.args[0])
                target = ast.unparse(node.args[1])
                is_mount = (
                    isinstance(node.args[1], ast.Call)
                    and resolve_python_name(node.args[1].func, aliases)
                    == "django.urls.include"
                )
                register_entrypoint(
                    context,
                    source_file,
                    "service" if is_mount else "http_endpoint",
                    target,
                    target,
                    node.lineno,
                    node.end_lineno,
                    route=route,
                    limitations=(
                        "Django route pattern; HTTP methods and parent mount prefixes are not resolved.",
                    ),
                )
        if posixpath.basename(file_path) in (
            "wsgi.py",
            "asgi.py",
            "__main__.py",
            "main.py",
        ):
            evidence_id = context.add_evidence(
                source_file, "python_entrypoint_convention"
            )
            context.entrypoints.append(
                EntrypointRecord(
                    id=create_identifier("entrypoint", file_path, "convention"),
                    project_id=source_file.project_id,
                    kind="application",
                    name=posixpath.basename(file_path),
                    target=file_path,
                    file_id=source_file.id,
                    detection="inferred",
                    evidence_ids=(evidence_id,),
                    limitations=("Detected by framework/package filename convention.",),
                )
            )
        if (
            posixpath.basename(file_path) == "__init__.py"
            and source_file.content.strip()
        ):
            evidence_id = context.add_evidence(source_file, "python_package_api")
            context.entrypoints.append(
                EntrypointRecord(
                    id=create_identifier("entrypoint", file_path, "public_api"),
                    project_id=source_file.project_id,
                    kind="public_api",
                    name=posixpath.dirname(file_path),
                    target=file_path,
                    file_id=source_file.id,
                    detection="inferred",
                    evidence_ids=(evidence_id,),
                    limitations=(
                        "Nonempty package initializer; public API stability is not assessed.",
                    ),
                )
            )


def javascript_import_aliases(syntax_tree, content_bytes):
    aliases = {}
    for node in syntax_tree.root_node.named_children:
        if node.type != "import_statement":
            continue
        source_node = node.child_by_field_name("source")
        if source_node is None:
            continue
        module_name = node_text(source_node, content_bytes).strip("\"'")
        pending_nodes = list(node.named_children)
        while pending_nodes:
            child = pending_nodes.pop()
            if child.type == "import_specifier":
                imported_name = child.child_by_field_name("name")
                alias_name = child.child_by_field_name("alias") or imported_name
                if imported_name is not None:
                    aliases[node_text(alias_name, content_bytes)] = (
                        f"{module_name}.{node_text(imported_name, content_bytes)}"
                    )
            pending_nodes.extend(child.named_children)
    return aliases


def decorator_string_argument(decorator: str) -> str | None:
    match = re.match(r"\w+\(\s*(['\"])(.*?)\1", decorator)
    return match.group(2) if match else None


def extract_javascript_entrypoints(context: AnalysisContext):
    for file_path, syntax_tree in context.javascript_trees.items():
        source_file = context.files[file_path]
        content_bytes = source_file.content.encode()
        aliases = javascript_import_aliases(syntax_tree, content_bytes)
        pending_nodes = [syntax_tree.root_node]
        while pending_nodes:
            node = pending_nodes.pop()
            pending_nodes.extend(reversed(node.named_children))
            if node.type != "call_expression":
                continue
            function_node = node.child_by_field_name("function")
            if function_node is None:
                continue
            function_name = node_text(function_node, content_bytes)
            receiver, _, method_name = function_name.rpartition(".")
            if aliases.get(receiver) == "@nestjs/core.NestFactory" and method_name in (
                "create",
                "createMicroservice",
            ):
                register_entrypoint(
                    context,
                    source_file,
                    "service",
                    "NestJS bootstrap",
                    file_path,
                    node.start_point[0] + 1,
                    node.end_point[0] + 1,
                )
        for symbol in (
            symbol for symbol in context.symbols if symbol.file_id == source_file.id
        ):
            parent = next(
                (
                    parent
                    for parent in context.symbols
                    if parent.id == symbol.parent_symbol_id
                ),
                None,
            )
            controller_prefix = ""
            if parent:
                for decorator in parent.decorators:
                    decorator_name = decorator.split("(", 1)[0]
                    if aliases.get(decorator_name) == "@nestjs/common.Controller":
                        controller_prefix = decorator_string_argument(decorator) or ""
            for decorator in symbol.decorators:
                decorator_name = decorator.split("(", 1)[0]
                canonical_name = aliases.get(decorator_name, "")
                method = canonical_name.removeprefix("@nestjs/common.").lower()
                if (
                    canonical_name.startswith("@nestjs/common.")
                    and method in HTTP_METHOD_NAMES
                ):
                    local_route = decorator_string_argument(decorator)
                    route = "/" + "/".join(
                        part.strip("/")
                        for part in (controller_prefix, local_route or "")
                        if part.strip("/")
                    )
                    register_entrypoint(
                        context,
                        source_file,
                        "http_endpoint",
                        symbol.qualified_name,
                        f"{file_path}:{symbol.qualified_name}",
                        symbol.start_line,
                        symbol.end_line,
                        symbol_id=symbol.id,
                        http_method=method.upper(),
                        route=route,
                        limitations=(
                            "Global NestJS prefixes and runtime configuration are not resolved.",
                        ),
                    )
        uses_next = any(
            dependency.project_id == source_file.project_id
            and dependency.name == "next"
            for dependency in context.dependencies
        )
        if uses_next:
            project = context.project_for_path(file_path)
            relative_path = (
                file_path if project.path == "." else file_path[len(project.path) + 1 :]
            )
            relative_path = relative_path.removeprefix("src/")
            if (
                relative_path.startswith("app/")
                and posixpath.basename(relative_path).split(".")[0]
                in ("page", "layout", "route")
                or relative_path.startswith("pages/")
                and relative_path.endswith((".js", ".jsx", ".ts", ".tsx"))
            ):
                evidence_id = context.add_evidence(
                    source_file, "nextjs_entrypoint_convention"
                )
                context.entrypoints.append(
                    EntrypointRecord(
                        id=create_identifier("entrypoint", file_path, "nextjs"),
                        project_id=source_file.project_id,
                        kind="framework_page",
                        name=relative_path,
                        target=file_path,
                        file_id=source_file.id,
                        detection="inferred",
                        evidence_ids=(evidence_id,),
                        limitations=(
                            "Framework entry file; deployment mode and final URL are not inferred.",
                        ),
                    )
                )


def extract_entrypoints(context: AnalysisContext):
    extract_python_entrypoints(context)
    extract_javascript_entrypoints(context)
