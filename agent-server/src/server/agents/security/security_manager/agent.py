from typing import List, Dict, Any
from ..sast_scanner import SASTScannerAgent
from ..secret_scanner import SecretScannerAgent
from ..knowledge_enrichment import KnowledgeEnrichmentAgent
from ..sca_dependency import SCADependencyAgent
from ..dast_sandbox import DASTSandboxAgent
from ..remediation_synthesizer import RemediationSynthesizerAgent
from ..patch_validator import PatchValidatorAgent
from ..security_verifier import SecurityVerifierAgent

class SecuritySupervisorAgent:
    def __init__(self, db_path: str = "security_patterns.db", api_key: str = None, model: str = "gpt-4o-mini"):
        self.sast_agent = SASTScannerAgent()
        self.secret_agent = SecretScannerAgent()
        self.enrichment_agent = KnowledgeEnrichmentAgent(db_path)
        self.sca_agent = SCADependencyAgent()
        self.dast_agent = DASTSandboxAgent()
        self.remediation_agent = RemediationSynthesizerAgent(api_key, model)
        self.validator_agent = PatchValidatorAgent()
        self.verifier_agent = SecurityVerifierAgent()

    def run(self, target_path: str) -> List[Dict[str, Any]]:
        findings = self.sast_agent.scan_path(target_path)
        findings.extend(self.secret_agent.scan_path(target_path))
        findings.extend(self.sca_agent.scan_dependencies(target_path))
        findings = self.enrichment_agent.enrich(findings)
        findings = self.remediation_agent.synthesize_patches(findings)
        findings = self.validator_agent.validate_patches(findings)
        verified = self.verifier_agent.filter_false_positives(findings)
        return [f.to_dict() for f in verified]
