"""Shared CLI lifecycle for orientation and architecture, with no analyst modes."""

import argparse
import asyncio
import copy
import hashlib
import json
import logging
import math
import sys
from pathlib import Path
from time import monotonic

from .agents.project_architecture import ArchitectureLimits, ProjectArchitectureAgent
from .agents.project_architecture.diagram import render_diagram
from .agents.project_architecture.smoke import ArchitectureSmokeModel
from .agents.project_orientation import ProjectOrientationAgent
from .agents.project_orientation.smoke import OrientationSmokeModel
from .agents.project_semantic_validation import (
    ProjectSemanticValidationAgent,
    ValidationLimits,
)
from .agents.project_semantic_validation.smoke import SemanticValidationSmokeModel
from .agents.repository_runtime import (
    ExecutionBudget,
    RepositoryContext,
    RepositoryInput,
    RepositoryToolset,
    ToolLimits,
)
from .agents.repository_runtime.access import RepositoryAccessError
from .agents.repository_runtime.model_runtime import (
    ModelGateway,
    close_model_clients,
    create_project_model,
)
from .config.settings import resolve_workspace_root
from .pipelines import ProjectArchitecturePipeline
from .repository_progress import ProgressReporter, with_progress
from .repository_reports import ArchitectureCheckpoint, load_architecture_report
from .services.repository_analysis import (
    RepositoryAnalysisInput,
    RepositoryAnalysisService,
)


def build_parser(mode):
    architecture = mode == "architecture"
    validation = mode == "semantic_validation"
    investigation = architecture or validation
    parser = argparse.ArgumentParser(
        description=f"Run project {mode} over one retained workspace snapshot."
    )
    parser.set_defaults(mode=mode)
    parser.add_argument("root", help="Selected repository checkout")
    parser.add_argument("--workspace-root", type=Path, default=resolve_workspace_root())
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
        "--max-total-tokens", type=int, default=80000 if investigation else 60000
    )
    parser.add_argument(
        "--max-input-tokens", type=int, default=10000 if investigation else 6000
    )
    parser.add_argument(
        "--max-objective-tokens", type=int, default=40000 if investigation else 20000
    )
    parser.add_argument(
        "--max-model-calls", type=int, default=8 if investigation else 4
    )
    parser.add_argument(
        "--max-tool-calls", type=int, default=20 if investigation else 6
    )
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
        parser.add_argument(
            "--validate-semantics",
            action="store_true",
            help="Review architectural claims; first review uses advisory token budgets, revalidation uses strict budgets",
        )
        parser.add_argument(
            "--diagram",
            dest="diagram",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Compose a component view after investigation, then print Mermaid (use --no-diagram to skip)",
        )
        parser.add_argument("--no-semantic-return", action="store_true")
        parser.add_argument(
            "--resume-report",
            type=Path,
            help="Resume composition from a saved report; skip orientation and investigation",
        )
        parser.add_argument(
            "--checkpoint",
            type=Path,
            help="Report checkpoint path (default: .architecture-checkpoints/<repository>.json)",
        )
        parser.add_argument(
            "--diagram-model", help="Model used only for diagram composition"
        )
        parser.add_argument(
            "--diagram-provider", help="Provider used only for diagram composition"
        )
        parser.add_argument(
            "--diagram-api-key", help="Credentials used only for diagram composition"
        )
        parser.add_argument(
            "--diagram-retry-backoff",
            type=float,
            default=10,
            help="Initial diagram retry wait in seconds (default: 10)",
        )
    if validation:
        parser.add_argument(
            "--report",
            type=Path,
            required=True,
            help="Exported ArchitectureResult JSON",
        )
    if investigation:
        parser.add_argument("--max-review-claims", type=int, default=18)
    return parser


def create_model(arguments):
    if arguments.smoke:
        if arguments.mode == "semantic_validation":
            return SemanticValidationSmokeModel()
        if arguments.mode == "architecture" and arguments.validate_semantics:

            class PipelineSmokeModel(ArchitectureSmokeModel):
                async def generate(self, prompt):
                    if "\nVALIDATION_DATA\n" in prompt:
                        return await SemanticValidationSmokeModel().generate(prompt)
                    return await super().generate(prompt)

            return PipelineSmokeModel()
        return (
            ArchitectureSmokeModel()
            if arguments.mode == "architecture"
            else OrientationSmokeModel()
        )
    from pydantic_settings import BaseSettings, SettingsConfigDict

    from .config.schemas import ModelCredentials, ModelSettings
    from .config.settings import ENV_FILE

    class Credentials(BaseSettings):
        model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")
        llm_api_key: str = ""

    provider = arguments.provider or "google"
    name = arguments.model
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


def combined_gateway_usage(*gateways):
    totals = [gateway.usage_totals() for gateway in gateways if gateway.calls]
    if not totals:
        return gateways[0].usage_totals()
    return {
        key: sum(total[key] for total in totals)
        if all(total[key] is not None for total in totals)
        else None
        for key in totals[0]
    }


def run_metadata(arguments, tools, model):
    server = Path(__file__).resolve().parent
    files = [
        Path(__file__),
        server / "repository_progress.py",
        server / "repository_reports.py",
        server / "pipelines/project_architecture.py",
        server / "pipelines/semantic_validation.py",
    ]
    for relative in (
        "agents/repository_runtime",
        "agents/project_orientation",
        "agents/project_architecture",
        "agents/project_semantic_validation",
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
    if arguments.mode == "architecture" and arguments.resume_report:
        arguments.diagram = True
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
        max_model_calls=min(
            8 if arguments.mode != "orientation" else 4, arguments.max_model_calls
        ),
        max_tool_calls=min(
            20 if arguments.mode != "orientation" else 6, arguments.max_tool_calls
        ),
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
        if isinstance(agent, ProjectSemanticValidationAgent):
            return await execute_awaitable(
                agent.run(tools, orientation, soft_token_budgets=True)
            )
        awaitable = (
            agent.run(tools, orientation)
            if isinstance(agent, ProjectArchitectureAgent)
            else agent.run(tools)
        )
        return await execute_awaitable(awaitable)

    async def execute_awaitable(awaitable):
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
    diagram_model = None
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
        if arguments.mode == "semantic_validation":
            original = load_architecture_report(arguments.report)
            agent = ProjectSemanticValidationAgent(
                model,
                generate=gateway,
                on_event=reporter,
                limits=ValidationLimits(max_claims=arguments.max_review_claims),
            )
            result = await execute(agent, tools, original)
            metadata["validation_limits"] = agent.limits.model_dump(mode="json")
            metadata["initial_review_soft_token_budgets"] = True
            diagram = render_diagram(original, findings=result.findings)
            return result.model_dump(mode="json") | {
                "architecture_diagram": diagram.model_dump(mode="json")
                if diagram
                else None,
                "execution_mode": "protocol_smoke"
                if arguments.smoke
                else arguments.mode,
                "run_metadata": metadata,
            }, result.completion_status != "failed"
        if architecture:
            saved = (
                load_architecture_report(arguments.resume_report)
                if arguments.resume_report
                else None
            )
            if saved is not None:
                tools.context.require_snapshot(saved.snapshot_hash)
            checkpoint_path = arguments.checkpoint or (
                Path.cwd()
                / ".architecture-checkpoints"
                / (
                    root.name
                    + "-"
                    + hashlib.sha256(str(root).encode()).hexdigest()[:10]
                    + ".json"
                )
            )
            checkpoint = ArchitectureCheckpoint(checkpoint_path)
            diagram_arguments = copy.copy(arguments)
            diagram_arguments.model = arguments.diagram_model or arguments.model
            diagram_arguments.provider = (
                arguments.diagram_provider or arguments.provider
            )
            diagram_arguments.api_key = arguments.diagram_api_key or arguments.api_key
            diagram_model = (
                create_model(diagram_arguments)
                if any(
                    (
                        arguments.diagram_model,
                        arguments.diagram_provider,
                        arguments.diagram_api_key,
                    )
                )
                else model
            )
            # Presentation failures must not stop the investigation/review gateway.
            diagram_gateway = ModelGateway(
                diagram_model,
                interval=arguments.request_interval,
                max_retries=arguments.max_retries,
                backoff=arguments.diagram_retry_backoff,
                on_event=reporter,
                trace=arguments.trace,
                remaining_seconds=lambda: max(0, deadline - monotonic()),
            )
            if diagram_model is model:

                def provider_event(event, values):
                    # Separate failure state, but retain pacing across shared-client stages.
                    next_allowed = max(
                        gateway.pacer.next_allowed, diagram_gateway.pacer.next_allowed
                    )
                    gateway.pacer.next_allowed = diagram_gateway.pacer.next_allowed = (
                        next_allowed
                    )
                    if reporter:
                        reporter(event, values)

                gateway.on_event = diagram_gateway.on_event = provider_event
            diagram_settings = getattr(diagram_model, "settings", None)
            metadata["diagram_model"] = {
                "provider": getattr(diagram_settings, "provider", "offline"),
                "name": getattr(diagram_settings, "name", "protocol_smoke"),
                "retry_backoff": arguments.diagram_retry_backoff,
            }
            architect = ProjectArchitectureAgent(
                model,
                generate=gateway,
                on_event=reporter,
                limits=ArchitectureLimits(
                    soft_token_budgets=not arguments.strict_architecture_budgets
                ),
            )
            validator = ProjectSemanticValidationAgent(
                model,
                generate=gateway,
                on_event=reporter,
                limits=ValidationLimits(max_claims=arguments.max_review_claims),
            )
            pipeline = ProjectArchitecturePipeline(
                architect,
                diagram_architect=ProjectArchitectureAgent(
                    diagram_model,
                    generate=diagram_gateway,
                    on_event=reporter,
                    limits=architect.limits,
                ),
                hooks=checkpoint if arguments.diagram or arguments.checkpoint else None,
                orientation=ProjectOrientationAgent(
                    model, generate=gateway, on_event=reporter
                ),
                validator=validator,
                on_event=reporter,
            )
            outcome = await pipeline.run(
                snapshot,
                budget=budget,
                workspace_root=workspace,
                include_orientation=not arguments.skip_orientation,
                validate_semantics=arguments.validate_semantics,
                allow_return=not arguments.no_semantic_return,
                include_diagram=arguments.diagram,
                resume_architecture=saved,
                deadline=deadline,
                execute=execute_awaitable,
            )
            metadata.update(
                architecture_limits=architect.limits.model_dump(mode="json"),
                orientation_included=outcome.orientation is not None,
            )
            data = outcome.architecture.model_dump(mode="json") | {
                "execution_mode": "protocol_smoke"
                if arguments.smoke
                else arguments.mode,
                "run_metadata": metadata,
                "orientation_result": outcome.orientation.model_dump(mode="json")
                if outcome.orientation
                else None,
                "pipeline_status": outcome.completion_status,
                "architecture_checkpoint": str(checkpoint_path.resolve())
                if arguments.diagram or arguments.checkpoint
                else None,
                "diagram_composition": outcome.diagram_composition.model_dump(
                    mode="json"
                )
                if outcome.diagram_composition
                else None,
                "pipeline_stages": [
                    stage.model_dump(mode="json") for stage in outcome.stages
                ],
                "architecture_diagram": outcome.diagram.model_dump(mode="json")
                if outcome.diagram
                else None,
                "pipeline_usage": combined_gateway_usage(gateway, diagram_gateway)
                | {
                    "model_calls": len(gateway.measurements)
                    + len(diagram_gateway.measurements),
                    "tool_calls": outcome.tool_calls,
                },
            }
            if outcome.semantic_validation:
                data["semantic_validation"] = outcome.semantic_validation.model_dump(
                    mode="json"
                )
                metadata.update(
                    validation_limits=validator.limits.model_dump(mode="json"),
                    initial_review_soft_token_budgets=True,
                    semantic_return_enabled=not arguments.no_semantic_return,
                )
            return data, outcome.usable
        result = await execute(
            ProjectOrientationAgent(model, generate=gateway, on_event=reporter), tools
        )
        data = result.model_dump(mode="json") | {
            "execution_mode": "protocol_smoke" if arguments.smoke else arguments.mode,
            "run_metadata": metadata,
            "file_paths": {
                source.id: source.path for source in tools.accessible_snapshot.files
            },
        }
        return data, result.completion_status != "failed"
    finally:
        emit("cleanup_started")
        failures = await with_progress(close_model_clients(model), reporter)
        if diagram_model is not None and diagram_model is not model:
            failures += await with_progress(
                close_model_clients(diagram_model), reporter
            )
        emit("cleanup_finished", failure_types=list(failures))


def print_summary(data):
    print(f"Mode: {data['execution_mode']}")
    if data.get("architecture_checkpoint"):
        print(f"Architecture checkpoint: {data['architecture_checkpoint']}")
    if data.get("pipeline_stages"):
        print(f"Pipeline status: {data['pipeline_status']}")
        for stage in data["pipeline_stages"]:
            if stage["status"] == "failed":
                print(
                    f"Failed stage: {stage['stage']} | Cause: {stage['reason'] or 'See stage issues.'}"
                )
            elif stage["status"] == "skipped":
                print(f"{stage['stage']}: skipped — {stage['reason']}")
            elif stage.get("reason"):
                print(f"Stage issue: {stage['stage']} | {stage['reason']}")
    shown = data
    review = data if "verdict" in data else None
    pipeline = data.get("semantic_validation")
    if pipeline:
        revised = pipeline.get("revised_architecture")
        shown = (
            revised
            if revised and revised.get("architecture")
            else pipeline["original_architecture"]
        )
        print(
            "Report shown: "
            + (
                "REVISED ARCHITECTURE REPORT"
                if shown is revised
                else "ORIGINAL ARCHITECTURE REPORT"
            )
        )
        print(f"Architecture generation: {shown['completion_status']}")
        print(
            f"Architect revision: {pipeline['return_count']} of 1"
            if pipeline["return_count"]
            else "Architect revision: not performed"
        )
        if revised and not revised.get("architecture"):
            print(
                f"Revision generation: {revised['completion_status']}; produced no report, showing the original report."
            )
        review = pipeline["validations"][-1]
        review_matches = review["original_result"] == shown
        if revised and shown is revised and not review_matches:
            print("Semantic revalidation: not performed")
        else:
            print(
                f"Semantic {'revalidation' if shown is revised else 'review'}: {review['completion_status']} / {review['verdict']}"
            )
        accepted = (
            review_matches
            and review["verdict"] == "accepted"
            and review["completion_status"] == "complete"
            and (not revised or shown is revised)
        )
        print(
            "Final acceptance: "
            + ("established for reviewed claims" if accepted else "not established")
        )
        if revised:
            print("Original report: preserved in revision history")
            if pipeline.get("diagram_revision"):
                for issue in pipeline["diagram_revision"]["execution_issues"]:
                    print(
                        f"Diagram revision issue: {issue['category']} | {issue['message']}"
                    )
            for issue in revised["execution_issues"]:
                print(f"Revision issue: {issue['category']} | {issue['message']}")
        if not review_matches:
            print(
                "Review details below concern the original report, not the displayed revision."
            )
    else:
        print(f"Status: {data['completion_status']}")
    report = shown.get("architecture") or shown.get("orientation")
    findings = (
        {item["target_id"]: item for item in review["findings"]}
        if review and (not pipeline or review_matches)
        else {}
    )

    def claim_status(claim, pointer):
        if not review:
            return claim["status"]
        semantic = findings.get(pointer)
        return f"architect certainty: {claim['status']} | semantic: {semantic['verdict'] if semantic else 'not reviewed'}"

    if review:
        print(
            f"Semantic review coverage: {len(review['findings'])} of {len(review['findings']) + len(review['pending_target_ids'])} claims"
        )
        for pointer in review["pending_target_ids"]:
            print(f"  Pending claim: {pointer}")
        for issue in review["execution_issues"]:
            print(f"Review issue: {issue['category']} | {issue['message']}")
        if not pipeline:
            print(
                f"Semantic verdict: {review['verdict']} | status={review['completion_status']}"
            )
        for finding in review["findings"]:
            print(
                f"  Semantic finding {finding['target_id']}: {finding['verdict']} | {finding['reason']}"
            )
            if finding.get("correction"):
                correction = finding["correction"]
                print(
                    f"    Proposed correction (not automatically applied): {correction['statement']} | scope={correction['scope']} | certainty={correction['status']}"
                )
            for request in finding.get("missing_evidence", []):
                print(
                    f"    Missing evidence: {request['question']} | paths={', '.join(request['paths']) or 'unspecified'}"
                )
    if report:
        for index, unit in enumerate(
            report.get("organization", report.get("components", []))
        ):
            print(
                f"\n{unit['name']}: {unit['responsibility']['statement']} ({claim_status(unit['responsibility'], f'/organization/{index}/responsibility')})"
            )
        classification = report.get("closest_architecture")
        if classification:
            print(
                f"\nClosest architecture: {classification['pattern']} ({claim_status(classification['assessment'], '/closest_architecture/assessment')})\n  {classification['assessment']['statement']}\n  Scope: {classification['assessment']['scope']}"
            )
        for name in ("project_type", "purpose", "explanation"):
            if report.get(name):
                print(
                    f"\n{name}: {report[name]['statement']} ({claim_status(report[name], '/' + name)})"
                )
        for item in report.get("uncertainties", []):
            print(f"  Uncertainty: {item}")
    for citation in shown.get("citations", []):
        print(
            f"  {citation['evidence_id']}: {citation['path']}:{citation['start_line']}-{citation['end_line']}"
        )
    for issue in shown["execution_issues"]:
        print(f"Issue: {issue['stage']} | {issue['category']} | {issue['message']}")
    if "pipeline_usage" in data:
        print("\nPipeline usage: " + json.dumps(data["pipeline_usage"]))
    if data.get("diagram_composition"):
        print(
            "Diagram composition usage: "
            + json.dumps(data["diagram_composition"]["usage"])
        )
        for issue in data["diagram_composition"]["execution_issues"]:
            print(f"Diagram issue: {issue['category']} | {issue['message']}")
    print(
        "\n"
        + ("Displayed report usage: " if pipeline else "Usage: ")
        + json.dumps(shown["usage"])
    )
    if pipeline:
        print("Semantic review usage: " + json.dumps(review["usage"]))
    for stage in shown["telemetry"]["stages"]:
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
        if (
            arguments.mode == "architecture"
            and arguments.diagram
            and not arguments.json
        ):
            diagram = data.get("architecture_diagram")
            if diagram:
                print(
                    f"\nArchitecture diagram ({diagram['report_origin']} report):\n```mermaid\n{diagram['mermaid'].rstrip()}\n```"
                )
            else:
                print(
                    "\nArchitecture diagram: unavailable; no valid component view was produced."
                )
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
