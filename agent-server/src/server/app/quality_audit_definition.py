"""Quality-audit pipeline adapter over the existing audit and report lifecycle."""

import asyncio
import base64
import subprocess
from pathlib import Path

from pydantic import ConfigDict, Field, ValidationError

from server.app.pipeline_contracts import PipelineDefinition, bind_no_context
from server.reporting.docx import render_audit_report_docx

from ..agent_services.execution_tracking.callback.schemas import ExecutionProgress
from ..agents.functional_adequacy.schemas import FunctionalRequirement
from ..agents.maintainability.v2.manager import MaintainabilityRequest
from ..agents.security.audit import SecurityAuditRequest
from ..blackboard.impls.memory import MemoryBlackboard
from ..config.settings import resolve_workspace_root
from ..runtimes.invocation_reporting import invocation_reporting
from .audit_attributes import QualityAttributes, audit_root
from .audit_models import validate_model_configs
from .audit_options import AuditExecutionOptions
from .audit_service import AuditService
from .errors import InvalidConfigError


class QualityAuditInput(AuditExecutionOptions):
    model_config = ConfigDict(extra="forbid")

    root_path: str
    attributes: QualityAttributes
    commit_hash: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    request: MaintainabilityRequest = Field(default_factory=MaintainabilityRequest)
    maintainability_selection: dict[str, list[str]] | None = None
    security_request: SecurityAuditRequest = Field(default_factory=SecurityAuditRequest)
    functional_requirements: list[FunctionalRequirement] | None = Field(default=None, max_length=100)
    # The full Blackboard snapshot is only delivered for internal pipelines/tests;
    # the frontend reads evidence via its dedicated endpoints, and returning it
    # inline couples the memory profile of the backend to the audit size.
    include_blackboard: bool = False


def parse_input(raw):
    try:
        parsed = QualityAuditInput.model_validate(raw)
        context = parsed.request.documented_architecture
        if "maintainability" in parsed.attributes and context is not None and (
            context.document_index is None
            or context.document_index.commit.lower() != parsed.commit_hash.lower()
            or context.execution_status == "failed"
        ):
            raise InvalidConfigError("Maintainability architecture context must be usable and match the audited commit.")
        if parsed.maintainability_selection is not None:
            if "maintainability" not in parsed.attributes:
                raise InvalidConfigError("maintainability_selection requires maintainability in attributes.")
            if not parsed.maintainability_selection:
                raise InvalidConfigError("Maintainability V2 requires at least one selected coordinator; empty selections are not executed.")
            from ..agents.maintainability.v2.manager.registry import (
                registered_coordinators,
            )
            from ..agents.maintainability.v2.modularity.coordinator.registry import (
                registered_investigators as modularity_investigators,
            )
            from ..agents.maintainability.v2.reusability.coordinator.registry import (
                registered_investigators as reusability_investigators,
            )

            coordinators = registered_coordinators()
            investigators_by_coordinator = {
                "modularity": modularity_investigators,
                "reusability": reusability_investigators,
            }
            for coordinator_id, investigator_ids in parsed.maintainability_selection.items():
                if coordinator_id not in coordinators:
                    raise InvalidConfigError("Maintainability V2 supports only registered coordinators; legacy selections are not executed.")
                if len(set(investigator_ids)) != len(investigator_ids):
                    raise InvalidConfigError("Maintainability V2 selection must not contain duplicate investigators.")
                allowed = set(investigators_by_coordinator.get(coordinator_id, modularity_investigators)())
                if any(investigator not in allowed for investigator in investigator_ids):
                    raise InvalidConfigError("Maintainability V2 supports only registered investigators for the selected coordinator; legacy selections are not executed.")
                if not investigator_ids and allowed:
                    raise InvalidConfigError("Maintainability V2 requires at least one investigator for coordinators with registered investigators; use not_applicable handling inside the coordinator for empty catalogs.")
        if "functional_adequacy" not in parsed.attributes and parsed.functional_requirements is not None:
            raise InvalidConfigError("functional_requirements requires functional_adequacy in attributes.")
        if parsed.functional_requirements and len({item.requirement_id for item in parsed.functional_requirements}) != len(parsed.functional_requirements):
            raise InvalidConfigError("Functional requirement IDs must be distinct.")
        return parsed
    except ValidationError:
        raise InvalidConfigError("Select supported quality attributes and a full commit hash.") from None


class QualityAuditRunner:
    def __init__(self, config, agent_configs=None):
        self.config = config
        self.agent_configs = agent_configs
        self.blackboard = MemoryBlackboard()

    async def run(self, parsed, hooks, *, blackboard=None, audit_service=None):
        root = Path(parsed.root_path).expanduser().resolve()
        if root.parent != resolve_workspace_root() or not root.is_dir():
            raise InvalidConfigError("root_path must be a checkout directly inside the shared workspace.")
        try:
            # Windows reload workers can use a SelectorEventLoop, which has no
            # asyncio subprocess support. Keep Git bounded and off the loop.
            revision = await asyncio.to_thread(subprocess.run,
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5,
                check=False, text=True)
        except subprocess.TimeoutExpired:
            raise InvalidConfigError("Git revision verification timed out.") from None
        except OSError:
            raise InvalidConfigError("Git revision verification could not start.") from None
        if revision.returncode or revision.stdout.strip().lower() != parsed.commit_hash.lower():
            raise InvalidConfigError("The checkout no longer matches the selected project revision.")
        board = blackboard or (audit_service.blackboard if audit_service is not None else self.blackboard)
        service = audit_service or AuditService(board)
        security = parsed.attributes == ["security"]
        stage = audit_root(parsed.attributes)
        if hooks:
            await hooks.on_stage_start(stage)
        state = None
        try:
            latest: dict[str, dict] = {}

            async def report_invocation(receipt):
                if hooks:
                    await hooks.on_invocation(stage, receipt)
                    invocation_id = receipt.get("invocation_id")
                    if invocation_id:
                        # Receipts are cumulative per invocation; the audit
                        # total is the sum across invocations. Null means the
                        # provider gave no count yet, so partial sums stay
                        # monotonic and usable while Running.
                        latest[invocation_id] = dict(receipt)
                        inputs = [row.get("input_tokens") for row in latest.values()
                            if isinstance(row.get("input_tokens"), int) and not isinstance(row.get("input_tokens"), bool)]
                        outputs = [row.get("output_tokens") for row in latest.values()
                            if isinstance(row.get("output_tokens"), int) and not isinstance(row.get("output_tokens"), bool)]
                        on_progress = getattr(hooks, "on_stage_progress", None)
                        if on_progress is not None:
                            await on_progress(stage, ExecutionProgress(
                                input_tokens=sum(inputs) if inputs else None,
                                output_tokens=sum(outputs) if outputs else None,
                                estimated_tokens=0,
                            ))

            with invocation_reporting(report_invocation):
                if parsed.maintainability_selection is not None:
                    parsed.request = parsed.request.model_copy(update={
                        "maintainability_selection": parsed.maintainability_selection})
                state = service.start(str(root), parsed.security_request if security else parsed.request, self.config, stage,
                    parsed.agent_defaults, parsed.audit_budget, parsed.call_limits,
                    agent_configs=self.agent_configs, attributes=parsed.attributes, security_request=parsed.security_request,
                    security_config=parsed.security_config, functional_requirements=parsed.functional_requirements,
                    attribute_options=parsed.attribute_options, functional_config=parsed.functional_config)
            if hooks:
                await hooks.on_audit_start(stage, state.run_id)
            await service.wait(state.run_id)
            snapshot = service.snapshot(state.run_id)
            report = await service.report(state.run_id)
            document = await asyncio.to_thread(render_audit_report_docx, report)
            # The backend stores this envelope from the HTTP response. Lifecycle
            # callbacks carry compact invocation lifecycle: large artifacts are sent once.
            audit: dict[str, object] = {
                "attributes": parsed.attributes,
                "status": snapshot.status,
                "run_id": state.run_id,
                "error_detail": snapshot.error_detail.model_dump(mode="json", by_alias=True) if snapshot.error_detail else None,
                "report": report.model_dump(mode="json"),
                "docx_base64": base64.b64encode(document).decode("ascii"),
            }
            if parsed.include_blackboard:
                audit["blackboard"] = snapshot.model_dump(mode="json")
            return {"audit": audit}
        finally:
            if audit_service is None:
                await service.aclose()
            elif state is not None:
                await service.cancel(state.run_id)


async def build_agents(exec_service, config, stage_configs, parsed, timeout_seconds):
    model_attributes = [attribute for attribute in parsed.attributes
        if attribute != "functional_adequacy" or parsed.functional_requirements]
    validate_model_configs(stage_configs, model_attributes)
    selected = (stage_configs or {}).get(audit_root(parsed.attributes), config)
    return {"maintainability_manager": QualityAuditRunner(selected, stage_configs)}, {}


def quality_audit_definition():
    return PipelineDefinition(
        name="quality-audit", stages=["maintainability_manager"], parse_input=parse_input,
        resolve_stages=lambda parsed: [audit_root(parsed.attributes)],
        build_agents=build_agents, adapt_hooks=lambda hooks: hooks,
        create_pipeline=lambda agents, hooks, ctx: (agents["maintainability_manager"], hooks),
        run_pipeline=lambda pipeline, parsed, ctx: pipeline[0].run(
            parsed, pipeline[1], blackboard=ctx.get("blackboard"),
            audit_service=ctx.get("audit_service")),
        bind_context=bind_no_context,
        requires_agent_execution_service=False,
    )
