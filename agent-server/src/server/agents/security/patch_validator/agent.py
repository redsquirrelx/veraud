from typing import List
from ..schemas import Finding

class PatchValidatorAgent:
    def validate_patches(self, findings: List[Finding]) -> List[Finding]:
        for f in findings:
            if f.remediation.get("patch_code"):
                code = f.remediation["patch_code"]
                if "pickle" not in code and "+" not in code:
                    f.remediation["validated_by_sast"] = True
        return findings
