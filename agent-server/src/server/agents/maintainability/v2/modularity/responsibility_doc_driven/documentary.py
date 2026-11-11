"""Task-local documentary knowledge and delivery receipts.

The documentary context is validated project knowledge for the current
responsibility investigation, never an entry in the code evidence ledger.
Claims whose documentary provenance cannot be verified are reported as
unavailable; they are not silently dropped from the delivery receipt.
"""

import json
from pathlib import Path

from server.services.document_indexing.service import identifier

from .schemas import ResponsibilityClaimAssessment


def documentary_context(task, plan, snapshot, context, character_limit):
    """Delivered claims for the current task plus host-recorded unavailable claims."""
    claims, unavailable = {}, {}
    documents = {item.path: item for item in getattr(context, "consulted_documents", []) or []} if context else {}
    repository = getattr(snapshot, "repository", None)
    snapshot_commit = getattr(repository, "commit", None)
    snapshot_root = getattr(repository, "root_path", None)
    snapshot_repository_id = identifier(str(Path(snapshot_root).resolve())) if snapshot_root else None
    for key in task.document_claim_ids:
        record = plan.document_claims.get(key) if plan else None
        reason = ""
        if record is None:
            reason = "Referenced claim is absent from plan.document_claims."
        else:
            claim, index = record.claim, record.document_index
            if (not index or not snapshot_commit or index.commit != snapshot_commit
                    or index.repository_id != snapshot_repository_id):
                reason = "Documentary repository/commit provenance is incompatible with this snapshot."
            elif not claim.evidence or not claim.section_ids or set(claim.section_ids) != {
                    item.section_id for item in claim.evidence} or set(record.section_paths) != set(claim.section_ids) or any(not item.quote for item in claim.evidence):
                reason = "Missing/inconsistent documentary section or quotation provenance."
            elif context and (index != getattr(context, "document_index", None)
                    or any(getattr(context, "section_paths", {}).get(section) != record.section_paths.get(section)
                        for section in claim.section_ids)
                    or any(path not in documents or any(getattr(documents[path], field) != getattr(index, field)
                        for field in ("index_id", "repository_id", "commit"))
                        for path in record.section_paths.values())
                    or any(item.end_line > documents[record.section_paths[item.section_id]].line_count
                        for item in claim.evidence
                        if record.section_paths.get(item.section_id) in documents)):
                reason = "Claim section paths or document provenance disagree with canonical context."
        if reason:
            unavailable[key] = reason
            continue
        sections = set(record.claim.section_ids)
        payload = {"claim_id": key,
            "category": record.claim.category,
            "subject": record.claim.subject,
            "statement": record.claim.statement,
            "related_subjects": list(record.claim.related_subjects),
            "certainty": record.claim.certainty,
            "constraint": record.claim.constraint,
            "evidence": [{"section_id": item.section_id, "start_line": item.start_line,
                "end_line": item.end_line, "quote": item.quote} for item in record.claim.evidence],
            "section_paths": record.section_paths,
            "status": record.status, "reason": record.reason,
            "scope_paths": [path for path in record.scope_paths if path in task.scope],
            "knowledge_issues": [issue.model_dump(mode="json") for issue in getattr(context, "knowledge_issues", [])
                if sections & set(issue.section_ids)] if context else [],
            "validation_errors": [error.model_dump(mode="json") for error in getattr(context, "validation_errors", [])
                if not error.section_ids or sections & set(error.section_ids)] if context else [],
            "execution_status": getattr(context, "execution_status", None) if context else None,
            "finalization_reason": getattr(context, "finalization_reason", None) if context else None,
            "coverage_assessment_status": getattr(context, "coverage_assessment_status", None) if context else None}
        if len(json.dumps(claims | {key: payload})) > character_limit:
            unavailable[key] = "Whole claim projection omitted by documentary context limit; original retained in plan."
        else:
            claims[key] = payload
    return {"document_claim_ids": list(task.document_claim_ids),
        "claims": claims, "unavailable_claims": unavailable,
        "scope_notice": "Local portions only. Planned associations and mappings are provisional; no whole-claim conformance is established."}


def pending_assessments(task, assessments, unavailable):
    """Host-pending inconclusive placeholders for claims without a delivered assessment."""
    present = {item.claim_id for item in assessments}
    return [*assessments, *(ResponsibilityClaimAssessment(
        claim_id=key, status="inconclusive", assessment_origin="host_pending",
        rationale=unavailable.get(key, "No validated individual assessment was returned for this obligation."),
        limitations=[unavailable.get(key, "Claim remains pending; no technical assessment established.")][:20])
        for key in task.document_claim_ids if key not in present)]
