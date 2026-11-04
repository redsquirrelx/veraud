"""
Schemas y Contrato Único de Datos para el Módulo de Seguridad.
Garantiza interoperabilidad entre todos los agentes de la tubería.
"""

from dataclasses import asdict, dataclass, field
from typing import Any


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
    owasp_official_title: str | None = None
    associated_cwes: str | None = None
    cisa_kev_match: bool = False
    
    # DAST Asíncrono (Agente 3)
    dast_validation: dict[str, Any] = field(default_factory=lambda: {
        "executed": False,
        "status": "UNCONFIRMED", # CONFIRMED, UNCONFIRMED, NOT_APPLICABLE
        "evidence": "Pending background analysis"
    })
    
    # Remedación LLM + Validación (Agentes 4 y 5)
    remediation: dict[str, Any] = field(default_factory=lambda: {
        "llm_generated": False,
        "validated_by_sast": False,
        "patch_code": None
    })

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
