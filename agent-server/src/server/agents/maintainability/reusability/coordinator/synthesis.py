"""Reuse existing provenance/grouping guards with reusability contracts."""

from .....runtimes.coordination import synthesis as shared
from .schemas import ConsolidatedFinding, EvidenceGap, FindingContribution


def polarity(finding):
    category = getattr(finding, "category", None)
    classification = getattr(finding, "classification", None)
    return {"useful_abstraction": "benefit", "unnecessary_abstraction": "barrier", "coupling": "barrier",
            "missed_reuse": "opportunity", "recommended": "opportunity", "conditional": "conditional_opportunity",
            "not_recommended": "against_sharing", "verified_obstacle": "barrier",
            "context_dependent_risk": "barrier"}.get(category or classification, "unknown")


def group_key(finding):
    return (*shared.semantic_key(finding), polarity(finding), getattr(finding, "assessed_context", ""))


def finding_index(records):
    return shared.finding_index(records, FindingContribution)


def detect_contradictions(records, withdrawn):
    # Host-rejected duplicates are not semantic disagreements with the retained item.
    filtered = [r.model_copy(update={"result": r.result.model_copy(update={"findings": [f for f in r.result.findings
                if not getattr(f, "duplicate_of", None)]})}) if r.result else r for r in records]
    return shared.detect_contradictions(filtered, withdrawn, gap_type=EvidenceGap, contribution_type=FindingContribution,
                                        key_function=group_key)


def consolidate(records, groups, gaps, withdrawn):
    return shared.consolidate(records, groups, gaps, withdrawn, contribution_type=FindingContribution,
                              consolidated_type=ConsolidatedFinding, id_prefix="reusability-finding", key_function=group_key)


def actionable(gap, records):
    if not gap.material or not gap.investigator_id or not gap.question.strip():
        return False
    matching = [r for r in records if shared.request_key(r.assignment.investigator_id, r.assignment.question,
        r.assignment.targets) == shared.request_key(gap.investigator_id, gap.question, gap.targets)]
    if not matching:
        return True
    index = shared.evidence_index(records)
    supplied = {shared.evidence_key(index[i]) for i in gap.evidence_refs if i in index and index[i].kind == "source"}
    known = {shared.evidence_key(e) for r in matching for e in r.evidence}
    if supplied - known:
        return True
    # One bounded retry for an essential failed/partial initial invocation, not
    # repeated expensive attempts with new UUIDs but the same question/evidence.
    return gap.kind == "essential_failure" and len(matching) == 1 and matching[0].status != "completed"
