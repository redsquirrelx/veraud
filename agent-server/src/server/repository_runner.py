"""Shared CLI lifecycle for orientation and architecture, with no analyst modes."""

import argparse
import asyncio
import hashlib
import json
import logging
import math
import sys
from pathlib import Path
from time import monotonic

from .agents.project_architecture import ArchitectureLimits, ProjectArchitectureAgent
from .agents.project_architecture.smoke import ArchitectureSmokeModel
from .agents.project_orientation import ProjectOrientationAgent
from .agents.project_orientation.smoke import OrientationSmokeModel
from .agents.repository_runtime import (
    ExecutionBudget,
    RepositoryContext,
    RepositoryInput,
    RepositoryToolset,
    ToolLimits,
)
from .agents.repository_runtime.access import (
    DEFAULT_WORKSPACE_ROOT,
    RepositoryAccessError,
)
from .agents.repository_runtime.model_runtime import (
    ModelGateway,
    close_model_clients,
    create_project_model,
)
from .repository_progress import ProgressReporter, with_progress
from .services.repository_analysis import (
    RepositoryAnalysisInput,
    RepositoryAnalysisService,
)


def build_parser(mode):
    architecture = mode == "architecture"
    parser = argparse.ArgumentParser(
        description=f"Run project {mode} over one retained workspace snapshot."
    )
    parser.set_defaults(mode=mode)
    parser.add_argument("root", help="Selected repository checkout")
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    parser.add_argument("--smoke", action="store_true", help="Offline protocol check")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--progress-interval", type=float, default=5)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument(
        "--max-tokens", type=int, default=3000, help="Provider output limit per call"
    )
    parser.add_argument(
        "--max-total-tokens", type=int, default=80000 if architecture else 60000
    )
    parser.add_argument(
        "--max-input-tokens", type=int, default=10000 if architecture else 6000
    )
    parser.add_argument(
        "--max-objective-tokens", type=int, default=40000 if architecture else 20000
    )
    parser.add_argument("--max-model-calls", type=int, default=8 if architecture else 4)
    parser.add_argument("--max-tool-calls", type=int, default=20 if architecture else 6)
    parser.add_argument("--max-retrieved-characters", type=int, default=150000)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--request-interval", type=float, default=0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--retry-backoff", type=float, default=2)
    parser.add_argument("--max-files", type=int, default=5000)
    parser.add_argument("--max-depth", type=int, default=30)
    if architecture:
        parser.add_argument("--skip-orientation", action="store_true")
        parser.add_argument("--strict-architecture-budgets", action="store_true")
    return parser


def create_model(arguments):
    if arguments.smoke:
        return (
            ArchitectureSmokeModel()
            if arguments.mode == "architecture"
            else OrientationSmokeModel()
        )
    from pydantic_settings import BaseSettings, SettingsConfigDict

    from .config.dev_agents_config import load_dev_agents_config
    from .config.schemas import ModelCredentials, ModelSettings
    from .config.settings import ENV_FILE

    class Credentials(BaseSettings):
        model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")
        llm_api_key: str = ""

    defaults = load_dev_agents_config().get("analyzer", (None, None))[1]
    provider = arguments.provider or (defaults.provider if defaults else "google")
    name = arguments.model or (
        defaults.name if defaults and provider == defaults.provider else None
    )
    api_key = arguments.api_key or Credentials().llm_api_key
    if not name or not api_key:
        raise ValueError(
            "Provide model/provider credentials or use --smoke for an offline check."
        )
    return create_project_model(
        ModelSettings(
            provider=provider,
            name=name,
            temperature=arguments.temperature,
            max_tokens=arguments.max_tokens,
        ),
        ModelCredentials(api_key=api_key),
    )


def make_tools(snapshot, budget, workspace):
    return RepositoryToolset(
        RepositoryContext(
            snapshot=snapshot,
            input=RepositoryInput(
                snapshot_hash=snapshot.repository.snapshot_hash, budget=budget
            ),
        ),
        workspace_root=workspace,
        limits=ToolLimits(
            compact=True,
            max_page_size=25,
            max_source_lines=80,
            max_source_characters=2400,
        ),
    )


def run_metadata(arguments, tools, model):
    server = Path(__file__).resolve().parent
    files = [Path(__file__), server / "repository_progress.py"]
    for relative in (
        "agents/repository_runtime",
        "agents/project_orientation",
        "agents/project_architecture",
        "services/repository_analysis",
    ):
        files.extend(
            source
            for source in (server / relative).rglob("*")
            if source.suffix in {".py", ".md"}
        )
    fingerprint = hashlib.sha256()
    for source in sorted(files):
        fingerprint.update(source.relative_to(server).as_posix().encode() + b"\0")
        fingerprint.update(hashlib.sha256(source.read_bytes()).digest())
    settings = getattr(model, "settings", None)
    return {
        "snapshot_hash": tools.context.input.snapshot_hash,
        "repository_name": tools.context.snapshot.repository.name,
        "repository_commit": tools.context.snapshot.repository.commit,
        "implementation_sha256": fingerprint.hexdigest(),
        "provider": getattr(settings, "provider", "offline"),
        "model": getattr(settings, "name", "protocol_smoke"),
        "temperature": getattr(settings, "temperature", None),
        "max_output_tokens": getattr(settings, "max_tokens", None),
        "budget": tools.context.input.budget.model_dump(mode="json"),
        "workflow": arguments.mode,
        "max_files": arguments.max_files,
        "max_depth": arguments.max_depth,
        "request_interval": arguments.request_interval,
        "max_retries": arguments.max_retries,
        "retry_backoff": arguments.retry_backoff,
    }


async def run(arguments):
    for value in (arguments.request_interval, arguments.retry_backoff):
        if not math.isfinite(value) or value < 0:
            raise ValueError("Provider pacing must be finite and nonnegative.")
    if (
        not math.isfinite(arguments.progress_interval)
        or arguments.progress_interval <= 0
        or arguments.max_retries < 0
    ):
        raise ValueError(
            "Progress interval must be positive and retry count nonnegative."
        )
    workspace = arguments.workspace_root.expanduser().resolve()
    root = Path(arguments.root).expanduser().resolve()
    if root.parent != workspace:
        raise RepositoryAccessError(
            "Select one checkout directly inside the configured workspace."
        )
    architecture = arguments.mode == "architecture"
    budget = ExecutionBudget(
        max_model_calls=min(8 if architecture else 4, arguments.max_model_calls),
        max_tool_calls=min(20 if architecture else 6, arguments.max_tool_calls),
        max_total_tokens=arguments.max_total_tokens,
        max_input_tokens_per_call=arguments.max_input_tokens,
        max_tokens_per_objective=arguments.max_objective_tokens,
        max_output_tokens_per_call=arguments.max_tokens,
        max_retrieved_characters=arguments.max_retrieved_characters,
        max_elapsed_seconds=arguments.timeout,
    )
    reporter = (
        None if arguments.quiet else ProgressReporter(arguments.progress_interval)
    )

    def emit(event, **values):
        if reporter:
            reporter(event, values)

    async def execute(agent, tools, orientation=None):
        awaitable = (
            agent.run(tools, orientation)
            if isinstance(agent, ProjectArchitectureAgent)
            else agent.run(tools)
        )
        if arguments.trace:
            from .config.tracing import traced_agent_run

            awaitable = traced_agent_run(awaitable, name=f"project_{arguments.mode}")
        return await with_progress(awaitable, reporter)

    emit(
        "snapshot_started",
        repository=str(root),
        max_files=arguments.max_files,
        max_depth=arguments.max_depth,
    )
    snapshot = await with_progress(
        RepositoryAnalysisService().analyze(
            RepositoryAnalysisInput(
                root_path=str(root),
                max_files=arguments.max_files,
                max_depth=arguments.max_depth,
            )
        ),
        reporter,
    )
    emit(
        "snapshot_ready",
        files=len(snapshot.files),
        projects=len(snapshot.projects),
        symbols=len(snapshot.symbols),
        entrypoints=len(snapshot.entrypoints),
    )
    tools = make_tools(snapshot, budget, workspace)
    deadline = monotonic() + budget.max_elapsed_seconds
    emit(
        "tools_ready",
        accessible_files=len(tools.accessible_snapshot.files),
        max_model_calls=budget.max_model_calls,
        max_tool_calls=budget.max_tool_calls,
        timeout_seconds=budget.max_elapsed_seconds,
    )
    emit("model_initializing", mode="protocol_smoke" if arguments.smoke else "model")
    model = create_model(arguments)
    settings = getattr(model, "settings", None)
    emit(
        "model_ready",
        provider=getattr(settings, "provider", "offline"),
        model=getattr(settings, "name", "protocol_smoke"),
    )
    try:
        gateway = ModelGateway(
            model,
            interval=arguments.request_interval,
            max_retries=arguments.max_retries,
            backoff=arguments.retry_backoff,
            on_event=reporter,
            trace=arguments.trace,
            remaining_seconds=lambda: max(0, deadline - monotonic()),
        )
        metadata = run_metadata(arguments, tools, model)
        orientation = None
        if architecture and not arguments.skip_orientation:
            emit("orientation_started")
            orientation = await execute(
                ProjectOrientationAgent(model, generate=gateway, on_event=reporter),
                tools,
            )
            emit("orientation_finished", status=orientation.completion_status)
            tools = make_tools(
                snapshot,
                budget.model_copy(
                    update={"max_elapsed_seconds": max(0.001, deadline - monotonic())}
                ),
                workspace,
            )
        agent = (
            ProjectArchitectureAgent(
                model,
                generate=gateway,
                on_event=reporter,
                limits=ArchitectureLimits(
                    soft_token_budgets=not arguments.strict_architecture_budgets
                ),
            )
            if architecture
            else ProjectOrientationAgent(model, generate=gateway, on_event=reporter)
        )
        result = await execute(agent, tools, orientation)
        data = result.model_dump(mode="json") | {
            "execution_mode": "protocol_smoke" if arguments.smoke else arguments.mode,
            "run_metadata": metadata,
        }
        if architecture:
            metadata.update(
                architecture_limits=agent.limits.model_dump(mode="json"),
                orientation_included=orientation is not None,
            )
            data.update(
                orientation_result=orientation.model_dump(mode="json")
                if orientation
                else None,
                pipeline_usage=gateway.usage_totals()
                | {
                    "model_calls": len(gateway.measurements),
                    "tool_calls": result.usage.tool_calls
                    + (orientation.usage.tool_calls if orientation else 0),
                },
            )
        else:
            data["file_paths"] = {
                source.id: source.path for source in tools.accessible_snapshot.files
            }
        return data, result.completion_status != "failed"
    finally:
        emit("cleanup_started")
        failures = await with_progress(close_model_clients(model), reporter)
        emit("cleanup_finished", failure_types=list(failures))


def print_summary(data):
    print(f"Mode: {data['execution_mode']}\nStatus: {data['completion_status']}")
    report = data.get("architecture") or data.get("orientation")
    if report:
        for unit in report.get("organization", report.get("components", [])):
            print(
                f"\n{unit['name']}: {unit['responsibility']['statement']} ({unit['responsibility']['status']})"
            )
        classification = report.get("closest_architecture")
        if classification:
            print(
                f"\nClosest architecture: {classification['pattern']} ({classification['assessment']['status']})\n  {classification['assessment']['statement']}\n  Scope: {classification['assessment']['scope']}"
            )
        for name in ("project_type", "purpose", "explanation"):
            if report.get(name):
                print(
                    f"\n{name}: {report[name]['statement']} ({report[name]['status']})"
                )
        for item in report.get("uncertainties", []):
            print(f"  Uncertainty: {item}")
    for citation in data.get("citations", []):
        print(
            f"  {citation['evidence_id']}: {citation['path']}:{citation['start_line']}-{citation['end_line']}"
        )
    for issue in data["execution_issues"]:
        print(f"Issue: {issue['stage']} | {issue['category']} | {issue['message']}")
    if "pipeline_usage" in data:
        print("\nPipeline usage: " + json.dumps(data["pipeline_usage"]))
    print("\nUsage: " + json.dumps(data["usage"]))
    for stage in data["telemetry"]["stages"]:
        print(
            f"  {stage['stage']}: calls={stage['calls']} input_tokens={stage['input_tokens']} output_tokens={stage['output_tokens']} unknown_usage_attempts={stage['unknown_usage_attempts']}"
        )


def main(argv=None, *, mode):
    arguments = build_parser(mode).parse_args(argv)
    logging.disable(logging.CRITICAL)
    try:
        data, valid = asyncio.run(run(arguments))
        print(
            json.dumps(data, indent=2, ensure_ascii=False)
        ) if arguments.json else print_summary(data)
        return 0 if valid else 1
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Repository analysis cancelled.", file=sys.stderr)
        return 130
