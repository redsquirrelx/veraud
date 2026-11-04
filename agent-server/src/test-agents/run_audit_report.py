"""Build report JSON offline from a saved /api/audits/{run_id} Blackboard snapshot."""

import argparse
import asyncio
import json
from pathlib import Path

from server.reporting import AuditReportRequest
from server.reporting.snapshot import (
    BlackboardSnapshot,
    report_from_snapshot,
)


async def build_report(snapshot, run_id):
    return await report_from_snapshot(BlackboardSnapshot.model_validate({**snapshot, "run_id": run_id}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="Saved Blackboard snapshot JSON")
    parser.add_argument("--run-id", help="Defaults to the snapshot's run_id")
    parser.add_argument("--output", type=Path, help="Write the report to this JSON file; default stdout")
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8-sig"))
    request = AuditReportRequest(run_id=args.run_id or snapshot.get("run_id", ""))
    report = asyncio.run(build_report(snapshot, request.run_id))
    document = report.model_dump_json(indent=2)
    if args.output:
        args.output.write_text(document + "\n", encoding="utf-8")
    else:
        print(document)


if __name__ == "__main__":
    main()
