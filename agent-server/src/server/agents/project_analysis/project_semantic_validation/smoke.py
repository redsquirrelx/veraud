"""Offline protocol model explicitly avoids semantic acceptance."""

import json


class SemanticValidationSmokeModel:
    async def generate(self, prompt):
        data = json.loads(str(prompt).split("\nVALIDATION_DATA\n", 1)[1])
        targets = data["active_targets"]
        if not data["source_evidence_ledger"] or data.get("uninspected_source_hints"):
            hints = data.get("uninspected_source_hints") or [
                hint for target in targets for hint in target["source_hints"]
            ]
            if hints:
                return json.dumps(
                    {
                        "tool_calls": [
                            {
                                "id": "smoke-read",
                                "name": "get_source_excerpt",
                                "arguments": {
                                    "path": hints[0]["path"],
                                    "start_line": hints[0]["start_line"],
                                    "end_line": hints[0]["end_line"],
                                },
                            }
                        ]
                    }
                )
            if data.get("candidate_paths"):
                return json.dumps(
                    {
                        "tool_calls": [
                            {
                                "id": "smoke-read",
                                "name": "get_source_excerpt",
                                "arguments": {"path": data["candidate_paths"][0]},
                            }
                        ]
                    }
                )
        return json.dumps(
            {
                "findings": [
                    {
                        "target_id": target["id"],
                        "checked_statement": target["claim"]["statement"],
                        "verdict": "insufficient_evidence",
                        "reason": "Offline protocol checks do not establish semantic correctness.",
                        "counterevidence_check": "No semantic counterevidence assessment is performed by this offline protocol model.",
                        "missing_evidence": [
                            {
                                "question": "Independently verify this claim with a semantic model and relevant implementation.",
                                "paths": list(
                                    dict.fromkeys(
                                        hint["path"] for hint in target["source_hints"]
                                    )
                                )[:6],
                            }
                        ],
                    }
                    for target in targets
                ]
            }
        )
