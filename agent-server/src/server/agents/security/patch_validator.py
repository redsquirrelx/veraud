"""
Agente 5: Patch Validator Loop (SAST Check)
Re-escanea estáticamente el parche generado para evitar alucinaciones del LLM.
"""

from typing import List
from .schemas import Finding

class PatchValidatorAgent:
    def validate_patches(self, findings: List[Finding]) -> List[Finding]:
        for f in findings:
            if f.remediation.get("patch_code"):
                # Verifica que el parche no contenga de nuevo patrones inseguros (ej. pickle o +)
                patch_str = f.remediation["patch_code"]
                if "pickle" not in patch_str and "+" not in patch_str:
                    f.remediation["validated_by_sast"] = True
        return findings