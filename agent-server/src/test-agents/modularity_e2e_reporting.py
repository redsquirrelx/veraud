"""Test-only progress reporting from actual invocation events and assessment records."""

from server.agents.maintainability.modularity.coordinator.registry import INVESTIGATORS
from server.app.tracing_port import NoOpTracingBackend, TracingBackend


def emit(message):
    print(message, flush=True)


class AssessmentProgress(TracingBackend):
    """Observe existing tracing boundaries without changing investigator execution."""

    def __init__(self, backend=None, *, registry=None):
        self.backend = backend if backend is not None else NoOpTracingBackend()
        self.registry = INVESTIGATORS if registry is None else registry
        self.records = []

    async def wrap_stage(self, coro, *, name, **metadata):
        self.records.append(metadata)
        agent = self.registry[metadata["investigator_id"]].capability.agent_name
        invocation = metadata["invocation_id"][:8]
        prefix = f"  [ronda {metadata['round']} | {invocation}] {agent}"
        emit(prefix + " -> iniciado")
        try:
            result = await self.backend.wrap_stage(coro, name=name, **metadata)
        except BaseException as error:
            # Observe cancellation as well, but never consume it or expose provider secrets.
            emit(prefix + f" -> interrumpido ({type(error).__name__})")
            raise
        emit(prefix + f" -> resultado recibido | {result.termination_reason}"
             f" | {result.tool_calls} herramientas | {result.model_calls} llamadas LLM")
        return result

    async def wrap_pipeline(self, coro, *, name, **metadata):
        return await self.backend.wrap_pipeline(coro, name=name, **metadata)


def begin_assessment(scenario, provider, root, *, attribute="modularidad"):
    emit(f"\n[E2E] {scenario}")
    emit(f"  Investigadores, grafos y herramientas: REALES | Proveedor: {provider}")
    emit(f"  Repositorio fixture: {root}")
    emit(f"  Iniciando evaluacion de {attribute}...")


def report_assessment(assessment, *, registry=None, followup_path=None):
    """Render facts, not expected scenario outcomes; pytest owns pass/fail reporting."""
    registry = INVESTIGATORS if registry is None else registry
    followup_path = followup_path or "reinvestigate -> plan_targeted_follow_up -> delegate_investigations"
    emit("\n  Resumen de la evaluacion ejecutada:")
    for round_number in sorted({r.assignment.round for r in assessment.invocations}):
        if round_number > 1:
            emit("  Ruta ejecutada: " + followup_path)
        emit(f"  Ronda {round_number}:")
        for record in assessment.invocations:
            if record.assignment.round != round_number:
                continue
            agent = registry[record.assignment.investigator_id].capability.agent_name
            usage = record.consumption
            emit(f"    {agent} [{record.assignment.invocation_id[:8]}] -> {record.status}"
                 f" | {usage.tool_calls} herramientas | {usage.model_calls} llamadas LLM"
                 f" | {usage.accounted_tokens} tokens contabilizados | {record.duration_seconds:.2f}s")
            if record.result and record.status != "completed":
                emit(f"      Terminacion: {record.result.termination_reason}")
                for warning in record.result.limitations:
                    if "provider_request:" in warning or "structured_output_setup:" in warning or "response_schema" in warning:
                        emit(f"      Diagnostico: {warning}")
                for missing in record.result.missing_information:
                    emit(f"      Evidencia pendiente: {missing}")
            if record.error:
                emit(f"      Error: {record.error}")
    emit(f"  Finalizacion: {assessment.termination_reason}")
    emit(f"  Estado de la evaluacion: {assessment.status}")
    emit(f"  Hallazgos consolidados: {len(assessment.consolidated_findings)}"
         f" | disputados: {sum(f.status == 'disputed' for f in assessment.consolidated_findings)}")
    emit(f"  Lagunas materiales pendientes: {len(assessment.material_gaps)}")
    for gap in assessment.material_gaps:
        emit(f"    [{gap.kind}] {gap.question}")
    for limitation in assessment.limitations:
        if "synthesize_findings:" in limitation:
            emit(f"  Diagnostico de sintesis: {limitation}")
    emit(f"  Consumo total: {assessment.consumption.model_calls} llamadas LLM"
         f" | {assessment.consumption.tool_calls} herramientas"
         f" | {assessment.consumption.accounted_tokens} tokens contabilizados"
         f" ({assessment.consumption.estimated_tokens} estimados)")
    emit("  Nodos ejecutados: " + " -> ".join(assessment.node_transitions))
    emit("  Resultado del test: lo determina pytest; partial no equivale a test fallido.")
