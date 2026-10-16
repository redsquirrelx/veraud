"""
Schemas y Contrato Único de Datos para el Módulo de Seguridad.
Garantiza interoperabilidad entre todos los agentes de la tubería.
"""

from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict

from .config import SecurityConfig  # noqa: F401 - compatibility export

@dataclass
class Finding:
    finding_id: str
    file_path: str
    line_number: int
    rule_id: str
    rule_name: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    category: str
    owasp_category: str
    snippet: str
    matched_text: str
    
    # Enriquecimiento (Agente 2)
    owasp_official_title: Optional[str] = None
    associated_cwes: Optional[str] = None
    cisa_kev_match: bool = False
    
    # DAST Asíncrono (Agente 3)
    dast_validation: Dict[str, Any] = field(default_factory=lambda: {
        "executed": False,
        "status": "UNCONFIRMED", # CONFIRMED, UNCONFIRMED, NOT_APPLICABLE
        "evidence": "Pending background analysis"
    })
    
    # Remedación LLM + Validación (Agentes 4 y 5)
    remediation: Dict[str, Any] = field(default_factory=lambda: {
        "llm_generated": False,
        "validated_by_sast": False,
        "patch_code": None
    })

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
