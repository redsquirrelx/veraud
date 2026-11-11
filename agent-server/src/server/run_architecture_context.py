"""Run document discovery, retrieval planning and bounded document retrieval."""

import argparse
import asyncio
import inspect
import json
import sqlite3
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from time import monotonic
from traceback import walk_tb
from types import SimpleNamespace

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from config.agents.execution import InvestigationConfig
from config.agents.repository_execution import ExecutionBudget
from server.agent_services.budgeting import policy
from server.agent_services.budgeting.shared_tokens import SharedTokenBudget
from server.agent_services.budgeting.timing import ActiveDeadline
from server.agents.architecture_context import (
    discover_documents,
    extract_knowledge,
    plan_retrieval,
    retrieve_documents,
    validate_and_finalize,
)
from server.agents.architecture_context.schemas import RetrievalPlan
from server.config.dev_agents_config import load_dev_agents_config
from server.config.schemas import ModelCredentials
from server.config.settings import get_server_settings
from server.infrastructure.llm.chat import build_chat_model
from server.infrastructure.llm.resources import close_model_clients
from server.run_document_indexing import default_database, result_limit
from server.runtimes.investigation.structured import safe_diagnostic
from server.runtimes.repository.budgeted_model import BudgetedModel
from server.services.document_indexing import DocumentIndexingService


def _trace_event(event: str, **values) -> None:
    """Operational metadata only; stdout remains available for the JSON report."""
    print(
        "[architecture_context] "
        + json.dumps({"event": event, **values}, ensure_ascii=False),
        file=sys.stderr,
        flush=True,
    )


def _trace_exception(error: BaseException) -> None:
    """Complete stack/cause locations without raw messages, source lines or locals."""
    seen = set()
    depth = 0
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        _trace_event(
            "exception",
            cause_depth=depth,
            error_type=type(error).__name__,
            diagnostic=safe_diagnostic(error, RetrievalPlan),
            traceback=[
                {
                    "file": frame.f_code.co_filename,
                    "line": line,
                    "function": frame.f_code.co_name,
                }
                for frame, line in walk_tb(error.__traceback__)
            ],
        )
        error = error.__cause__ or error.__context__
        depth += 1


_MODEL_USAGE_PHASES = ("planning", "initial_extraction", "coverage_assessment")
_MODEL_USAGE_NODES = (
    "discover_documents",
    "plan_retrieval",
    "retrieve_documents",
    "extract_knowledge",
    "validate_and_finalize",
)


def _aggregate_model_usage(calls: list[dict]) -> dict:
    def aggregate(items: list[dict]) -> dict:
        input_tokens = sum(item["input_tokens"] or 0 for item in items)
        output_tokens = sum(item["output_tokens"] or 0 for item in items)
        unknown_attempts = sum(item["unknown_usage_attempts"] for item in items)
        return {
            "model_calls": len(items),
            "provider_attempts": sum(item["provider_attempts"] for item in items),
            "provider_retries": sum(item["provider_retries"] for item in items),
            "reported_input_tokens": input_tokens,
            "reported_output_tokens": output_tokens,
            "reported_total_tokens": input_tokens + output_tokens,
            "reported_usage_complete": all(
                item["input_tokens"] is not None
                and item["output_tokens"] is not None
                and item["unknown_usage_attempts"] == 0
                for item in items
            ),
            "unknown_usage_attempts": unknown_attempts,
            "accounted_tokens": sum(item["accounted_tokens"] for item in items),
            "estimated_tokens": sum(item["estimated_tokens"] for item in items),
        }

    nodes = {key: [] for key in _MODEL_USAGE_NODES}
    phases = {key: [] for key in _MODEL_USAGE_PHASES}
    for item in calls:
        nodes.setdefault(item["node"], []).append(item)
        phases.setdefault(item["phase"], []).append(item)
    return {
        "total": aggregate(calls),
        "by_node": {key: aggregate(items) for key, items in nodes.items()},
        "by_phase": {key: aggregate(items) for key, items in phases.items()},
        "calls": list(calls),
    }


def _print_model_usage_summary(model_usage: dict, *, stream) -> None:
    """Print provider-reported usage separately from the budget ledger view."""
    print("\nModel token usage by phase:", file=stream)
    print(
        f"{'Phase':28} {'Calls':>5} {'Attempts':>8} {'Input':>10} "
        f"{'Output':>10} {'Reported':>10} {'Accounted':>10} {'Estimated':>10} {'Unknown':>7}",
        file=stream,
    )
    for phase, values in model_usage["by_phase"].items():
        print(
            f"{phase:28} {values['model_calls']:5d} "
            f"{values['provider_attempts']:8d} "
            f"{values['reported_input_tokens']:10d} "
            f"{values['reported_output_tokens']:10d} "
            f"{values['reported_total_tokens']:10d} "
            f"{values['accounted_tokens']:10d} "
            f"{values['estimated_tokens']:10d} "
            f"{values['unknown_usage_attempts']:7d}",
            file=stream,
        )
    total = model_usage["total"]
    print(
        f"{'TOTAL':28} {total['model_calls']:5d} "
        f"{total['provider_attempts']:8d} "
        f"{total['reported_input_tokens']:10d} "
        f"{total['reported_output_tokens']:10d} "
        f"{total['reported_total_tokens']:10d} "
        f"{total['accounted_tokens']:10d} "
        f"{total['estimated_tokens']:10d} "
        f"{total['unknown_usage_attempts']:7d}",
        file=stream,
    )
    print("\nModel token usage by node:", file=stream)
    for node, values in model_usage["by_node"].items():
        print(
            f"  {node}: calls={values['model_calls']}, "
            f"attempts={values['provider_attempts']}, "
            f"reported={values['reported_total_tokens']}, "
            f"accounted={values['accounted_tokens']}, "
            f"estimated={values['estimated_tokens']}, "
            f"unknown_attempts={values['unknown_usage_attempts']}",
            file=stream,
        )
    print(
        "Reported totals and budget-accounted totals are separate views; "
        "unknown usage is not interpreted as zero.",
        file=stream,
    )


def create_planning_model(args):
    """Reuse dev model settings and server credentials, without registering an agent."""
    configurations = load_dev_agents_config()
    if args.agent_config not in configurations:
        raise ValueError(f"Unknown model configuration: {args.agent_config}")
    _, settings = configurations[args.agent_config]
    overrides = {
        key: value
        for key, value in {"provider": args.provider, "name": args.model}.items()
        if value
    }
    if getattr(args, "max_output_tokens", None) is not None:
        overrides["max_tokens"] = args.max_output_tokens
    settings = settings.model_copy(update=overrides)
    credentials = ModelCredentials(api_key=get_server_settings().llm_api_key)
    return build_chat_model(settings, credentials), settings


async def run_graph(service, index, args, *, usage_calls: list[dict] | None = None):
    client = None
    started = monotonic()
    active = {"node": "setup", "round": 0}

    def trace(event, *, exception=None, **values):
        if not getattr(args, "trace", True):
            return
        _trace_event(
            event,
            elapsed_seconds=round(monotonic() - started, 3),
            **{**active, **values},
        )
        if exception is not None:
            _trace_exception(exception)

    try:
        managed = None
        limits = InvestigationConfig()
        retrieval_budget = ExecutionBudget()
        if index.documents and not args.discovery_only:
            trace("model_setup_started", agent_config=args.agent_config)
            client, settings = create_planning_model(args)
            options = {
                key: value
                for key, value in {
                    "max_output_tokens": getattr(args, "max_output_tokens", None),
                    "timeout_seconds": args.timeout,
                }.items()
                if value is not None
            }
            limits = InvestigationConfig(**options)
            limits = limits.model_copy(
                update={
                    "max_output_tokens": min(
                        limits.max_output_tokens, settings.max_tokens
                    )
                }
            )
            managed = BudgetedModel(
                client,
                limits,
                SharedTokenBudget(limits.max_total_tokens),
                ActiveDeadline(limits.timeout_seconds),
            )
            # The global budget policy governs model calls, retries and tools.
            call_ledger_starts = {}

            def model_event(event, values):
                call_number = values.get("call")
                if event == "model_call_started" and call_number is not None:
                    call_ledger_starts[call_number] = {
                        "accounted_tokens": managed.tokens.used,
                        "estimated_tokens": managed.tokens.estimated,
                        "node": active["node"],
                        "round": active["round"],
                        "phase": values.get("stage", "unknown"),
                    }
                elif event == "model_call_finished" and call_number is not None:
                    start = call_ledger_starts.pop(call_number, {})
                    record = (
                        managed.gateway.calls[call_number - 1]
                        if call_number <= len(managed.gateway.calls)
                        else {}
                    )
                    input_tokens = record.get("input_tokens")
                    output_tokens = record.get("output_tokens")
                    accounted_delta = max(
                        0,
                        managed.tokens.used
                        - start.get("accounted_tokens", managed.tokens.used),
                    )
                    estimated_delta = max(
                        0,
                        managed.tokens.estimated
                        - start.get("estimated_tokens", managed.tokens.estimated),
                    )
                    values = {
                        **values,
                        "unknown_usage_attempts": record.get(
                            "unknown_usage_attempts", 0
                        ),
                        "accounted_tokens": accounted_delta,
                        "estimated_tokens": estimated_delta,
                    }
                    if usage_calls is not None:
                        usage_calls.append(
                            {
                                "call": call_number,
                                "node": start.get("node", active["node"]),
                                "round": start.get("round", active["round"]),
                                "phase": start.get(
                                    "phase", values.get("stage", "unknown")
                                ),
                                "status": record.get("status", values.get("status")),
                                "provider_attempts": record.get(
                                    "attempts", values.get("attempts", 0)
                                ),
                                "provider_retries": max(
                                    0,
                                    record.get("attempts", values.get("attempts", 0))
                                    - 1,
                                ),
                                "input_tokens": input_tokens,
                                "output_tokens": output_tokens,
                                "reported_total_tokens": (
                                    input_tokens + output_tokens
                                    if input_tokens is not None
                                    and output_tokens is not None
                                    else None
                                ),
                                "unknown_usage_attempts": record.get(
                                    "unknown_usage_attempts", 0
                                ),
                                "accounted_tokens": accounted_delta,
                                "estimated_tokens": estimated_delta,
                            }
                        )
                trace(event, **values)

            managed.gateway.on_event = model_event
            trace(
                "model_setup_finished",
                provider=getattr(settings, "provider", None),
                model=getattr(settings, "name", None),
                max_output_tokens=limits.max_output_tokens,
            )
        if managed is not None:
            retrieval_budget = retrieval_budget.model_copy(
                update={
                    "max_tool_calls": min(
                        managed.limits.max_tool_calls, retrieval_budget.max_tool_calls
                    ),
                }
            )
        trace(
            "execution_config",
            cumulative_tokens_unlimited=not policy.budgets_enabled(),
            max_output_tokens=limits.max_output_tokens,
            max_model_calls=limits.max_model_calls,
            model_call_limit_enabled=(
                policy.budgets_enabled() if managed else None
            ),
            max_tool_calls=retrieval_budget.max_tool_calls,
            timeout_seconds=limits.timeout_seconds,
        )

        async def run_node(state, *, name, node, schema=None, **kwargs):
            active.update(
                node=name,
                round=state.get("retrieval_round", 0) + (name == "plan_retrieval"),
            )
            node_started = monotonic()
            node_tokens_before = managed.tokens.used if managed else 0
            node_estimated_before = managed.tokens.estimated if managed else 0
            trace(
                "node_started",
                documents=len(state.get("documents", [])),
                retained_sections=len(state.get("retrieved_sections", [])),
            )
            try:
                if inspect.iscoroutinefunction(node):
                    update = await node(state, **kwargs)
                else:
                    update = await asyncio.to_thread(node, state, **kwargs)
                    if inspect.isawaitable(update):
                        update = await update
            except Exception as error:
                diagnostic = f"{name}: {safe_diagnostic(error, schema)}"
                annotated = ValueError(diagnostic)
                annotated.__cause__ = error
                trace(
                    "node_failed",
                    exception=annotated,
                    seconds=round(monotonic() - node_started, 3),
                    diagnostic=safe_diagnostic(error, schema),
                    node_accounted_tokens=(
                        max(0, managed.tokens.used - node_tokens_before)
                        if managed
                        else 0
                    ),
                    node_estimated_tokens=(
                        max(0, managed.tokens.estimated - node_estimated_before)
                        if managed
                        else 0
                    ),
                )
                if name == "validate_and_finalize":
                    raise
                # Keep the graph's current state so deterministic finalization can
                # preserve earlier rounds even when a later operation raises.
                trace("route", destination="validate_and_finalize", reason=f"{name}_failed")
                update = {"context_stop_reason": f"{name}_failed", "execution_error": diagnostic}
                if name == "plan_retrieval":
                    update["retrieval_plan"] = RetrievalPlan(tasks=[])
                elif name == "discover_documents":
                    update.update(
                        documents=[], document_discovery_status="error",
                        document_discovery_error=safe_diagnostic(error, schema),
                        retrieval_context="Document catalog unavailable",
                    )
                return update
            result = {**state, **update}
            trace(
                "node_finished",
                seconds=round(monotonic() - node_started, 3),
                documents=len(result.get("documents", [])),
                discovery_status=result.get("document_discovery_status"),
                retained_sections=len(result.get("retrieved_sections", [])),
                stop_reason=result.get("context_stop_reason"),
                model_attempts=managed.attempts if managed else 0,
                cumulative_tokens=managed.tokens.used if managed else 0,
                estimated_tokens=managed.tokens.estimated if managed else 0,
                node_accounted_tokens=(
                    max(0, managed.tokens.used - node_tokens_before) if managed else 0
                ),
                node_estimated_tokens=(
                    max(0, managed.tokens.estimated - node_estimated_before)
                    if managed
                    else 0
                ),
            )
            if name == "plan_retrieval":
                trace(
                    "retrieval_plan",
                    tasks=[
                        task.model_dump(mode="json")
                        for task in result["retrieval_plan"].tasks
                    ],
                )
            if name == "retrieve_documents":
                trace(
                    "route",
                    destination="extract_knowledge",
                    reason="retrieval_completed",
                )
            if name == "extract_knowledge":
                trace(
                    "knowledge_extraction",
                    claims=len(result.get("knowledge", [])),
                    issues=len(result.get("knowledge_issues", [])),
                    processed_sections=len(result.get("processed_section_ids", [])),
                    covered_categories=result.get("covered_categories", []),
                    pending_categories=result.get("pending_categories", []),
                )
            if name == "discover_documents" and args.discovery_only:
                trace("route", destination="validate_and_finalize", reason="discovery_only")
            return update

        def route_discovery(state):
            destination = (
                "plan_retrieval"
                if state["document_discovery_status"] == "ready"
                else "validate_and_finalize"
            )
            trace(
                "route",
                destination=destination,
                reason=state["document_discovery_status"],
            )
            return destination

        from server.agents.architecture_context.workflow import build_workflow

        graph = build_workflow(
            service, managed, retrieval_budget, node_runner=run_node,
            discovery_only=args.discovery_only, trace=trace, discovery_router=route_discovery,
            nodes={
                "discover_documents": discover_documents,
                "plan_retrieval": plan_retrieval,
                "retrieve_documents": retrieve_documents,
                "extract_knowledge": extract_knowledge,
                "validate_and_finalize": validate_and_finalize,
            },
        )
        # The process-wide budget switch governs the CLI and production equally.
        result = await graph.ainvoke(
            {"document_index": service.get_index(index.index_id)},
            config={"recursion_limit": max(25, 3 * retrieval_budget.max_tool_calls + 4)},
        )
        trace(
            "execution_finished",
            rounds=result.get("retrieval_round", 0),
            stop_reason=result.get("context_stop_reason"),
        )
        return result
    finally:
        if client is not None:
            trace("model_cleanup_started", node="cleanup")
            await close_model_clients(SimpleNamespace(llm=client))
            trace("model_cleanup_finished", node="cleanup")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run documentary retrieval and architectural knowledge extraction until coverage is sufficient or no useful retrieval remains. No code evaluation or audit findings.",
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Exact Git directory scope to index (not expanded to its parent)",
    )
    parser.add_argument(
        "--discovery-only",
        action="store_true",
        help="Skip the LLM planner (offline metadata discovery only)",
    )
    parser.add_argument(
        "--agent-config",
        default="dummy",
        help="Model settings key in config/dev-agents.yaml (default: dummy; only its model is reused)",
    )
    parser.add_argument("--provider", help="Override the configured model provider")
    parser.add_argument("--model", help="Override the configured model name")
    parser.add_argument(
        "--no-trace",
        dest="trace",
        action="store_false",
        default=True,
        help="Disable operational traces and sanitized stack traces on stderr",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        help="Override the per-response output cap for planning (default: model settings)",
    )
    parser.add_argument(
        "--timeout", type=float, help="Override the planning timeout in seconds"
    )
    parser.add_argument(
        "--commit",
        default="HEAD",
        help="Git commit or ref to verify and index (default: HEAD)",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=default_database(),
        help="SQLite index outside the repository (default: host cache)",
    )
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument(
        "--output", "--output-file", type=Path,
        help="Save the canonical final result as JSON; must be a new file",
    )
    destination.add_argument(
        "--stdout",
        action="store_true",
        help="Print the final result as JSON to stdout instead of a file (summary goes to stderr)",
    )
    parser.add_argument(
        "--diagnostics", action="store_true",
        help="Export the diagnostic report (internal state and usage) instead of only the final result",
    )
    parser.add_argument(
        "--limit",
        type=result_limit,
        default=20,
        help="Maximum documents displayed, 1–100 (export includes the full catalog)",
    )
    args = parser.parse_args(argv)
    model_usage_calls: list[dict] = []
    usage_summary_printed = False

    try:
        root = args.directory.expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("A repository directory is required")
        database = args.database.expanduser().resolve()
        output = args.output.expanduser().resolve() if args.output else None
        if output is not None and (output == database or output.exists()):
            raise ValueError(
                "Output must be a new file, different from the SQLite database"
            )
        if database.is_relative_to(root):
            raise ValueError(
                "Database must be outside the audited repository; use --database"
            )

        # Host-side preparation reads this directory's committed Markdown. The node does not.
        service = DocumentIndexingService(database)
        preparation_started = monotonic()
        if args.trace:
            _trace_event(
                "index_preparation_started", directory=str(root), commit=args.commit
            )
        index = service.index_repository(root, args.commit)
        if args.trace:
            _trace_event(
                "index_preparation_finished",
                seconds=round(monotonic() - preparation_started, 3),
                documents=index.documents,
                processed=index.processed,
                reused=index.reused,
                commit=index.commit,
            )
        state = asyncio.run(
            run_graph(service, index, args, usage_calls=model_usage_calls)
        )
        model_usage = _aggregate_model_usage(model_usage_calls)

        summary_stream = sys.stderr if args.stdout or state.get("execution_status") == "failed" else sys.stdout
        print(f"Repository: {root}", file=summary_stream)
        print(f"Commit: {index.commit}", file=summary_stream)
        print(f"Database: {database}", file=summary_stream)
        print(
            f"Index preparation: processed {index.processed}; reused {index.reused}",
            file=summary_stream,
        )
        print(
            f"Discovery status: {state['document_discovery_status']}",
            file=summary_stream,
        )
        print(f"Documents discovered: {len(state['documents'])}", file=summary_stream)
        print(f"Planner summary: {state['retrieval_context']}", file=summary_stream)
        for document in state["documents"][: args.limit]:
            print(
                f"  {document.path} ({document.line_count} lines; SHA-256: {document.content_hash})",
                file=summary_stream,
            )
        if len(state["documents"]) > args.limit:
            print(
                f"[Showing {args.limit} documents; the full catalog remains in state]",
                file=summary_stream,
            )
        if "retrieval_plan" in state:
            print("\nRetrieval plan:", file=summary_stream)
            print(
                state["retrieval_plan"].model_dump_json(indent=2), file=summary_stream
            )

        if "retrieved_sections" in state:
            print(
                f"Retrieved sections: {len(state['retrieved_sections'])}",
                file=summary_stream,
            )
            for record in state["retrieval_history"]:
                print(
                    f"  {record.task.operation}: {record.status}"
                    + (f" ({record.error})" if record.error else ""),
                    file=summary_stream,
                )

        if "knowledge" in state:
            print(
                f"Architectural claims: {len(state['knowledge'])}; "
                f"documentary issues: {len(state.get('knowledge_issues', []))}",
                file=summary_stream,
            )
            coverage_status = state.get("coverage_assessment_status", "not_run")
            if coverage_status == "completed":
                covered = state.get("covered_categories", [])
                evaluated = state.get("evaluated_categories", [])
                incomplete = any(
                    value != "completed"
                    for value in state.get("extraction_section_status", {}).values()
                )
                print(
                    f"Coverage assessment: completed; model considers {len(evaluated)}/7 sufficient; "
                    + (
                        "confirmation pending (incomplete extraction)"
                        if incomplete else f"confirmed {len(covered)}/7"
                    ),
                    file=summary_stream,
                )
            else:
                print(f"Coverage assessment: {coverage_status}", file=summary_stream)
            section_status = state.get("extraction_section_status", {})
            partial = sum(value == "partial" for value in section_status.values())
            failed = sum(value == "failed" for value in section_status.values())
            print(
                f"Section extraction states: {sum(value == 'completed' for value in section_status.values())} completed, "
                f"{partial} partial, {failed} failed",
                file=summary_stream,
            )

        if state.get("context_stop_reason"):
            print(
                f"Context execution stopped: {state['context_stop_reason']}",
                file=summary_stream,
            )

        print(
            f"Finalization: {state['execution_status']} ({state['finalization_reason']}); "
            f"validation errors: {len(state['validation_errors'])}",
            file=summary_stream,
        )

        if output is not None or args.stdout:
            report = {
                "schema_version": "1",
                "repository_path": str(root),
                "database_path": str(database),
                "indexing": index.model_dump(mode="json"),
                "model_usage": model_usage,
                "state": {
                    **state,
                    "result": state["result"].model_dump(mode="json"),
                    "document_index": state["document_index"].model_dump(mode="json"),
                    "documents": [
                        document.model_dump(mode="json")
                        for document in state["documents"]
                    ],
                    **(
                        {
                            "retrieval_plan": state["retrieval_plan"].model_dump(
                                mode="json"
                            )
                        }
                        if "retrieval_plan" in state
                        else {}
                    ),
                    **(
                        {
                            "retrieved_sections": [
                                section.model_dump(mode="json")
                                for section in state["retrieved_sections"]
                            ],
                            "retrieval_history": [
                                record.model_dump(mode="json")
                                for record in state["retrieval_history"]
                            ],
                            "retrieval_usage": state["retrieval_usage"].model_dump(
                                mode="json"
                            ),
                        }
                        if "retrieved_sections" in state
                        else {}
                    ),
                    **{
                        key: [item.model_dump(mode="json") for item in state.get(key, [])]
                        for key in ("knowledge", "knowledge_issues", "consulted_documents", "validation_errors")
                    },
                },
            }
            if not args.diagnostics:
                report = state["result"].model_dump(mode="json")
            if args.stdout:
                json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
                sys.stdout.write("\n")
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open("x", encoding="utf-8", newline="\n") as stream:
                    json.dump(report, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                print(f"JSON report: {output}")
        _print_model_usage_summary(
            model_usage, stream=summary_stream
        )
        usage_summary_printed = True
        if state.get("execution_error"):
            print(f"Architecture context failed: {state['execution_error']}", file=sys.stderr)
        if state["document_discovery_status"] == "error":
            print(
                f"Document discovery failed: {state['document_discovery_error']}",
                file=sys.stderr,
            )
            return 1
        if any(
            record.status in {"error", "limited"}
            for record in state.get("retrieval_history", [])
        ):
            return 1
        if state.get("context_stop_reason"):
            return 1
        if state.get("execution_status") == "failed" or state.get("validation_errors"):
            return 1
        return 0
    except (OSError, ValueError, sqlite3.Error, subprocess.TimeoutExpired) as error:
        if args.trace:
            _trace_exception(error)
        if model_usage_calls and not usage_summary_printed:
            _print_model_usage_summary(
                _aggregate_model_usage(model_usage_calls), stream=sys.stderr
            )
        print(f"Architecture context failed: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001 - CLI boundary; do not echo provider payloads/credentials
        if args.trace:
            _trace_exception(error)
        if model_usage_calls and not usage_summary_printed:
            _print_model_usage_summary(
                _aggregate_model_usage(model_usage_calls), stream=sys.stderr
            )
        print(
            f"Architecture context failed: {safe_diagnostic(error, RetrievalPlan)}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
