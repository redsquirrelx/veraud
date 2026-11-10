"""Evaluate the patch suite with the configured LLM (provider costs apply).

    uv run python src/test-agents/run_finding_resolution_patch_suite.py
    uv run python src/test-agents/run_finding_resolution_patch_suite.py --scenario 003-fix-all --report-dir reports

The control is always included. Repeat --scenario or supply several IDs to select
patches; omit it to run all. report.json and report.csv are checkpointed after each
scenario. No staging/commits or changes to the original fixture are performed.
"""

import argparse
import asyncio
import csv
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from run_finding_resolution import load_findings, run
from run_finding_resolution_scenarios import DEFAULT_SUITE, compare_result

from server.agents.finding_resolution import (
    FindingResolutionRequest,
    FindingResolutionResult,
)

DEFAULT_FINDINGS = DEFAULT_SUITE / "findings.json"
STATUSES = {"resolved", "persists", "inconclusive"}
CSV_FIELDS = ["scenario_id", "outcome", "finding_id", "expected", "actual", "match",
    "reason", "evidence_ids", "evidence", "validation_errors", "scenario_accuracy",
    "scenario_accounted_tokens", "scenario_estimated_tokens", "scenario_model_calls",
    "scenario_tool_calls", "finding_accounted_tokens", "elapsed_seconds", "error_type"]


def load_suite(suite, findings, selected):
    """Inspect the real oracle shape without rewriting its metadata or expectations."""
    oracle = json.loads((suite / "expected-results.json").read_text(encoding="utf-8-sig"))
    scenarios = [oracle["control"], *oracle["scenarios"]]
    identifiers = [item["id"] for item in scenarios]
    if len(identifiers) != len(set(identifiers)) or oracle["control"]["patch"] is not None:
        raise ValueError("Invalid control or duplicate scenario IDs.")
    unknown = set(selected) - set(identifiers)
    if unknown:
        raise ValueError(f"Unknown scenarios: {sorted(unknown)}")
    requested_findings = findings
    if findings is None:
        findings = suite / "findings.json"
    if not findings.is_file():
        raise FileNotFoundError(f"Findings file not found: {findings}")
    originals = load_findings(findings)
    request = FindingResolutionRequest(repository_path=str(suite / "fixture_A"), findings=originals)
    for scenario in scenarios:
        expected = scenario["expected"]
        if not isinstance(expected, dict) or set(expected.values()) - STATUSES:
            raise ValueError(f"Invalid expected ID/status map: {scenario['id']}")
        # Validate exact original-ID coverage using the existing contract; oracle
        # rows intentionally have no fixed explanation or evidence requirements.
        FindingResolutionResult.model_validate({"results": [{"finding_id": identifier,
            "status": status, "reason": "Oracle status, not an observed result.", "evidence_ids": []}
            for identifier, status in expected.items()]}, context={"request": request})
    chosen = [item for item in scenarios if not selected or item["id"] in selected or item is oracle["control"]]
    return oracle, chosen, findings.resolve(), requested_findings


def prepare_repository(suite, scenario, repository):
    shutil.copytree(suite / "fixture_A", repository, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    if not scenario["patch"]:
        return
    patch = (suite / scenario["patch"]).resolve()
    if not patch.is_relative_to(suite.resolve()) or patch.suffix != ".patch":
        raise ValueError("Patch must be a .patch file within the suite.")
    if scenario.get("patch_sha256") and hashlib.sha256(patch.read_bytes()).hexdigest() != scenario["patch_sha256"]:
        raise ValueError("Patch SHA-256 mismatch.")
    for arguments in (["--check"], []):
        subprocess.run(["git", "apply", *arguments, str(patch)], cwd=repository,
            check=True, capture_output=True, timeout=60)


def finding_rows(scenario, state, comparison):
    actual = {item.finding_id: item for item in state["final_result"].results}
    records = {item.finding_id: item for item in state["investigations"]}
    rows = []
    for identifier in sorted(scenario["expected"].keys() | actual.keys()):
        result, record = actual.get(identifier), records.get(identifier)
        expected = scenario["expected"].get(identifier)
        status = result.status if result else None
        rows.append({"finding_id": identifier, "expected": expected, "actual": status,
            "match": identifier in actual and status == expected,
            "reason": result.reason if result else "No result returned.",
            "evidence_ids": result.evidence_ids if result else [],
            "evidence": [reference.model_dump(mode="json") for reference in record.evidence
                if result and reference.id in result.evidence_ids] if record else [],
            "validation_errors": [item for item in comparison["validation_errors"]
                if item.get("finding_id", identifier) == identifier],
            "consumption": record.consumption.model_dump() if record else None})
    return rows


def summarize(reports):
    matches = sum(len(item.get("matches", [])) for item in reports)
    total = sum(len(item["scenario"]["expected"]) + sum(
        row["finding_id"] not in item["scenario"]["expected"] for row in item.get("findings", [])) for item in reports)
    return {"scenarios_completed": len(reports), "passed": sum(item["outcome"] == "passed" for item in reports),
        "errors": sum(item["outcome"].endswith("_error") for item in reports),
        "discrepant_scenarios": sum(bool(item.get("discrepancies")) for item in reports),
        "matching_statuses": matches, "total_statuses": total, "status_accuracy": matches / total if total else 0,
        "usage_unavailable": sum(item.get("consumption") is None for item in reports),
        "consumption": {field: sum((item.get("consumption") or {}).get(field, 0) for item in reports)
            for field in ("accounted_tokens", "estimated_tokens", "model_calls", "tool_calls")}}


def save_reports(report, directory):
    """Checkpoint each completed scenario. CSV token columns are scenario totals."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (directory / "report.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for scenario in report["scenarios"]:
            usage = scenario.get("consumption") or {}
            rows = scenario.get("findings") or [{"finding_id": key, "expected": status, "match": False}
                for key, status in scenario["scenario"]["expected"].items()]
            for row in rows:
                writer.writerow({"scenario_id": scenario["scenario"]["id"], "outcome": scenario["outcome"],
                    **{key: row.get(key) for key in ("finding_id", "expected", "actual", "match", "reason")},
                    **{key: json.dumps(row.get(key, []), ensure_ascii=False)
                        for key in ("evidence_ids", "evidence", "validation_errors")},
                    "scenario_accuracy": scenario.get("status_accuracy"),
                    **{f"scenario_{key}": usage.get(key) for key in
                        ("accounted_tokens", "estimated_tokens", "model_calls", "tool_calls")},
                    "finding_accounted_tokens": (row.get("consumption") or {}).get("accounted_tokens"),
                    "elapsed_seconds": scenario["elapsed_seconds"], "error_type": scenario.get("error_type")})


async def run_suite(suite=DEFAULT_SUITE, *, findings=None, selected=(), agent_config="dummy", report_dir=Path("patch-suite-report")):
    suite, report_dir = Path(suite).resolve(), Path(report_dir).resolve()
    if report_dir.is_relative_to(suite / "fixture_A"):
        raise ValueError("Reports must be written outside the original fixture.")
    oracle, scenarios, findings, requested = load_suite(suite, Path(findings) if findings is not None else None, selected)
    report = {"result_contract": "FindingResolutionResult", "oracle": oracle,
        "suite": str(suite), "findings_path": str(findings),
        "requested_findings_path": str(requested) if requested else None,
        "agent_config": agent_config, "selected_scenarios": [item["id"] for item in scenarios], "scenarios": []}
    report["summary"] = summarize([])
    save_reports(report, report_dir)
    for number, scenario in enumerate(scenarios, 1):
        print(f"\n[{number}/{len(scenarios)}] {scenario['id']} — {scenario['title']}", flush=True)
        started, stage = time.perf_counter(), "patch"
        result = {"scenario": scenario, "consumption": None, "findings": [], "matches": [], "discrepancies": []}
        try:
            with tempfile.TemporaryDirectory(prefix="finding-resolution-patch-") as temporary:
                repository = Path(temporary) / "repository"
                await asyncio.to_thread(prepare_repository, suite, scenario, repository)
                stage = "agent"
                request, state, capture = await run(str(repository), str(findings), agent_config, output=None)
                result.update(consumption=state["consumption"].model_dump(), diagnostics=capture.diagnostics,
                    traces=capture.traces, limitations=state["limitations"])
                stage = "comparison"
                comparison = compare_result(request, state, scenario["expected"])
                result.update(comparison)
                result["findings"] = finding_rows(scenario, state, comparison)
                result["outcome"] = "validation_error" if comparison["validation_errors"] else (
                    "passed" if comparison["passed"] else "discrepancy")
        except Exception as error:  # noqa: BLE001 - isolate scenarios; never export raw provider errors.
            result.update(passed=False, outcome=f"{stage}_error", error_type=type(error).__name__)
            if isinstance(error, subprocess.CalledProcessError):
                result["patch_returncode"] = error.returncode
        result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        denominator = len(result["findings"]) or len(scenario["expected"])
        result["status_accuracy"] = len(result["matches"]) / denominator if denominator else 0
        for row in result["findings"]:
            print(f"  {'OK' if row['match'] else 'DISCREPANCIA'} {row['finding_id']}: "
                f"esperado={row['expected']}, obtenido={row['actual']}", flush=True)
        if result["outcome"].endswith("_error"):
            print(f"  ERROR [{result['outcome']}]: {result.get('error_type', 'invalid_result')}", flush=True)
            for issue in result.get("validation_errors", []):
                print(f"    {issue.get('finding_id', 'resultado')}: {issue['rule']}", flush=True)
        print(f"  {result['outcome']} | Exactitud de estados: {len(result['matches'])}/{denominator} "
            f"({result['status_accuracy']:.1%}) | Tokens: {(result['consumption'] or {}).get('accounted_tokens', 'no disponibles')}", flush=True)
        report["scenarios"].append(result)
        report["summary"] = summarize(report["scenarios"])
        save_reports(report, report_dir)
    summary = report["summary"]
    print(f"\nRESUMEN: {summary['passed']}/{summary['scenarios_completed']} escenarios correctos; "
        f"{summary['discrepant_scenarios']} con discrepancias; {summary['errors']} errores. "
        f"Exactitud global: {summary['status_accuracy']:.1%}. "
        f"Tokens contabilizados: {summary['consumption']['accounted_tokens']}.\nReportes: {report_dir}", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--findings", type=Path, help=f"Original findings (default: {DEFAULT_FINDINGS}; follows --suite)")
    parser.add_argument("--scenario", action="extend", nargs="+", default=[], help="Scenario IDs; control is always included")
    parser.add_argument("--agent-config", default="dummy")
    parser.add_argument("--report-dir", type=Path, default=Path("patch-suite-report"))
    args = parser.parse_args()
    report = asyncio.run(run_suite(args.suite, findings=args.findings, selected=args.scenario,
        agent_config=args.agent_config, report_dir=args.report_dir))
    return 0 if all(item["outcome"] == "passed" for item in report["scenarios"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
