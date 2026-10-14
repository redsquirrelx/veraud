"""Describe structural signals without claiming architectural compliance."""

import posixpath
import re

from .context import AnalysisContext, create_identifier
from .schemas import ArchitectureSignal, RelationshipRecord

LAYER_DIRECTORY_NAMES = frozenset(
    {
        "domain",
        "application",
        "infrastructure",
        "presentation",
        "controllers",
        "services",
        "repositories",
        "adapters",
        "ports",
        "models",
        "views",
    }
)


def find_import_cycles(context: AnalysisContext) -> list[tuple[str, ...]]:
    """Iterative strongly connected components, avoiding recursion on large repos."""
    file_ids = {source_file.id for source_file in context.files.values()}
    graph: dict[str, set[str]] = {}
    reverse_graph: dict[str, set[str]] = {}
    for relationship in context.relationships:
        if (
            relationship.source_id not in file_ids
            or relationship.target_id not in file_ids
        ):
            continue
        graph.setdefault(relationship.source_id, set()).add(relationship.target_id)
        graph.setdefault(relationship.target_id, set())
        reverse_graph.setdefault(relationship.target_id, set()).add(
            relationship.source_id
        )
        reverse_graph.setdefault(relationship.source_id, set())
    visited = set()
    finish_order = []
    for origin in sorted(graph):
        if origin in visited:
            continue
        pending = [(origin, False)]
        while pending:
            node, expanded = pending.pop()
            if expanded:
                finish_order.append(node)
            elif node not in visited:
                visited.add(node)
                pending.append((node, True))
                pending.extend(
                    (target, False)
                    for target in sorted(graph[node], reverse=True)
                    if target not in visited
                )
    visited.clear()
    cycles = []
    for origin in reversed(finish_order):
        if origin in visited:
            continue
        component = set()
        pending = [origin]
        while pending:
            node = pending.pop()
            if node in visited:
                continue
            visited.add(node)
            component.add(node)
            pending.extend(sorted(reverse_graph[node] - visited))
        if len(component) > 1 or origin in graph[origin]:
            cycles.append(tuple(sorted(component)))
    return sorted(cycles)


def extract_architecture_signals(context: AnalysisContext, directories):
    for directory in directories:
        if posixpath.basename(directory.path).lower() not in LAYER_DIRECTORY_NAMES:
            continue
        member_files = [
            source_file
            for source_file in context.processed_files()
            if source_file.project_id == directory.project_id
            and source_file.path.startswith(directory.path + "/")
            and source_file.language in ("python", "javascript", "typescript")
        ]
        if not member_files:
            continue
        evidence_ids = tuple(
            context.add_evidence(source_file, "candidate_layer_directory")
            for source_file in member_files
        )
        context.architecture_signals.append(
            ArchitectureSignal(
                id=create_identifier("architecture", directory.id, "layer"),
                project_id=directory.project_id,
                kind="candidate_layer",
                name=directory.path,
                description="Source files grouped under a conventional architectural directory name.",
                detection="inferred",
                entity_ids=(
                    directory.id,
                    *(source_file.id for source_file in member_files),
                ),
                evidence_ids=evidence_ids,
                limitations=(
                    "Directory names do not prove architectural boundaries or dependency rules.",
                ),
            )
        )
    class_symbols = [
        symbol for symbol in context.symbols if symbol.kind in ("class", "interface")
    ]
    for symbol in class_symbols:
        imported_files = {
            relationship.target_id
            for relationship in context.relationships
            if relationship.source_id == symbol.file_id
            and relationship.resolution == "internal"
        }
        for base_name in symbol.base_names:
            simple_name = re.split(r"[<\[]", base_name)[0].rsplit(".", 1)[-1].strip()
            candidates = [
                base
                for base in class_symbols
                if base.name == simple_name
                and (base.file_id == symbol.file_id or base.file_id in imported_files)
            ]
            if len(candidates) != 1:
                continue
            base = candidates[0]
            relationship = RelationshipRecord(
                id=create_identifier("relationship", "inherits", symbol.id, base.id),
                project_id=symbol.project_id,
                source_id=symbol.id,
                target_id=base.id,
                kind="inherits",
                specifier=base_name,
                resolution="internal",
                evidence_ids=symbol.evidence_ids,
            )
            context.relationships.append(relationship)
            if "repository" in base.name.lower() or base.name.lower().endswith("port"):
                context.architecture_signals.append(
                    ArchitectureSignal(
                        id=create_identifier("architecture", symbol.id, base.id),
                        project_id=symbol.project_id,
                        kind="repository_or_port_implementation",
                        name=symbol.qualified_name,
                        description=f"{symbol.name} inherits or implements the locally resolved {base.name} type.",
                        detection="observed",
                        entity_ids=(symbol.id, base.id),
                        evidence_ids=symbol.evidence_ids + base.evidence_ids,
                        limitations=(
                            "Static inheritance does not establish runtime wiring or architectural compliance.",
                        ),
                    )
                )
        for decorator in symbol.decorators:
            if decorator.startswith("Module("):
                context.architecture_signals.append(
                    ArchitectureSignal(
                        id=create_identifier("architecture", symbol.id, "module"),
                        project_id=symbol.project_id,
                        kind="decorated_module",
                        name=symbol.qualified_name,
                        description="A class has a Module decorator.",
                        detection="observed",
                        entity_ids=(symbol.id,),
                        evidence_ids=symbol.evidence_ids,
                        limitations=(
                            "Decorator identity and runtime provider wiring require further analysis.",
                        ),
                    )
                )
    for component in find_import_cycles(context):
        source_file = context.source_file_for_id(component[0])
        evidence_ids = tuple(
            sorted(
                {
                    evidence_id
                    for relationship in context.relationships
                    if relationship.source_id in component
                    and relationship.target_id in component
                    for evidence_id in relationship.evidence_ids
                }
            )
        )
        context.architecture_signals.append(
            ArchitectureSignal(
                id=create_identifier("architecture", "import_cycle", *component),
                project_id=source_file.project_id,
                kind="import_cycle",
                name="Circular import component",
                description="Resolved file imports form a strongly connected component.",
                detection="observed",
                entity_ids=component,
                evidence_ids=evidence_ids,
                limitations=(
                    "Includes conditional/type-only imports; this does not prove a runtime failure.",
                ),
            )
        )
    for configuration_path, configuration in context.configuration.items():
        if configuration.get("output") == "export":
            source_file = context.files[configuration_path]
            evidence_id = context.add_evidence(
                source_file, "static_export_configuration", configuration_key="output"
            )
            context.architecture_signals.append(
                ArchitectureSignal(
                    id=create_identifier(
                        "architecture", source_file.id, "static_export"
                    ),
                    project_id=source_file.project_id,
                    kind="static_export",
                    name="Static export configuration",
                    description="Configuration declares output=export.",
                    detection="declared",
                    entity_ids=(source_file.id,),
                    evidence_ids=(evidence_id,),
                )
            )
