"""Traceable component views and deterministic Mermaid; no new repository reads."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from ..repository_runtime.schemas import AgentContract
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
    return pointers


def _edge_targets(report, edge, index):
    pointers = (edge.claim_ref,)
    if not is_projected_diagram(report):
        pointers += ("/diagram/scope",)
        if edge.kind != "relationship":
            pointers += (f"/diagram/edges/{index}",)
    return pointers


@dataclass(frozen=True)
class DiagramInterpretation:
    pointer: str
    kind: str
    claim: ArchitecturalClaim
    context: dict


def diagram_interpretations(report):
    """Only new grouping/type/scope interpretations need extra semantic targets."""
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
                f"Component view {diagram.title!r} describes these responsibilities: {', '.join(unit.name for unit in units)}.",
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
        if edge.kind == "relationship":
            continue
        connection = diagram_connection(report, edge.claim_ref)
        result.append(
            DiagramInterpretation(
                f"/diagram/edges/{index}",
                "diagram_relation",
                claim(
                    f"Diagram relation {edge.kind}: {connection.source_unit} -> {connection.target_unit}.",
                    diagram.scope,
                    [connection.description],
                ),
                {
                    "claim_ref": edge.claim_ref,
                    "linked_statement": connection.description.statement,
                    "linked_scope": connection.description.scope,
                    "relation_kind": edge.kind,
                },
            )
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


class RenderedArchitectureDiagram(AgentContract):
    snapshot_hash: str
    report_hash: str
    report_origin: Literal["original", "revised"]
    structure: ArchitectureDiagram
    mermaid: str
    nodes: tuple[DiagramAnnotation, ...] = ()
    edges: tuple[DiagramAnnotation, ...] = ()
    limitations: tuple[str, ...] = ()


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
    nodes, edges = [], []
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
    return RenderedArchitectureDiagram(
        snapshot_hash=result.snapshot_hash,
        report_hash=hashlib.sha256(text.encode()).hexdigest(),
        report_origin=report_origin,
        structure=diagram,
        mermaid=render_mermaid(report, findings=findings),
        nodes=tuple(nodes),
        edges=tuple(edges),
        limitations=diagram.limitations,
    )


def render_mermaid(report: ArchitectureReport, *, findings=()):
    """Render only this report's structure; caller supplies matching review findings."""
    validate_diagram(report)
    if not report.diagram:
        return None
    diagram = report.diagram
    reviewed = {finding.target_id: finding.verdict for finding in findings}

    def verdict(*pointers):
        return _semantic_verdict(reviewed, pointers)

    lines = [
        "flowchart LR",
        f"  %% {_label(diagram.title)} | scope: {_label(diagram.scope)}",
        "  %% Solid = architect supported; dashed = hypothesis/unresolved. Semantic verdicts are separate.",
    ]
    ids = {node.id: f"n{index}" for index, node in enumerate(diagram.nodes)}

    def node_line(node, indent):
        unit = diagram_unit(report, node.unit_ref)
        review = verdict(*_node_targets(report, node))
        return f'{indent}{ids[node.id]}["{_label(unit.name)} | architect: {unit.responsibility.status} | semantic: {review}"]'

    for index, group in enumerate(diagram.groups):
        lines.append(
            f'  subgraph g{index}["{_label(group.title)} | scope: {_label(group.scope)}"]'
        )
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
        text = f"{edge.kind} | architect: {connection.description.status} | semantic: {verdict(*_edge_targets(report, edge, index))}"
        lines.append(f'  {ids[edge.source]} {style}|"{text}"| {ids[edge.target]}')
    for node in diagram.nodes:
        if diagram_unit(report, node.unit_ref).responsibility.status != "supported":
            lines.append(f"  style {ids[node.id]} stroke-dasharray: 5 5")
    lines.extend(f"  %% Limitation: {_label(item)}" for item in diagram.limitations)
    return "\n".join(lines) + "\n"
