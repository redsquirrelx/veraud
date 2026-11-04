from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from types import SimpleNamespace

import httpx
import pytest

from server.benchmark import pacing
from server.runtimes.investigation.provider import (
    provider_diagnostic,
    retry_delay,
    retry_hint,
)


def error(headers=None, details=None):
    value = RuntimeError("PRIVATE_PAYLOAD_MUST_NOT_BE_LOGGED")
    value.response = SimpleNamespace(headers=httpx.Headers(headers or {}))
    value.details = details or {}
    value.status_code = 429
    return value


@pytest.mark.parametrize("headers, details, seconds, source", [
    ({"Retry-After": "69273"}, {}, 69273, "retry-after.seconds"),
    ({"retry-after-ms": "69273"}, {}, 69.273, "retry-after-ms"),
    ({}, {"error": {"details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "69.273s"}]}},
        69.273, "google.rpc.RetryInfo.retryDelay"),
])
def test_retry_units_and_sources_are_preserved(headers, details, seconds, source):
    value = error(headers, details)
    hint = retry_hint(value)
    assert hint.seconds == pytest.approx(seconds)
    assert hint.source == source
    diagnostic = provider_diagnostic(value)
    assert f"retry_after_source={source}" in diagnostic
    assert "PRIVATE" not in diagnostic


def test_http_date_is_converted_as_a_date_instead_of_a_numeric_duration(monkeypatch):
    now = datetime(2026, 10, 17, 4, 45, tzinfo=UTC)

    class FixedDate(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(pacing, "datetime", FixedDate)
    hint = retry_hint(error({"Retry-After": format_datetime(now + timedelta(seconds=60), usegmt=True)}))
    assert hint.seconds == 60 and hint.source == "retry-after.http-date"


def test_original_response_takes_precedence_over_wrapper_retry_metadata():
    original = error(details={"details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "5s"}]})
    wrapper = error(headers={"Retry-After": "69273"})
    wrapper.__cause__ = original
    assert retry_delay(wrapper) == 5
    assert retry_hint(wrapper).source == "google.rpc.RetryInfo.retryDelay"


def test_diagnostic_identifies_the_quota_without_dumping_body_or_dimensions():
    value = error(details={"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaDimensions": {"project": "PRIVATE_PROJECT"}, "description": "PRIVATE_DESCRIPTION",
        }]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "69273s"},
    ]}})
    diagnostic = provider_diagnostic(value)
    assert "quota_window=day" in diagnostic
    assert "quota_id=GenerateRequestsPerDayPerProjectPerModel-FreeTier" in diagnostic
    assert "retry_after_seconds=69273" in diagnostic
    assert "retry_after_source=google.rpc.RetryInfo.retryDelay" in diagnostic
    assert "PRIVATE" not in diagnostic


def test_malformed_retry_hints_do_not_become_a_cooldown():
    for headers in ({"Retry-After": "nan"}, {"Retry-After": "-1"}, {"retry-after-ms": "inf"}):
        assert retry_hint(error(headers)) is None
