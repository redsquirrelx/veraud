"""Independent structural scores, judge calibration, and human review scores."""

import hashlib
import itertools
import json
from collections import Counter
from pathlib import Path
from statistics import mean

from ..agents.analyzer.parsing import split_evidence
from .schemas import BenchmarkCase, HumanReview

VERDICTS = ("supported", "contradicted", "unverifiable")


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def path_scores(actual: list[str], expected: list[str], exhaustive: bool = False):
    actual_set, expected_set = set(actual), set(expected)
    hits = actual_set & expected_set
    return {
        "reference_hits": len(hits),
        "reference_total": len(expected_set),
        "predicted_total": len(actual_set),
        "reference_recall": ratio(len(hits), len(expected_set)),
        "precision": ratio(len(hits), len(actual_set)) if exhaustive else None,
        "reference_exhaustive": exhaustive,
        "missing": sorted(expected_set - actual_set),
    }


def citation_valid(root: Path, entry: str) -> bool:
    split = split_evidence(entry)
    if split is None:
        return False
    path, ranges = split
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        return False
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    return ranges is None or all(1 <= start <= end <= len(lines) for start, end in ranges)


def automatic_scores(root: Path, case: BenchmarkCase, analysis: dict, description: dict):
    citations = [
        entry
        for item in description.get("quality_notes", []) + description.get("deviations", [])
        for entry in item.get("evidence", [])
    ]
    components = description.get("components", [])
    return {
        "kind_correct": analysis.get("kind") in case.kinds if case.kinds else None,
        "language_correct": analysis.get("primary_language") == case.primary_language,
        "entrypoints": path_scores(analysis.get("entrypoints", []), case.entrypoints, case.entrypoints_exhaustive),
        "key_components": path_scores(analysis.get("key_components", []), case.key_components, case.components_exhaustive),
        "architect_components": path_scores([item["path"] for item in components], case.key_components, case.components_exhaustive),
        "responsibility_completion": ratio(sum(bool(item.get("responsibility", "").strip()) for item in components), len(components)),
        "citation_count": len(citations),
        "valid_citation_count": sum(citation_valid(root, entry) for entry in citations),
        "citation_validity": ratio(sum(citation_valid(root, entry) for entry in citations), len(citations)),
    }


def judge_scores(items: list[dict]):
    matrix = {expected: {predicted: 0 for predicted in VERDICTS} for expected in VERDICTS}
    for item in items:
        matrix[item["expected"]][item["predicted"]] += 1
    per_class = {}
    for label in VERDICTS:
        tp = matrix[label][label]
        support = sum(matrix[label].values())
        predicted = sum(row[label] for row in matrix.values())
        denominator = support + predicted
        per_class[label] = {
            "support": support,
            "precision": ratio(tp, predicted),
            "recall": ratio(tp, support),
            "f1": 2 * tp / denominator if denominator else None,
        }
    f1s = [values["f1"] for values in per_class.values() if values["f1"] is not None]
    false = matrix["contradicted"]
    non_supported = sum(matrix["contradicted"].values()) + sum(matrix["unverifiable"].values())
    return {
        "items": len(items),
        "accuracy": ratio(sum(matrix[label][label] for label in VERDICTS), len(items)),
        "macro_f1": mean(f1s) if f1s else None,
        "confusion_matrix": matrix,
        "per_class": per_class,
        "false_support_rate": ratio(false["supported"], sum(false.values())),
        "unsupported_acceptance_rate": ratio(matrix["contradicted"]["supported"] + matrix["unverifiable"]["supported"], non_supported),
    }


def artifact_hash(record: dict) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def review_template(record: dict, case: BenchmarkCase) -> HumanReview:
    claims = []

    def add(section, text, evidence=()):
        if not str(text).strip():
            return
        claims.append({"id": f"claim-{len(claims) + 1:03d}", "section": section, "claim": text, "evidence": list(evidence)})

    analysis = record.get("analysis", {})
    description = record.get("description", {})
    add("summary", analysis.get("summary", ""))
    add("style", f"{description.get('style', '')}: {description.get('style_explanation', '')}" if description else "")
    add("intended_style", f"{description.get('intended_style', '')}: {description.get('intended_explanation', '')}" if description else "")
    add("data_flow", description.get("data_flow", ""))
    for item in description.get("components", []):
        add("component", item.get("responsibility", ""), [item["path"]])
    for section, key, text_key in (("note", "quality_notes", "observation"), ("deviation", "deviations", "observation"), ("container", "containers", "responsibility")):
        for item in description.get(key, []):
            add(section, item.get(text_key, ""), item.get("evidence", item.get("files", [])))
    for text in description.get("risks", []):
        add("risk", text)
    return HumanReview(
        run_id=record["run_id"], artifact_sha256=artifact_hash(record), claims=claims,
        expected_facts=[{"id": fact.id, "description": fact.description, "evidence": fact.evidence} for fact in case.expected_facts],
    )


def human_scores(review: HumanReview, template: HumanReview):
    # Ratings can change; the evaluated artifact, claims and references cannot.
    if review.run_id != template.run_id or review.artifact_sha256 != template.artifact_sha256:
        raise ValueError("Review belongs to a different run/artifact")
    def identities(items, excluded):
        return [item.model_dump(exclude=excluded) for item in items]
    if identities(review.claims, {"verdict", "comment"}) != identities(template.claims, {"verdict", "comment"}):
        raise ValueError("Review claims were changed, removed or reordered")
    if identities(review.expected_facts, {"found", "comment"}) != identities(template.expected_facts, {"found", "comment"}):
        raise ValueError("Review reference facts were changed, removed or reordered")
    counts = Counter(item.verdict for item in review.claims if item.verdict is not None)
    reviewed = sum(counts.values())
    facts = [item for item in review.expected_facts if item.found is not None]
    return {
        "reviewer": review.reviewer,
        "claims_total": len(review.claims), "claims_reviewed": reviewed,
        "review_completion": ratio(reviewed, len(review.claims)),
        "support_rate": ratio(counts["supported"], reviewed),
        "contradiction_rate": ratio(counts["contradicted"], reviewed),
        "unverifiable_rate": ratio(counts["unverifiable"], reviewed),
        "facts_reviewed": len(facts), "facts_total": len(review.expected_facts),
        "expected_fact_recall": ratio(sum(item.found for item in facts), len(facts)),
        "fact_review_completion": ratio(len(facts), len(review.expected_facts)),
    }


def stability(records: list[dict]):
    # Error/fallback outputs must not make a broken system appear stable.
    good = [record for record in records if all(record["stages"].get(stage, {}).get("status") == "completed" for stage in ("analyzer", "architect"))]
    pairs = list(itertools.combinations(good, 2))
    def jaccard(left, right):
        union = left | right
        return len(left & right) / len(union) if union else None
    def average(values):
        values = [value for value in values if value is not None]
        return mean(values) if values else None
    return {
        "eligible_runs": len(good), "pairs": len(pairs),
        "kind_agreement": average([a["analysis"]["kind"] == b["analysis"]["kind"] for a, b in pairs]),
        "style_agreement": average([a["description"]["style"] == b["description"]["style"] for a, b in pairs]),
        "component_jaccard": average([jaccard(set(a["analysis"]["key_components"]), set(b["analysis"]["key_components"])) for a, b in pairs]),
        "quality_evidence_jaccard": average([jaccard({(n["characteristic"], e) for n in a["description"].get("quality_notes", []) for e in n["evidence"]}, {(n["characteristic"], e) for n in b["description"].get("quality_notes", []) for e in n["evidence"]}) for a, b in pairs]),
    }
