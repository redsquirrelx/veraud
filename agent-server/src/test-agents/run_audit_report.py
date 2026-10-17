"""Build report JSON offline from a saved /api/audits/{run_id} Blackboard snapshot."""

import argparse
import asyncio
import json
from pathlib import Path

from server.agents.audit_report import AuditReportAgent, AuditReportRequest
from server.blackboard.impls.memory import MemoryBlackboard
from server.blackboard.models import Assessment, Evidence, Finding


async def build_report(snapshot, run_id):
    board = MemoryBlackboard()
    for key, schema, publish in (
        ("evidence", Evidence, board.publish_evidence),
        ("findings", Finding, board.publish_finding),
        ("assessments", Assessment, board.publish_assessment),
    ):
        for value in snapshot.get(key, []):
            record = schema.model_validate(value)
            if record.run_id == run_id:
                publish(record)
    return await AuditReportAgent(blackboard=board).run(AuditReportRequest(run_id=run_id))


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
