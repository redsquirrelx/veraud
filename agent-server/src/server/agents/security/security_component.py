"""
Security Component Orchestrator (Tubería Asíncrona Multi-Etapa)
Integra el flujo completo para el Dispatcher del Agent Server.
"""

from typing import List, Dict, Any
from .sast_scanner import SASTScannerAgent
from .knowledge_enrichment import KnowledgeEnrichmentAgent
from .dast_sandbox import DASTSandboxAgent
from .remediation_synthesizer import RemediationSynthesizerAgent
from .patch_validator import PatchValidatorAgent

class SecurityComponentAgent:
    def __init__(self, db_path: str = "security_patterns.db"):
        self.sast_agent = SASTScannerAgent()
        self.enrichment_agent = KnowledgeEnrichmentAgent(db_path)
        self.dast_agent = DASTSandboxAgent()
        self.remediation_agent = RemediationSynthesizerAgent()
        self.validator_agent = PatchValidatorAgent()

    def run_fast_path(self, target_path: str) -> List[Dict[str, Any]]:
        """Flujo Síncrono Rápido: SAST -> BD -> Remedación LLM -> Validación."""
        # 1. SAST
        raw_findings = self.sast_agent.scan_path(target_path)
        # 2. Enriquecimiento
        enriched_findings = self.enrichment_agent.enrich(raw_findings)
        # 4. Parches LLM
        patched_findings = self.remediation_agent.synthesize_patches(enriched_findings)
        # 5. Validación Parche
        final_findings = self.validator_agent.validate_patches(patched_findings)

        return [f.to_dict() for f in final_findings]

    async def run_dast_background(self, findings_dicts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Flujo Asíncrono: DAST Sandbox Validation."""
        # Re-construir objetos y ejecutar DAST
        # (Se despacha en background mediante Webhook / Polling)
        return findings_dicts