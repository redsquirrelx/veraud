"""Real-model regression matrix and Polleria evaluation. Never repairs audited code.

Run from agent-server: uv run python src/test-agents/evaluate_probe_node.py polleria
or: ... regression (civitaspermit/galleryforge/harborcold/vetoria).
Results are append-only by timestamp under ignored artifacts/testability-probe/.
"""

import argparse
import asyncio
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from server.agents.testability_probe.agent import TestabilityProbeAgent
from server.agents.testability_probe.config import TestabilityProbeConfig
from server.agents.testability_probe.llm_client import ProviderProbeLLMClient
from server.agents.testability_probe.schemas import ProbeRequest
from server.config import tracing as _tracing


def _enable_tracing() -> None:
    try:
        _tracing.setup()
    except Exception as error:  # noqa: BLE001 - evaluation runs are still usable without tracing
        print(f"warning: tracing disabled ({error})", flush=True)


async def main(selection, finding_ids=None):
    stamp = datetime.now(UTC).strftime("node-%Y%m%dT%H%M%S")
    root = Path("artifacts/testability-probe")
    polleria = Path("../appdata/workspace/1373928788-Cesar-Sanchez-sof-Polleria").resolve()
    cases = ([
        ("polleria", polleria,
         Path("../appdata/workspace/.veraud-artifacts/28709a1c587b46d6a12260a65c37dce7/verification-suite/probe-input.json"))]
        if selection == "polleria" else [
            ("civitaspermit-01", Path("examples/testcontrollability/civitaspermit-01/repository"),
             Path("artifacts/test-controllability-civitaspermit-004.json")),
            ("galleryforge-01", Path("examples/testcontrollability/galleryforge-01/repository"),
             Path("artifacts/test-controllability-galleryforge-001.json")),
            ("harborcold-01", Path("examples/testisolation/harborcold-01/repository"),
             Path("artifacts/test-isolation-harborcold-012.json")),
            ("vetoria-01", Path("examples/testisolation/vetoria-01/repository"),
             Path("artifacts/test-isolation-vetoria-003.json"))])
    for name, repo, findings in cases:
        output = root / name / stamp
        output.mkdir(parents=True, exist_ok=False)
        if finding_ids:
            payload = json.loads(findings.read_text(encoding="utf-8"))
            payload["findings"] = [f for f in payload.get("findings", []) if f.get("id") in finding_ids]
            if not payload["findings"]:
                raise ValueError("Requested findings are absent from the evaluation input")
            findings = output / "selected-findings.json"
            findings.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        before = (await asyncio.to_thread(subprocess.run, ["git", "-C", str(repo), "status", "--porcelain"],
                                           capture_output=True, text=True, check=True)).stdout
        config = TestabilityProbeConfig(allow_local_unsafe_execution=True,
                                       max_investigation_iterations=3,
                                       provider_request_interval_seconds=6)
        try:
            client = ProviderProbeLLMClient(config, "dummy")
            if json.loads(findings.read_text(encoding="utf-8")).get("findings"):
                # Fail early on auth/quota rather than repeating a rejected call per finding.
                await client.complete("access_check", "Reply with OK.")
            result = await TestabilityProbeAgent(config, client).run(ProbeRequest(
                findings_path=str(findings), repo_path=str(repo), output_path=str(output), audit_id=name))
            (output / "result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
            print(name, result.termination_reason, dict(Counter(v.outcome for v in result.verifications)),
                  result.metrics, str(output), flush=True)
        except Exception as error:  # noqa: BLE001 - preserve failed experimental runs without exposing credentials
            (output / "blocked.json").write_text(json.dumps({"error_type": type(error).__name__}), encoding="utf-8")
            print(name, "blocked", type(error).__name__, flush=True)
        after = (await asyncio.to_thread(subprocess.run, ["git", "-C", str(repo), "status", "--porcelain"],
                                          capture_output=True, text=True, check=True)).stdout
        (output / "repository-integrity.json").write_text(json.dumps({"unchanged": before == after}), encoding="utf-8")
        if before != after:
            raise RuntimeError("Audited repository status changed; stopping experiments")


if __name__ == "__main__":
    _enable_tracing()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", choices=["polleria", "regression"])
    parser.add_argument("--finding", action="append", help="Generate only these finding IDs, preserving the selected input")
    args = parser.parse_args()
    asyncio.run(main(args.selection, args.finding))
