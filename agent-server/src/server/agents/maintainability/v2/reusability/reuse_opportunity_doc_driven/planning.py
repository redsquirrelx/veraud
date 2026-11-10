"""Documentary projections and navigation; no capability decisions or source analysis."""

import re


def documentary_records(architecture):
    if architecture is None:
        return {}
    return {
        f"claim-{index}": {
            "id": f"claim-{index}",
            "document_index": architecture.document_index.model_dump(mode="json") if architecture.document_index else None,
            **claim.model_dump(mode="json"),
            "section_paths": {key: architecture.section_paths[key]
                for key in claim.section_ids if key in architecture.section_paths},
        }
        for index, claim in enumerate(architecture.knowledge)
    }


def discovery_projection(record):
    """Locator/intent projection only; original evidence is read before formulation."""
    return {key: record[key] for key in (
        "id", "category", "subject", "statement", "related_subjects", "certainty", "constraint", "section_ids",
    )}


def complementary_claims(selected_ids, records):
    """Recover same-section and exact documented-entity context, not obligations.

    No token-overlap or layer naming heuristic decides semantic applicability.
    The model must interpret these original claims, including exceptions, together.
    """
    selected = [records[key] for key in selected_ids]
    sections = {section for record in selected for section in record["section_ids"]}
    entities = {value.strip().casefold() for record in selected
        for value in [record["subject"], *record["related_subjects"]] if value.strip()}
    return [key for key, record in records.items() if key in selected_ids
        or sections.intersection(record["section_ids"])
        or entities.intersection(value.strip().casefold()
            for value in [record["subject"], *record["related_subjects"]] if value.strip())]


def indexed_target_candidates(records, paths):
    """Return indexed files/directories explicitly mentioned by documentary claims.

    This is navigation grounding only: absence from the list means the model must
    not propose that path. It does not establish why the path exists or imply source
    access beyond the snapshot. Cap exploration to the most frequently referenced
    explicit paths before falling back to path order.
    """
    text = "\n".join(" ".join([record["subject"], record["statement"],
        *record.get("related_subjects", [])]) for record in records)
    targets = set(paths)
    for path in paths:
        parts = path.split("/")
        for depth in range(1, len(parts)):
            targets.add("/".join(parts[:depth]))
    matches = []
    for target in targets:
        occurrences = len(re.findall(r"(?<![\w./@])" + re.escape(target) + r"(?:/|\b)", text,
            flags=re.IGNORECASE))
        if occurrences:
            matches.append((occurrences, target))
    return [target for _count, target in sorted(matches, key=lambda item: (-item[0], item[1]))[:30]]


def relevant_paths(records, paths):
    """Prefer paths explicitly mentioned by these claims, never alphabetical samples."""
    return indexed_target_candidates(records, paths)
