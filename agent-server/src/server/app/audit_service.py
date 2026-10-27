"""Process-local audit tasks sharing the server's blackboard and model configuration."""

import asyncio
from datetime import UTC, datetime
from operator import attrgetter
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

from pydantic import TypeAdapter, ValidationError

from config.agents.audit import (
    AuditAgentDefaults,
    AuditCallLimits,
    apply_audit_call_limits,
    apply_audit_defaults,
    validate_audit_agents,
    validate_audit_output_capacity,
)
from config.agents.budgets import TokenBudgetConfig
from config.agents.catalog import validate_agent_config
from server.app.audit_state import (
    AuditActivity as AuditActivity,  # noqa: PLC0414 - public compatibility export
)
from server.app.audit_state import (
    AuditSnapshot,
    AuditState,
    AuditStatus,
)
from server.app.audit_state import (
    AuditWait as AuditWait,  # noqa: PLC0414 - public compatibility export
)
from server.app.execution_config import ExecutionConfig
from server.infrastructure.tracing import LangSmithTracingBackend
from server.reporting import AuditReportAgent, AuditReportRequest, SoftwareAuditReport
from server.reporting.schemas import ReportGenerationSummary
from server.services.audit_diagnostics import execution_diagnostics

from ..agents.functional_adequacy.audit import run_functional_audit
from ..agents.functional_adequacy.config import FunctionalAdequacyConfig
from ..agents.functional_adequacy.schemas import FunctionalAdequacyInput
from ..agents.maintainability.manager import (
    MaintainabilityConfig,
    MaintainabilityManagerAgent,
    MaintainabilityRequest,
)
from ..agents.maintainability.manager.validation import validate_call_capacity
from ..agents.security.audit import (
    SecurityAuditRequest,
    run_security_audit,
)
from ..agents.security.config import (
    SecurityAuditConfig,
    SecurityAuditOverrides,
    resolve_security_audit_config,
)
from ..blackboard.identity import AuditIdentity
from ..blackboard.interface import Blackboard
from ..blackboard.models import Assessment
from ..blackboard.publication import publish_audit_context, publish_audit_outcome
from ..config import tracing
from ..config.logs import get_logger
from ..config.schemas import ModelCredentials, ModelSettings
from ..config.settings import resolve_workspace_root
from ..infrastructure.llm.chat import PROVIDERS, build_chat_model
from ..infrastructure.llm.resources import close_model_clients
from ..runtimes.invocation_reporting import observe_invocation
from ..runtimes.repository.shared_tokens import SharedTokenBudget
from ..runtimes.repository.timing import ActiveDeadline, within_deadline
from ..runtimes.repository.tools import RepositoryToolset as RepositoryToolset  # noqa: PLC0414 - test compatibility
from ..services.repository_analysis import (
    RepositoryAnalysisInput,
    RepositoryAnalysisService,
)
from .audit_attributes import QualityAttributes, audit_root
from .audit_configuration import resolve_attribute_limits
from .audit_models import validate_model_configs
from .audit_resources import audit_client, repository_tools
from .errors import InvalidConfigError
from .model_configuration import default_model_configuration, resolve_model_settings

logger = get_logger("audit-service")


class AuditService:
    def __init__(self, blackboard: Blackboard):
        self.blackboard = blackboard
        self._states: dict[str, AuditState] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._timings: dict[str, ActiveDeadline] = {}
        self._closing = False
        self._report_generations: dict[str, dict[str, SoftwareAuditReport]] = {}
        self._base_model_config: dict | None = None

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
        report = await AuditReportAgent(blackboard=self.blackboard).run(AuditReportRequest(run_id=run_id))
        self.retain_report(report)
        return report

    def retain_report(self, report: SoftwareAuditReport) -> None:
        """Keep immutable output receipts separate from the audit's input Blackboard."""
        generation = report.annexes_and_traceability.generation
        if generation is None:
            raise ValueError("A generated report must include its construction trace.")
        reports = self._report_generations.setdefault(report.identification.audit_id, {})
        existing = reports.get(generation.generation_id)
        if existing is not None and existing != report:
            raise ValueError("Cannot overwrite an original report generation.")
        reports[generation.generation_id] = report.model_copy(deep=True)

    def report_generations(self, run_id: str) -> list[ReportGenerationSummary]:
        return [ReportGenerationSummary(**{key: getattr(report.annexes_and_traceability.generation, key)
                for key in ReportGenerationSummary.model_fields})
            for report in self._report_generations.get(run_id, {}).values()]

    def saved_report(self, run_id: str, generation_id: str) -> SoftwareAuditReport | None:
        report = self._report_generations.get(run_id, {}).get(generation_id)
        return report.model_copy(deep=True) if report is not None else None

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

    def start(self, repository_path: str, request: MaintainabilityRequest | SecurityAuditRequest,
              config: ExecutionConfig, agent_config: str,
              agent_defaults: AuditAgentDefaults | None = None,
              audit_budget: TokenBudgetConfig | None = None,
              call_limits: AuditCallLimits | None = None, *,
              agent_configs: dict[str, ExecutionConfig] | None = None,
              attributes: list[str] | None = None, security_request: SecurityAuditRequest | None = None,
               security_config: SecurityAuditOverrides | None = None, functional_requirements=None,
               attribute_options=None, functional_config=None) -> AuditState:
        """Validate before acceptance and retain a task until its owned resources are closed."""
        if self._closing:
            raise RuntimeError("Audit service is shutting down.")
        try:
            attributes = TypeAdapter(QualityAttributes).validate_python(attributes if attributes is not None else [
                "security" if isinstance(request, SecurityAuditRequest) else "maintainability"])
        except ValidationError:
            raise InvalidConfigError("Select distinct supported quality attributes.") from None
        security = attributes == ["security"]
        maintainability = "maintainability" in attributes
        combined = len(attributes) > 1
        if "functional_adequacy" in attributes:
            try:
                functional_requirements = FunctionalAdequacyInput(requirements=functional_requirements).requirements
            except ValidationError:
                raise InvalidConfigError("Functional adequacy requires distinct, nonempty functional_requirements.") from None
        elif functional_requirements is not None:
            raise InvalidConfigError("functional_requirements requires functional_adequacy in attributes.")
        if not security and isinstance(request, SecurityAuditRequest):
            raise InvalidConfigError("Audits selecting maintainability require its request plus an optional security_request.")
        if security:
            request = security_request or (request if isinstance(request, SecurityAuditRequest) else SecurityAuditRequest())
        validate_model_configs(agent_configs, attributes)
        if security_config is not None and "security" not in attributes:
            raise InvalidConfigError("security_config requires security in attributes.")
        if not maintainability and call_limits is not None:
            raise InvalidConfigError("call_limits requires maintainability in attributes.")
        if functional_config is not None and "functional_adequacy" not in attributes:
            raise InvalidConfigError("functional_config requires functional_adequacy in attributes.")
        if attribute_options and set(attribute_options) - set(attributes):
            raise InvalidConfigError("attribute_options must belong to selected attributes.")
        root = Path(repository_path).expanduser().resolve()
        workspace = resolve_workspace_root()
        if root.parent != workspace:
            raise InvalidConfigError("repository_path must be a checkout directly inside the shared workspace.")
        if not root.is_dir():
            raise FileNotFoundError("Repository directory not found.")
        limits = MaintainabilityConfig() if maintainability else (
            SecurityAuditConfig() if "security" in attributes else FunctionalAdequacyConfig())
        functional_limits = FunctionalAdequacyConfig()
        if agent_defaults is not None:
            functional_limits = apply_audit_defaults(functional_limits, agent_defaults)
        total_tokens = audit_budget.max_total_tokens if audit_budget is not None else limits.max_total_tokens
        security_limits = None
        if "security" in attributes:
            try:
                if security_config is not None:
                    security_config = SecurityAuditOverrides.model_validate(security_config)
                security_limits = resolve_security_audit_config(defaults=agent_defaults, overrides=security_config,
                    base=limits if security else SecurityAuditConfig())
            except ValidationError:
                raise InvalidConfigError("Invalid security operating configuration.") from None
            if security:
                limits = security_limits
        if maintainability and (agent_defaults is not None or call_limits is not None):
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
        try:
            for attribute, overrides in (attribute_options or {}).items():
                if "audit_budget" in overrides:
                    raise InvalidConfigError("Use the shared audit_budget outside attribute_options.")
                if attribute == "maintainability":
                    limits = resolve_attribute_limits(attribute, overrides, base=limits)
                    validate_call_capacity(limits, request)
                elif attribute == "security":
                    security_limits = resolve_attribute_limits(attribute, overrides, base=security_limits)
                    if security:
                        limits = security_limits
                else:
                    functional_limits = resolve_attribute_limits(attribute, overrides, base=functional_limits)
            if functional_config is not None:
                functional_limits = resolve_attribute_limits("functional_adequacy",
                    {"functional_config": functional_config.model_dump(exclude_unset=True)}, base=functional_limits)
            if attributes == ["functional_adequacy"]:
                limits = functional_limits
        except (ValidationError, ValueError) as error:
            raise InvalidConfigError(str(error)) from None
        if config.timeout_seconds is not None:
            try:
                timeout = config.timeout_seconds
                if security and security_config is not None and "timeout_seconds" in security_config.model_fields_set:
                    timeout = min(timeout, limits.timeout_seconds)
                limits = validate_agent_config(audit_root(attributes),
                    {"timeout_seconds": timeout}, base=limits)
            except ValidationError:
                raise InvalidConfigError("Invalid audit timeout.") from None
        if attributes == ["functional_adequacy"]:
            functional_limits = functional_limits.model_copy(update={"timeout_seconds": limits.timeout_seconds})
        # model.max_tokens is the wire alias of an explicit per-agent output
        # override, not a second cap. Resolve it once into the owning runtime field.
        output_overrides = {name: selected.model.max_tokens for name, selected in (agent_configs or {}).items()
            if selected.model.max_tokens is not None}
        root_id = audit_root(attributes)
        if root_id not in output_overrides and config.model.max_tokens is not None:
            output_overrides[root_id] = config.model.max_tokens
        try:
            for value in output_overrides.values():
                AuditAgentDefaults(max_output_tokens=value)
            if root_id in output_overrides:
                limits = type(limits).model_validate({**limits.model_dump(), "max_output_tokens": output_overrides[root_id]})
            if "security" in output_overrides and security_limits is not None:
                security_limits = type(security_limits).model_validate({**security_limits.model_dump(),
                    "max_output_tokens": output_overrides["security"]})
            if "functional_adequacy" in output_overrides:
                functional_limits = type(functional_limits).model_validate({**functional_limits.model_dump(),
                    "max_output_tokens": output_overrides["functional_adequacy"]})
        except ValidationError:
            raise InvalidConfigError("Invalid per-agent output token override; use the runtime max_output_tokens constraints.") from None
        try:
            validate_audit_output_capacity(limits)
            if "security" in attributes:
                validate_audit_output_capacity(security_limits)
            if "functional_adequacy" in attributes:
                validate_audit_output_capacity(functional_limits)
        except ValueError as error:
            raise InvalidConfigError(str(error)) from None
        root_config = (agent_configs or {}).get(audit_root(attributes), config)
        if self._base_model_config is None:
            self._base_model_config = default_model_configuration()
        # The direct-run service used to be instantiated here only to resolve
        # configuration (also registering direct agents and initializing tracing).
        tracing.setup()
        settings, credentials, _ = resolve_model_settings(
            self._base_model_config,
            agent_config,
            root_config.model_copy(update={"timeout_seconds": limits.timeout_seconds}),
        )
        if settings.provider.lower() not in PROVIDERS:
            raise InvalidConfigError("Unsupported model provider.")
        model_selections = {}
        for agent_type, selected in (agent_configs or {}).items():
            resolved, access, _ = resolve_model_settings(
                self._base_model_config, agent_type, selected
            )
            if resolved.provider.lower() not in PROVIDERS:
                raise InvalidConfigError("Unsupported model provider.")
            model_selections[agent_type] = (resolved, access)
        identity = AuditIdentity()
        state = AuditState(run_id=identity.run_id, invocation_id=identity.invocation_id, status="queued",
            view_url=f"/blackboard?run_id={identity.run_id}", created_at=datetime.now(UTC))
        self._states[identity.run_id] = state
        task = asyncio.create_task(
            self._execute(identity, root, request, limits, settings, credentials, total_tokens, model_selections,
                security_request=(security_request or SecurityAuditRequest()) if combined and "security" in attributes else None,
                security_limits=security_limits, attributes=attributes,
                functional_requirements=functional_requirements, functional_limits=functional_limits,
                output_overrides=output_overrides), name=f"audit-{identity.run_id}",
        )
        self._tasks[identity.run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(identity.run_id, None))
        return state

    def _update(self, run_id: str, status: AuditStatus, error: str | None = None) -> None:
        self._states[run_id] = self._states[run_id].model_copy(update={"status": status, "error": error})
        if status in {"completed", "partial", "failed", "cancelled"}:
            publish_audit_outcome(self.blackboard,
                AuditIdentity(run_id=run_id, invocation_id=self._states[run_id].invocation_id), status)

    async def _execute(self, identity: AuditIdentity, root: Path, request: MaintainabilityRequest | SecurityAuditRequest,
                       limits: MaintainabilityConfig | SecurityAuditConfig | FunctionalAdequacyConfig, settings: ModelSettings, credentials: ModelCredentials,
                       total_tokens: int, model_selections=None, *, security_request=None, security_limits=None,
                       attributes=None, functional_requirements=None, functional_limits=None, output_overrides=None) -> None:
        model = None
        clients = {}
        self._update(identity.run_id, "running")
        timing = ActiveDeadline(limits.timeout_seconds, wall_deadline=monotonic() + limits.max_wall_time_seconds,
            cancellation_grace_seconds=limits.cancellation_grace_seconds,
            label="quality_audit" if len(attributes) > 1 else audit_root(attributes), invocation_id=identity.invocation_id)
        self._timings[identity.run_id] = timing

        async def run():
            nonlocal model
            with timing.stage("repository_snapshot"):
                snapshot = await RepositoryAnalysisService().analyze(RepositoryAnalysisInput(root_path=str(root)))
            context_request = request if security_request is None else SimpleNamespace(
                objective=request.objective + "\n" + security_request.objective,
                targets=list(dict.fromkeys([*request.targets, *security_request.targets])))
            if functional_requirements is not None:
                scopes = [request] if "maintainability" in attributes else []
                if security_request is not None:
                    scopes.append(security_request)
                context_request = SimpleNamespace(objective="\n".join([*(scope.objective for scope in scopes),
                    "Contrastar los requisitos funcionales suministrados con el código de la revisión seleccionada."]),
                    targets=list(dict.fromkeys(target for scope in scopes for target in scope.targets)))
            publish_audit_context(self.blackboard, identity, snapshot, context_request,
                started_at=self._states[identity.run_id].created_at,
                attributes=attributes)
            if security_request is not None or functional_requirements is not None:
                return await self._run_combined(identity, root, snapshot, request, security_request, limits,
                    settings, credentials, total_tokens, model_selections, timing, clients, security_limits,
                    attributes, functional_requirements, functional_limits, output_overrides)
            tools = repository_tools(
                snapshot,
                root,
                limits,
                total_tokens,
                timing,
                SharedTokenBudget(total_tokens),
                output_overrides,
                security=isinstance(request, SecurityAuditRequest),
            )
            model = audit_client(clients, settings, credentials, build_chat_model)
            tracing = LangSmithTracingBackend()
            if isinstance(request, SecurityAuditRequest):
                with timing.stage("security_audit"):
                    return await observe_invocation(tracing.wrap_stage(run_security_audit(tools, request,
                        limits,
                        model, self.blackboard, identity),
                        name="security-audit", audit_id=identity.run_id, invocation_id=identity.invocation_id,
                        repository_id=snapshot.repository.name, snapshot_hash=snapshot.repository.snapshot_hash),
                        agent_id="security", invocation_id=identity.invocation_id, run_id=identity.run_id)
            models = {agent_type: audit_client(clients, selected, access, build_chat_model)
                for agent_type, (selected, access) in (model_selections or {}).items()}
            manager = MaintainabilityManagerAgent(model, limits, blackboard=self.blackboard,
                audit_identity=identity, tracing_backend=tracing)
            manager.agent_models = models
            manager.agent_output_limits = output_overrides or {}
            with timing.stage("maintainability_audit"):
                return await observe_invocation(tracing.wrap_stage(manager.run(tools, request), name="maintainability-manager",
                    audit_id=identity.run_id, invocation_id=identity.invocation_id,
                    repository_id=snapshot.repository.name, snapshot_hash=snapshot.repository.snapshot_hash),
                    agent_id="maintainability_manager", invocation_id=identity.invocation_id, run_id=identity.run_id)

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
                if clients:
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

    async def _run_combined(self, identity, root, snapshot, request, security_request, limits,
                            settings, credentials, total_tokens, model_selections, timing, clients, security_limits,
                            attributes, functional_requirements, functional_limits, output_overrides=None):
        """One snapshot and token ledger; attribute failures do not cancel their sibling."""
        shared_tokens = SharedTokenBudget(total_tokens)
        tracing = LangSmithTracingBackend()

        async def evaluate(attribute, selected_request, policy):
            # Keep the manager's established root identity for report authority
            # and continuation lineage; security owns a distinct invocation.
            agent_id = audit_root([attribute])
            child = identity if agent_id == audit_root(attributes) else AuditIdentity(run_id=identity.run_id)
            deadline = timing.fork(policy.timeout_seconds, label=agent_id, invocation_id=child.invocation_id,
                max_wall_time_seconds=policy.max_wall_time_seconds,
                cancellation_grace_seconds=policy.cancellation_grace_seconds)

            async def execute():
                tools = repository_tools(
                    snapshot,
                    root,
                    policy,
                    total_tokens,
                    deadline,
                    shared_tokens.fork(),
                    output_overrides,
                    security=attribute == "security",
                )
                selected, access = (model_selections or {}).get(agent_id, (settings, credentials))
                model = audit_client(clients, selected, access, build_chat_model)
                if attribute == "functional_adequacy":
                    operation = run_functional_audit(snapshot, selected_request, policy, model,
                        self.blackboard, child, shared_tokens.fork(), deadline)
                elif attribute == "security":
                    operation = run_security_audit(tools, selected_request,
                        policy,
                        model, self.blackboard, child)
                else:
                    manager = MaintainabilityManagerAgent(model, policy, blackboard=self.blackboard,
                        audit_identity=child, tracing_backend=tracing)
                    manager.agent_models = {name: audit_client(clients, *selection, build_chat_model)
                        for name, selection in (model_selections or {}).items()
                        if name not in {"security", "functional_adequacy"}}
                    manager.agent_output_limits = output_overrides or {}
                    operation = manager.run(tools, selected_request)
                with deadline.stage(attribute + "_audit"):
                    return await observe_invocation(tracing.wrap_stage(operation, name=attribute + "-audit", audit_id=identity.run_id,
                        invocation_id=child.invocation_id, repository_id=snapshot.repository.name,
                        snapshot_hash=snapshot.repository.snapshot_hash),
                        agent_id=agent_id, invocation_id=child.invocation_id, run_id=identity.run_id)

            try:
                return (await within_deadline(execute(), deadline)).status
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - retain the sibling result and safe failure provenance
                self.blackboard.publish_assessment(Assessment(agent_id=agent_id, run_id=identity.run_id,
                    invocation_id=child.invocation_id, repository_id=snapshot.repository.name,
                    snapshot_hash=snapshot.repository.snapshot_hash, commit=snapshot.repository.commit,
                    objective=getattr(selected_request, "objective", "Evaluar los requisitos funcionales suministrados."),
                    targets=tuple(getattr(selected_request, "targets", ())),
                    quality_attribute=attribute, status="failed", termination_reason="attribute_execution_failed",
                    limitations=(f"El análisis de {attribute} terminó con {type(error).__name__}.",),
                    details={"quality_attribute": attribute, "execution_error_type": type(error).__name__}))
                return "failed"

        operations = []
        if "maintainability" in attributes:
            operations.append(evaluate("maintainability", request, limits))
        if "security" in attributes:
            operations.append(evaluate("security", security_request, security_limits))
        if "functional_adequacy" in attributes:
            operations.append(evaluate("functional_adequacy", functional_requirements, functional_limits))
        statuses = await asyncio.gather(*operations)
        status = "completed" if all(value in {"complete", "completed"} for value in statuses) else (
            "failed" if all(value == "failed" for value in statuses) else "partial")
        return SimpleNamespace(status=status)

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
