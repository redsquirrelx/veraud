"""Quality-audit pipeline adapter over the existing audit and report lifecycle."""

import asyncio
import base64
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..agents.maintainability.manager import MaintainabilityRequest
from ..blackboard.impls.memory import MemoryBlackboard
from ..config.settings import resolve_workspace_root
from ..services.audit_report_docx import render_audit_report_docx
from .audit_models import validate_model_configs
from .audit_service import AuditService
from .execution_service import InvalidConfigError


class QualityAuditInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_path: str
    attributes: list[Literal["maintainability"]] = Field(min_length=1, max_length=1)
    commit_hash: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    request: MaintainabilityRequest = Field(default_factory=MaintainabilityRequest)


def parse_input(raw):
    try:
        return QualityAuditInput.model_validate(raw)
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
        if hooks:
            await hooks.on_stage_start("maintainability_manager")
        state = None
        try:
            state = service.start(str(root), parsed.request, self.config, "maintainability_manager",
                agent_configs=self.agent_configs)
            if hooks:
                await hooks.on_audit_start("maintainability_manager", state.run_id)
            await service.wait(state.run_id)
            snapshot = service.snapshot(state.run_id)
            report = await service.report(state.run_id)
            document = await asyncio.to_thread(render_audit_report_docx, report)
            # The backend stores this envelope from the HTTP response. Lifecycle
            # callbacks only mark Running: large report artifacts are sent once.
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
    validate_model_configs(stage_configs)
    selected = (stage_configs or {}).get("maintainability_manager", config)
    return {"maintainability_manager": QualityAuditRunner(selected, stage_configs)}, {}


def quality_audit_definition():
    from .pipeline_service import PipelineDefinition

    return PipelineDefinition(
        name="quality-audit", stages=["maintainability_manager"], parse_input=parse_input,
        build_agents=build_agents, adapt_hooks=lambda hooks: hooks,
        create_pipeline=lambda agents, hooks, ctx: (agents["maintainability_manager"], hooks),
        run_pipeline=lambda pipeline, parsed, ctx: pipeline[0].run(parsed, pipeline[1]),
    )
