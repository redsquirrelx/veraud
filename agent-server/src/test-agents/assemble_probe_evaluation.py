"""Assemble validated evaluation batches without changing any generated test code.

Original artifacts remain intact; duplicate verification IDs are renamed in metadata only.
The final frozen ZIP must cover every input finding and execute without errors.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from server.agents.testability_probe.config import TestabilityProbeConfig
from server.agents.testability_probe.input_adapter import load_probe_document
from server.agents.testability_probe.packaging import build_suite
from server.agents.testability_probe.schemas import (
    PlannedVerification,
    ValidationRecord,
    VerificationResult,
)
from server.agents.testability_probe.validate import validate_zip


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    document, diagnostics = load_probe_document(args.findings)
    if document is None or not diagnostics.ok:
        raise ValueError("Invalid findings document")
    plans, candidates, records, results, provenance = [], [], [], [], []
    ids, paths = set(), set()
    for artifact in args.artifacts:
        batch = json.loads((artifact / "result.json").read_text(encoding="utf-8"))
        batch_candidates = {c["verification_id"]: c for c in json.loads((artifact / "candidates.json").read_text(encoding="utf-8"))}
        batch_records = {r["verification_id"]: r for r in batch["validation_records"]}
        batch_results = {r["verification_id"]: r for r in batch["verifications"]}
        for raw_plan in json.loads((artifact / "plans.json").read_text(encoding="utf-8")):
            old_id = raw_plan["verification_id"]
            record = dict(batch_records[old_id])
            if record["status"] not in ("validated_red", "validated_red_green"):
                raise ValueError(f"Unvalidated test in {artifact}: {old_id}")
            new_id = old_id
            if new_id in ids:
                index = len(ids) + 1
                while f"probe-{index:03d}" in ids:
                    index += 1
                new_id = f"probe-{index:03d}"
            ids.add(new_id)
            candidate = dict(batch_candidates[old_id])
            if candidate["test_path"] in paths:
                raise ValueError("Duplicate test path; refusing to overwrite a generated test")
            paths.add(candidate["test_path"])
            result = dict(batch_results[old_id])
            for item in (raw_plan, candidate, record, result):
                item["verification_id"] = new_id
            plans.append(PlannedVerification.model_validate(raw_plan))
            candidates.append(candidate)
            records.append(ValidationRecord.model_validate(record))
            results.append(VerificationResult.model_validate(result))
            provenance.append({"artifact": str(artifact), "original_id": old_id, "verification_id": new_id,
                               "source_sha256": hashlib.sha256(candidate["content"].encode()).hexdigest()})
    covered = {p.finding_id for p in plans}
    expected = {f.id for f in document.findings}
    if covered != expected:
        raise ValueError(f"Coverage mismatch: missing={sorted(expected - covered)}, extra={sorted(covered - expected)}")
    before = subprocess.check_output(["git", "-C", str(args.repo), "status", "--porcelain"])
    try:
        manifest, archive = build_suite(document, plans, candidates, records, diagnostics.limitations,
                                         args.output / "verification-suite.zip", results=results)
        for name, payload in (("plans.json", [p.model_dump() for p in plans]),
                              ("candidates.json", candidates), ("provenance.json", provenance)):
            (args.output / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        report = validate_zip(archive, args.repo, None, TestabilityProbeConfig(allow_local_unsafe_execution=True))
        (args.output / "execution.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        failed = [v for v in report["verifications"] if v["status"] != "VIOLATION_PRESENT"]
        if failed:
            raise RuntimeError(f"Baseline regression: {[(v['verification_id'], v['status']) for v in failed]}")
        print(archive, len(manifest.verifications), "VIOLATION_PRESENT; all input findings covered")
    finally:
        after = subprocess.check_output(["git", "-C", str(args.repo), "status", "--porcelain"])
        (args.output / "repository-integrity.json").write_text(json.dumps({"unchanged": before == after}), encoding="utf-8")
        if before != after:
            raise RuntimeError("Audited repository status changed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    parser.add_argument("--findings", required=True, type=Path)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    main(parser.parse_args())
