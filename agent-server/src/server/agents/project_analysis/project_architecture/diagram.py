"""Traceable component views and deterministic Mermaid; no new repository reads."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from ....runtimes.repository.schemas import AgentContract
from .schemas import (
    ArchitecturalClaim,
    ArchitectureConnection,
    ArchitectureDiagram,
    ArchitectureReport,
)


def diagram_unit(report, reference):
    match = re.fullmatch(r"/organization/(0|[1-9][0-9]*)", reference)
    if not match or int(match[1]) >= len(report.organization):
        raise ValueError("Diagram nodes must reference existing organization units.")
    return report.organization[int(match[1])]


def diagram_connection(report, reference):
    match = re.fullmatch(r"/connections/(0|[1-9][0-9]*)/description", reference)
    if match and int(match[1]) < len(report.connections):
        return report.connections[int(match[1])]
    classification = report.closest_architecture
    if classification:
        match = re.fullmatch(
            r"/closest_architecture/observed_dependencies/(0|[1-9][0-9]*)/description",
            reference,
        )
        if match and int(match[1]) < len(classification.observed_dependencies):
            return classification.observed_dependencies[int(match[1])]
        match = re.fullmatch(
            r"/closest_architecture/observed_paths/(0|[1-9][0-9]*)/(0|[1-9][0-9]*)/description",
            reference,
        )
        if match and int(match[1]) < len(classification.observed_paths):
            path = classification.observed_paths[int(match[1])]
            if int(match[2]) < len(path):
                return path[int(match[2])]
    raise ValueError(
        "Diagram edges must reference existing connection description claims."
    )


def validate_diagram(report):
    diagram = report.diagram
    if diagram is None:
        return
    for view in diagram.views:
        validate_diagram(
            report.model_copy(
                update={"diagram": ArchitectureDiagram(**view.model_dump())}
            )
        )
    groups = {group.id for group in diagram.groups}
    nodes = {node.id: node for node in diagram.nodes}
    if len(groups) != len(diagram.groups) or len(nodes) != len(diagram.nodes):
        raise ValueError(
            "Diagram group and node IDs must be unique within their collections."
        )
    if len({node.unit_ref for node in diagram.nodes}) != len(diagram.nodes):
        raise ValueError("Diagram nodes cannot duplicate organization units.")
    for node in diagram.nodes:
        diagram_unit(report, node.unit_ref)
        if node.group_id is not None and node.group_id not in groups:
            raise ValueError("Diagram node group_id must name an existing group.")
    if any(
        not any(node.group_id == group for node in diagram.nodes) for group in groups
    ):
        raise ValueError("Diagram groups cannot be empty.")
    links = set()
    for edge in diagram.edges:
        if edge.source not in nodes or edge.target not in nodes:
            raise ValueError("Diagram edge endpoints must name existing nodes.")
        connection = diagram_connection(report, edge.claim_ref)
        source, target = (
            diagram_unit(report, nodes[key].unit_ref).name
            for key in (edge.source, edge.target)
        )
        if (source, target) != (connection.source_unit, connection.target_unit):
            raise ValueError(
                "Diagram edge direction must match the referenced connection."
            )
        identity = (edge.source, edge.target, edge.kind, edge.claim_ref)
        if identity in links:
            raise ValueError(
                "Diagram edges cannot repeat the same directed claim and kind."
            )
        links.add(identity)
    references = set()
    for annotation in diagram.deviations:
        diagram_deviation(report, annotation.deviation_ref)
        if annotation.deviation_ref in references:
            raise ValueError("A diagram view cannot repeat a deviation annotation.")
        references.add(annotation.deviation_ref)
        if len(set(annotation.node_ids)) != len(annotation.node_ids) or any(
            node_id not in nodes for node_id in annotation.node_ids
        ):
            raise ValueError(
                "Deviation annotations must reference distinct existing nodes."
            )


def diagram_deviation(report, reference):
    match = re.fullmatch(r"/deviations/(0|[1-9][0-9]*)", reference)
    if not match or int(match[1]) >= len(report.deviations):
        raise ValueError(
            "Diagram deviations must reference existing report deviations."
        )
    return report.deviations[int(match[1])]


def report_connections(report):
    """Enumerate report connection locations with their exact claim pointers."""
    links = [
        (f"/connections/{index}/description", edge)
        for index, edge in enumerate(report.connections)
    ]
    if report.closest_architecture:
        links.extend(
            (f"/closest_architecture/observed_dependencies/{index}/description", edge)
            for index, edge in enumerate(
                report.closest_architecture.observed_dependencies
            )
        )
        links.extend(
            (f"/closest_architecture/observed_paths/{index}/{step}/description", edge)
            for index, path in enumerate(report.closest_architecture.observed_paths)
            for step, edge in enumerate(path)
        )
    return links


def project_component_diagram(report):
    """A mechanical view adds no relation-type, group, or scope interpretation."""
    if not report.organization:
        return None
    names = {
        unit.name: f"unit_{index}" for index, unit in enumerate(report.organization)
    }
    selected, seen = [], set()
    for pointer, edge in report_connections(report):
        identity = (edge.source_unit, edge.target_unit, edge.description)
        if (
            edge.source_unit not in names
            or edge.target_unit not in names
            or identity in seen
        ):
            continue
        seen.add(identity)
        selected.append(
            {
                "source": names[edge.source_unit],
                "target": names[edge.target_unit],
                "claim_ref": pointer,
                "kind": "relationship",
            }
        )
    return ArchitectureDiagram(
        title="Component view of inspected responsibilities",
        scope="Inspected report responsibilities; no repository-wide completeness implied.",
        nodes=tuple(
            {"id": names[unit.name], "unit_ref": f"/organization/{index}"}
            for index, unit in enumerate(report.organization)
        ),
        edges=tuple(selected[:16]),
        limitations=(
            "Relationships reproduce report claims; invocation, static dependency, and implementation are not inferred.",
            *(
                (
                    "Additional report relationships were omitted from this bounded view.",
                )
                if len(selected) > 16
                else ()
            ),
        ),
    )


def is_projected_diagram(report):
    return report.diagram is not None and report.diagram == project_component_diagram(
        report
    )


def _node_targets(report, node):
    pointers = (node.unit_ref + "/responsibility",)
    if not is_projected_diagram(report):
        pointers += ("/diagram/scope",)
    if node.group_id is not None:
        pointers += (
            f"/diagram/groups/{next(index for index, group in enumerate(report.diagram.groups) if group.id == node.group_id)}",
        )
    if node.role != "component":
        pointers += (
            f"/diagram/nodes/{next(index for index, item in enumerate(report.diagram.nodes) if item.id == node.id)}/role",
        )
    return pointers


def _edge_targets(report, edge, index):
    pointers = (edge.claim_ref,)
    if not is_projected_diagram(report):
        pointers += ("/diagram/scope",)
        if edge.kind != "relationship" or edge.label:
            pointers += (f"/diagram/edges/{index}",)
    return pointers


@dataclass(frozen=True)
class DiagramInterpretation:
    pointer: str
    kind: str
    claim: ArchitecturalClaim
    context: dict


def diagram_interpretations(report):
    """Expose grouping, roles, mechanisms and deviation placement for review."""
    diagram = report.diagram
    if not diagram or is_projected_diagram(report):
        return ()
    result = []

    def claim(statement, scope, linked):
        certainty = (
            "supported"
            if all(item.status == "supported" for item in linked)
            else "hypothesis"
        )
        return ArchitecturalClaim(
            statement=statement,
            scope=scope,
            status=certainty,
            evidence_ids=tuple(
                dict.fromkeys(
                    identifier for item in linked for identifier in item.evidence_ids
                )
            ),
            limitations=()
            if certainty == "supported"
            else ("Diagram interpretation inherits uncertainty from linked claims.",),
        )

    units = [diagram_unit(report, node.unit_ref) for node in diagram.nodes]
    result.append(
        DiagramInterpretation(
            "/diagram/scope",
            "diagram_scope",
            claim(
                f"{diagram.view_kind.capitalize()} view {diagram.title!r} describes these responsibilities: {', '.join(unit.name for unit in units)}.",
                diagram.scope,
                [unit.responsibility for unit in units],
            ),
            {
                "unit_refs": [node.unit_ref for node in diagram.nodes],
                "limitations": diagram.limitations,
            },
        )
    )
    for index, group in enumerate(diagram.groups):
        units = [
            diagram_unit(report, node.unit_ref)
            for node in diagram.nodes
            if node.group_id == group.id
        ]
        result.append(
            DiagramInterpretation(
                f"/diagram/groups/{index}",
                "diagram_group",
                claim(
                    f"Group {group.title!r} contains these responsibilities: {', '.join(unit.name for unit in units)}.",
                    group.scope,
                    [unit.responsibility for unit in units],
                ),
                {
                    "unit_refs": [
                        node.unit_ref
                        for node in diagram.nodes
                        if node.group_id == group.id
                    ]
                },
            )
        )
    for index, edge in enumerate(diagram.edges):
        if edge.kind == "relationship" and not edge.label:
            continue
        connection = diagram_connection(report, edge.claim_ref)
        result.append(
            DiagramInterpretation(
                f"/diagram/edges/{index}",
                "diagram_relation",
                claim(
                    f"Diagram relation {edge.kind}: {connection.source_unit} -> {connection.target_unit}."
                    + (f" Mechanism: {edge.label}." if edge.label else ""),
                    diagram.scope,
                    [connection.description],
                ),
                {
                    "claim_ref": edge.claim_ref,
                    "linked_statement": connection.description.statement,
                    "linked_scope": connection.description.scope,
                    "relation_kind": edge.kind,
                    "mechanism": edge.label,
                },
            )
        )
    for index, node in enumerate(diagram.nodes):
        if node.role == "component":
            continue
        unit = diagram_unit(report, node.unit_ref)
        result.append(
            DiagramInterpretation(
                f"/diagram/nodes/{index}/role",
                "diagram_role",
                claim(
                    f"{unit.name} is represented as {node.role}.",
                    diagram.scope,
                    [unit.responsibility],
                ),
                {
                    "unit_ref": node.unit_ref,
                    "role": node.role,
                    "linked_statement": unit.responsibility.statement,
                },
            )
        )
    for index, annotation in enumerate(diagram.deviations):
        deviation = diagram_deviation(report, annotation.deviation_ref)
        affected = [
            diagram_unit(
                report,
                next(node.unit_ref for node in diagram.nodes if node.id == node_id),
            )
            for node_id in annotation.node_ids
        ]
        result.append(
            DiagramInterpretation(
                f"/diagram/deviations/{index}",
                "diagram_deviation",
                claim(
                    f"Deviation affects {', '.join(unit.name for unit in affected)}: {annotation.explanation}",
                    diagram.scope,
                    [
                        deviation.observed_decision,
                        *(unit.responsibility for unit in affected),
                    ],
                ),
                {
                    "deviation_ref": annotation.deviation_ref,
                    "observed_decision": deviation.observed_decision.statement,
                    "pattern_expectation": deviation.pattern_expectation,
                    "explanation": deviation.explanation,
                },
            )
        )
    for index, view in enumerate(diagram.views):
        local = report.model_copy(
            update={"diagram": ArchitectureDiagram(**view.model_dump())}
        )
        result.extend(
            DiagramInterpretation(
                item.pointer.replace("/diagram/", f"/diagram/views/{index}/", 1),
                item.kind,
                item.claim,
                item.context,
            )
            for item in diagram_interpretations(local)
        )
    return tuple(result)


def _label(text):
    # Numeric entities prevent labels from introducing Mermaid syntax or HTML.
    return "".join(
        character
        if character.isalnum() or character in " .,/_-:"
        else f"#{ord(character)};"
        for character in " ".join(text.split())
    )


class DiagramAnnotation(AgentContract):
    id: str
    label: str
    claim_ref: str
    review_target_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    architect_status: Literal["supported", "hypothesis", "unresolved"]
    semantic_verdict: Literal[
        "supported",
        "overstated",
        "contradicted",
        "insufficient_evidence",
        "not_reviewed",
    ]


class DiagramLegendItem(AgentContract):
    layer: Literal["architect", "semantic"]
    status: str
    color: str


class DiagramDeviationNote(AgentContract):
    id: str
    observation: str
    expectation: str
    explanation: str
    architect_status: str
    semantic_verdict: str


class RenderedArchitectureDiagram(AgentContract):
    snapshot_hash: str
    report_hash: str
    report_origin: Literal["original", "revised"]
    structure: ArchitectureDiagram
    mermaid: str
    nodes: tuple[DiagramAnnotation, ...] = ()
    edges: tuple[DiagramAnnotation, ...] = ()
    deviations: tuple[DiagramAnnotation, ...] = ()
    views: tuple["RenderedArchitectureDiagram", ...] = ()
    limitations: tuple[str, ...] = ()
    deviation_notes: tuple[DiagramDeviationNote, ...] = ()
    legend: tuple[DiagramLegendItem, ...] = ()


ARCHITECT_COLORS = {
    "supported": "#dbeafe",
    "hypothesis": "#fef3c7",
    "unresolved": "#e5e7eb",
}
SEMANTIC_COLORS = {
    "supported": "#15803d",
    "overstated": "#c2410c",
    "contradicted": "#b91c1c",
    "insufficient_evidence": "#64748b",
    "not_reviewed": "#94a3b8",
}
DIAGRAM_LEGEND = tuple(
    {"layer": "architect", "status": status, "color": color}
    for status, color in ARCHITECT_COLORS.items()
) + tuple(
    {"layer": "semantic", "status": status, "color": color}
    for status, color in SEMANTIC_COLORS.items()
)


def _semantic_verdict(reviewed, pointers):
    values = [reviewed.get(pointer, "not_reviewed") for pointer in pointers]
    for value in (
        "contradicted",
        "overstated",
        "insufficient_evidence",
        "not_reviewed",
    ):
        if value in values:
            return value
    return "supported"


def render_diagram(result, *, findings=(), report_origin="original"):
    """Backend artifact points back to the exact snapshot/report/claim IDs."""
    report = result.architecture
    if report is None or report.diagram is None:
        return None
    diagram = report.diagram
    reviewed = {finding.target_id: finding.verdict for finding in findings}
    nodes, edges, deviations = [], [], []
    for node in diagram.nodes:
        unit = diagram_unit(report, node.unit_ref)
        pointers = _node_targets(report, node)
        nodes.append(
            DiagramAnnotation(
                id=node.id,
                label=unit.name,
                claim_ref=node.unit_ref + "/responsibility",
                review_target_ids=pointers,
                evidence_ids=unit.responsibility.evidence_ids,
                architect_status=unit.responsibility.status,
                semantic_verdict=_semantic_verdict(reviewed, pointers),
            )
        )
    for index, edge in enumerate(diagram.edges):
        connection = diagram_connection(report, edge.claim_ref)
        pointers = _edge_targets(report, edge, index)
        edges.append(
            DiagramAnnotation(
                id=f"edge_{index}",
                label=edge.kind,
                claim_ref=edge.claim_ref,
                review_target_ids=pointers,
                evidence_ids=connection.description.evidence_ids,
                architect_status=connection.description.status,
                semantic_verdict=_semantic_verdict(reviewed, pointers),
            )
        )
    text = json.dumps(
        report.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    for index, annotation in enumerate(diagram.deviations):
        decision = diagram_deviation(report, annotation.deviation_ref).observed_decision
        pointers = (
            annotation.deviation_ref + "/observed_decision",
            f"/diagram/deviations/{index}",
        )
        deviations.append(
            DiagramAnnotation(
                id=f"deviation_{index}",
                label=decision.statement,
                claim_ref=annotation.deviation_ref + "/observed_decision",
                review_target_ids=pointers,
                evidence_ids=decision.evidence_ids,
                architect_status=decision.status,
                semantic_verdict=_semantic_verdict(reviewed, pointers),
            )
        )
    views = []
    for index, view in enumerate(diagram.views):
        local_report = report.model_copy(
            update={"diagram": ArchitectureDiagram(**view.model_dump())}
        )
        local_findings = tuple(
            finding.model_copy(
                update={
                    "target_id": finding.target_id.replace(
                        f"/diagram/views/{index}/", "/diagram/", 1
                    )
                }
            )
            for finding in findings
            if not finding.target_id.startswith("/diagram/")
            or finding.target_id.startswith(f"/diagram/views/{index}/")
        )
        rendered = render_diagram(
            result.model_copy(update={"architecture": local_report}),
            findings=local_findings,
            report_origin=report_origin,
        )
        annotations = {
            key: tuple(
                item.model_copy(
                    update={
                        "review_target_ids": tuple(
                            pointer.replace("/diagram/", f"/diagram/views/{index}/", 1)
                            for pointer in item.review_target_ids
                        )
                    }
                )
                for item in getattr(rendered, key)
            )
            for key in ("nodes", "edges", "deviations")
        }
        views.append(
            rendered.model_copy(
                update={
                    "report_hash": hashlib.sha256(text.encode()).hexdigest(),
                    **annotations,
                }
            )
        )
    return RenderedArchitectureDiagram(
        snapshot_hash=result.snapshot_hash,
        report_hash=hashlib.sha256(text.encode()).hexdigest(),
        report_origin=report_origin,
        structure=diagram,
        mermaid=render_mermaid(report, findings=findings),
        nodes=tuple(nodes),
        edges=tuple(edges),
        deviations=tuple(deviations),
        views=tuple(views),
        limitations=diagram.limitations,
        legend=DIAGRAM_LEGEND,
        deviation_notes=tuple(
            {
                "id": f"D{index + 1}",
                "observation": diagram_deviation(
                    report, item.deviation_ref
                ).observed_decision.statement,
                "expectation": diagram_deviation(
                    report, item.deviation_ref
                ).pattern_expectation,
                "explanation": item.explanation,
                "architect_status": deviations[index].architect_status,
                "semantic_verdict": deviations[index].semantic_verdict,
            }
            for index, item in enumerate(diagram.deviations)
        ),
    )


def render_mermaid(report: ArchitectureReport, *, findings=(), _prefix=""):
    """Render only this report's structure; caller supplies matching review findings."""
    validate_diagram(report)
    if not report.diagram:
        return None
    diagram = report.diagram
    reviewed = {finding.target_id: finding.verdict for finding in findings}

    def verdict(*pointers):
        return _semantic_verdict(reviewed, pointers)

    lines = [
        f"flowchart {diagram.direction}",
        f"  %% {_label(diagram.title)} | scope: {_label(diagram.scope)}",
        "  %% Solid = architect supported; dashed = hypothesis/unresolved. Semantic verdicts are separate.",
    ]
    ids = {node.id: f"{_prefix}n{index}" for index, node in enumerate(diagram.nodes)}

    def node_line(node, indent):
        unit = diagram_unit(report, node.unit_ref)
        label = _label(unit.name)
        shapes = {
            "actor": ('(["', '"])'),
            "interface": ('{{"', '"}}'),
            "data_store": ('[("', '")]'),
            "event_bus": ('{{"', '"}}'),
        }
        opening, closing = shapes.get(node.role, ('["', '"]'))
        return f"{indent}{ids[node.id]}{opening}{label}{closing}"

    for index, group in enumerate(diagram.groups):
        lines.append(f'  subgraph {_prefix}g{index}["{_label(group.title)}"]')
        lines.extend(
            node_line(node, "    ")
            for node in diagram.nodes
            if node.group_id == group.id
        )
        lines.append("  end")
    lines.extend(
        node_line(node, "  ") for node in diagram.nodes if node.group_id is None
    )
    for index, edge in enumerate(diagram.edges):
        connection: ArchitectureConnection = diagram_connection(report, edge.claim_ref)
        style = "-->" if connection.description.status == "supported" else "-.->"
        text = _label(edge.label or edge.kind)
        lines.append(f'  {ids[edge.source]} {style}|"{text}"| {ids[edge.target]}')
        color = SEMANTIC_COLORS[verdict(*_edge_targets(report, edge, index))]
        lines.append(f"  linkStyle {index} stroke:{color},stroke-width:2px")
    for node in diagram.nodes:
        status = diagram_unit(report, node.unit_ref).responsibility.status
        semantic = verdict(*_node_targets(report, node))
        lines.append(
            f"  style {ids[node.id]} fill:{ARCHITECT_COLORS[status]},stroke:{SEMANTIC_COLORS[semantic]},stroke-width:{1 if semantic == 'not_reviewed' else 3}px,color:#172033"
            + (",stroke-dasharray: 5 5" if semantic == "insufficient_evidence" else "")
        )
    for index, annotation in enumerate(diagram.deviations):
        deviation = diagram_deviation(report, annotation.deviation_ref)
        decision = deviation.observed_decision
        identifier = f"{_prefix}d{index}"
        semantic = verdict(
            annotation.deviation_ref + "/observed_decision",
            f"/diagram/deviations/{index}",
        )
        label = f"D{index + 1}"
        lines.append(f'  {identifier}["{label}"]')
        lines.append(
            f"  style {identifier} fill:#fff3cd,stroke:{SEMANTIC_COLORS[semantic]},color:#513c06"
            + (",stroke-dasharray: 5 5" if decision.status != "supported" else "")
        )
        for node_id in annotation.node_ids:
            lines.append(f"  {identifier} -.-> {ids[node_id]}")
    lines.extend(f"  %% Limitation: {_label(item)}" for item in diagram.limitations)
    return "\n".join(lines) + "\n"
