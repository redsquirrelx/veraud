"""Replay recorded generated tests through execution and real-model repair, without regeneration.

Accepts any probe artifact directory/repository; never edits original artifacts or repository files.
This focused evaluation is useful when provider quota prevents repeating planning/investigation.
"""

import argparse
import asyncio
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from server.agents.testability_probe.config import TestabilityProbeConfig
from server.agents.testability_probe.execution import TestabilityProbeExecution
from server.agents.testability_probe.llm_client import ProviderProbeLLMClient
from server.agents.testability_probe.schemas import PlannedVerification, ProbeRequest
from server.agents.testability_probe.validate import validate_zip


async def main(args):
    output = args.output or args.artifact / datetime.now(UTC).strftime("repair-replay-%Y%m%dT%H%M%S")
    output.mkdir(parents=True, exist_ok=False)
    candidates = json.loads((args.artifact / "candidates.json").read_text(encoding="utf-8"))
    by_id = {c["verification_id"]: c for c in candidates}
    for overlay in args.overlay:
        for candidate in json.loads((overlay / "candidates.json").read_text(encoding="utf-8")):
            old = by_id.get(candidate["verification_id"])
            if old is None or any(old.get(key) != candidate.get(key)
                                  for key in ("finding_id", "test_path", "test_name")):
                raise ValueError("Repair overlay must preserve the original verification identity")
            by_id[candidate["verification_id"]] = candidate
    candidates = list(by_id.values())
    candidates = [c for c in candidates if c.get("content") and (not args.only or c["verification_id"] in args.only)]
    ids = {c["verification_id"] for c in candidates}
    plans = [PlannedVerification.model_validate(p) for p in json.loads(
        (args.plans or args.artifact / "plans.json").read_text(encoding="utf-8")) if p["verification_id"] in ids]
    (output / "plans.json").write_text(json.dumps([p.model_dump() for p in plans], indent=2), encoding="utf-8")
    (output / "provenance.json").write_text(json.dumps({
        "seed": str(args.artifact), "overlays": [str(p) for p in args.overlay],
        "reuse_unchanged_verdicts": args.reuse_verdicts,
    }, indent=2), encoding="utf-8")
    config = TestabilityProbeConfig(allow_local_unsafe_execution=True, provider_request_interval_seconds=12)
    execution = TestabilityProbeExecution(config, ProviderProbeLLMClient(config, "dummy"))
    request = ProbeRequest(findings_path=str(args.findings), repo_path=str(args.repo), output_path=str(output))
    before = await asyncio.to_thread(subprocess.check_output, ["git", "-C", str(args.repo), "status", "--porcelain"])
    state = {"request": request}
    try:
        state.update(execution.prepare_input(state))
        for candidate in candidates:
            candidate.update(classification=None, outcome=None, attempts=1, tool_calls=0)
            if not args.reuse_verdicts:
                candidate.update(verdict_key=None, llm_verdict=None)
        state.update(plans=plans, candidates=candidates)
        state.update(execution.execute_tests(state))
        state.update(await execution.evaluate(state))
        while execution._route_evaluated(state) == "repair":
            state.update(await execution.repair(state))
            state.update(await execution.evaluate(state))
        state.update(execution.finalize(state))
        result = state["result"]
        (output / "result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
        report = validate_zip(Path(result.output_zip), args.repo, None, config)
        (output / "execution.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(output, [(v["verification_id"], v["status"]) for v in report["verifications"]], flush=True)
    finally:
        after = await asyncio.to_thread(subprocess.check_output, ["git", "-C", str(args.repo), "status", "--porcelain"])
        (output / "repository-integrity.json").write_text(json.dumps({"unchanged": before == after}), encoding="utf-8")
        if before != after:
            raise RuntimeError("Audited checkout status changed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--findings", required=True, type=Path)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--only", action="append")
    parser.add_argument("--plans", type=Path, help="Explicit plan artifact for older replays without plans.json")
    parser.add_argument("--overlay", type=Path, action="append", default=[], help="Identity-preserving repaired candidates")
    parser.add_argument("--output", type=Path, help="New artifact directory; existing directories are never overwritten")
    parser.add_argument("--reuse-verdicts", action="store_true", help="Reuse saved assessments only when code hash and backend classification match")
    asyncio.run(main(parser.parse_args()))
