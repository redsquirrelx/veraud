"""Structured execution failures with safe messages and measurable shortfalls."""

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ResourceShortfall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    resource: str
    available: float
    required: float


class ExecutionFailure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    code: str
    stage: str
    summary: str
    exception_type: str | None = None
    resources: list[ResourceShortfall] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class ExecutionValidationError(ValueError):
    """Only trusted host-defined codes/messages belong in this exception."""

    def __init__(self, code, summary, *, resources=(), diagnostics=(), stage="validate_result"):
        super().__init__(summary)
        self.failure = ExecutionFailure(code=code, stage=stage, summary=summary,
            exception_type="ValueError", resources=list(resources), diagnostics=list(diagnostics))


def failure_from_exception(error, stage, schema=None):
    if isinstance(error, ExecutionValidationError):
        return error.failure.model_copy(update={"stage": stage if error.failure.stage == "validate_result" else error.failure.stage})
    if isinstance(error, ValidationError):
        allowed = set()
        if schema is not None:
            contract = schema.model_json_schema()
            allowed.update(contract.get("properties", {}))
            for definition in contract.get("$defs", {}).values():
                allowed.update(definition.get("properties", {}))
        diagnostics = []
        for item in error.errors(include_input=False, include_context=False, include_url=False)[:6]:
            location = ".".join(str(part) if isinstance(part, int) or part in allowed else "<campo>" for part in item["loc"])
            diagnostics.append(f"{location or 'response'}: {item['type']}")
        return ExecutionFailure(code="result_contract_invalid", stage=stage, exception_type="ValidationError",
            summary="La respuesta recibida no cumple el contrato esperado.", diagnostics=diagnostics)
    timeout = isinstance(error, TimeoutError)
    return ExecutionFailure(code="execution_timeout" if timeout else "child_execution_error", stage=stage,
        exception_type=type(error).__name__, summary=("Se agotó el tiempo de ejecución."
            if timeout else f"La ejecución produjo {type(error).__name__} en la etapa {stage}; no se publicó un detalle seguro adicional."))
