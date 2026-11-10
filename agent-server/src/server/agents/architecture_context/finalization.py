"""Final documentary integrity checks; no model calls or evidence repairs."""

from typing import get_args

from pydantic import ValidationError

from server.runtimes.investigation.structured import safe_diagnostic
from server.services.document_indexing import (
    DocumentRecord,
    DocumentSection,
    IndexReference,
)

from .extraction import _validate_section
from .schemas import (
    ArchitectureContextResult,
    FinalizationDiagnostic,
    KnowledgeClaim,
    KnowledgeIssue,
    RetrievalCategory,
    RetrievalRecord,
    SectionKnowledge,
)
from .state import ArchitectureContextState


def _revalidate(value, schema):
    # model_copy/update can bypass validation: explicitly validate fresh data.
    return schema.model_validate(value.model_dump() if hasattr(value, "model_dump") else value)


def validate_and_finalize(state: ArchitectureContextState) -> ArchitectureContextState:
    """Preserve valid items and report each failure independently in the final state."""
    diagnostics = []

    def reject(target, position, reason, section_ids=()):
        diagnostics.append(FinalizationDiagnostic(
            target=target, position=position, reason=reason, section_ids=list(section_ids),
        ))

    if state.get("execution_error"):
        reject("execution", None, state["execution_error"])

    try:
        index = _revalidate(state.get("document_index"), IndexReference)
    except ValidationError as error:
        index = None
        reject("index", None, safe_diagnostic(error, IndexReference))

    documents = {}
    duplicate_paths = set()
    for position, raw in enumerate(state.get("documents", [])):
        try:
            document = _revalidate(raw, DocumentRecord)
            if index is None or any(
                getattr(document, key) != getattr(index, key)
                for key in IndexReference.model_fields
            ):
                raise ValueError("Document provenance does not match the trusted index")
            if document.path in documents:
                duplicate_paths.add(document.path)
                raise ValueError("Duplicate document path in catalog")
            documents[document.path] = document
        except (ValidationError, ValueError) as error:
            reject("document", position, safe_diagnostic(error, DocumentRecord) if isinstance(error, ValidationError) else str(error))
    for path in duplicate_paths:
        documents.pop(path, None)

    sections = {}
    duplicate_ids = set()
    invalid_section_ids = set()
    for position, raw in enumerate(state.get("retrieved_sections", [])):
        try:
            section = _revalidate(raw, DocumentSection)
            document = documents.get(section.path)
            if document is None or any(
                getattr(section, key) != getattr(document, key)
                for key in DocumentRecord.model_fields
            ):
                raise ValueError("Section provenance does not match its catalog document")
            if len(section.content.splitlines(keepends=True)) != section.end_line - section.start_line + 1:
                raise ValueError("Section text does not match its original line range")
            if section.section_id in sections:
                duplicate_ids.add(section.section_id)
                raise ValueError("Duplicate section ID in retrieved sections")
            sections[section.section_id] = section
        except (ValidationError, ValueError) as error:
            section_id = raw.get("section_id") if isinstance(raw, dict) else getattr(raw, "section_id", None)
            if isinstance(section_id, str):
                invalid_section_ids.add(section_id)
            reject("section", position, safe_diagnostic(error, DocumentSection) if isinstance(error, ValidationError) else str(error),
                   [section_id] if isinstance(section_id, str) else [])
    for section_id in duplicate_ids | invalid_section_ids:
        sections.pop(section_id, None)

    claims, issues = [], []
    rejected_categories = set()
    invalid_claim_sections = set()
    for position, raw in enumerate(state.get("knowledge", [])):
        claim = None
        try:
            claim = _revalidate(raw, KnowledgeClaim)
            if len(set(claim.section_ids)) != len(claim.section_ids):
                raise ValueError("Claim section IDs must be unique")
            if not set(claim.section_ids) <= sections.keys():
                raise ValueError("Claim references an unavailable or invalid section")
            for evidence in claim.evidence:
                section = sections.get(evidence.section_id)
                if section is None:
                    raise ValueError("Claim evidence references an unavailable section")
                first = evidence.start_line - section.start_line
                last = evidence.end_line - section.start_line
                lines = section.content.splitlines(keepends=True)
                if first < 0 or last < first or last >= len(lines):
                    raise ValueError("Claim evidence range is outside its original section")
                if evidence.quote != "".join(lines[first : last + 1]):
                    raise ValueError("Claim quote does not match its original lines literally")
            _, _, errors = _validate_section(
                SectionKnowledge(section_id=claim.section_ids[0], claims=[claim]),
                sections[claim.section_ids[0]], sections,
            )
            if errors:
                raise ValueError(str(errors[0]))
            claims.append(claim)
        except (ValidationError, ValueError) as error:
            ids = claim.section_ids if claim else []
            if claim:
                rejected_categories.add(claim.category)
                invalid_claim_sections.update(ids)
            else:
                rejected_categories.update(get_args(RetrievalCategory))
            reject("claim", position, safe_diagnostic(error, KnowledgeClaim) if isinstance(error, ValidationError) else str(error), ids)

    for position, raw in enumerate(state.get("knowledge_issues", [])):
        issue = None
        try:
            issue = _revalidate(raw, KnowledgeIssue)
            if len(set(issue.section_ids)) != len(issue.section_ids) or not set(issue.section_ids) <= sections.keys():
                raise ValueError("Issue section IDs must be unique and reference valid sections")
            if any(reference not in documents for reference in issue.document_references):
                raise ValueError("Issue document reference does not exist in the trusted catalog")
            issues.append(issue)
        except (ValidationError, ValueError) as error:
            if issue:
                rejected_categories.add(issue.category)
                invalid_claim_sections.update(issue.section_ids)
            else:
                rejected_categories.update(get_args(RetrievalCategory))
            reject("issue", position, safe_diagnostic(error, KnowledgeIssue) if isinstance(error, ValidationError) else str(error), issue.section_ids if issue else [])

    section_status = dict(state.get("extraction_section_status", {}))
    for section_id in invalid_section_ids | duplicate_ids:
        section_status[section_id] = "failed"
    for section_id in state.get("processed_section_ids", []):
        if section_id not in sections:
            reject("execution", None, "Processed section ID does not reference a valid section", [section_id])
        else:
            section_status.setdefault(section_id, "completed")
    for section_id in sections:
        if section_id in invalid_claim_sections:
            section_status[section_id] = "partial"
        else:
            section_status.setdefault(section_id, "failed")
    processed_ids = [
        section_id for section_id in dict.fromkeys(state.get("processed_section_ids", []))
        if section_id in sections and section_status.get(section_id) == "completed"
    ]
    categories = list(get_args(RetrievalCategory))
    covered = [
        category for category in categories
        if state.get("coverage_assessment_status") == "completed"
        and category in state.get("covered_categories", [])
        and category not in state.get("pending_categories", [])
        and category not in rejected_categories
        and any(claim.category == category for claim in claims)
    ]
    incomplete = any(status != "completed" for status in section_status.values()) or bool(
        sections.keys() - set(processed_ids)
    )
    if incomplete or any(item.target in {"index", "document", "section", "execution"} for item in diagnostics):
        covered = []
    pending = [category for category in categories if category not in covered]
    discovery_failed = state.get("document_discovery_status") == "error"
    retrieval_failed = any(
        isinstance(record, RetrievalRecord) and record.status in {"error", "limited"}
        for record in state.get("retrieval_history", [])
    )
    stop_reason = state.get("context_stop_reason") or ("retrieval_incomplete" if retrieval_failed else None)
    if not pending and not diagnostics and not stop_reason and not discovery_failed:
        status, reason = "complete", "coverage_complete"
    elif (discovery_failed or diagnostics or stop_reason) and not claims and not issues:
        status = "failed"
        reason = stop_reason or ("document_discovery_failed" if discovery_failed else "validation_failed")
    else:
        status = "partial"
        reason = stop_reason or ("validation_failed" if diagnostics else "incomplete_coverage")
    consulted_paths = {section.path for section in sections.values()}
    consulted_documents = [document for path, document in documents.items() if path in consulted_paths]
    result = ArchitectureContextResult(
        document_index=index,
        knowledge=claims,
        knowledge_issues=issues,
        covered_categories=covered,
        pending_categories=pending,
        coverage_assessment_status=state.get("coverage_assessment_status", "not_run"),
        evaluated_categories=list(state.get("evaluated_categories", [])),
        consulted_documents=consulted_documents,
        section_paths={section_id: section.path for section_id, section in sections.items()},
        validation_errors=diagnostics,
        execution_status=status,
        finalization_reason=reason,
        execution_error=state.get("execution_error") or state.get("document_discovery_error"),
    )
    return {
        "result": result,
        "knowledge": claims,
        "knowledge_issues": issues,
        "covered_categories": covered,
        "pending_categories": pending,
        "coverage_assessment_status": state.get("coverage_assessment_status", "not_run"),
        "evaluated_categories": list(state.get("evaluated_categories", [])),
        "processed_section_ids": processed_ids,
        "extraction_section_status": section_status,
        "consulted_documents": consulted_documents,
        "validation_errors": diagnostics,
        "execution_status": status,
        "finalization_reason": reason,
    }
