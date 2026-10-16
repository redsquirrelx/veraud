#!/usr/bin/env python3
"""
Agente 4: Remediation & Patch Synthesizer Agent [LLM] (HU-010)
Genera parches defensivos sugeridos para las vulnerabilidades detectadas mediante LLM o Fallback local.
"""

import os
import json
from typing import List
from .schemas import Finding
from .config import SecurityConfig

class RemediationSynthesizerAgent:
    def __init__(self, api_key: str = None, model: str | None = None, *, config: SecurityConfig | None = None):
        self.config = config or SecurityConfig()
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("GROQ_API_KEY")
        self.model = model if model is not None else self.config.remediation_model.name

    def _call_llm(self, finding: Finding) -> dict:
        user_prompt = f"""
        Vulnerabilidad Detectada:
        - Regla: {finding.rule_name} ({finding.rule_id})
        - Categoría OWASP: {finding.owasp_category}
        - Archivo: {finding.file_path}:{finding.line_number}
        - Código Vulnerable: {finding.snippet}

        Por favor, genera la corrección segura para esa línea/fragmento de código.
        """

        if self.api_key:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=self.api_key)
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self.config.remediation_system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=self.config.remediation_model.temperature,
                    max_tokens=self.config.remediation_model.max_tokens,
                )
                return json.loads(response.choices[0].message.content)
            except Exception:
                return self._fallback_patch(finding)
        else:
            return self._fallback_patch(finding)

    def _fallback_patch(self, finding: Finding) -> dict:
        patch = finding.snippet
        if finding.rule_id == "SQLI-001":
            patch = "cursor.execute('SELECT * FROM users WHERE username = ?', (user_input,))"
        elif "DESER" in finding.rule_id:
            patch = "import json; data = json.loads(payload)"
        elif "SEC" in finding.rule_id:
            patch = "AWS_KEY = os.getenv('AWS_ACCESS_KEY_ID')"

        return {
            "finding_id": finding.finding_id,
            "patch_code": patch,
            "explanation": "Parche de código seguro generado por motor de reglas local."
        }

    def synthesize_patches(self, findings: List[Finding]) -> List[Finding]:
        for f in findings:
            llm_result = self._call_llm(f)
            f.remediation = {
                "llm_generated": True if self.api_key else False,
                "validated_by_sast": False,
                "patch_code": llm_result.get("patch_code"),
                "explanation": llm_result.get("explanation")
            }
        return findings
