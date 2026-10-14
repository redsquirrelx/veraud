"""Combined orientation/architecture offline protocol smoke model."""

import json

from ..project_orientation.smoke import OrientationSmokeModel


class ArchitectureSmokeModel(OrientationSmokeModel):
    async def generate(self, prompt):
        if "\nORIENTATION_DATA\n" in prompt:
            return await super().generate(prompt)
        data = json.loads(prompt.split("\nARCHITECTURE_DATA\n", 1)[1])
        sources = [json.loads(item["content"]) for item in data["tool_results"]]
        inspected = [
            record
            for item in sources
            for record in item.get("evidence", [])
            if record["kind"] == "source"
        ]
        if not inspected:
            inspected = data.get("source_evidence_ledger", [])
        files = data["representation"]["candidate_files"]
        if not inspected and files:
            return json.dumps(
                {
                    "tool_calls": [
                        {
                            "id": f"read-{index}",
                            "name": "get_source_excerpt",
                            "arguments": {"path": item["path"]},
                        }
                        for index, item in enumerate(files[:2])
                    ]
                }
            )
        claim = {
            "statement": "Offline protocol smoke does not classify architecture.",
            "scope": "Inspected technical files",
            "status": "unresolved",
            "limitations": ["No semantic architecture interpretation was performed."],
        }
        return json.dumps(
            {
                "architecture": {
                    "closest_architecture": {
                        "pattern": "No clear pattern established",
                        "assessment": claim,
                    },
                    "explanation": claim,
                    "uncertainties": [
                        "Verify organization, patterns, deviations, and infrastructure with a real model."
                    ],
                }
            }
        )
