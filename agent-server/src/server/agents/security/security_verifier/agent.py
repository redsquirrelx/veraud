from typing import List
from ..schemas import Finding

class SecurityVerifierAgent:
    def filter_false_positives(self, findings: List[Finding]) -> List[Finding]:
        verified = []
        for f in findings:
            if "test_" not in f.file_path.lower():
                f.verified = True
                verified.append(f)
        return verified
