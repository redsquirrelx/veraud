from pydantic import BaseModel, Field


class DummyInput(BaseModel):
    code: str = Field(description="Code snippet to audit")

    evaluated_attribute: str = Field(
        default="maintainability",
        description="Quality attribute under evaluation (dummy)",
    )


class Finding(BaseModel):
    title: str
    description: str
    severity: str = Field(default="low", description="low | medium | high")


class DummyOutput(BaseModel):
    evaluated_attribute: str
    score: float = Field(ge=0, le=100, description="Score 0-100")
    findings: list[Finding] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
