
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ComplianceStatus = Literal[
    "cumple",
    "no_cumple",
    "evidencia_insuficiente",
]
AuditMode = Literal["requirements_based", "exploratory"]
FindingClassification = Literal[
    "confirmado",
    "probable",
    "no_verificado",
]
SubattributeName = Literal[
    "completitud",
    "correccion",
    "pertinencia",
]
CapabilityKind = Literal[
    "application",
    "cli",
    "http_endpoint",
    "framework_page",
    "public_api",
    "service",
    "function",
    "method",
    "class",
    "fragment",
]
DetectionKind = Literal["declared", "observed", "inferred"]


class FunctionalRequirement(BaseModel):
    """Requisito funcional que será evaluado."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    requirement_id: str = Field(min_length=1, max_length=128, pattern=r"\S")
    description: str = Field(min_length=1, max_length=10000, pattern=r"\S")


class CodeFragment(BaseModel):
    """Fragmento de código disponible como evidencia."""

    fragment_id: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    code: str = Field(min_length=1)


class EvidenceLocation(BaseModel):
    """Ubicación rastreable de una evidencia de código."""

    file_path: str = Field(min_length=1)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    symbol: str | None = None
    fragment_id: str | None = None
    snippet: str | None = None


class CapabilityCall(BaseModel):
    """Llamada estática resuelta desde una capacidad hacia otra."""

    target_capability_id: str | None = None
    target_symbol: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    snippet: str | None = None


class FunctionalCapability(BaseModel):
    """Capacidad funcional detectada sin requisitos explícitos."""

    capability_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: CapabilityKind
    description: str = Field(min_length=1)
    detection: DetectionKind = "observed"
    http_method: str | None = None
    route: str | None = None
    evidence: list[EvidenceLocation] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    calls: list[CapabilityCall] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class RepositoryContext(BaseModel):
    """Hechos del análisis de repositorio reutilizados por el agente."""

    repository_name: str | None = None
    capabilities: list[FunctionalCapability] = Field(
        default_factory=list
    )
    analysis_limitations: list[str] = Field(default_factory=list)
    analysis_issues: list[str] = Field(default_factory=list)


class FunctionalAdequacyInput(BaseModel):
    """Datos recibidos por el agente."""

    requirements: list[FunctionalRequirement] = Field(
        default_factory=list, max_length=100
    )
    code_fragments: list[CodeFragment] = Field(
        default_factory=list
    )
    repository_context: RepositoryContext | None = None

    @model_validator(mode="after")
    def validate_unique_ids(self):
        requirement_ids = [
            item.requirement_id for item in self.requirements
        ]
        fragment_ids = [
            item.fragment_id for item in self.code_fragments
        ]

        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("Duplicate requirement IDs")

        if len(fragment_ids) != len(set(fragment_ids)):
            raise ValueError("Duplicate fragment IDs")

        if self.repository_context is not None:
            capability_ids = [
                item.capability_id
                for item in self.repository_context.capabilities
            ]
            if len(capability_ids) != len(set(capability_ids)):
                raise ValueError("Duplicate capability IDs")

        return self


class CodeEvidence(BaseModel):
    """Evidencia de código recuperada mediante SBERT."""

    fragment_id: str
    file_path: str
    similarity: float = Field(ge=-1.0, le=1.0)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    symbol: str | None = None
    snippet: str | None = None


class RequirementResult(BaseModel):
    """Resultado de la evaluación de un requisito."""

    requirement_id: str
    description: str
    status: ComplianceStatus
    justification: str
    evidence: list[CodeEvidence] = Field(
        default_factory=list
    )


class CapabilityFinding(BaseModel):
    """Hallazgo exploratorio de un subatributo para una capacidad."""

    finding_id: str
    capability_id: str
    capability_name: str
    attribute: SubattributeName
    classification: FindingClassification
    justification: str
    criteria: str
    evidence: list[EvidenceLocation] = Field(default_factory=list)


class SubattributeSummary(BaseModel):
    """Resumen cualitativo de un subatributo exploratorio."""

    attribute: SubattributeName
    evaluated_capabilities: int = Field(ge=0)
    confirmed: int = Field(ge=0)
    probable: int = Field(ge=0)
    unverified: int = Field(ge=0)
    summary: str


class FunctionalAdequacyOutput(BaseModel):
    """Resultado estructurado de la auditoría funcional."""

    evaluated_attribute: Literal["functional_adequacy"] = (
        "functional_adequacy"
    )

    audit_mode: AuditMode = "requirements_based"

    score: float = Field(ge=0.0, le=100.0)
    score_applicable: bool = True
    score_meaning: str = (
        "Porcentaje de requisitos evaluados clasificados como cumplidos; "
        "no representa la cobertura funcional del repositorio."
    )

    total_requirements: int = Field(ge=0)
    fulfilled_requirements: int = Field(ge=0)

    results: list[RequirementResult] = Field(
        default_factory=list
    )

    capabilities: list[FunctionalCapability] = Field(
        default_factory=list
    )
    findings: list[CapabilityFinding] = Field(
        default_factory=list
    )
    subattributes: list[SubattributeSummary] = Field(
        default_factory=list
    )
    classification_criteria: dict[str, str] = Field(
        default_factory=dict
    )

    limitations: list[str] = Field(
        default_factory=list
    )
    recommendations: list[str] = Field(
        default_factory=list
    )
