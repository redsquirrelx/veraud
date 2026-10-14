"""Resolve imports using only the snapshot, not packages installed on this host."""

import posixpath
import sys

from ..dependency_graph.extractors import (
    PythonImportExtractor,
    TypeScriptImportExtractor,
)
from .context import AnalysisContext, create_identifier, normalize_dependency_name
from .manifests import register_dependency
from .schemas import RelationshipRecord

JAVASCRIPT_EXTENSIONS = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
NODE_BUILTINS = frozenset(
    {
        "assert",
        "async_hooks",
        "buffer",
        "child_process",
        "cluster",
        "console",
        "crypto",
        "dgram",
        "diagnostics_channel",
        "dns",
        "events",
        "fs",
        "http",
        "http2",
        "https",
        "module",
        "net",
        "os",
        "path",
        "perf_hooks",
        "process",
        "querystring",
        "readline",
        "stream",
        "string_decoder",
        "timers",
        "tls",
        "tty",
        "url",
        "util",
        "v8",
        "vm",
        "wasi",
        "worker_threads",
        "zlib",
        "test",
    }
)
PYTHON_IMPORT_DISTRIBUTIONS = {
    "yaml": "pyyaml",
    "PIL": "pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "google.genai": "google-genai",
}


def join_repository_path(directory: str, relative_path: str) -> str | None:
    joined_path = posixpath.normpath(
        posixpath.join("" if directory == "." else directory, relative_path)
    )
    if joined_path == ".." or joined_path.startswith(("../", "/")):
        return None
    return joined_path


def python_target(context: AnalysisContext, module_path: str):
    for candidate_path in (module_path + ".py", module_path + "/__init__.py"):
        source_file = context.files.get(candidate_path)
        if source_file is not None and source_file.status == "processed":
            return source_file
    return None


def resolve_python_import(context: AnalysisContext, source_file, import_record):
    specifier = import_record.specifier.lstrip(".")
    if import_record.reason == "dynamic_expr":
        return None
    if import_record.level:
        package_directory = posixpath.dirname(source_file.path)
        for _ in range(import_record.level - 1):
            if not package_directory:
                return None
            package_directory = posixpath.dirname(package_directory)
        module_path = join_repository_path(
            package_directory, specifier.replace(".", "/")
        )
        if not specifier:
            for imported_name in import_record.names:
                target = python_target(
                    context,
                    f"{module_path}/{imported_name}"
                    if module_path and module_path != "."
                    else imported_name,
                )
                if target is not None:
                    return target
        target = python_target(context, module_path) if module_path else None
        if target is not None:
            return target
        for imported_name in import_record.names:
            target = python_target(
                context,
                f"{module_path}/{imported_name}" if module_path else imported_name,
            )
            if target is not None:
                return target
        return None
    project = context.project_for_path(source_file.path)
    import_roots = [project.path, join_repository_path(project.path, "src"), "."]
    # A root pointing at an importable package also permits sibling absolute imports.
    import_roots.append(posixpath.dirname(source_file.path) or ".")
    for import_root in dict.fromkeys(import_roots):
        module_path = join_repository_path(import_root, specifier.replace(".", "/"))
        target = python_target(context, module_path) if module_path else None
        if target is not None:
            return target
    return None


def javascript_target(context: AnalysisContext, target_path: str | None):
    if target_path is None:
        return None
    candidates = [target_path]
    target_stem = target_path
    for extension in JAVASCRIPT_EXTENSIONS:
        if target_path.endswith(extension):
            target_stem = target_path[: -len(extension)]
            break
    candidates.extend(target_stem + extension for extension in JAVASCRIPT_EXTENSIONS)
    candidates.extend(
        target_path + "/index" + extension for extension in JAVASCRIPT_EXTENSIONS
    )
    for candidate in candidates:
        source_file = context.files.get(candidate)
        if source_file is not None and source_file.status == "processed":
            return source_file
    return None


def compiler_options(context: AnalysisContext, configuration_path: str, visited=()):
    if configuration_path in visited:
        context.add_issue(
            configuration_path,
            "configuration_cycle",
            "TypeScript extends chain contains a cycle.",
        )
        return {}, posixpath.dirname(configuration_path)
    configuration = context.configuration.get(configuration_path, {})
    options = {}
    base_directory = posixpath.dirname(configuration_path)
    parent = configuration.get("extends")
    if isinstance(parent, str):
        parent_path = join_repository_path(base_directory, parent)
        if (
            parent_path not in context.configuration
            and parent_path
            and not parent_path.endswith(".json")
        ):
            parent_path += ".json"
        if parent_path in context.configuration:
            options, base_directory = compiler_options(
                context, parent_path, (*visited, configuration_path)
            )
        else:
            context.add_issue(
                configuration_path,
                "unresolved_configuration",
                "TypeScript extends target is not present in the retained inventory.",
            )
    own_options = configuration.get("compilerOptions", {})
    if "baseUrl" in own_options:
        base_directory = (
            join_repository_path(
                posixpath.dirname(configuration_path), own_options["baseUrl"]
            )
            or "."
        )
    elif "paths" in own_options and not options:
        base_directory = posixpath.dirname(configuration_path)
    return {**options, **own_options}, base_directory


def resolve_javascript_import(context: AnalysisContext, source_file, specifier: str):
    if specifier.startswith("."):
        return javascript_target(
            context,
            join_repository_path(posixpath.dirname(source_file.path), specifier),
        )
    configurations = [
        path
        for path in context.configuration
        if posixpath.basename(path) in ("tsconfig.json", "jsconfig.json")
        and (
            not posixpath.dirname(path)
            or source_file.path.startswith(posixpath.dirname(path) + "/")
        )
    ]
    for configuration_path in sorted(
        configurations, key=lambda path: (-len(posixpath.dirname(path)), path)
    ):
        options, base_directory = compiler_options(context, configuration_path)
        for alias, targets in sorted(options.get("paths", {}).items()):
            prefix, separator, suffix = alias.partition("*")
            matches = (
                specifier == alias
                if not separator
                else specifier.startswith(prefix) and specifier.endswith(suffix)
            )
            if not matches:
                continue
            wildcard = (
                specifier[
                    len(prefix) : len(specifier) - len(suffix) if suffix else None
                ]
                if separator
                else ""
            )
            for target_pattern in targets:
                target = javascript_target(
                    context,
                    join_repository_path(
                        base_directory, target_pattern.replace("*", wildcard)
                    ),
                )
                if target is not None:
                    return target
        if options.get("baseUrl") is not None:
            target = javascript_target(
                context, join_repository_path(base_directory, specifier)
            )
            if target is not None:
                return target
    for project in context.projects:
        if specifier != project.name and not specifier.startswith(project.name + "/"):
            continue
        subpath = specifier[len(project.name) :].lstrip("/")
        if subpath:
            target = javascript_target(
                context, join_repository_path(project.path, subpath)
            )
            if target:
                return target
        for manifest_path in project.manifest_paths:
            package = context.configuration.get(manifest_path, {})
            for field in ("source", "module", "main"):
                if isinstance(package.get(field), str):
                    target = javascript_target(
                        context, join_repository_path(project.path, package[field])
                    )
                    if target:
                        return target
    return None


def declared_dependency_for_import(context, source_file, specifier: str):
    ecosystem = "python" if source_file.language == "python" else "node"
    if ecosystem == "python":
        import_name = specifier.split(".", 1)[0]
        distribution_name = next(
            (
                distribution
                for import_prefix, distribution in PYTHON_IMPORT_DISTRIBUTIONS.items()
                if specifier == import_prefix
                or specifier.startswith(import_prefix + ".")
            ),
            import_name,
        )
        dependency_name = normalize_dependency_name(distribution_name, ecosystem)
    else:
        dependency_name = (
            "/".join(specifier.split("/")[:2])
            if specifier.startswith("@")
            else specifier.split("/", 1)[0]
        )
    candidates = [
        dependency
        for dependency in context.dependencies
        if dependency.project_id == source_file.project_id
        and dependency.ecosystem == ecosystem
        and dependency.name == dependency_name
    ]
    return next(
        (dependency for dependency in candidates if dependency.scope != "transitive"),
        candidates[0] if candidates else None,
    )


def extract_import_relationships(context: AnalysisContext):
    extractors = {
        "python": PythonImportExtractor(),
        "javascript": TypeScriptImportExtractor(),
        "typescript": TypeScriptImportExtractor(),
    }
    for source_file in context.processed_files():
        extractor = extractors.get(source_file.language)
        if (
            extractor is None
            or source_file.path not in context.python_trees
            and source_file.path not in context.javascript_trees
        ):
            continue
        for import_record in extractor.extract(source_file.content):
            target = (
                resolve_python_import(context, source_file, import_record)
                if source_file.language == "python"
                else resolve_javascript_import(
                    context, source_file, import_record.specifier
                )
            )
            # Existing Python extractor emits synthetic submodule probes; only real local matches survive.
            is_submodule_probe = (
                source_file.language == "python"
                and import_record.is_from
                and not import_record.names
                and import_record.level == 0
                and "." in import_record.specifier
                and import_record.kind != "dynamic"
            )
            if is_submodule_probe and target is None:
                continue
            evidence_id = context.add_evidence(
                source_file, "source_import", import_record.line, import_record.line
            )
            dependency = declared_dependency_for_import(
                context, source_file, import_record.specifier
            )
            if import_record.reason == "dynamic_expr":
                resolution = "dynamic"
            elif target is not None:
                resolution = "internal"
            elif (
                source_file.language == "python"
                and import_record.level == 0
                and import_record.specifier.split(".", 1)[0] in sys.stdlib_module_names
            ) or (
                source_file.language != "python"
                and (
                    import_record.specifier.startswith("node:")
                    or import_record.specifier.split("/", 1)[0] in NODE_BUILTINS
                )
            ):
                resolution = "builtin"
            elif dependency is not None:
                resolution = "external"
            else:
                resolution = "unresolved"
            context.relationships.append(
                RelationshipRecord(
                    id=create_identifier(
                        "relationship",
                        source_file.id,
                        import_record.line,
                        import_record.kind,
                        import_record.specifier,
                        target.id if target else None,
                    ),
                    project_id=source_file.project_id,
                    source_id=source_file.id,
                    target_id=target.id
                    if target
                    else dependency.id
                    if dependency and resolution == "external"
                    else None,
                    kind=import_record.kind,
                    specifier=import_record.specifier,
                    resolution=resolution,
                    evidence_ids=(evidence_id,),
                )
            )
            if resolution == "unresolved" and not import_record.level:
                # Preserve use without asserting that an undeclared import is definitely external.
                import_name = (
                    import_record.specifier.split(".", 1)[0]
                    if source_file.language == "python"
                    else "/".join(import_record.specifier.split("/")[:2])
                    if import_record.specifier.startswith("@")
                    else import_record.specifier.split("/", 1)[0]
                )
                if not import_name.startswith((".", "/", "<")):
                    register_dependency(
                        context,
                        source_file.project_id,
                        import_name,
                        "python" if source_file.language == "python" else "node",
                        "unresolved_import",
                        "observed",
                        evidence_id,
                    )
    for symbol in context.symbols:
        context.relationships.append(
            RelationshipRecord(
                id=create_identifier(
                    "relationship", "contains", symbol.file_id, symbol.id
                ),
                project_id=symbol.project_id,
                source_id=symbol.parent_symbol_id or symbol.file_id,
                target_id=symbol.id,
                kind="contains",
                specifier=symbol.qualified_name,
                resolution="internal",
                evidence_ids=symbol.evidence_ids,
            )
        )
