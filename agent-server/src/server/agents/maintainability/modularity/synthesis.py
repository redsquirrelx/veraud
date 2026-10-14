"""Deterministic grouping, provenance and duplicate-request guards; no generated facts."""

import hashlib
import json

from .schemas import ConsolidatedFinding, EvidenceGap, FindingContribution


def stable_id(prefix, value):
    return prefix + "-" + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:20]


def normalized(text):
    return " ".join(text.casefold().split())


def request_key(investigator, question, targets):
    return investigator, normalized(question), tuple(sorted(targets))


def evidence_key(reference):
    return (reference.snapshot_hash, reference.file_id, reference.content_hash,
            reference.kind, reference.start_line, reference.end_line)


def evidence_index(records):
    return {f"{r.assignment.invocation_id}/{e.id}": e for r in records for e in r.evidence}


def finding_index(records, contribution_type=FindingContribution):
    return {f"{r.assignment.invocation_id}/{f.id}": contribution_type(
        reference=f"{r.assignment.invocation_id}/{f.id}", invocation_id=r.assignment.invocation_id,
        investigator_id=r.assignment.investigator_id, finding=f,
    ) for r in records if r.result for f in r.result.findings}


def actionable(gap, records):
    if not gap.material or gap.investigator_id is None or not gap.question.strip():
        return False
    completed = [r for r in records if r.status == "completed" and request_key(
        r.assignment.investigator_id, r.assignment.question, r.assignment.targets,
    ) == request_key(gap.investigator_id, gap.question, gap.targets)]
    if not completed:
        return True
    index = evidence_index(records)
    supplied = {evidence_key(index[i]) for i in gap.evidence_refs if i in index and index[i].kind == "source"}
    # New retrieval IDs for the same bytes/ranges are NOT new evidence.
    already_known = {evidence_key(e) for r in completed for e in r.evidence}
    return bool(supplied - already_known)


def semantic_key(finding):
    return (normalized(finding.title), normalized(finding.criterion.description),
            tuple(sorted(normalized(c) for c in finding.components)), finding.kind)


def detect_contradictions(records, withdrawn, *, gap_type=EvidenceGap, contribution_type=FindingContribution,
                          key_function=None):
    key_function = key_function or semantic_key
    groups = {}
    for ref, contribution in finding_index(records, contribution_type).items():
        if ref not in withdrawn:
            groups.setdefault(key_function(contribution.finding), []).append(contribution)
    gaps = []
    for key, group in groups.items():
        accepted = [c for c in group if c.finding.validation_status == "accepted"]
        rejected = [c for c in group if c.finding.validation_status == "rejected"]
        if accepted and rejected:
            refs = sorted(c.reference for c in group)
            gaps.append(gap_type(
                id=stable_id("contradiction", key), kind="contradiction",
                investigator_id=accepted[0].investigator_id,
                question="Resolve conflicting accepted/rejected conclusions about: " + accepted[0].finding.title,
                finding_refs=refs,
            ))
    return gaps


def consolidate(records, proposed_groups, gaps, withdrawn, *, contribution_type=FindingContribution,
                consolidated_type=ConsolidatedFinding, id_prefix="modularity-finding", key_function=None):
    key_function = key_function or semantic_key
    index = {ref: c for ref, c in finding_index(records, contribution_type).items()
             if c.finding.validation_status == "accepted" and ref not in withdrawn}
    groups = {}
    for ref, contribution in index.items():
        groups.setdefault(key_function(contribution.finding), set()).add(ref)
    buckets = list(groups.values())
    for proposal in proposed_groups:
        refs = set(proposal.finding_refs)
        if not refs <= index.keys():
            continue
        overlapping = [bucket for bucket in buckets if bucket & refs]
        merged = refs.union(*overlapping)
        buckets = [bucket for bucket in buckets if not bucket & refs] + [merged]
    findings = []
    for bucket in buckets:
        contributions = [index[ref] for ref in sorted(bucket)]
        first = contributions[0].finding
        disputed = any(g.kind == "contradiction" and set(g.finding_refs) & bucket for g in gaps)
        severities = {c.finding.severity for c in contributions}
        findings.append(consolidated_type(
            id=stable_id(id_prefix, sorted({key_function(c.finding) for c in contributions})),
            concern=first.title, affected_components=sorted({x for c in contributions for x in c.finding.components}),
            status="disputed" if disputed else "supported",
            evidence=list({(e.id, e.tool_call_id): e for c in contributions for e in c.finding.evidence}.values()),
            contributions=contributions,
            severity=next(iter(severities)) if len(severities) == 1 and not disputed else None,
            confidence=first.confidence if len(contributions) == 1 and not disputed else None,
            limitations=["Conflicting conclusions remain unresolved."] if disputed else [],
        ))
    return findings
