"""Structural diagram reference checks, independent of report schema classes."""

import re


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

def diagram_deviation(report, reference):
    match = re.fullmatch(r"/deviations/(0|[1-9][0-9]*)", reference)
    if not match or int(match[1]) >= len(report.deviations):
        raise ValueError(
            "Diagram deviations must reference existing report deviations."
        )
    return report.deviations[int(match[1])]

def validate_diagram(report):
    diagram = report.diagram
    if diagram is None:
        return
    for view in diagram.views:
        _validate_diagram_view(report, view)
    _validate_diagram_view(report, diagram)


def _validate_diagram_view(report, diagram):
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
