"""Explicit offline protocol smoke model; it does not interpret project semantics."""

import json

from ...services.repository_analysis.context import create_identifier


class ProtocolSmokeModel:
    async def generate(self, prompt):
        if "\nINVESTIGATION_DATA\n" in prompt:
            data = json.loads(prompt.split("\nINVESTIGATION_DATA\n", 1)[1])
            responses = [
                json.loads(message["content"])
                for message in data["history"]
                if message["role"] == "tool"
            ]
            source = next(
                (
                    response
                    for response in reversed(responses)
                    if response["status"] == "ok"
                    and response.get("data", {}).get("content") is not None
                ),
                None,
            )
            if source:
                excerpt = source["data"]
                evidence = next(
                    record
                    for record in source["evidence"]
                    if record["kind"] == "source"
                )
                return json.dumps(
                    {
                        "result": {
                            "id": data["finding_id"],
                            "investigation_id": data["objective"]["id"],
                            "status": "incomplete",
                            "limitations": [
                                "Offline protocol smoke test; semantic project interpretation was not performed."
                            ],
                            "open_questions": [
                                {
                                    "id": create_identifier(
                                        "question", data["finding_id"]
                                    ),
                                    "investigation_id": data["objective"]["id"],
                                    "question": data["objective"]["objective"],
                                    "reason": "Protocol smoke does not interpret functional behavior.",
                                    "entity_ids": data["objective"]["seed_entity_ids"],
                                }
                            ],
                            "claims": [
                                {
                                    "id": create_identifier(
                                        "claim", data["finding_id"]
                                    ),
                                    "statement": f"A retained technical excerpt from {excerpt['path']} was retrieved.",
                                    "status": "supported",
                                    "entity_ids": [excerpt["file_id"]],
                                    "evidence_ids": [evidence["id"]],
                                }
                            ],
                        }
                    }
                )
            listing = next(
                (
                    response
                    for response in reversed(responses)
                    if response["status"] == "ok"
                    and "items" in (response.get("data") or {})
                ),
                None,
            )
            if listing:
                source_file = next(
                    (
                        record
                        for record in listing["data"]["items"]
                        if record.get("line_count", 0) > 0
                    ),
                    None,
                )
                if source_file:
                    return self.tool_call(
                        "get_source_excerpt",
                        {
                            "path": source_file["path"],
                            "start_line": 1,
                            "end_line": min(8, source_file["line_count"]),
                        },
                    )
            for seed in data["seed_entities"]:
                if "qualified_name" in seed:
                    return self.tool_call(
                        "get_symbol_source", {"symbol_id": seed["id"]}
                    )
                if "path" in seed and "line_count" in seed and seed["line_count"]:
                    return self.tool_call(
                        "get_source_excerpt",
                        {
                            "path": seed["path"],
                            "start_line": 1,
                            "end_line": min(8, seed["line_count"]),
                        },
                    )
            return self.tool_call(
                "list_files",
                {"project_id": data["objective"]["project_id"], "limit": 10},
            )
        if "\nREPORT_DATA\n" in prompt:
            data = json.loads(prompt.split("\nREPORT_DATA\n", 1)[1])
            return json.dumps(
                {
                    name: [record["id"] for record in records]
                    for name, records in data["accepted_facts"].items()
                }
            )
        data = json.loads(prompt.split("\nREPOSITORY_DATA\n", 1)[1])
        candidates = data["candidates"]
        orientations = [
            candidate
            for candidate in candidates
            if candidate["category"] == "project_orientation"
        ]
        selected = (
            orientations
            + [candidate for candidate in candidates if candidate not in orientations]
        )[: data["maximum_investigations"]]
        return json.dumps(
            {
                "investigations": [
                    {
                        "candidate_ids": [candidate["id"]],
                        "objective": {
                            "id": create_identifier("investigation", candidate["id"]),
                            "project_id": candidate["project_id"],
                            "objective": "Investigate: " + candidate["description"],
                            "seed_entity_ids": candidate["seed_entity_ids"],
                            "questions": [
                                "What can inspected code establish about this unit?"
                            ],
                            "report_sections": ["project_identification"]
                            if candidate["category"] == "project_orientation"
                            else ["main_flows"],
                            "selection_reason": "Protocol smoke coverage of an offered candidate.",
                            "priority_tier": candidate["category"],
                            "expected_deliverable": "Evidence-backed findings or explicit unresolved questions.",
                            "completion_criteria": [
                                "Inspect source and report remaining uncertainty."
                            ],
                        },
                    }
                    for candidate in selected
                ]
            }
        )

    @staticmethod
    def tool_call(name, arguments):
        return json.dumps(
            {"tool_calls": [{"id": "smoke-call", "name": name, "arguments": arguments}]}
        )
