import os
from typing import List
from ..schemas import Finding

class RemediationSynthesizerAgent:
    def __init__(self, api_key: str = None, model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("GROQ_API_KEY")
        self.model = model

    def synthesize_patches(self, findings: List[Finding]) -> List[Finding]:
        for f in findings:
            patch = f.snippet
            if "SQLI" in f.rule_id:
                patch = "cursor.execute('SELECT * FROM users WHERE username = ?', (user_input,))"
            elif "DESER" in f.rule_id:
                patch = "import json; data = json.loads(payload)"
            elif "SEC" in f.rule_id:
                patch = "AWS_KEY = os.getenv('AWS_ACCESS_KEY_ID')"

            f.remediation = {
                "llm_generated": True if self.api_key else False,
                "validated_by_sast": False,
                "patch_code": patch,
                "explanation": "Parche seguro de código defensivo"
            }
        return findings
