"""Conservative scope checks: syntax and a narrow label cannot certify broader prose.

These checks only withhold unsupported conclusions. They never infer compliance or
prove architectural semantics from keywords; the semantic review remains required.
"""

import re


def conclusion_requirements(subject):
    fields = (("rationale",) if subject.status == "discarded" else ("question", "rationale")) if hasattr(subject, "question") else (
        "title", "description", "justification", "modularity_impact")
    text = " ".join(getattr(subject, name, "") for name in fields).lower()
    # A concrete counterexample can disprove isolation without proving absence
    # throughout the whole component; do not reverse that burden of proof.
    text = re.sub(r"\bnot\s+(?:cleanly\s+)?decoupled\b|\bno\s+(?:runtime\s+|service\s+)?isolation\b", "", text)
    requirements = set()
    if re.search(r"independen\w*\s+(?:development and\s+)?deploy|deploy\w*\s+independen|desplieg\w*\s+independ", text):
        requirements.add("deployment")
    if re.search(r"decoupl|desacopl|clean(?:ly)?\s+(?:separat|isolat)|clear\s+architectural\s+boundar|"
            r"service\s+isolat|runtime\s+isolat|aislamiento|no\s+(?:shared|cross.service)\s+(?:database|dependenc)", text):
        requirements.add("isolation")
    if re.search(r"(?:absence|free|no|without)\s+(?:of\s+)?(?:dependency\s+)?cycles|sin\s+ciclos", text):
        requirements.add("absence_of_cycles")
    return requirements


def assertion_issues(subject, check):
    required = conclusion_requirements(subject)
    if "deployment" in required and check.claim_kind != "deployment":
        return ["boundary_claim_understates_conclusion:deployment"]
    if "isolation" in required and check.claim_kind not in {"isolation", "deployment"}:
        return ["boundary_claim_understates_conclusion:isolation"]
    if "absence_of_cycles" in required and check.claim_kind != "absence_of_cycles":
        return ["boundary_claim_understates_conclusion:absence_of_cycles"]
    return []
