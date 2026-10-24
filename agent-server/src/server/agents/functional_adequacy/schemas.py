
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import FunctionalAdequacyConfig  # noqa: F401 - compatibility export

ComplianceStatus = Literal[
    "cumple",
    "no_cumple",
    "evidencia_insuficiente",
]


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


class FunctionalAdequacyInput(BaseModel):
    """Datos recibidos por el agente."""

    requirements: list[FunctionalRequirement] = Field(
        min_length=1, max_length=100
    )
    code_fragments: list[CodeFragment] = Field(
        default_factory=list
    )

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

        return self


class CodeEvidence(BaseModel):
    """Evidencia de código recuperada mediante SBERT."""

    fragment_id: str
    file_path: str
    similarity: float = Field(ge=-1.0, le=1.0)


class RequirementResult(BaseModel):
    """Resultado de la evaluación de un requisito."""

    requirement_id: str
    description: str
    status: ComplianceStatus
    justification: str
    evidence: list[CodeEvidence] = Field(
        default_factory=list
    )


class FunctionalAdequacyOutput(BaseModel):
    """Resultado estructurado de la auditoría funcional."""

    evaluated_attribute: Literal["functional_adequacy"] = (
        "functional_adequacy"
    )

    score: float = Field(ge=0.0, le=100.0)

    total_requirements: int = Field(ge=0)
    fulfilled_requirements: int = Field(ge=0)

    results: list[RequirementResult] = Field(
        default_factory=list
    )
    recommendations: list[str] = Field(
        default_factory=list
    )
