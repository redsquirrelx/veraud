"""Routing of audit-export findings between the verification-suite generators.

Maintainability is the attribute; the subcharacteristic is the routing key:
``testability`` findings go to the TestabilityProbeAgent, other maintainability
findings the FindingTestGenerationAgent consumes go to it, and everything else
is reported as unsupported (never silently dropped).
"""

from typing import Any, Literal

TESTABILITY_CRITERIA = {"test-isolation", "test-controllability"}
MAINTAINABILITY_CRITERIA = {"architectural-boundaries", "single-responsibility"}

Agent = Literal["probe", "ftg", "unsupported"]

__all__ = [
    "MAINTAINABILITY_CRITERIA",
    "TESTABILITY_CRITERIA",
    "Agent",
    "criterion_id_of",
    "group_of",
    "route_agent",
    "split_findings",
]


def _read_attr(finding: Any, name: str) -> str:
    if isinstance(finding, dict):
        value = finding.get(name)
    else:
        value = getattr(finding, name, None)
    if isinstance(value, dict):  # criterion may be nested {id, ...}
        value = value.get("id")
    return str(value).strip() if value not in (None, "") else ""


def criterion_id_of(finding: Any) -> str:
    direct = _read_attr(finding, "criterion_id") or _read_attr(finding, "criterion")
    return direct.strip().lower()


def group_of(finding: Any) -> str:
    sub = _read_attr(finding, "subcharacteristic").lower()
    if sub:
        return sub
    crit = criterion_id_of(finding)
    return crit or "other"


def route_agent(finding: Any) -> Agent:
    group = group_of(finding)
    crit = criterion_id_of(finding)
    if group == "testability" or crit in TESTABILITY_CRITERIA:
        return "probe"
    if crit in MAINTAINABILITY_CRITERIA:
        return "ftg"
    return "unsupported"


def split_findings(findings: list[Any]) -> dict[str, list[Any]]:
    buckets: dict[str, list[Any]] = {"probe": [], "ftg": [], "unsupported": []}
    for finding in findings:
        buckets[route_agent(finding)].append(finding)
    return buckets
