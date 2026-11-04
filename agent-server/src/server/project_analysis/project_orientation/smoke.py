"""Explicit offline protocol model; it does not interpret project semantics."""

import json


class OrientationSmokeModel:
    async def generate(self, prompt):
        data = json.loads(prompt.split("\nORIENTATION_DATA\n", 1)[1])
        for response in reversed(data["tool_results"]):
            value = json.loads(response["content"])
            evidence = next(
                (
                    item
                    for item in value.get("evidence", [])
                    if item["kind"] == "source"
                ),
                None,
            )
            if evidence:
                uncertain = {
                    "statement": "Project semantics were not interpreted in this offline protocol test.",
                    "status": "unresolved",
                    "limitations": ["Offline protocol smoke only."],
                }
                return json.dumps(
                    {
                        "orientation": {
                            "project_type": uncertain,
                            "purpose": uncertain,
                            "starting_points": [
                                {
                                    "file_id": evidence["file_id"],
                                    "reason": "A retained technical excerpt was retrieved.",
                                }
                            ],
                            "uncertainties": [
                                "Determine project purpose and responsibilities using a real model."
                            ],
                        }
                    }
                )
        files = data["representation"]["candidate_files"]
        if not files:
            return json.dumps(
                {
                    "orientation": {
                        "uncertainties": ["No accessible technical source was found."]
                    }
                }
            )
        return json.dumps(
            {
                "tool_calls": [
                    {
                        "id": "read-1",
                        "name": "get_source_excerpt",
                        "arguments": {"path": files[0]["path"]},
                    }
                ]
            }
        )
