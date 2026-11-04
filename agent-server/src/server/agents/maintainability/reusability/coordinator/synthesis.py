"""Reuse existing provenance/grouping guards with reusability contracts."""

from pathlib import Path

from .....runtimes.coordination import synthesis as shared
from .....runtimes.coordination.execution import CoordinatorSynthesisExecution
from .schemas import ConsolidatedFinding, EvidenceGap, FindingContribution


def qualified_limitations(item, findings):
    required = list(dict.fromkeys(text for ref in item.finding_refs for text in findings[ref]["required_qualifications"]))
    if not required:
        return item.limitations
    block = "Original investigator qualifications:\n" + "\n".join(required)
    # Respect Conclusion's bounded list without dropping any original qualification.
    return [*item.limitations, block] if len(item.limitations) < 12 else [*item.limitations[:-1], item.limitations[-1] + "\n" + block]


def qualified_statement(item, findings):
    details = [findings[ref]["details"] for ref in item.finding_refs]
    if not any(d.get("classification") in {"conditional", "context_dependent_risk"} for d in details):
        return item.statement
    # Do not revive categorical extraction/rewrite claims through synthesis prose.
    # The original host-qualified consequences/conditions remain complete below.
    statements = []
    for value in details:
        if value.get("classification") == "conditional":
            boundary = value.get("sharing_boundary") or value["title"]
            statements.append("Conditional sharing proposal: " + boundary + ". Its recorded prerequisites must be verified before extraction.")
        else:
            statements.append("Context-qualified observation: " + (value.get("adaptation_impact") or value["modularity_impact"]))
    statement = "\n".join(dict.fromkeys(statements))
    return statement if len(statement) <= 2000 else "Context-qualified investigator observations; original contexts, conditions and local consequences are retained in limitations."


class ReusabilitySynthesisExecution(CoordinatorSynthesisExecution):
    """Validate model proposals before they can change consolidated knowledge or gaps."""

    trace_name = "reusability-synthesis"
    prompt_directory = Path(__file__).parent / "prompts"
    last_draft = None

    async def call(self, node, state, schema=None):
        draft = await super().call(node, state, schema)
        self.last_draft = None
        if draft is None:
            return None
        context = state["compact_context"]
        findings, evidence = context["findings"], context["evidence"]
        try:
            paths = {f.path for f in self.tools.accessible_snapshot.files}
            draft = draft.model_copy(update={"gaps": [g.model_copy(update={"targets": g.targets or self.request.targets}) for g in draft.gaps]})
            for gap in draft.gaps:
                if any(t not in paths and not any(p.startswith(t.rstrip("/") + "/") for p in paths) for t in gap.targets):
                    raise ValueError
            for group in draft.groups:
                if len(set(group.finding_refs)) < 2 or not set(group.finding_refs) <= findings.keys():
                    raise ValueError
                # Do not collapse distinct reusability lenses merely because paths overlap.
                signatures = {findings[r]["polarity"] for r in group.finding_refs}
                if len(signatures) != 1 or any(findings[r]["validation_status"] != "accepted" for r in group.finding_refs):
                    raise ValueError
                if len({str(findings[r]["grouping_identity"]) for r in group.finding_refs}) != 1:
                    raise ValueError
            for item in [*draft.gaps, *draft.resolutions, *draft.conclusions, *draft.relationships]:
                if not set(item.evidence_refs) <= evidence.keys():
                    raise ValueError
                if any(evidence[r]["kind"] != "source" for r in item.evidence_refs):
                    raise ValueError
                refs = getattr(item, "finding_refs", [])
                if not set(refs) <= findings.keys():
                    raise ValueError
            for item in draft.conclusions:
                if any(findings[r]["validation_status"] != "accepted" for r in item.finding_refs):
                    raise ValueError
                cited = {e for r in item.finding_refs for e in findings[r]["evidence_refs"]}
                if not set(item.evidence_refs) <= cited:
                    raise ValueError
            draft = draft.model_copy(update={"conclusions": [item.model_copy(update={"limitations": qualified_limitations(item, findings),
                "statement": qualified_statement(item, findings)})
                for item in draft.conclusions]})
            invocations = {r["invocation_id"]: r for r in context["invocations"]}
            for resolution in draft.resolutions:
                invocation = invocations.get(resolution.invocation_id)
                if not invocation or not set(resolution.withdrawn_finding_refs) <= findings.keys():
                    raise ValueError
                if any(not r.startswith(resolution.invocation_id + "/") for r in resolution.evidence_refs):
                    # The coordinator checks new source OR a bound host-validation
                    # transition against actual records, not the model's explanation.
                    draft = draft.model_copy(update={"resolutions": [r for r in draft.resolutions if r is not resolution]})
            for relationship in draft.relationships:
                if len(set(relationship.finding_refs)) < 2:
                    raise ValueError
                if relationship.kind == "conflicts" and not any(g.kind == "contradiction"
                        and set(relationship.finding_refs) <= set(g.finding_refs) for g in draft.gaps):
                    raise ValueError
        except ValueError:
            self.stop = "invalid_synthesis_references"
            self.issues.append("Synthesis rejected: unknown/unsupported references, incompatible grouping or untracked contradiction.")
            return None
        self.last_draft = draft
        return draft


def polarity(finding):
    category = getattr(finding, "category", None)
    classification = getattr(finding, "classification", None)
    return {"useful_abstraction": "benefit", "unnecessary_abstraction": "barrier", "coupling": "barrier",
            "missed_reuse": "opportunity", "recommended": "opportunity", "conditional": "conditional_opportunity",
            "not_recommended": "against_sharing", "verified_obstacle": "barrier",
            "context_dependent_risk": "barrier"}.get(category or classification, "unknown")


def group_key(finding):
    identity = getattr(finding, "stable_id", "") or shared.stable_id("semantic", shared.semantic_key(finding))
    return (identity, polarity(finding), shared.qualification_key(finding))


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
    if gap.task_type == "external_context":
        return False
    prior = [r for r in records if r.assignment.investigator_id == gap.investigator_id]
    if prior and (shared.terminal_provider_blocker(prior[-1].result) or shared.terminal_collection_blocker(prior[-1])):
        return False
    attempts = [r for r in records if gap.id in r.assignment.gap_ids]
    if attempts:
        # One targeted attempt per unchanged commitment. A new model phrasing or
        # invocation ID cannot reopen the same bounded repair indefinitely.
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
