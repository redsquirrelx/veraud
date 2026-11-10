"""Run independent patch scenarios against the configured LLM (provider costs apply).

    uv run python src/test-agents/run_finding_resolution_scenarios.py --scenario 003-fix-all --report report.json

Without --scenario, run the control and all 34 patches. Originals are never patched.
"""

import argparse
import asyncio
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from pydantic import ValidationError
from run_finding_resolution import FIXTURES, run

from server.agents.finding_resolution import FindingResolutionResult

DEFAULT_SUITE = FIXTURES / "example_repos" / "A"


def compare_result(request, state, expected):
    """Compare only ID/status; separately validate reasons and current citations."""
    final = state["final_result"]
    actual = {item.finding_id: item for item in final.results}
    matches, discrepancies, validation_errors = [], [], []
    for identifier in sorted(expected.keys() | actual.keys()):
        observed = actual[identifier].status if identifier in actual else None
        row = {"finding_id": identifier, "expected": expected.get(identifier), "actual": observed}
        (matches if expected.get(identifier) == observed else discrepancies).append(row)
    for result in final.results:
        records = [item for item in state["investigations"] if item.finding_id == result.finding_id]
        current = {reference.id for record in records for reference in record.evidence
            if any(reference.id == delivered.id and reference.snapshot_hash == response.snapshot_hash
                and reference.snapshot_hash == delivered.snapshot_hash
                and reference.file_id == delivered.file_id and reference.content_hash == delivered.content_hash
                for response in record.tool_results for delivered in response.evidence)}
        if not result.reason.strip():
            validation_errors.append({"finding_id": result.finding_id, "rule": "nonempty_reason"})
        if set(result.evidence_ids) - current:
            validation_errors.append({"finding_id": result.finding_id, "rule": "finding_local_current_evidence_ids"})
    try:
        FindingResolutionResult.model_validate(final.model_dump(), context={"request": request})
    except ValidationError:
        validation_errors.append({"rule": "FindingResolutionResult"})
    return {"passed": not discrepancies and not validation_errors, "matches": matches,
        "discrepancies": discrepancies, "validation_errors": validation_errors,
        "final_result": final.model_dump(mode="json"), "consumption": state["consumption"].model_dump(),
        "termination_reason": state["termination_reason"]}


async def run_scenarios(suite, selected, agent_config):
    oracle = json.loads((suite / "expected-results.json").read_text(encoding="utf-8-sig"))
    scenarios = [oracle["control"], *oracle["scenarios"]]
    unknown = set(selected) - {item["id"] for item in scenarios}
    if unknown:
        raise ValueError(f"Unknown scenarios: {sorted(unknown)}")
    reports = []
    for scenario in scenarios:
        if selected and scenario["id"] not in selected:
            continue
        report = {"scenario": scenario}
        try:
            with tempfile.TemporaryDirectory(prefix="finding-resolution-") as temporary:
                repository = Path(temporary) / "repository"
                shutil.copytree(suite / "fixture_A", repository, ignore=shutil.ignore_patterns(".git", "__pycache__"))
                if scenario["patch"]:
                    patch = (suite / scenario["patch"]).resolve()
                    if hashlib.sha256(patch.read_bytes()).hexdigest() != scenario["patch_sha256"]:
                        raise ValueError("Patch SHA-256 mismatch")
                    for arguments in (["--check"], []):
                        await asyncio.to_thread(subprocess.run, ["git", "apply", *arguments, str(patch)], cwd=repository,
                            check=True, capture_output=True, text=True)
                request, state, capture = await run(str(repository), str(suite / "findings.json"), agent_config, output=None)
                report.update(consumption=state["consumption"].model_dump(),
                    diagnostics=capture.diagnostics, traces=capture.traces)
                report.update(compare_result(request, state, scenario["expected"]))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            # Do not export provider messages, credentials or raw subprocess output.
            report.update(passed=False, error_type=type(error).__name__, matches=[], discrepancies=[],
                validation_errors=[{"rule": "scenario_execution_failed"}])
            report.setdefault("consumption", None)
        reports.append(report)
        print(f"{scenario['id']}: {'PASS' if report['passed'] else 'FAIL'}")
    return {"result_contract": "FindingResolutionResult", "scenarios": reports}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--agent-config", default="dummy")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run_scenarios(args.suite.resolve(), args.scenario, args.agent_config))
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(0 if all(item["passed"] for item in report["scenarios"]) else 1)
