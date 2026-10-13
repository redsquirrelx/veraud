"""Workspace evaluation: structural proxies plus explicit semantic review cards."""

import hashlib
import json

from .context import walk_contracts
from .schemas import AnalysisClaim


def evaluate_run(
    result,
    snapshot,
    reference,
    *,
    protocol_smoke=False,
    input_price=None,
    output_price=None,
):
    report = result.report
    claims = {
        record.id: record
        for finding in result.validated_findings
        for record in walk_contracts(finding)
        if isinstance(record, AnalysisClaim)
    }
    if report is not None:
        claims.update(
            {
                record.id: record
                for record in walk_contracts(report)
                if isinstance(record, AnalysisClaim)
            }
        )
    retrievals = {record.id: record for record in result.retrieved_evidence}
    evidence = {record.id: record for record in snapshot.evidence}
    paths = {source.id: source.path for source in snapshot.files}
    citations = []
    for claim in claims.values():
        for identifier in claim.evidence_ids:
            record = retrievals.get(identifier) or evidence.get(identifier)
            citations.append(
                {
                    "claim_id": claim.id,
                    "evidence_id": identifier,
                    "valid": record is not None,
                    "path": paths.get(record.file_id) if record is not None else None,
                    "start_line": record.start_line if record is not None else None,
                    "end_line": record.end_line if record is not None else None,
                    "inspected_source": getattr(record, "kind", None) == "source",
                }
            )
    locations = [
        record for record in citations if record["valid"] and record["inspected_source"]
    ]
    commit_matches = (
        reference.get("commit") is None
        or reference["commit"] == snapshot.repository.commit
    )
    covered = []
    for fact in reference.get("expected_facts", []):
        for location in fact.get("evidence", []):
            path, span = location.rsplit(":", 1)
            start, _, end = span.partition("-")
            if any(
                record["path"] == path
                and record["start_line"] <= int(end or start)
                and record["end_line"] >= int(start)
                for record in locations
            ):
                covered.append(fact["id"])
                break
    component_paths = {
        paths[identifier]
        for component in (report.functional_components if report else ())
        for identifier in component.file_ids
    }
    expected_components = set(reference.get("key_components", []))
    fingerprint = hashlib.sha256(
        json.dumps(
            sorted((claim.statement, claim.status) for claim in claims.values())
        ).encode()
    ).hexdigest()
    return {
        "case_id": reference["id"],
        "execution_mode": "protocol_smoke" if protocol_smoke else "model",
        "completion_status": result.completion_status,
        "reference_commit_matches": commit_matches,
        "snapshot_hash": snapshot.repository.snapshot_hash,
        "actual_commit": snapshot.repository.commit,
        "usage": result.usage.model_dump(mode="json"),
        "factual_fingerprint": fingerprint,
        "estimated_cost_usd": (
            result.usage.input_tokens * input_price
            + result.usage.output_tokens * output_price
        )
        / 1_000_000
        if result.usage.input_tokens is not None
        and result.usage.output_tokens is not None
        and input_price is not None
        and output_price is not None
        else None,
        "execution_issue_categories": [
            issue.category for issue in result.execution_issues
        ],
        "metrics": {
            "valid_citation_rate": sum(record["valid"] for record in citations)
            / len(citations)
            if citations
            else None,
            "source_citation_rate": len(locations) / len(citations)
            if citations
            else None,
            "reference_location_coverage": len(covered)
            / len(reference.get("expected_facts", []))
            if commit_matches and reference.get("expected_facts")
            else None,
            "reference_component_coverage": len(component_paths & expected_components)
            / len(expected_components)
            if commit_matches and expected_components
            else None,
            "covered_reference_fact_locations": covered if commit_matches else [],
            "supported_claim_count": sum(
                claim.status == "supported" for claim in claims.values()
            ),
            "unresolved_question_count": len(result.unresolved_questions),
        },
        "semantic_review": {
            "status": "not_applicable_protocol_smoke"
            if protocol_smoke
            else "pending_human_review",
            "reference_facts": reference.get("expected_facts", []),
            "claims": [claim.model_dump(mode="json") for claim in claims.values()],
            "citations": citations,
            "criteria": [
                "Does the cited source support the responsibility or flow?",
                "Are runtime wiring and unresolved steps stated accurately?",
                "Would these findings help an architect investigate boundaries?",
            ],
        },
        "limitations": [
            "Citation and source-location overlap are structural proxies, not semantic correctness scores.",
            "Reference components/facts are curated minimums, not exhaustive coverage.",
            "Unknown token usage remains null; extraction and investigation omissions remain explicit.",
        ],
        "result": result.model_dump(mode="json"),
    }


def summarize_evaluation(records):
    case_ids = sorted({record["case_id"] for record in records})
    return {
        "runs": records,
        "summary": {
            "run_count": len(records),
            "case_count": len(case_ids),
            "status_counts": {
                status: sum(record["completion_status"] == status for record in records)
                for status in ("complete", "partial", "failed")
            },
            "repeat_stability": {
                case_id: len(
                    {
                        record["factual_fingerprint"]
                        for record in records
                        if record["case_id"] == case_id
                    }
                )
                == 1
                if sum(record["case_id"] == case_id for record in records) > 1
                else None
                for case_id in case_ids
            },
            "model_calls": sum(record["usage"]["model_calls"] for record in records),
            "tool_calls": sum(record["usage"]["tool_calls"] for record in records),
            "semantic_quality": "unscored_pending_review",
        },
    }
