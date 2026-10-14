#!/usr/bin/env python3
"""
Agente 4: Remediation & Patch Synthesizer Agent [LLM] (HU-010)
Genera parches defensivos sugeridos para las vulnerabilidades detectadas mediante LLM o Fallback local.
"""

import os
import json
from typing import List
from .schemas import Finding

SYSTEM_PROMPT = """
Eres un experto en DevSecOps y desarrollo seguro de software.
Tu tarea es analizar un hallazgo de vulnerabilidad en código fuente y generar un parche defensivo.

REGLAS OBLIGATORIAS:
1. Reemplaza el patrón inseguro por código seguro según las mejores prácticas de OWASP.
2. NO agregues explicaciones extensas de texto fuera del JSON.
3. Responde ÚNICAMENTE en formato JSON válido con la siguiente estructura:
{
  "finding_id": "<ID_DEL_HALLAZGO>",
  "patch_code": "<CÓDIGO_CORREGIDO_REPARADO>",
  "explanation": "<EXPLICACIÓN_BREVE_DE_LA_REPARACIÓN>"
}
"""

class RemediationSynthesizerAgent:
    def __init__(self, api_key: str = None, model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("GROQ_API_KEY")
        self.model = model

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
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2
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