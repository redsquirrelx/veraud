"""Full linear audit lifecycle, plus explicit compatibility entry points."""

import json
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from server.blackboard.publication import publication_for
from server.runtimes.coordination.execution import CoordinatorAgent
from server.runtimes.invocation_reporting import phase_node

from .config import MaintainabilityConfig
from .execution import MaintainabilityManagerExecution
from .registry import coordinator_catalog, registered_coordinators
from .schemas import MaintainabilityRequest


def deterministic_objective(request: MaintainabilityRequest, capabilities: Iterable | None = None) -> MaintainabilityRequest:
    """Compose a deterministic hierarchy prompt from the frontend selection."""
    catalog = coordinator_catalog(capabilities)
    if not catalog:
        return request
    try:
        from server.agents.maintainability.v2.modularity.coordinator.registry import (
            registered_investigators,
        )
        investigators = registered_investigators()
    except Exception:  # noqa: BLE001 - hierarchy stays deterministic without investigators
        investigators = {}
    lines = []
    for coordinator_id in sorted(catalog):
        spec = catalog[coordinator_id]
        if coordinator_id == "modularity" and investigators:
            subagents = ", ".join(sorted(investigators))
            lines.append(f"- Coordinador {coordinator_id} ({spec.agent_name}): subagentes [{subagents}]")
        else:
            lines.append(f"- Coordinador {coordinator_id} ({spec.agent_name}): sin subagentes registrados")
    hierarchy = "\n".join(lines)
    if hierarchy in request.objective:
        return request
    suffix = (
        "\n\nEjecución determinista:\n"
        f"- Coordinadores a ejecutar: {', '.join(sorted(catalog))}\n"
        f"{hierarchy}\n"
        "Selecciona y delega exactamente esos coordinadores/investigadores; no inventes otros."
    )
    return request.model_copy(update={"objective": request.objective + suffix})


class MaintainabilityManager(CoordinatorAgent):
    agent_type = "maintainability_manager"
    config_type = MaintainabilityConfig
    trace_name = "maintainability-v2-manager"

    def _execution(self, tools, request):
        execution = MaintainabilityManagerExecution(self.model, self.config, tools, request)
        execution.tracing = self.tracing
        execution.audit_identity = self.audit_identity
        execution.owner = self
        if self.provider_pacer is not None and execution.provider_pacer.scope is None:
            execution.provider_pacer = self.provider_pacer
        return execution

    async def run(self, tools, request, *, capabilities=None):
        """Return the final typed audit result; partial work stays explicitly partial."""
        request = MaintainabilityRequest.model_validate(request)
        request = deterministic_objective(request, capabilities)
        if self.blackboard is not None:
            self._blackboard_publication = publication_for(self)
        execution = self._execution(tools, request)
        if self.blackboard is not None:
            execution.audit_identity = self._blackboard_publication.identity
        state = execution.initial_state()
        state["coordinator_catalog"] = list(coordinator_catalog(capabilities).values())
        state = await self.tracing.wrap_stage(execution.graph.ainvoke(state, {"recursion_limit": 12}), name=self.trace_name)
        result = state["result"]
        # TEMP: export raw like the runner, without affecting execution.
        try:
            path = Path(tempfile.gettempdir()) / f"maintainability-raw-{getattr(result, 'assessment_id', 'unknown')[:8]}.json"
            path.write_text(json.dumps(TypeAdapter(Any).dump_python(result, mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001, S110 - TEMP export must never break the audit
            pass
        publication = publication_for(self)
        if publication is not None and execution.timing.publication_allowed:
            children = []
            for record in result.coordinator_results:
                child = publication.child(record.assignment_id, record.assignment.coordinator_id)
                if child.result is None and record.result is not None:
                    # Reconcile: persist the raw coordinator result already present
                    # in the manager output so the blackboard matches the runner raw.
                    try:
                        spec = registered_coordinators().get(record.assignment.coordinator_id)
                        if isinstance(record.result, BaseModel):
                            child.publish_assessment(record.result)
                        elif spec is not None and spec.result_class is not None:
                            coordinator_result = TypeAdapter(spec.result_class).validate_python(record.result)
                            child.publish_assessment(coordinator_result)
                    except Exception:  # noqa: BLE001, S110 - retain other children; missing IDs remain visible
                        pass
                if child.result is not None:
                    children.append(child.result)
            publication.publish_assessment(result, children=children)
        return result

    async def plan_audit(self, tools, request, *, capabilities=None):
        """Compatibility entry point: execute only the original planning node."""
        request = MaintainabilityRequest.model_validate(request)
        catalog = coordinator_catalog(capabilities)
        execution = self._execution(tools, request)
        state = execution.initial_state()
        state["coordinator_catalog"] = list(catalog.values())
        operation = phase_node("plan_audit", execution.plan_audit)
        update = await self.tracing.wrap_stage(operation(state, {}), name="plan_audit")
        return {**state, **update}

    async def delegate_coordinators(self, tools, state):
        """Explicitly execute this node only; do not collect or synthesize results."""
        request = MaintainabilityRequest.model_validate(state["request"])
        execution = self._execution(tools, request)
        state = {**state, "request": request,
            "coordinator_catalog": list(coordinator_catalog(state["coordinator_catalog"]).values())}
        operation = phase_node("delegate_coordinators", execution.delegate_coordinators)
        update = await self.tracing.wrap_stage(operation(state, {}), name="delegate_coordinators")
        return {**state, **update}
