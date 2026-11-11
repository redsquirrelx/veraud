"""Stored documentary context remains canonical and revision-bound at ingress."""

from typing import get_args

import pytest

from server.agents.architecture_context.schemas import RetrievalCategory
from server.app.errors import InvalidConfigError
from server.app.quality_audit_definition import parse_input


def context(commit="a" * 40, status="partial"):
    return {
        "schema_version": "1", "document_index": {"index_id": "index", "repository_id": "repository", "commit": commit},
        "knowledge": [], "knowledge_issues": [], "covered_categories": [],
        "pending_categories": list(get_args(RetrievalCategory)), "evaluated_categories": [],
        "coverage_assessment_status": "not_run", "consulted_documents": [], "section_paths": {},
        "validation_errors": [], "execution_status": status, "finalization_reason": "incomplete_coverage",
        "execution_error": None,
    }


def test_saved_partial_context_is_forwarded_without_promoting_coverage():
    source = context()
    parsed = parse_input({"root_path": "checkout", "commit_hash": "a" * 40,
                          "attributes": ["maintainability", "security"],
                          "request": {"documented_architecture": source}})
    assert parsed.request.documented_architecture.model_dump(mode="json") == source
    assert parsed.request.documented_architecture.execution_status == "partial"


@pytest.mark.parametrize("source", [context("b" * 40), context(status="failed"), {**context(), "document_index": None}])
def test_mismatched_or_failed_context_is_rejected_before_execution(source):
    with pytest.raises(InvalidConfigError, match="context"):
        parse_input({"root_path": "checkout", "commit_hash": "a" * 40, "attributes": ["maintainability"],
                     "request": {"documented_architecture": source}})


def test_security_does_not_require_maintainability_context():
    assert parse_input({"root_path": "checkout", "commit_hash": "a" * 40, "attributes": ["security"]}).attributes == ["security"]
