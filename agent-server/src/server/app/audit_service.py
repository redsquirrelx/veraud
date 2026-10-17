"""Process-local audit tasks sharing the server's blackboard and model configuration."""

import asyncio
from datetime import UTC, datetime
from operator import attrgetter
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config.agents.audit import (
    AuditAgentDefaults,
    AuditCallLimits,
    apply_audit_call_limits,
    apply_audit_defaults,
    validate_audit_agents,
)
from config.agents.budgets import TokenBudgetConfig
from config.agents.catalog import validate_agent_config

from ..agents.audit_report import (
    AuditReportAgent,
    AuditReportRequest,
    SoftwareAuditReport,
)
from ..agents.maintainability.manager import (
    MaintainabilityConfig,
    MaintainabilityManagerAgent,
    MaintainabilityRequest,
)
from ..agents.maintainability.manager.validation import validate_call_capacity
from ..api.schemas import ExecutionConfig
from ..blackboard.identity import AuditIdentity
from ..blackboard.interface import Blackboard
from ..blackboard.models import Assessment, Evidence, Finding
from ..blackboard.publication import publish_audit_context, publish_audit_outcome
from ..config.logs import get_logger
from ..config.schemas import ModelCredentials, ModelSettings
from ..config.settings import resolve_workspace_root
from ..infrastructure.llm.chat import PROVIDERS, build_chat_model
from ..runtimes.repository.context import RepositoryContext
from ..runtimes.repository.model_runtime import close_model_clients
from ..runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from ..runtimes.repository.shared_tokens import SharedTokenBudget
from ..runtimes.repository.timing import ActiveDeadline, within_deadline
from ..runtimes.repository.tools import RepositoryToolset, ToolLimits
from ..services.audit_diagnostics import ExecutionDiagnostic, execution_diagnostics
from ..services.repository_analysis import (
    RepositoryAnalysisInput,
    RepositoryAnalysisService,
)
from .audit_models import validate_model_configs
from .execution_service import InvalidConfigError, get_execution_service
from .tracing_port import LangSmithTracingBackend

logger = get_logger("audit-service")
AuditStatus = Literal["queued", "running", "completed", "partial", "failed", "cancelled"]


class AuditState(BaseModel):
    """Public lifecycle state; results live in the Blackboard, credentials never enter this model."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    invocation_id: str
    status: AuditStatus
    view_url: str
    created_at: datetime
    error: str | None = None


class AuditWait(BaseModel):
    agent_id: str | None
    invocation_id: str | None
    reason: str
    source: str | None
    retry_after_seconds: float | None = Field(ge=0)


class AuditSnapshot(AuditState):
    """Lifecycle state and the audit's currently published knowledge, including partial results."""

    findings: list[Finding] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    assessments: list[Assessment] = Field(default_factory=list)
    waiting: list[AuditWait] = Field(default_factory=list)
    execution_issues: list[ExecutionDiagnostic] = Field(default_factory=list)
    activity: list["AuditActivity"] = Field(default_factory=list)
    last_progress_at: datetime | None = None
    active_seconds_remaining: float | None = None
    wall_seconds_remaining: float | None = None


class AuditActivity(BaseModel):
    agent_id: str | None
    invocation_id: str | None
    stage: str
    started_at: datetime
    elapsed_seconds: float = Field(ge=0)
    status: Literal["running", "cancellation_pending"]


class AuditService:
    def __init__(self, blackboard: Blackboard):
        self.blackboard = blackboard
        self._states: dict[str, AuditState] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._timings: dict[str, ActiveDeadline] = {}
        self._closing = False

    def get(self, run_id: str) -> AuditState | None:
        return self._states.get(run_id)

    async def wait(self, run_id: str) -> AuditState:
        """Join an accepted audit, including bounded resource cleanup."""
        task = self._tasks.get(run_id)
        if task is not None:
            await task
        return self._states[run_id]

    async def report(self, run_id: str) -> SoftwareAuditReport | None:
        if self.get(run_id) is None:
            return None
        return await AuditReportAgent(blackboard=self.blackboard).run(AuditReportRequest(run_id=run_id))

    def snapshot(self, run_id: str) -> AuditSnapshot | None:
        state = self.get(run_id)
        if state is None:
            return None
        # Read evidence last: publishers append it before findings/assessments.
        # Each query returns detached copies; no internal storage is exposed.
        assessments = self.blackboard.query_assessments(run_id)
        findings = self.blackboard.query_findings(run_id)
        evidence = self.blackboard.query_evidence(run_id)
        order = attrgetter("created_at", "id")
        timing = self._timings.get(run_id)
        return AuditSnapshot(**state.model_dump(),
            execution_issues=execution_diagnostics(assessments, evidence, findings),
            findings=sorted(findings, key=order), evidence=sorted(evidence, key=order),
            assessments=sorted(assessments, key=order), waiting=timing.waiting() if timing is not None else [],
            activity=timing.activity() if timing is not None else [],
            last_progress_at=timing.last_progress_at if timing is not None else None,
            active_seconds_remaining=timing.active_remaining if timing is not None else None,
            wall_seconds_remaining=timing.wall_remaining if timing is not None else None)

    def start(self, repository_path: str, request: MaintainabilityRequest,
              config: ExecutionConfig, agent_config: str,
              agent_defaults: AuditAgentDefaults | None = None,
              audit_budget: TokenBudgetConfig | None = None,
              call_limits: AuditCallLimits | None = None, *,
              agent_configs: dict[str, ExecutionConfig] | None = None) -> AuditState:
        """Validate before acceptance and retain a task until its owned resources are closed."""
        if self._closing:
            raise RuntimeError("Audit service is shutting down.")
        validate_model_configs(agent_configs)
        root = Path(repository_path).expanduser().resolve()
        workspace = resolve_workspace_root()
        if root.parent != workspace:
            raise InvalidConfigError("repository_path must be a checkout directly inside the shared workspace.")
        if not root.is_dir():
            raise FileNotFoundError("Repository directory not found.")
        limits = MaintainabilityConfig()
        total_tokens = audit_budget.max_total_tokens if audit_budget is not None else limits.max_total_tokens
        if agent_defaults is not None or call_limits is not None:
            try:
                if agent_defaults is not None:
                    limits = apply_audit_defaults(limits, agent_defaults)
                if call_limits is not None:
                    limits = apply_audit_call_limits(limits, call_limits)
                validate_audit_agents(limits)
            except ValidationError:
                raise InvalidConfigError("Invalid developer agent defaults for the audit hierarchy.") from None
            try:
                validate_call_capacity(limits, request)
            except ValueError as error:
                raise InvalidConfigError(str(error)) from None
        if config.timeout_seconds is not None:
            try:
                limits = validate_agent_config("maintainability_manager", {"timeout_seconds": config.timeout_seconds}, base=limits)
            except ValidationError:
                raise InvalidConfigError("Invalid audit timeout.") from None
        root_config = (agent_configs or {}).get("maintainability_manager", config)
        settings, credentials, _ = get_execution_service().resolve_model_settings(
            agent_config, root_config.model_copy(update={"timeout_seconds": limits.timeout_seconds}),
        )
        if settings.provider.lower() not in PROVIDERS:
            raise InvalidConfigError("Unsupported model provider.")
        model_selections = {}
        for agent_type, selected in (agent_configs or {}).items():
            resolved, access, _ = get_execution_service().resolve_model_settings(agent_type, selected)
            if resolved.provider.lower() not in PROVIDERS:
                raise InvalidConfigError("Unsupported model provider.")
            model_selections[agent_type] = (resolved, access)
        identity = AuditIdentity()
        state = AuditState(run_id=identity.run_id, invocation_id=identity.invocation_id, status="queued",
            view_url=f"/blackboard?run_id={identity.run_id}", created_at=datetime.now(UTC))
        self._states[identity.run_id] = state
        task = asyncio.create_task(
            self._execute(identity, root, request, limits, settings, credentials, total_tokens, model_selections), name=f"audit-{identity.run_id}",
        )
        self._tasks[identity.run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(identity.run_id, None))
        return state

    def _update(self, run_id: str, status: AuditStatus, error: str | None = None) -> None:
        self._states[run_id] = self._states[run_id].model_copy(update={"status": status, "error": error})
        if status in {"completed", "partial", "failed", "cancelled"}:
            publish_audit_outcome(self.blackboard,
                AuditIdentity(run_id=run_id, invocation_id=self._states[run_id].invocation_id), status)

    async def _execute(self, identity: AuditIdentity, root: Path, request: MaintainabilityRequest,
                       limits: MaintainabilityConfig, settings: ModelSettings, credentials: ModelCredentials,
                       total_tokens: int, model_selections=None) -> None:
        model = None
        clients = {}
        self._update(identity.run_id, "running")
        timing = ActiveDeadline(limits.timeout_seconds, wall_deadline=monotonic() + limits.max_wall_time_seconds,
            cancellation_grace_seconds=limits.cancellation_grace_seconds,
            label="maintainability_manager", invocation_id=identity.invocation_id)
        self._timings[identity.run_id] = timing

        async def run():
            nonlocal model
            with timing.stage("repository_snapshot"):
                snapshot = await RepositoryAnalysisService().analyze(RepositoryAnalysisInput(root_path=str(root)))
            publish_audit_context(self.blackboard, identity, snapshot, request,
                started_at=self._states[identity.run_id].created_at)
            budget = ExecutionBudget(
                max_model_calls=limits.max_model_calls, max_tool_calls=limits.max_tool_calls,
                max_total_tokens=total_tokens, max_tokens_per_objective=total_tokens,
                max_input_tokens_per_call=max(500, limits.max_context_characters // 2),
                max_output_tokens_per_call=limits.max_output_tokens, max_elapsed_seconds=limits.timeout_seconds,
            )
            tools = RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(
                snapshot_hash=snapshot.repository.snapshot_hash, budget=budget,
            )), workspace_root=root.parent, limits=ToolLimits(compact=True),
                token_budget=SharedTokenBudget(total_tokens), timing=timing)
            def client(selected, access):
                key = (selected.model_dump_json(), access.api_key)
                if key not in clients:
                    clients[key] = build_chat_model(selected, access)
                return clients[key]

            model = client(settings, credentials)
            models = {agent_type: client(selected, access)
                for agent_type, (selected, access) in (model_selections or {}).items()}
            tracing = LangSmithTracingBackend()
            manager = MaintainabilityManagerAgent(model, limits, blackboard=self.blackboard,
                audit_identity=identity, tracing_backend=tracing)
            manager.agent_models = models
            with timing.stage("maintainability_audit"):
                return await tracing.wrap_stage(manager.run(tools, request), name="maintainability-manager",
                    audit_id=identity.run_id, invocation_id=identity.invocation_id,
                    repository_id=snapshot.repository.name, snapshot_hash=snapshot.repository.snapshot_hash)

        try:
            result = await within_deadline(run(), timing)
            if timing.publication_allowed:
                self._update(identity.run_id, "completed" if result.status == "complete" else result.status)
        except asyncio.CancelledError:
            self._update(identity.run_id, "cancelled")
            raise
        except TimeoutError:
            self._update(identity.run_id, "failed", "Audit timed out.")
        except Exception as error:  # noqa: BLE001 - keep task errors and provider secrets out of HTTP responses
            logger.error("Audit %s failed (%s)", identity.run_id, type(error).__name__)
            self._update(identity.run_id, "failed", f"Audit failed ({type(error).__name__}).")
        finally:
            try:
                if model is not None:
                    cleanup = ActiveDeadline(max(0.001, limits.cancellation_grace_seconds), cancellation_grace_seconds=0)
                    with timing.stage("close_provider_clients"):
                        try:
                            await within_deadline(asyncio.gather(*(
                                close_model_clients(SimpleNamespace(llm=entry))
                                for entry in {id(value): value for value in clients.values()}.values())), cleanup)
                        except TimeoutError:
                            logger.warning("Audit %s provider_cleanup_timeout", identity.run_id)
            finally:
                self._timings.pop(identity.run_id, None)

    async def cancel(self, run_id: str) -> None:
        """Cancel one pipeline audit without affecting other active audits."""
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return
        task.cancel()
        cleanup = ActiveDeadline(MaintainabilityConfig().cancellation_grace_seconds, cancellation_grace_seconds=0)
        try:
            await within_deadline(asyncio.gather(task, return_exceptions=True), cleanup)
        except TimeoutError:
            logger.warning("Audit %s cancellation_pending", run_id)

    async def aclose(self) -> None:
        """Cancel active work and await cleanup before the application releases its Blackboard."""
        self._closing = True
        tasks = list(self._tasks.values())
        for run_id, task in self._tasks.items():
            if self._states[run_id].status in {"queued", "running"}:
                task.cancel()
        if tasks:
            cleanup = ActiveDeadline(MaintainabilityConfig().cancellation_grace_seconds, cancellation_grace_seconds=0)
            try:
                await within_deadline(asyncio.gather(*tasks, return_exceptions=True), cleanup)
            except TimeoutError:
                logger.warning("audit_shutdown_cancellation_pending")
        for run_id, state in self._states.items():
            if state.status in {"queued", "running"}:
                self._update(run_id, "cancelled")
        self._tasks.clear()
