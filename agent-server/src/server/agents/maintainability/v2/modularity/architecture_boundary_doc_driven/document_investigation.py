"""Task-local documentary knowledge and scoped coverage; never a code evidence ledger."""

import json
from pathlib import Path

from server.services.document_indexing.service import identifier

from .documentation import claim_identity
from .schemas import ClaimAssessment


def documentary_context(task, plan, snapshot, context, character_limit):
    claims, unavailable = {}, {}
    documents = {item.path: item for item in context.consulted_documents} if context else {}
    for key in task.document_claim_ids:
        record = plan.document_claims.get(key)
        reason = ""
        if record is None:
            reason = "Referenced claim is absent from plan.document_claims."
        else:
            claim, index = record.claim, record.document_index
            if not index or index.commit != snapshot.repository.commit or index.repository_id != identifier(
                str(Path(snapshot.repository.root_path).resolve())
            ) or not snapshot.repository.commit:
                reason = "Documentary repository/commit provenance is incompatible with this snapshot."
            elif record.status in {"incompatible", "invalid_reference"} or not claim.evidence or not claim.section_ids or (
                set(claim.section_ids) != {item.section_id for item in claim.evidence}
            ) or set(record.section_paths) != set(claim.section_ids) or any(
                item.section_id not in record.section_paths or not item.quote for item in claim.evidence):
                reason = "Missing/inconsistent documentary section or quotation provenance."
            elif context and (index != context.document_index or claim_identity(claim, context) != key or any(
                context.section_paths.get(section) != record.section_paths.get(section) for section in claim.section_ids
            ) or any(path not in documents or any(getattr(documents[path], field) != getattr(index, field)
                for field in ("index_id", "repository_id", "commit")) for path in record.section_paths.values()) or any(
                item.end_line > documents[record.section_paths[item.section_id]].line_count for item in claim.evidence
            )):
                reason = "Claim identity, section paths or document provenance disagree with canonical context."
        if reason:
            unavailable[key] = reason
            continue
        sections = set(record.claim.section_ids)
        payload = {"claim_id": key, **record.claim.model_dump(mode="json"),
            "document_index": record.document_index.model_dump(mode="json"), "section_paths": record.section_paths,
            "status": record.status, "reason": record.reason, "mapping_basis": record.mapping_basis,
            "unresolved_references": record.unresolved_references,
            "scope_paths": [path for path in record.scope_paths if path in task.scope],
            "excluded_paths": record.excluded_paths,
            "portions": [portion.model_dump(mode="json") for portion in record.portions if task.id in portion.opportunity_ids],
            "knowledge_issues": [issue.model_dump(mode="json") for issue in context.knowledge_issues
                if sections & set(issue.section_ids)] if context else [],
            "validation_errors": [error.model_dump(mode="json") for error in context.validation_errors
                if not error.section_ids or sections & set(error.section_ids)] if context else [],
            "execution_status": context.execution_status if context else None,
            "finalization_reason": context.finalization_reason if context else None,
            "coverage_assessment_status": context.coverage_assessment_status if context else None}
        if len(json.dumps(claims | {key: payload})) > character_limit:
            unavailable[key] = "Whole claim projection omitted by documentary context limit; original retained in plan."
        else:
            claims[key] = payload
    return {"claims": claims, "unavailable_claims": unavailable,
        "scope_notice": "Local portions only. Planned associations and mappings are provisional; no whole-claim conformance is established."}


def pending_assessments(task, assessments, unavailable):
    present = {item.claim_id for item in assessments}
    return [*assessments, *(ClaimAssessment(claim_id=key, status="inconclusive",
        assessment_origin="host_pending",
        rationale=unavailable.get(key, "No validated individual assessment was returned for this obligation."),
        limitations=[unavailable.get(key, "Claim remains pending; no technical assessment established.")])
        for key in task.document_claim_ids if key not in present)]


def investigation_coverage(plan, results):
    """Unique claims and per-investigation outcomes, separate from immutable planning metrics."""
    tasks = {task.id: task for task in plan.investigations}
    rows = [{"investigation_id": result.investigation_id, **assessment.model_dump(mode="json"),
        "portion_ids": [portion.id for portion in plan.document_claims[assessment.claim_id].portions
            if result.investigation_id in portion.opportunity_ids] if assessment.claim_id in plan.document_claims else [],
        "local_only": True}
        for result in results for assessment in result.claim_assessments]
    selected = {key for task in tasks.values() for key in task.document_claim_ids}
    examined = {row["claim_id"] for row in rows if row["code_evidence_ids"]}
    return {"selected_claim_ids": sorted(selected), "examined_claim_ids": sorted(examined),
        "investigated": len(examined), "assessment_count": len(rows),
        "by_status": {status: sorted({row["claim_id"] for row in rows if row["status"] == status})
            for status in ("supported", "contradicted", "not_applicable", "inconclusive")},
        "pending_claim_ids": sorted(selected - examined), "assessments": rows,
        "unresolved_claim_ids": sorted({row["claim_id"] for row in rows if row["status"] == "inconclusive"} |
            (selected - {row["claim_id"] for row in rows})),
        "whole_claim_compliance_established": False,
        "definition": "Examined means a validated local assessment cites inspected source. Status sets may overlap across investigations; never sum them as unique claims."}
