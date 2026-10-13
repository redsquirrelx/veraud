"""Run the new workspace-bound project analyst, or an offline protocol smoke test."""

import argparse
import asyncio
import hashlib
import json
import logging
import math
import sys
from contextlib import suppress
from pathlib import Path
from time import monotonic

from pydantic import ValidationError

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.agents.project_analysis import (
    InvestigationBudget,
    ProjectAnalysisAgent,
    ProjectAnalysisContext,
    ProjectAnalysisInput,
    RepositoryToolset,
)
from server.agents.project_analysis.access import (
    DEFAULT_WORKSPACE_ROOT,
    RepositoryAccessError,
)
from server.agents.project_analysis.agent import AnalysisLimits
from server.agents.project_analysis.baseline_agent import (
    AnalysisLimits as BaselineLimits,
)
from server.agents.project_analysis.baseline_agent import BaselineProjectAnalysisAgent
from server.agents.project_analysis.evaluation import evaluate_run, summarize_evaluation
from server.agents.project_analysis.graph import InvestigationPlanner
from server.agents.project_analysis.model_runtime import (
    ModelGateway,
    close_model_clients,
    create_project_model,
)
from server.agents.project_analysis.planning import select_deterministic_plan
from server.agents.project_analysis.schemas import (
    ArchitectureAnalysisInput,
    ArchitectureBrief,
)
from server.agents.project_analysis.smoke import ProtocolSmokeModel
from server.agents.project_analysis.tools import ToolLimits
from server.agents.project_orientation import ProjectOrientationAgent
from server.agents.project_orientation.smoke import OrientationSmokeModel
from server.services.repository_analysis import (
    RepositoryAnalysisInput,
    RepositoryAnalysisService,
)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Investigate one repository checkout inside appdata/workspace using LangGraph."
    )
    parser.add_argument("root", nargs="?", help="Selected repository checkout")
    parser.add_argument(
        "--orientation",
        action="store_true",
        help="Run the small representation-backed LangGraph orientation agent (4 model calls, 6 tools maximum)",
    )
    parser.add_argument(
        "--evaluate-workspace",
        action="store_true",
        help="Evaluate the pinned workspace suite; metrics are structural proxies",
    )
    parser.add_argument(
        "--suite",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "benchmarks" / "workspace.yaml",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="Restrict evaluation to a case ID (repeatable)",
    )
    parser.add_argument(
        "--repeat", type=int, default=1, help="Evaluation repetitions per case"
    )
    parser.add_argument(
        "--input-price",
        type=float,
        default=None,
        help="Evaluation USD per million input tokens",
    )
    parser.add_argument(
        "--output-price",
        type=float,
        default=None,
        help="Evaluation USD per million output tokens",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=DEFAULT_WORKSPACE_ROOT,
        help="Trusted host workspace configuration",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Offline protocol test; no semantic analysis or credentials",
    )
    parser.add_argument(
        "--plan-only", action="store_true", help="Run only the planning subgraph"
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Run the retained model-planning/model-synthesis analyst for comparison",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit structured execution result to stdout"
    )
    parser.add_argument(
        "--handoff",
        action="store_true",
        help="Emit architecture input instead of the run result",
    )
    parser.add_argument(
        "--compact-handoff",
        action="store_true",
        help="Emit functional facts and citations without full planning audits",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress progress on stderr"
    )
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=5,
        help="Seconds between progress heartbeats while waiting (default: 5)",
    )
    parser.add_argument(
        "--trace", action="store_true", help="Use configured LangSmith tracing"
    )
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--max-tokens", type=int, default=3000, help="Per-call output token limit"
    )
    parser.add_argument("--max-total-tokens", type=int, default=60000)
    parser.add_argument("--max-input-tokens", type=int, default=6000)
    parser.add_argument("--max-objective-tokens", type=int, default=20000)
    parser.add_argument("--max-investigations", type=int, default=6)
    parser.add_argument("--max-model-calls", type=int, default=24)
    parser.add_argument(
        "--report-call-reserve",
        type=int,
        default=0,
        help="Legacy baseline report reserve; simplified finalization needs no model calls",
    )
    parser.add_argument("--max-tool-calls", type=int, default=100)
    parser.add_argument("--max-retrieved-characters", type=int, default=150000)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--max-turns", type=int, default=6)
    parser.add_argument("--request-interval", type=float, default=0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--retry-backoff", type=float, default=2)
    parser.add_argument("--max-files", type=int, default=5000)
    parser.add_argument("--max-depth", type=int, default=30)
    return parser


def create_model(arguments):
    if arguments.smoke or (arguments.plan_only and not arguments.baseline):
        return (
            OrientationSmokeModel() if arguments.orientation else ProtocolSmokeModel()
        )
    from pydantic_settings import BaseSettings, SettingsConfigDict

    from server.config.dev_agents_config import load_dev_agents_config
    from server.config.schemas import ModelCredentials, ModelSettings
    from server.config.settings import ENV_FILE

    class Credentials(BaseSettings):
        model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")
        llm_api_key: str = ""

    defaults = load_dev_agents_config().get("analyzer", (None, None))[1]
    provider = arguments.provider or (defaults.provider if defaults else "google")
    name = arguments.model or (
        defaults.name if defaults and provider == defaults.provider else None
    )
    if not name:
        raise ValueError("--model is required when switching provider.")
    api_key = arguments.api_key or Credentials().llm_api_key
    if not api_key:
        raise ValueError(
            "Provide --api-key or LLM_API_KEY, or use --smoke for an offline protocol test."
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


def progress(event, values):
    details = " ".join(
        f"{name}={json.dumps(value, ensure_ascii=True)}"
        for name, value in values.items()
    )
    print(f"[{event}] {details}", file=sys.stderr, flush=True)


def run_metadata(arguments, tools, model):
    """Reproducibility metadata with explicit settings and no credentials/source."""
    server = Path(__file__).resolve().parent
    files = sorted(
        [
            *Path(__file__).parent.joinpath("agents/project_analysis").glob("*.py"),
            *server.joinpath("services/repository_analysis").glob("*.py"),
            *server.joinpath("agents/project_orientation").rglob("*.py"),
            *server.joinpath("agents/project_orientation/prompts").glob("*.md"),
            Path(__file__),
        ]
    )
    fingerprint = hashlib.sha256()
    for source in files:
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
        "max_turns": arguments.max_turns,
        "max_files": arguments.max_files,
        "max_depth": arguments.max_depth,
        "request_interval": arguments.request_interval,
        "max_retries": arguments.max_retries,
        "retry_backoff": arguments.retry_backoff,
        "workflow": "orientation"
        if arguments.orientation
        else "baseline"
        if arguments.baseline
        else "simplified",
    }


class ProgressReporter:
    """Flushed stderr events and periodic status during asynchronous waits."""

    def __init__(self, interval):
        self.interval = interval
        self.started = monotonic()
        self.active_event = "startup"
        self.active_since = self.started
        self.active_values = {}

    def __call__(self, event, values):
        self.active_event = event
        self.active_since = monotonic()
        self.active_values = dict(values)
        progress(
            event, {"elapsed_seconds": round(monotonic() - self.started, 1), **values}
        )

    async def heartbeat(self):
        while True:
            await asyncio.sleep(self.interval)
            details = {
                "activity": self.active_event,
                "activity_seconds": round(monotonic() - self.active_since, 1),
                "elapsed_seconds": round(monotonic() - self.started, 1),
            }
            for key in ("call", "attempt", "max_attempts", "reason", "http_status"):
                if key in self.active_values:
                    details[key] = self.active_values[key]
            if self.active_event == "provider_wait":
                total = self.active_values.get("wait_seconds", 0)
                details["wait_total_seconds"] = round(total, 1)
                details["wait_remaining_seconds"] = round(
                    max(0, total - (monotonic() - self.active_since)), 1
                )
                details["next_action"] = "send_provider_request"
            progress("still_running", details)


async def with_progress(awaitable, reporter):
    """Stop the heartbeat on completion, failure, timeout, or cancellation."""
    if reporter is None:
        return await awaitable
    heartbeat = asyncio.create_task(reporter.heartbeat())
    try:
        return await awaitable
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat


async def run(arguments, *, reference=None, shared_pacer=None):
    if arguments.orientation and (
        arguments.baseline
        or arguments.plan_only
        or arguments.handoff
        or arguments.compact_handoff
        or arguments.evaluate_workspace
    ):
        raise ValueError(
            "--orientation requires a selected checkout and cannot be combined with baseline, planning, analyst handoff, or workspace evaluation modes."
        )
    if not arguments.root:
        raise ValueError("A selected repository root is required.")
    if (
        not math.isfinite(arguments.progress_interval)
        or arguments.progress_interval <= 0
    ):
        raise ValueError("Progress interval must be finite and positive.")
    reporter = (
        None if arguments.quiet else ProgressReporter(arguments.progress_interval)
    )

    def emit(event, **values):
        if reporter is not None:
            reporter(event, values)

    if any(
        value is not None and (value < 0 or not math.isfinite(value))
        for value in (
            arguments.input_price,
            arguments.output_price,
            arguments.request_interval,
            arguments.retry_backoff,
        )
    ):
        raise ValueError("Provider pacing and prices must be finite and nonnegative.")
    workspace = arguments.workspace_root.expanduser().resolve()
    root = Path(arguments.root).expanduser().resolve()
    if root.parent != workspace:
        raise RepositoryAccessError(
            "Select one checkout directly inside the configured workspace."
        )
    if (
        arguments.request_interval < 0
        or arguments.max_retries < 0
        or arguments.retry_backoff < 0
        or arguments.max_tokens < 1
    ):
        raise ValueError(
            "Provider limits must be nonnegative and max-tokens must be positive."
        )
    if (arguments.handoff or arguments.compact_handoff) and arguments.plan_only:
        raise ValueError("--handoff requires a full analysis, not --plan-only.")
    budget = InvestigationBudget(
        max_investigations=arguments.max_investigations,
        max_model_calls=min(4, arguments.max_model_calls)
        if arguments.orientation
        else arguments.max_model_calls,
        reserved_report_model_calls=arguments.report_call_reserve,
        max_total_tokens=arguments.max_total_tokens,
        max_input_tokens_per_call=arguments.max_input_tokens,
        max_tokens_per_investigation=arguments.max_objective_tokens,
        max_output_tokens_per_call=arguments.max_tokens,
        max_tool_calls=min(6, arguments.max_tool_calls)
        if arguments.orientation
        else arguments.max_tool_calls,
        max_retrieved_characters=arguments.max_retrieved_characters,
        max_elapsed_seconds=arguments.timeout,
    )
    limits = (BaselineLimits if arguments.baseline else AnalysisLimits)(
        max_model_calls_per_investigation=arguments.max_turns
    )
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
    tools = RepositoryToolset(
        ProjectAnalysisContext(
            snapshot=snapshot,
            input=ProjectAnalysisInput(
                snapshot_hash=snapshot.repository.snapshot_hash, budget=budget
            ),
        ),
        workspace_root=workspace,
        limits=ToolLimits(
            compact=not arguments.baseline,
            max_page_size=25 if not arguments.baseline else 50,
            max_source_lines=80 if not arguments.baseline else 120,
            max_source_characters=2200 if not arguments.baseline else 12000,
        ),
    )
    emit(
        "tools_ready",
        accessible_files=len(tools.accessible_snapshot.files),
        max_model_calls=budget.max_model_calls,
        max_tool_calls=budget.max_tool_calls,
        max_investigations=budget.max_investigations,
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
    gateway = ModelGateway(
        model,
        interval=arguments.request_interval,
        max_retries=arguments.max_retries,
        backoff=arguments.retry_backoff,
        on_event=reporter,
        trace=arguments.trace,
        remaining_seconds=lambda: max(
            0, budget.max_elapsed_seconds - tools.context.elapsed_seconds
        ),
    )
    if shared_pacer is not None:
        gateway.pacer = shared_pacer
    try:
        metadata = run_metadata(arguments, tools, model)
        if arguments.orientation:
            agent = ProjectOrientationAgent(model, generate=gateway, on_event=reporter)
            if arguments.trace:
                from server.config.tracing import traced_agent_run

                result = await with_progress(
                    traced_agent_run(agent.run(tools), name="project_orientation"),
                    reporter,
                )
            else:
                result = await with_progress(agent.run(tools), reporter)
            referenced = set(result.inspected_file_ids)
            if result.orientation:
                referenced.update(
                    point.file_id for point in result.orientation.starting_points
                )
                referenced.update(
                    identifier
                    for component in result.orientation.components
                    for identifier in component.file_ids
                )
            return result.model_dump(mode="json") | {
                "execution_mode": "protocol_smoke"
                if arguments.smoke
                else "orientation",
                "run_metadata": metadata,
                "file_paths": {
                    source.id: source.path
                    for source in tools.accessible_snapshot.files
                    if source.id in referenced
                },
            }, result.orientation is not None
        if arguments.plan_only:
            emit("planning")
            if arguments.baseline:
                state = await with_progress(
                    InvestigationPlanner(model, generate=gateway).plan(tools), reporter
                )
            else:
                state = tools.initial_state()
                state["investigation_plan"] = select_deterministic_plan(tools)
                state["planning_status"] = "ready"
            emit(
                "planning_finished",
                status=state["planning_status"],
                objectives=len(state["investigation_plan"].objectives),
            )
            usage = state["budget_usage"].model_copy(update=gateway.usage_totals())
            return {
                "mode": "protocol_smoke" if arguments.smoke else "model",
                "planning_status": state["planning_status"],
                "plan": state["investigation_plan"].model_dump(mode="json"),
                "usage": usage.model_dump(mode="json"),
                "telemetry": gateway.telemetry(tools.tool_measurements).model_dump(
                    mode="json"
                ),
                "run_metadata": metadata,
                "execution_issues": [
                    record.model_dump(mode="json")
                    for record in state["execution_issues"]
                ],
            }, state["planning_status"] == "ready"
        agent = (
            BaselineProjectAnalysisAgent if arguments.baseline else ProjectAnalysisAgent
        )(
            model,
            generate=gateway,
            limits=limits,
            on_event=reporter,
        )
        if arguments.trace:
            from server.config.tracing import traced_agent_run

            result = await with_progress(
                traced_agent_run(agent.run(tools), name="project_analysis"), reporter
            )
        else:
            result = await with_progress(agent.run(tools), reporter)
        for execution_issue in result.execution_issues:
            emit(
                "execution_issue",
                stage=execution_issue.stage,
                category=execution_issue.category,
                message=execution_issue.message,
            )
        if reference is not None:
            evaluated = evaluate_run(
                result,
                snapshot,
                reference,
                protocol_smoke=arguments.smoke,
                input_price=arguments.input_price,
                output_price=arguments.output_price,
            )
            evaluated["run_metadata"] = metadata
            return evaluated, result.report is not None
        if arguments.handoff:
            handoff = ArchitectureAnalysisInput.from_result(result)
            tools.context.validate_architecture_input(handoff)
            return handoff.model_dump(mode="json"), True
        if arguments.compact_handoff:
            brief = ArchitectureBrief.from_result(result)
            tools.context.validate_architecture_brief(brief)
            return brief.model_dump(mode="json"), True
        return result.model_dump(mode="json") | {
            "execution_mode": "protocol_smoke" if arguments.smoke else "model",
            "run_metadata": metadata,
        }, result.report is not None
    finally:
        emit("cleanup_started")
        failures = await with_progress(close_model_clients(model), reporter)
        emit("cleanup_finished", failure_types=list(failures))


async def evaluate_workspace(arguments):
    import yaml

    from server.benchmark.pacing import RequestPacer

    if (
        arguments.root
        or arguments.handoff
        or arguments.compact_handoff
        or arguments.plan_only
        or arguments.repeat < 1
    ):
        raise ValueError(
            "Workspace evaluation requires no root/handoff/plan-only and a positive repeat count."
        )
    suite = yaml.safe_load(arguments.suite.read_text(encoding="utf-8"))
    cases = suite.get("cases", [])
    if any(
        identifier not in {case["id"] for case in cases}
        for identifier in arguments.case
    ):
        raise ValueError("Unknown evaluation case ID.")
    selected = [
        case for case in cases if not arguments.case or case["id"] in arguments.case
    ]
    if not selected:
        raise ValueError("The evaluation suite has no selected cases.")
    pacer = RequestPacer(
        interval=arguments.request_interval,
        max_retries=arguments.max_retries,
        backoff=arguments.retry_backoff,
    )
    records = []
    valid = True
    for case in selected:
        for repeat in range(1, arguments.repeat + 1):
            options = argparse.Namespace(**vars(arguments))
            options.root = str(arguments.workspace_root / case["repository"])
            if not arguments.quiet:
                progress("evaluation", {"case": case["id"], "repeat": repeat})
            record, success = await run(options, reference=case, shared_pacer=pacer)
            record["repeat"] = repeat
            records.append(record)
            valid = valid and success
    return summarize_evaluation(records), valid


def print_summary(data):
    print(
        f"Mode: {data.get('execution_mode', data.get('mode', 'architecture_handoff'))}"
    )
    print(
        f"Status: {data.get('completion_status', data.get('planning_status', 'valid'))}"
    )
    orientation = data.get("orientation")
    if orientation:
        print(f"Snapshot: {data['snapshot_hash']}")
        paths = data.get("file_paths", {})
        for field in ("project_type", "purpose"):
            observation = orientation.get(field)
            if observation:
                print(
                    f"\n{field.replace('_', ' ').title()} ({observation['status']}): {observation['statement']}"
                )
        for component in orientation["components"]:
            print(
                f"\nComponent: {component['name']} ({component['responsibility']['status']})\n  {component['responsibility']['statement']}"
            )
        for point in orientation["starting_points"]:
            print(
                f"\nStarting point: {paths.get(point['file_id'], point['file_id'])}\n  {point['reason']}"
            )
        for uncertainty in orientation["uncertainties"]:
            print(f"\nUncertainty: {uncertainty}")
        for limitation in data.get("limitations", []):
            print(f"  limitation: {limitation}")
    report = data.get("report") or data.get("project_analysis_report")
    if report:
        print(f"Snapshot: {report['snapshot_hash']}")
        for project in report["project_identification"]:
            print(
                f"\nProject: {project['name']} | {', '.join(project['application_types'])}\n  {project['purpose']['statement']}"
            )
        for component in report["functional_components"]:
            print(
                f"\nComponent: {component['name']}\n  {component['responsibility']['statement']}"
            )
        for flow in report["main_flows"]:
            print(f"\nFlow: {flow['name']}")
            for step in flow["steps"]:
                print(f"  - {step['description']['statement']}")
        for claim in report["claims"]:
            print(f"\nClaim ({claim['status']}): {claim['statement']}")
        for integration in report["integrations_and_state"]:
            print(
                f"\nIntegration: {integration['name']} | {integration['usage']} | {integration['state_kind']}\n  {integration['description']['statement']}"
            )
        for question in report["open_questions"]:
            print(f"\nOpen question: {question['question']}\n  {question['reason']}")
        coverage = report["investigation_coverage"]
        print(
            f"\nInvestigations: {len(coverage['completed_investigation_ids'])} completed, {len(coverage['incomplete_investigation_ids'])} incomplete, {len(coverage['pending_investigation_ids'])} pending"
        )
        print(
            f"Inspected files: {len(coverage['inspected_file_ids'])}; retrieval records: {len(report['retrieved_evidence'])}"
        )
        for limitation in coverage["limitations"]:
            print(f"  limitation: {limitation}")
    if "plan" in data:
        for objective in data["plan"]["objectives"]:
            print(f"  {objective['priority_tier']}: {objective['objective']}")
    for issue in data.get("execution_issues", []):
        print(f"Issue: {issue['stage']} | {issue['category']} | {issue['message']}")
    if "usage" in data:
        print("\nUsage: " + json.dumps(data["usage"]))
        usage = data["usage"]
        if usage.get("unknown_usage_attempts", 0):
            print(
                f"  Incomplete provider usage: {usage['unknown_usage_attempts']} attempt(s) did not report usage. "
                f"Known reported tokens: input={usage['reported_input_tokens']}, output={usage['reported_output_tokens']}. "
                "Complete totals remain unknown; reported counts exclude unmeasured usage."
            )
    print_telemetry(data.get("telemetry"))


def print_telemetry(telemetry):
    if not telemetry:
        return
    print("\nContext telemetry (serialized characters; token estimates are heuristic):")
    for stage in telemetry["stages"]:
        print(
            f"  {stage['stage']}: calls={stage['calls']} corrections={stage['correction_calls']} "
            f"input_tokens={stage['input_tokens']} output_tokens={stage['output_tokens']} "
            f"reported_input_tokens={stage['reported_input_tokens']} reported_output_tokens={stage['reported_output_tokens']} "
            f"estimated_input_tokens={stage['estimated_input_tokens']} unknown_usage_attempts={stage['unknown_usage_attempts']}"
        )
        print(
            "    characters: "
            + ", ".join(
                f"{part['category']}={part['characters']}" for part in stage["context"]
            )
        )
    print(
        f"  Repeated tool requests: {telemetry['repeated_tool_requests']} / {len(telemetry['tool_requests'])}"
    )


def main(argv=None):
    arguments = build_parser().parse_args(argv)
    logging.disable(logging.CRITICAL)
    try:
        data, valid = asyncio.run(
            evaluate_workspace(arguments)
            if arguments.evaluate_workspace
            else run(arguments)
        )
        if arguments.json or arguments.handoff or arguments.compact_handoff:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        elif arguments.evaluate_workspace:
            print(json.dumps(data["summary"], indent=2))
            for record in data["runs"]:
                print(
                    f"{record['case_id']} repeat={record['repeat']}: {record['completion_status']} | issues={record['execution_issue_categories']} | {json.dumps(record['metrics'])}"
                )
                print_telemetry(record["result"].get("telemetry"))
        else:
            print_summary(data)
        return 0 if valid else 1
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except (ValueError, ValidationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Analysis cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
