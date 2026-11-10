"""Evidence-validated incremental extraction of architectural context."""

import json
import logging
import re
from importlib.resources import files
from typing import get_args

from server.runtimes.investigation.structured import parse_structured
from server.runtimes.repository.telemetry import measured_prompt

from .schemas import (
    KnowledgeCoverage,
    KnowledgeExtraction,
    RetrievalCategory,
)
from .state import ArchitectureContextState

logger = logging.getLogger(__name__)
_MAX_SECTIONS_PER_BATCH = 4
_QUOTE_SAMPLE_LIMIT = 160


def _section_payload(section):
    return {
        "section_id": section.section_id,
        "path": section.path,
        "start_line": section.start_line,
        "end_line": section.end_line,
        "headings": [heading.title for heading in section.headings],
        "lines": [
            {"line_number": number, "text": text}
            for number, text in enumerate(
                section.content.splitlines(keepends=True), start=section.start_line
            )
        ],
    }


def _prompt(instructions, schema, label, payload, stage):
    return measured_prompt(
        [
            (instructions + "\n", "instructions"),
            ("Response schema:\n", "framing"),
            (json.dumps(schema.model_json_schema(), ensure_ascii=False), "contracts"),
            (f"\n{label}:\n", "framing"),
            (json.dumps(payload, ensure_ascii=False), "source"),
        ],
        stage=stage,
    )


def _validate_section(item, section, sections_by_id):
    if item.section_id != section.section_id:
        raise ValueError("Extraction result section ID does not match its source")
    accepted_claims = []
    errors = []
    for claim in item.claims:
        try:
            evidence_ids = {evidence.section_id for evidence in claim.evidence}
            if evidence_ids != set(claim.section_ids) or section.section_id not in evidence_ids:
                raise ValueError("Claim evidence and section IDs must agree")
            if not evidence_ids <= sections_by_id.keys():
                raise ValueError("Claim evidence references a section outside its batch")
            reconstructed = []
            for evidence in claim.evidence:
                source_section = sections_by_id[evidence.section_id]
                lines = source_section.content.splitlines(keepends=True)
                first = evidence.start_line - source_section.start_line
                last = evidence.end_line - source_section.start_line
                if (
                    evidence.start_line < source_section.start_line
                    or evidence.end_line > source_section.end_line
                    or first < 0
                    or last < first
                    or last >= len(lines)
                ):
                    logger.warning(
                        "knowledge claim rejected section_id=%s reason=invalid_line_range lines=%s-%s quote_sample=%r",
                        section.section_id,
                        evidence.start_line,
                        evidence.end_line,
                        source_section.content[:_QUOTE_SAMPLE_LIMIT],
                    )
                    raise ValueError("Evidence line range is outside its original section")
                quote = "".join(lines[first : last + 1])
                if not quote.strip():
                    raise ValueError("Evidence line range reconstructed empty text")
                nonblank = [line.strip() for line in lines[first : last + 1] if line.strip()]
                if all(
                    re.fullmatch(r"#{1,6}(?:\s+.*)?|(?:=+|-+)", line)
                    for line in nonblank
                ) or (
                    len(nonblank) == 2
                    and re.fullmatch(r"=+|-+", nonblank[1])
                ):
                    raise ValueError("Evidence contains only a heading without supporting content")
                reconstructed.append(evidence.model_copy(update={"quote": quote}))
            accepted_claims.append(
                claim.model_copy(update={"evidence": reconstructed})
            )
        except (ValueError, KeyError) as error:
            errors.append(error)
            if "non_literal_quote" not in str(error):
                evidence = claim.evidence[0] if claim.evidence else None
                evidence_section = (
                    sections_by_id.get(evidence.section_id) if evidence else None
                )
                logger.warning(
                    "knowledge claim rejected section_id=%s reason=%s lines=%s-%s source_sample=%r",
                    section.section_id,
                    str(error),
                    evidence.start_line if evidence else None,
                    evidence.end_line if evidence else None,
                    evidence_section.content[:_QUOTE_SAMPLE_LIMIT] if evidence_section else "",
                )
    accepted_issues = []
    for issue in item.issues:
        try:
            if section.section_id not in issue.section_ids or not set(issue.section_ids) <= sections_by_id.keys():
                raise ValueError("Issue references must belong to its extraction batch")
            accepted_issues.append(issue)
        except (ValueError, KeyError) as error:
            errors.append(error)
            logger.warning("knowledge extraction issue rejected (%s): %s", type(error).__name__, error)
    return accepted_claims, accepted_issues, errors


def _validate_batch(result: KnowledgeExtraction, sections):
    by_id = {section.section_id: section for section in sections}
    outputs = {}
    invalid_ids = set()
    for item in result.sections:
        if item.section_id not in by_id:
            logger.warning("knowledge extraction returned unknown section %s", item.section_id)
        elif item.section_id in outputs:
            invalid_ids.add(item.section_id)
            logger.error("knowledge extraction duplicated section %s", item.section_id)
        else:
            outputs[item.section_id] = item
    return outputs, invalid_ids


def _unique(existing, additions):
    values = list(existing)
    seen = {item.model_dump_json() for item in values}
    for item in additions:
        key = item.model_dump_json()
        if key not in seen:
            values.append(item)
            seen.add(key)
    return values


def _documentary_sources(state, section_status):
    """Expose retrieval provenance, never inferred contents or filename relevance."""
    by_path = {}
    for section in state.get("retrieved_sections", []):
        by_path.setdefault(section.path, []).append({
            "section_id": section.section_id,
            "start_line": section.start_line,
            "end_line": section.end_line,
            "processing_status": section_status.get(section.section_id, "pending"),
        })
    return {
        "catalog_available": "documents" in state,
        "documents": [
            {
                "path": document.path,
                "line_count": document.line_count,
                "retrieved_sections": by_path.get(document.path, []),
            }
            for document in state.get("documents", [])
        ],
        "unretrieved_document_paths": [
            document.path for document in state.get("documents", [])
            if document.path not in by_path
        ],
    }


def _coverage_claim(claim):
    """Lossless claim selection; full evidence and rationale remain in state."""
    return {
        "category": claim.category,
        "subject": claim.subject,
        "statement": claim.statement,
        "certainty": claim.certainty,
        "constraint": claim.constraint,
        "references": [
            [evidence.section_id, evidence.start_line, evidence.end_line]
            for evidence in claim.evidence
        ],
    }


async def extract_knowledge(
    state: ArchitectureContextState, *, model
) -> ArchitectureContextState:
    """Extract supported claims, then assess all accumulated category coverage once."""
    pending_sections = []
    processed = set(state.get("processed_section_ids", []))
    seen = set()
    for section in state.get("retrieved_sections", []):
        if section.section_id not in processed and section.section_id not in seen:
            pending_sections.append(section)
            seen.add(section.section_id)

    if model is None:
        categories = list(get_args(RetrievalCategory))
        return {
            "knowledge": list(state.get("knowledge", [])),
            "knowledge_issues": list(state.get("knowledge_issues", [])),
            "processed_section_ids": list(state.get("processed_section_ids", [])),
            "covered_categories": list(state.get("covered_categories", [])),
            "pending_categories": list(state.get("pending_categories", categories)),
            "extraction_section_status": dict(state.get("extraction_section_status", {})),
            "coverage_assessment_status": state.get("coverage_assessment_status", "not_run"),
            "evaluated_categories": list(state.get("evaluated_categories", [])),
        }

    claims = list(state.get("knowledge", []))
    issues = list(state.get("knowledge_issues", []))
    processed_ids = list(state.get("processed_section_ids", []))
    section_status = dict(state.get("extraction_section_status", {}))
    for section_id in processed_ids:
        section_status.setdefault(section_id, "completed")
    stop_reason = None
    package = files(__package__).joinpath("prompts")
    extraction_instructions = package.joinpath("extract_knowledge.md").read_text(encoding="utf-8")
    coverage_instructions = package.joinpath("assess_coverage.md").read_text(encoding="utf-8")
    limit = model.limits.max_context_characters

    batches = []
    batch = []
    for section in pending_sections:
        candidate = [*batch, section]
        prompt = _prompt(
            extraction_instructions,
            KnowledgeExtraction,
            "Retrieved sections",
            [_section_payload(item) for item in candidate],
            "initial_extraction",
        )
        if len(prompt) <= limit and len(candidate) <= _MAX_SECTIONS_PER_BATCH:
            batch = candidate
        elif batch:
            batches.append(batch)
            batch = []
            single_prompt = _prompt(
                extraction_instructions, KnowledgeExtraction, "Retrieved sections",
                [_section_payload(section)], "initial_extraction",
            )
            if len(single_prompt) <= limit:
                batch = [section]
            else:
                stop_reason = "extraction_context_exhausted"
                section_status[section.section_id] = "failed"
        else:
            stop_reason = "extraction_context_exhausted"
            section_status[section.section_id] = "failed"
    if batch:
        batches.append(batch)

    for batch in batches:
        prompt = _prompt(
            extraction_instructions, KnowledgeExtraction, "Retrieved sections",
            [_section_payload(item) for item in batch], "initial_extraction",
        )
        try:
            response = await model.call(prompt, schema=KnowledgeExtraction)
            result = parse_structured(response, KnowledgeExtraction, native=False)
        except Exception:  # log and leave failed sections unprocessed
            logger.exception("knowledge extraction failed for sections=%s", [s.section_id for s in batch])
            stop_reason = "extraction_failed"
            section_status.update({section.section_id: "failed" for section in batch})
            continue
        try:
            outputs, invalid_ids = _validate_batch(result, batch)
        except (TypeError, ValueError):
            logger.exception("knowledge extraction response invalid")
            stop_reason = "extraction_failed"
            continue
        sections_by_id = {section.section_id: section for section in batch}
        for section in batch:
            output = outputs.get(section.section_id)
            if output is None:
                logger.error("knowledge extraction omitted section %s", section.section_id)
                stop_reason = "extraction_failed"
                section_status[section.section_id] = "failed"
                continue
            if section.section_id in invalid_ids:
                stop_reason = "extraction_failed"
                section_status[section.section_id] = "failed"
                continue
            valid_claims, valid_issues, errors = _validate_section(
                output, section, sections_by_id
            )
            claims = _unique(claims, valid_claims)
            issues = _unique(issues, valid_issues)
            if errors:
                stop_reason = "extraction_failed"
                section_status[section.section_id] = "partial"
            else:
                processed_ids.append(section.section_id)
                section_status[section.section_id] = "completed"

    categories = list(get_args(RetrievalCategory))
    assessments = None
    knowledge_payload = {
        "claims": [_coverage_claim(claim) for claim in claims],
        "issues": [issue.model_dump(mode="json") for issue in issues],
        "section_processing": section_status,
        "documentary_sources": _documentary_sources(state, section_status),
    }
    if not claims:
        categories = list(get_args(RetrievalCategory))
        return {
            "knowledge": claims,
            "knowledge_issues": issues,
            "processed_section_ids": list(dict.fromkeys(processed_ids)),
            "extraction_section_status": section_status,
            "covered_categories": [],
            "pending_categories": categories,
            "coverage_assessment_status": "not_run",
            "evaluated_categories": [],
            **({"context_stop_reason": stop_reason} if stop_reason else {}),
        }

    coverage_prompt = _prompt(
        coverage_instructions,
        KnowledgeCoverage,
        "Accumulated knowledge",
        knowledge_payload,
        "coverage_assessment",
    )
    if len(coverage_prompt) <= limit:
        try:
            response = await model.call(coverage_prompt, schema=KnowledgeCoverage)
            coverage = parse_structured(response, KnowledgeCoverage, native=False)
            assessments = {item.category: item for item in coverage.categories}
            coverage_status = "completed"
        except Exception:  # fail closed without inventing coverage
            logger.exception("knowledge coverage assessment failed")
            stop_reason = stop_reason or "coverage_assessment_failed"
            coverage_status = "failed"
    else:
        logger.warning(
            "compact coverage context exceeds limit: prompt_characters=%s max_context_characters=%s "
            "claims=%s issues=%s; coverage not run, no claims omitted",
            len(coverage_prompt), limit, len(claims), len(issues),
        )
        stop_reason = stop_reason or "coverage_context_exhausted"
        coverage_status = "not_run"

    has_pending_sections = any(
        section_status.get(section.section_id) != "completed"
        for section in state.get("retrieved_sections", [])
    ) or any(status != "completed" for status in section_status.values())
    evaluated = [
        category for category in categories
        if assessments is not None and assessments[category].sufficient
        and any(claim.category == category for claim in claims)
    ]
    covered = [] if has_pending_sections else evaluated
    return {
        "knowledge": claims,
        "knowledge_issues": issues,
        "processed_section_ids": list(dict.fromkeys(processed_ids)),
        "extraction_section_status": section_status,
        "coverage_assessment_status": coverage_status,
        "evaluated_categories": evaluated,
        "covered_categories": covered,
        "pending_categories": [category for category in categories if category not in covered],
        **({"context_stop_reason": stop_reason} if stop_reason else {}),
    }
