"""Quality-audit pipeline adapter over the existing audit and report lifecycle."""

import asyncio
import base64
import subprocess
from pathlib import Path

from pydantic import ConfigDict, Field, ValidationError

from ..agents.functional_adequacy.schemas import FunctionalRequirement
from ..agents.maintainability.manager import MaintainabilityRequest
from ..agents.security.audit import SecurityAuditRequest
from ..blackboard.impls.memory import MemoryBlackboard
from ..config.settings import resolve_workspace_root
from ..runtimes.invocation_reporting import invocation_reporting
from ..services.audit_report_docx import render_audit_report_docx
from .audit_attributes import QualityAttributes, audit_root
from .audit_models import validate_model_configs
from .audit_options import AuditExecutionOptions
from .audit_service import AuditService
from .execution_service import InvalidConfigError


class QualityAuditInput(AuditExecutionOptions):
    model_config = ConfigDict(extra="forbid")

    root_path: str
    attributes: QualityAttributes
    commit_hash: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    request: MaintainabilityRequest = Field(default_factory=MaintainabilityRequest)
    security_request: SecurityAuditRequest = Field(default_factory=SecurityAuditRequest)
    functional_requirements: list[FunctionalRequirement] | None = Field(default=None, min_length=1, max_length=100)


def parse_input(raw):
    try:
        parsed = QualityAuditInput.model_validate(raw)
        if ("functional_adequacy" in parsed.attributes) != (parsed.functional_requirements is not None):
            raise InvalidConfigError("Functional adequacy requires functional_requirements; omit them for other attributes.")
        if parsed.functional_requirements and len({item.requirement_id for item in parsed.functional_requirements}) != len(parsed.functional_requirements):
            raise InvalidConfigError("Functional requirement IDs must be distinct.")
        return parsed
    except ValidationError:
        raise InvalidConfigError("Select supported quality attributes and a full commit hash.") from None


class QualityAuditRunner:
    uses_audit_service = True

    def __init__(self, config, agent_configs=None):
        self.config = config
        self.agent_configs = agent_configs
        self.blackboard = MemoryBlackboard()
        self.audit_service = None

    async def run(self, parsed, hooks):
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
        service = self.audit_service or AuditService(self.blackboard)
        security = parsed.attributes == ["security"]
        stage = audit_root(parsed.attributes)
        if hooks:
            await hooks.on_stage_start(stage)
        state = None
        try:
            async def report_invocation(receipt):
                if hooks:
                    await hooks.on_invocation(stage, receipt)

            with invocation_reporting(report_invocation):
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
            return {"audit": {
                "attributes": parsed.attributes,
                "status": snapshot.status,
                "run_id": state.run_id,
                "report": report.model_dump(mode="json"),
                "blackboard": snapshot.model_dump(mode="json"),
                "docx_base64": base64.b64encode(document).decode("ascii"),
            }}
        finally:
            if self.audit_service is None:
                await service.aclose()
            elif state is not None:
                await service.cancel(state.run_id)


async def build_agents(exec_service, config, stage_configs, parsed, timeout_seconds):
    validate_model_configs(stage_configs, parsed.attributes)
    selected = (stage_configs or {}).get(audit_root(parsed.attributes), config)
    return {"maintainability_manager": QualityAuditRunner(selected, stage_configs)}, {}


def quality_audit_definition():
    from .pipeline_service import PipelineDefinition

    return PipelineDefinition(
        name="quality-audit", stages=["maintainability_manager"], parse_input=parse_input,
        resolve_stages=lambda parsed: [audit_root(parsed.attributes)],
        build_agents=build_agents, adapt_hooks=lambda hooks: hooks,
        create_pipeline=lambda agents, hooks, ctx: (agents["maintainability_manager"], hooks),
        run_pipeline=lambda pipeline, parsed, ctx: pipeline[0].run(parsed, pipeline[1]),
    )
