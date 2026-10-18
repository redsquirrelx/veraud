from typing import Any

from ..config import SecurityConfig
from ..dast_sandbox import DASTSandboxAgent
from ..knowledge_enrichment import KnowledgeEnrichmentAgent
from ..patch_validator import PatchValidatorAgent
from ..remediation_synthesizer import RemediationSynthesizerAgent
from ..sast_scanner import SASTScannerAgent
from ..sca_dependency import SCADependencyAgent
from ..secret_scanner import SecretScannerAgent
from ..security_verifier import SecurityVerifierAgent


class SecuritySupervisorAgent:
    config_type = SecurityConfig

    def __init__(self, db_path: str | None = None, api_key: str | None = None, model: str | None = None,
                 *, config: SecurityConfig | None = None):
        self.config = config or self.config_type()
        self.sast_agent = SASTScannerAgent()
        self.secret_agent = SecretScannerAgent()
        self.enrichment_agent = KnowledgeEnrichmentAgent(db_path, config=self.config)
        self.sca_agent = SCADependencyAgent()
        self.dast_agent = DASTSandboxAgent(config=self.config)
        self.remediation_agent = RemediationSynthesizerAgent(api_key, model, config=self.config)
        self.validator_agent = PatchValidatorAgent()
        self.verifier_agent = SecurityVerifierAgent()

    def run(self, target_path: str) -> list[dict[str, Any]]:
        findings = self.sast_agent.scan_path(target_path)
        findings.extend(self.secret_agent.scan_path(target_path))
        findings.extend(self.sca_agent.scan_dependencies(target_path))
        findings = self.enrichment_agent.enrich(findings)
        findings = self.remediation_agent.synthesize_patches(findings)
        findings = self.validator_agent.validate_patches(findings)
        verified = self.verifier_agent.filter_false_positives(findings)
        return [f.to_dict() for f in verified]

    def run_fast_path(self, target_path: str) -> list[dict[str, Any]]:
        """Legacy entry point uses the same supervisor and all current scanners."""
        return self.run(target_path)

    async def run_dast_background(self, findings_dicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return findings_dicts
