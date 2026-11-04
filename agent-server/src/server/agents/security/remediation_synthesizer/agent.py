import json
import os

from config.agents.user import ProviderRateLimits

from ....infrastructure.llm.quota import (
    acquire_global_sync,
    global_quota_store,
    quota_scope,
    reported_tokens,
)
from ..config import SecurityConfig
from ..schemas import Finding


class RemediationSynthesizerAgent:
    def __init__(self, api_key: str | None = None, model: str | None = None, *, config: SecurityConfig | None = None):
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
                client = OpenAI(api_key=self.api_key, max_retries=0)
                reservation = acquire_global_sync(quota_scope("openai", self.model), ProviderRateLimits(),
                    len(self.config.remediation_system_prompt + user_prompt) + self.config.remediation_model.max_tokens)
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
                actual = reported_tokens(response)
                if actual is not None:
                    global_quota_store().settle(reservation, actual)
                return json.loads(response.choices[0].message.content)
            except Exception:  # noqa: BLE001 - Preserve local fallback for provider failures.
                return self._fallback_patch(finding)
        return self._fallback_patch(finding)

    def _fallback_patch(self, finding: Finding) -> dict:
        patch = finding.snippet
        if "SQLI" in finding.rule_id:
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

    def synthesize_patches(self, findings: list[Finding]) -> list[Finding]:
        for f in findings:
            llm_result = self._call_llm(f)
            f.remediation = {
                "llm_generated": bool(self.api_key),
                "validated_by_sast": False,
                "patch_code": llm_result.get("patch_code"),
                "explanation": llm_result.get("explanation")
            }
        return findings
