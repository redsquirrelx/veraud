"""Grounded investigation followed by deterministic synthesis and finalization."""

import json
import math
from pathlib import Path
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic_core import PydanticCustomError

from server.agent_services.budgeting.policy import budgets_enabled
from server.runtimes.investigation.agent import InvestigationExecution
from server.runtimes.investigation.structured import safe_diagnostic
from server.runtimes.invocation_reporting import phase_node
from server.runtimes.repository.tools import TOOL_SCHEMAS, tool_signatures

from .config import BoundaryConfig
from .investigation import (
    examined_relationships,
    initial_queries,
    reference_catalog,
    reference_errors,
)
from .planning import (
    balance_candidates,
    nonproduction_path,
    planning_diagnostics,
    prepare_planning,
)
from .schemas import (
    BoundaryCitationRepair,
    BoundaryFinding,
    BoundaryInvestigationResult,
    BoundaryInvestigationTurn,
    BoundaryPlan,
    BoundaryPlanSelection,
    BoundaryResult,
)
from .state import BoundaryState
from .synthesis import consolidate_candidates


class BoundaryExecution(InvestigationExecution):
    trace_name = "architecture-boundary"
    tool_prefix = "boundary"
    prompt_directory = Path(__file__).parent / "prompts"
    result_schema = BoundaryResult

    def __init__(self, model, config, tools, request):
        # Coordinators may supply the common investigator envelope. Resolve the
        # local planning policy without losing any trusted shared overrides.
        super().__init__(model, BoundaryConfig.model_validate(config.model_dump()), tools, request)

    def _check_planning(self):
        self.timing.check_cancellation()
        if self.remaining_seconds() <= 0:
            raise TimeoutError("Structural planning deadline exhausted.")

    def model_context(self, node, state):
        if node == "plan_investigation":
            return self._planning_context
        return self._repair_context if getattr(self, "_repair_context", None) is not None else self._investigation_context(state)

    async def call(self, node, state, schema=None, guidance=""):
        if node != "investigate":
            return await super().call(node, state, schema, guidance)
        config = self.config
        self._invalid_turn = self._repair_context = None
        # Use the existing retry allowance for small citation patches, not for
        # regenerating an entire finding narrative with the source repeated.
        self.config = config.model_copy(update={"max_schema_retries": 0})
        try:
            for attempt in range(1 + config.max_schema_retries):
                result = await super().call(node, state, schema if attempt == 0 else BoundaryCitationRepair,
                    guidance if attempt == 0 else "Repair only the listed citation fields using the supplied reference catalog. "
                    "Do not rewrite claims or narrative. Request tools for missing source, or return inconclusive with a concrete limitation.")
                if result is not None or self.stop != "model_or_schema_error" or self._invalid_turn is None:
                    return result
                if attempt < config.max_schema_retries:
                    self.stop = ""
                    self._repair_context = self._citation_correction_context(state)
            return None
        finally:
            self.config = config
            self._repair_context = None

    def provider_history(self, state, messages, *, overhead_characters=0, node=None):
        if node == "investigate":
            return []  # Current tool views/catalog are authoritative, not prior turns/tasks.
        return super().provider_history(state, messages, overhead_characters=overhead_characters, node=node)

    def prepare_structured_result(self, node, result, state):
        if node == "investigate":
            if isinstance(result, BoundaryCitationRepair):
                result = self._apply_citation_repair(result)
            try:
                self._validate_turn(result, state)
            except ValueError as error:
                code = str(error) if str(error) in BoundaryInvestigationTurn.validation_feedback else "invalid_boundary_query"
                if result.action == "close" and result.conclusion is not None and code in {
                        "unknown_or_undelivered_evidence", "uninspected_component", "unexamined_relationship",
                        "uninspected_symbol", "candidate_evidence_not_in_conclusion",
                        "dependency_endpoints_source_not_inspected", "unverified_source_provenance",
                        "conclusion_requires_inspected_source_and_components"}:
                    self._invalid_turn, self._citation_error = result, code
                raise PydanticCustomError(code, BoundaryInvestigationTurn.validation_feedback[code]) from error
            return result
        allowed = {item.id for item in self._opportunities}
        if len(result.opportunity_ids) > self.config.max_planned_investigations:
            raise PydanticCustomError("planning_size_limit", "Respect budget.max_investigations in this request.")
        if len(set(result.opportunity_ids)) != len(result.opportunity_ids) or set(result.opportunity_ids) - allowed:
            raise PydanticCustomError("planning_unknown_opportunity", "Select unique opportunity_ids from the supplied menu only.")
        for query in result.discovery_queries:
            if query.tool not in self.config.tools:
                raise PydanticCustomError("planning_disabled_tool", "Discovery must use an enabled structural tool.")
            TOOL_SCHEMAS[query.tool].model_validate(query.arguments)
        return result

    async def provider_request(self, model, messages, overhead, node, schema, reserved_calls):
        if node == "investigate":
            # The shared structured-output instruction forbids native tool calls,
            # but here tools are requested THROUGH the structured turn. Do not
            # accidentally tell this agent to skip its tools branch as well.
            messages = [message.model_copy(update={"content": (
                "Return the requested JSON, not native tool calls. To investigate an unresolved question, "
                "return action=tools with focused queries; the graph executes them and returns their evidence "
                "for your next decision. Initial retrieval is a starting point, not a completed investigation. "
                "Before closing, compare evidence_needed and completion_condition with the delivered source ranges. "
                "If a relevant contract, called implementation or reverse interaction is still unread, request "
                "that missing evidence instead of assuming legitimacy from imports or absence of explicit rules. "
                "Close directly when the existing evidence suffices: support no_finding with the observed access "
                "contract, or a candidate with the boundary and contradictory use. If further investigation cannot "
                "proceed and neither conclusion is supported, close inconclusive with concrete limitations."
            )}) if message.type == "human" and message.content ==
                "Now execute investigate. Return the requested JSON, no tools." else message for message in messages]
        # Preserve shared accounting/pacing/retries without reserving absent
        # evaluation/review stages. Task limits also apply to correction attempts.
        if node == "investigate":
            budget = self._active_budget
            reserve = math.ceil((len(json.dumps([m.model_dump() for m in messages], default=str)) + len(overhead)) * .5) + self.output_limit
            reason = self._task_exhaustion(budget)
            if budgets_enabled() and self.tokens + reserve > budget["token_end"]:
                reason = reason or "investigation_token_limit"
                if budget["token_end"] == self.token_limit:
                    self.stop = "token_limit"
                    reason = "token_limit"
            if reason:
                self._task_stop = reason
                self.stop = self.stop or "boundary_task_limit"
                return None
        if node != "investigate":
            return await super().provider_request(model, messages, overhead, node, schema, 0)
        # Bound the shared retry loop as well as the first request.
        global_calls, global_tokens, timing = self.call_limit, self.token_limit, self.timing
        self.call_limit = min(global_calls, budget["call_end"] if budget["call_end"] is not None else math.inf) if budgets_enabled() else math.inf
        self.token_limit = min(global_tokens, budget["token_end"])
        self.timing = timing.fork(max(.001, self._task_seconds(budget)))
        try:
            response = await super().provider_request(model, messages, overhead, node, schema, 0)
        finally:
            self.timing.close()
            self.call_limit, self.token_limit, self.timing = global_calls, global_tokens, timing
        local_stop = ((self.stop == "model_call_limit" and self.calls < global_calls) or
            (self.stop == "token_limit" and budget["token_end"] < global_tokens) or
            (self.stop == "time_limit" and timing.remaining > 0))
        if local_stop:
            self._task_stop, self.stop = "investigation_" + self.stop, "boundary_task_limit"
        return response

    async def plan_investigation(self, state):
        limitations = ["Investigation conclusions and candidates are provisional, not compliance verdicts. No critical review is performed."]
        self._opportunities = []
        inventory = {}
        selected = []
        model_selected = []
        query_cache = {}
        try:
            self._opportunities, inventory, structural_limits = prepare_planning(
                self.tools.accessible_snapshot, self.request,
                limit=self.tools.limits.max_metadata_items, check=self._check_planning,
                config=self.config, character_limit=self.tools.context.input.budget.max_retrieved_characters,
            )
            limitations.extend(structural_limits)
            self._planning_context = {
                "objective": self.request.objective,
                "project_context": self.request.architectural_context,
                "criteria": [item.model_dump() for item in self.request.criteria],
                "targets": self.request.targets,
                "enabled_structural_tools": sorted(set(self.config.tools) & {"list_files", "find_symbols", "list_relationships"}),
                "snapshot_hash": self.tools.context.input.snapshot_hash,
                "inventory": {"counts": inventory["counts"], "project_coverage": inventory["project_coverage"],
                    "integration_diagnostics": inventory["integration_diagnostics"]},
                "opportunities": [{"id": item.id, "priority": item.priority, "scope": item.scope[:3],
                    "project_ids": inventory["_task_projects"][item.id], "scope_kind": item.scope_kind,
                    "kind": item.structural_signal.kind, "basis": item.structural_signal.basis,
                    "signal": item.structural_signal.observed[:2], "omitted_paths": max(0, len(item.scope) - 3)}
                    for item in self._opportunities],
                "budget": {"max_investigations": self.config.max_planned_investigations,
                    "remaining_tool_calls": self._remaining_tools(self.tool_limit)},
                "discovery_results": [],
            }
            # Leave room for provider/schema instructions; truncation removes
            # whole tasks, never their endpoints or provenance.
            prompt = self.config.prompts.get("plan_investigation")
            if prompt is None:
                prompt = (self.prompt_directory / "plan_investigation.md").read_text(encoding="utf-8")
            overhead = len(prompt) + 2 * len(json.dumps(BoundaryPlanSelection.model_json_schema())) + 1000
            cap = max(0, min(self.config.max_context_characters,
                2 * self.tools.context.input.budget.max_input_tokens_per_call) - overhead)
            context = self._planning_context
            if len(json.dumps(context)) > cap:
                context["inventory"] = {"counts": inventory["counts"], "limitations": inventory["limitations"],
                    "project_coverage": [{key: row[key] for key in ("project_id", "root", "eligible_files", "eligible_relationships", "index_status")}
                        for row in inventory["project_coverage"]]}
            original_count = len(self._opportunities)
            while context["opportunities"] and len(json.dumps(context)) > cap:
                context["opportunities"].pop()
                self._opportunities.pop()
            if len(self._opportunities) < original_count:
                limitations.append(f"Context allowance omitted {original_count - len(self._opportunities)} candidate tasks; no exhaustive coverage is claimed.")
                if not self._opportunities:
                    self.stop = "context_limit"
            seen_queries = set()
            # Optional planning discovery stays bounded inside this node.
            for turn in range(3):
                self._check_planning()
                if not self._opportunities:
                    break
                context["budget"]["remaining_model_calls"] = self._remaining_model_calls(self.call_limit)
                context["budget"]["remaining_tool_calls"] = self._remaining_tools(self.tool_limit)
                selection = await self.call("plan_investigation", state, BoundaryPlanSelection)
                if selection is None:
                    break
                model_selected = [next(item for item in self._opportunities if item.id == key) for key in selection.opportunity_ids]
                # Diversity may reorder the selection, never add unchosen tasks.
                selected = balance_candidates(self._opportunities, inventory["_coverage_units"],
                    self.config.max_planned_investigations, preferred=model_selected)
                if not selection.discovery_queries:
                    break
                if turn == 2:
                    limitations.append("Additional planning discovery deferred: bounded planning turn limit reached.")
                    break
                results = []
                for query in selection.discovery_queries:
                    self._check_planning()
                    arguments = TOOL_SCHEMAS[query.tool].model_validate(query.arguments).model_dump()
                    arguments["limit"] = min(arguments.get("limit", 20), self.tools.limits.max_page_size,
                        self.tools.limits.max_metadata_items)
                    signature = json.dumps([query.tool, arguments], sort_keys=True)
                    if signature in seen_queries:
                        limitations.append("A redundant planning query was skipped; previous results remain available.")
                        continue
                    if len(seen_queries) >= 3 or self.tools.budget_usage.tool_calls >= self.tool_limit:
                        limitations.append("Planning discovery stopped at the configured tool allowance.")
                        break
                    seen_queries.add(signature)
                    response = self.tools.execute(query.tool, arguments, tool_call_id=f"boundary-plan-{len(seen_queries)}")
                    # Whitelist structural fields: no signatures, descriptions,
                    # comments or source content from metadata tools.
                    data = response.data or {}
                    fields = {"id", "path", "file_id", "project_id", "name", "kind", "source_id", "target_id",
                        "resolution", "start_line", "end_line"}
                    rows = data.get("items", [])
                    eligible = inventory["_eligible_file_ids"]
                    rows = [row for row in rows if (
                        row.get("id") in inventory["_eligible_relationship_ids"] if query.tool == "list_relationships"
                        else row.get("file_id", row.get("id")) in eligible)]
                    # Retain the same compact tool response for later tasks;
                    # its provenance IDs belong to RepositoryToolset, not a new ledger.
                    view = self.tools.model_view(response)
                    if "data" in view:
                        retained_ids = {row["id"] for row in rows}
                        view["data"]["items"] = [row for row in view["data"].get("items", []) if row.get("id") in retained_ids]
                    view["evidence"] = [record for record in view.get("evidence", []) if record["file_id"] in eligible]
                    query_cache[signature] = view | {"tool_call_id": response.tool_call_id, "snapshot_hash": response.snapshot_hash}
                    results.append({"tool": query.tool, "arguments": arguments,
                        "items": [{key: value for key, value in row.items() if key in fields} for row in rows],
                        "index_total_before_production_filter": data.get("total"),
                        "excluded_nonproduction_rows": len(data.get("items", [])) - len(rows), "next_offset": data.get("next_offset"),
                        "error": response.error.code if response.error else None})
                    if response.error:
                        limitations.append(f"Structural discovery unavailable: {response.error.code}.")
                if not results:
                    break
                if len(json.dumps(context)) + len(json.dumps(results)) > cap:
                    limitations.append("Discovery metadata retained by tools but omitted from model context to respect its volume limit.")
                    break
                context["discovery_results"].extend(results)
        except TimeoutError:
            self.stop = "time_limit"
            limitations.append("The planning time allowance was exhausted; no further discovery was attempted.")
        limitations.extend(self.issues)
        if self.stop:
            limitations.append("Model planning did not finish; retained tasks are exploration seeds from the last valid selection, not verified conclusions.")
        diagnostics = planning_diagnostics(inventory, self._opportunities, selected, model_selected,
            maximum=self.config.max_planned_investigations)
        diagnostics["opportunities"]["context_budget_omitted"] = max(0, inventory.get("_initial_menu_size", len(self._opportunities)) - len(self._opportunities))
        plan = BoundaryPlan(objectives=[self.request.objective],
            components=list(dict.fromkeys(path for task in selected for path in task.scope)),
            investigations=selected, limitations=list(dict.fromkeys(limitations)),
            snapshot_hash=self.tools.context.input.snapshot_hash)
        reason = self.stop or "planning_completed"
        result = self.result_schema(
            repository_id=state["repository_id"], commit=state["commit"],
            snapshot_hash=self.tools.context.input.snapshot_hash,
            objective=state["objective"], plan=plan, findings=[], hypotheses=[],
            missing_information=[], limitations=plan.limitations,
            termination_reason=reason, model_calls=self.calls, tool_calls=self.tools.budget_usage.tool_calls,
            iterations=0, accounted_tokens=self.tokens, estimated_tokens=self.estimates,
            deferred_stages=self.deferred_stages, evidence=self.references(),
            consumption_by_phase={"plan_investigation": {key: value for key, value in self._consumption().items()
                if key != "remaining_seconds"}},
            investigation_tasks=[item.model_dump() for item in selected],
            investigation_coverage={"counts": inventory.get("counts", {}), "selected": len(selected),
                "candidate_menu": len(self._opportunities), "exhaustive": False, **diagnostics},
        )
        return {"plan": plan, "result": result, "termination_reason": result.termination_reason,
            "missing_information": result.missing_information, "limitations": result.limitations,
            "query_cache": query_cache}

    def _build_graph(self):
        graph = StateGraph(BoundaryState)
        graph.add_node("plan_investigation", phase_node("plan_investigation", self.plan_investigation))
        graph.add_node("investigate", phase_node("investigate", self.investigate))
        graph.add_node("tools", phase_node("tools", self.execute_investigation_tools))
        graph.add_node("synthesis", phase_node("synthesis", self.synthesis))
        graph.add_node("finalize", phase_node("finalize", self.finalize))
        graph.add_edge(START, "plan_investigation")
        graph.add_edge("plan_investigation", "investigate")
        graph.add_conditional_edges("investigate", self.route_investigation,
            {"tools": "tools", "investigate": "investigate", "synthesis": "synthesis"})
        graph.add_edge("tools", "investigate")
        graph.add_edge("synthesis", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    def initial_state(self):
        return super().initial_state() | {"current_investigation": 0, "investigation_results": [],
            "candidates": [], "pending_queries": [], "query_cache": {}, "active_query_keys": [],
            "task_budget": {}, "task_limitations": [], "no_progress_turns": 0, "consumption": {},
            "initial_evidence_loaded": False}

    def _task_exhaustion(self, budget):
        self.timing.check_cancellation()
        if not budgets_enabled():
            return self.stop
        if self.remaining_seconds() <= 0:
            self.stop = "time_limit"
        elif self.calls >= self.call_limit:
            self.stop = "model_call_limit"
        elif self.tokens >= self.token_limit:
            self.stop = "token_limit"
        if self.stop:
            return self.stop
        if budget["call_end"] is not None and self.calls >= budget["call_end"]:
            return "investigation_call_limit"
        if self.tokens >= min(budget["token_end"], budget["token_share_end"]):
            return "investigation_token_limit"
        if self._task_seconds(budget) <= 0:
            return "investigation_time_limit"
        return ""

    def _task_seconds(self, budget):
        if not budgets_enabled():
            return math.inf
        return budget["seconds"] - (budget["active_start"] - self.timing.active_remaining)

    def _new_task_budget(self, state):
        remaining = len(state["plan"].investigations) - state["current_investigation"]
        task_calls = self.config.max_calls_per_investigation if budgets_enabled() else None
        global_calls = self._remaining_model_calls(self.call_limit)
        if global_calls is not None:
            share = math.ceil(global_calls / remaining)
            task_calls = share if task_calls is None else min(task_calls, share)
        task_tools = self.config.max_tools_per_investigation if budgets_enabled() else None
        global_tools = self._remaining_tools(self.tool_limit)
        if global_tools is not None:
            share = math.ceil(global_tools / remaining)
            task_tools = share if task_tools is None else min(task_tools, share)
        return {"call_start": self.calls, "tool_start": self.tools.budget_usage.tool_calls,
            "token_start": self.tokens,
            "call_end": None if task_calls is None else self.calls + task_calls,
            "tool_end": None if task_tools is None else self.tools.budget_usage.tool_calls + task_tools,
            # Fairness uses charged usage, not the provider's pessimistic next-
            # request reservation: a small share must not reject every task
            # merely because schema/input + maximum output exceeds that share.
            # The configured per-task and global admission limits remain hard.
            "token_share_end": self.tokens + math.ceil(max(0, self.token_limit - self.tokens) / remaining),
            "token_end": min(self.token_limit, self.tokens + self.config.max_tokens_per_investigation),
            "active_start": self.timing.active_remaining if budgets_enabled() else None,
            "seconds": min(self.config.max_seconds_per_investigation, self.remaining_seconds() / remaining)}

    def _remaining_tools(self, limit):
        return None if limit is None or math.isinf(limit) else max(0, limit - self.tools.budget_usage.tool_calls)

    def _remaining_model_calls(self, limit):
        return None if limit is None or math.isinf(limit) else max(0, limit - self.calls)

    def _allowed_files(self):
        snapshot = self.tools.accessible_snapshot
        # Production remains the default, with the planner's explicit target exceptions.
        targets = {value.replace("\\", "/").rstrip("/") or "." for value in (self.request.targets or
            [value for item in self.request.follow_up for value in [*item.paths, *item.subject_ids]])}
        symbols = {symbol.id: symbol.file_id for symbol in snapshot.symbols}
        test_paths = {path for testing in snapshot.testing for path in testing.file_paths}
        return {file.id: file for file in snapshot.files
            if not (nonproduction_path(file.path) or file.path in test_paths) or any(
                target in {file.id, file.path, file.module_name} or symbols.get(target) == file.id or
                (nonproduction_path(target) and file.path.startswith(target + "/")) for target in targets)}

    def _normalize_query(self, query, task):
        if query.tool not in self.config.tools:
            raise ValueError("disabled_tool")
        args = TOOL_SCHEMAS[query.tool].model_validate(query.arguments).model_dump()
        files = self._allowed_files()
        paths = {file.path: file for file in files.values()}
        snapshot = self.tools.accessible_snapshot
        entity_files = {symbol.id: symbol.file_id for symbol in snapshot.symbols} | {key: key for key in files}
        evidence_files = {record.id: record.file_id for record in snapshot.evidence}
        selected_paths = []
        for key in ("path", "file_path"):
            if args.get(key):
                if args[key] not in paths:
                    raise ValueError("unavailable_or_nonproduction_path")
                selected_paths.append(args[key])
        for key in ("source_id", "target_id", "evidence_id"):
            if args.get(key):
                file_id = (evidence_files if key == "evidence_id" else entity_files).get(args[key])
                if file_id not in files:
                    raise ValueError("unavailable_entity")
                selected_paths.append(files[file_id].path)
        if (not selected_paths or any(path not in task.scope for path in selected_paths)) and not query.scope_expansion.strip():
            raise ValueError("scope_expansion_reason_required")
        if "limit" in args:
            args["limit"] = min(args["limit"], 10, self.tools.limits.max_page_size, self.tools.limits.max_metadata_items)
        if query.tool == "get_source_excerpt":
            start = args["start_line"]
            args["end_line"] = min(args["end_line"] or start + 59, start + 59,
                start + self.tools.limits.max_source_lines - 1, paths[args["path"]].line_count)
        return args, json.dumps([query.tool, args], sort_keys=True)

    def _investigation_context(self, state):
        task = state["plan"].investigations[state["current_investigation"]]
        keys = state["active_query_keys"]
        references = [ref for ref in self.references() if ref.id in self._delivered_ids(state)]
        catalog = reference_catalog(self.tools.accessible_snapshot, references,
            examined_relationships(self.tools.accessible_snapshot, state), task)
        results, result_queries = [], []
        for key in keys:
            view = state["query_cache"][key]
            data = view.get("data", {})
            if view["tool_name"] == "get_source_excerpt":
                data = {field: data[field] for field in ("path", "start_line", "end_line", "content", "truncated") if field in data}
            elif view["tool_name"] == "list_relationships":
                # The authoritative endpoint/citation map below replaces edge metadata.
                continue
            results.append({"tool_name": view["tool_name"], "status": view["status"],
                **({"data": data} if view["status"] == "ok" else {"error": view["error"]})})
            result_queries.append(json.loads(key))
        scope_files = {file.id for file in self.tools.accessible_snapshot.files if file.path in task.scope}
        reusable = [json.loads(key) for key, view in state["query_cache"].items() if key not in keys
            and any(ref["file_id"] in scope_files for ref in view.get("evidence", []))][-6:]
        context = {"investigation": task.model_dump(exclude={"structural_signal", "investigation_strategy"}) | {
                "structural_signal": task.structural_signal.model_dump(include={"kind", "observed", "inference"})},
            "criteria": state["criteria"],
            "commit": state["commit"], "snapshot_hash": self.tools.context.input.snapshot_hash,
            "tools": {key: value for key, value in tool_signatures().items() if key in self.config.tools},
            "tool_results": results, "reusable_queries": reusable,
            "evidence": catalog.pop("evidence"), "reference_catalog": catalog,
            "limitations": state["task_limitations"],
            "remaining_investigation_calls": self._remaining_model_calls(state["task_budget"]["call_end"]),
            "remaining_tool_calls": self._remaining_tools(state["task_budget"]["tool_end"])}
        # Drop whole older response views only; never truncate source lines or
        # alter the evidence ledger. An omitted query can be replayed from cache.
        cap = min(self.config.max_context_characters, 2 * self.tools.context.input.budget.max_input_tokens_per_call) // 2
        omitted = []
        while len(context["tool_results"]) > 1 and len(json.dumps(context)) > cap:
            context["tool_results"].pop(0)
            omitted.append(result_queries.pop(0))
        context["omitted_tool_results_reusable_queries"] = omitted
        return context

    def _citation_correction_context(self, state):
        task = state["plan"].investigations[state["current_investigation"]]
        refs = [ref for ref in self.references() if ref.id in self._delivered_ids(state)]
        catalog = reference_catalog(self.tools.accessible_snapshot, refs,
            examined_relationships(self.tools.accessible_snapshot, state), task)
        conclusion = self._invalid_turn.conclusion
        return {"investigation_id": task.id, "validation_error": self._citation_error,
            "errors": reference_errors(self._invalid_turn, self._citation_error, catalog),
            "reference_catalog": catalog,
            "source_not_retrieved": [path for path in task.scope if path not in catalog["source_evidence_by_component"]],
            "limitations": state["task_limitations"],
            "subjects": [{"subject_id": identifier, **{field: getattr(subject, field) for field in
                ("components", "evidence_ids", "symbol_ids", "relationship_ids")}}
                for identifier, subject in [("conclusion", conclusion), *((item.id, item) for item in conclusion.candidates)]]}

    def _apply_citation_repair(self, repair):
        if repair.action == "tools" and repair.queries and not repair.corrections:
            return BoundaryInvestigationTurn(action="tools", queries=repair.queries)
        if repair.action == "inconclusive" and repair.limitation.strip() and not repair.queries and not repair.corrections:
            return BoundaryInvestigationTurn(action="close", conclusion=BoundaryInvestigationResult(
                investigation_id=self._invalid_turn.conclusion.investigation_id, status="inconclusive",
                summary="Citation requirements could not be satisfied.", justification=repair.limitation,
                limitations=[repair.limitation]))
        if repair.action != "patch" or not repair.corrections or repair.queries:
            raise ValueError("invalid_citation_repair")
        payload = self._invalid_turn.model_dump()
        subjects = {"conclusion": payload["conclusion"], **{item["id"]: item for item in payload["conclusion"]["candidates"]}}
        for patch in repair.corrections:
            if patch.subject_id not in subjects:
                raise ValueError("unknown_citation_subject")
            subjects[patch.subject_id][patch.field] = patch.values
        # Re-validate canonical types, collection bounds and all provenance checks.
        return BoundaryInvestigationTurn.model_validate(payload)

    def _initial_queries(self, task):
        return initial_queries(self.tools.accessible_snapshot, task, self.config.tools)

    @staticmethod
    def _delivered_ids(state):
        return {record["id"] for key in state["active_query_keys"]
            for record in state["query_cache"][key].get("evidence", [])}

    def _validate_turn(self, turn, state):
        task = state["plan"].investigations[state["current_investigation"]]
        if turn.action == "tools":
            if not turn.queries or turn.conclusion is not None:
                raise ValueError("tools_requires_queries_without_conclusion")
            for query in turn.queries:
                self._normalize_query(query, task)
            return
        result = turn.conclusion
        if turn.queries or result is None or result.investigation_id != task.id:
            raise ValueError("close_requires_current_investigation_conclusion")
        if (result.status == "finding_candidate") != bool(result.candidates):
            raise ValueError("candidate_status_mismatch")
        if result.status == "inconclusive" and not result.limitations:
            raise ValueError("inconclusive_requires_limitations")
        references = {ref.id: ref for ref in self.references() if ref.id in self._delivered_ids(state)}
        if set(result.evidence_ids) - references.keys():
            raise ValueError("unknown_or_undelivered_evidence")
        snapshot = self.tools.accessible_snapshot
        symbols = {symbol.id: symbol for symbol in snapshot.symbols}
        relationship_ids = examined_relationships(snapshot, state).keys()
        candidate_ids = {item.id for item in state["candidates"]}
        for subject in [result, *result.candidates]:
            if set(subject.evidence_ids) - set(result.evidence_ids):
                raise ValueError("candidate_evidence_not_in_conclusion")
            cited = [references[key] for key in subject.evidence_ids]
            if subject is not result or result.status != "inconclusive":
                if not any(ref.kind == "source" for ref in cited) or not subject.components:
                    raise ValueError("conclusion_requires_inspected_source_and_components")
                _, issues = self.evidence_issues(subject.evidence_ids, references)
                if issues:
                    raise ValueError("unverified_source_provenance")
            inspected_paths = {ref.path for ref in cited if ref.kind == "source" or result.status == "inconclusive"}
            if set(subject.components) - inspected_paths:
                raise ValueError("uninspected_component")
            if set(subject.relationship_ids) - relationship_ids:
                raise ValueError("unexamined_relationship")
            if subject is not result:
                owners = {symbol.id: symbol.file_id for symbol in snapshot.symbols}
                for relationship in snapshot.relationships:
                    if relationship.id in subject.relationship_ids and any(
                            not any(ref.kind == "source" and ref.file_id == owners.get(entity, entity) for ref in cited)
                            for entity in (relationship.source_id, relationship.target_id)):
                        raise ValueError("dependency_endpoints_source_not_inspected")
            for identifier in subject.symbol_ids:
                symbol = symbols.get(identifier)
                if symbol is None or not any(ref.kind == "source" and ref.file_id == symbol.file_id
                        and ref.start_line <= symbol.end_line and ref.end_line >= symbol.start_line for ref in cited):
                    raise ValueError("uninspected_symbol")
            if subject is not result:
                if subject.id in candidate_ids or subject.criterion_id not in {item.id for item in self.request.criteria}:
                    raise ValueError("duplicate_candidate_or_unknown_criterion")
                candidate_ids.add(subject.id)

    def _consumption(self):
        return {"model_calls": self.calls, "tool_calls": self.tools.budget_usage.tool_calls,
            "accounted_tokens": self.tokens, "estimated_tokens": self.estimates,
            "retrieved_characters": self.tools.budget_usage.retrieved_characters,
            "remaining_seconds": max(0, self.remaining_seconds())}

    def _new_evidence_bound(self, tool, arguments):
        """Conservative bound for the shared output's 400-reference envelope."""
        snapshot = self.tools.accessible_snapshot
        collections = {"find_symbols": snapshot.symbols, "list_relationships": snapshot.relationships,
            "get_infrastructure": snapshot.infrastructure, "list_files": snapshot.files}
        if tool == "get_source_excerpt":
            return 1
        if tool == "get_evidence":
            return 2
        extras = max((len(getattr(item, "evidence_ids", ())) for item in collections.get(tool, ())), default=0)
        return arguments.get("limit", 1) * (1 + min(extras, self.tools.limits.max_metadata_items))

    def _trace_investigation(self, state, transition, **details):
        """Content-free per-task trace using the existing charged usage ledger."""
        budget = state["task_budget"]
        self.logger.info("investigation_trace %s", json.dumps({
            "investigation_id": state["plan"].investigations[state["current_investigation"]].id,
            "transition": transition,
            "model_calls": self.calls - budget["call_start"],
            "tool_calls": self.tools.budget_usage.tool_calls - budget["tool_start"],
            "accounted_tokens": self.tokens - budget["token_start"], **details}, sort_keys=True))

    def _close_investigation(self, state, conclusion):
        self._trace_investigation(state, "investigate->close", status=conclusion.status,
            evidence_ids=conclusion.evidence_ids)
        task_limits = list(dict.fromkeys([*conclusion.limitations, *state["task_limitations"]]))
        if len(task_limits) > 40:
            task_limits = [*task_limits[:39], "Additional limitations are retained in the execution output."]
        conclusion = conclusion.model_copy(update={"limitations": task_limits})
        results = [*state["investigation_results"], conclusion]
        candidates = [*state["candidates"], *conclusion.candidates]
        index = state["current_investigation"] + 1
        done = index == len(state["plan"].investigations)
        ledger, _ = self.verify_references(self.references())
        progress = [*state["result"].investigation_progress, {"investigation_id": conclusion.investigation_id,
            "status": conclusion.status, "model_calls": self.calls - state["task_budget"]["call_start"],
            "tool_calls": self.tools.budget_usage.tool_calls - state["task_budget"]["tool_start"],
            "accounted_tokens": self.tokens - state["task_budget"]["token_start"]}]
        reason = self.stop or ("investigations_completed" if done else "investigating")
        limitations = list(dict.fromkeys([*state["limitations"], *state["task_limitations"], *conclusion.limitations, *self.issues,
            *([] if state["commit"] else ["No commit is available; evidence is attributed to retained snapshot bytes only."])]))
        result = state["result"].model_copy(update={"investigation_results": results, "candidates": candidates,
            "investigation_progress": progress, "next_phase": "synthesis" if done else None,
            "termination_reason": reason, "limitations": limitations, "evidence": ledger,
            "model_calls": self.calls, "tool_calls": self.tools.budget_usage.tool_calls,
            "accounted_tokens": self.tokens, "estimated_tokens": self.estimates,
            "iterations": state["iterations"] + 1, "deferred_stages": self.deferred_stages})
        return {"current_investigation": index, "investigation_results": results, "candidates": candidates,
            "pending_queries": [], "active_query_keys": [], "task_budget": {}, "task_limitations": [],
            "initial_evidence_loaded": False,
            "no_progress_turns": 0, "result": result, "evidence": ledger, "limitations": limitations,
            "model_calls": self.calls, "tool_calls": self.tools.budget_usage.tool_calls,
            "iterations": state["iterations"] + 1, "consumption": self._consumption(),
            "termination_reason": reason, "next_phase": "synthesis" if done else "investigate"}

    async def investigate(self, state):
        tasks = state["plan"].investigations
        if state["current_investigation"] >= len(tasks):
            return {"next_phase": "synthesis", "result": state["result"].model_copy(update={"next_phase": "synthesis"})}
        state = dict(state)
        if not state["task_budget"]:
            state["task_budget"] = self._new_task_budget(state)
        self._active_budget, self._task_stop = state["task_budget"], ""
        reason = self._task_exhaustion(state["task_budget"])
        if not reason and not state["initial_evidence_loaded"]:
            state["initial_evidence_loaded"] = True
            queries = self._initial_queries(tasks[state["current_investigation"]])
            if queries:
                self._trace_investigation(state, "investigate->tools", origin="initial_evidence", queries=len(queries))
                return {"pending_queries": queries, "initial_evidence_loaded": True, "task_budget": state["task_budget"]}
        if state["no_progress_turns"] >= 2:
            reason = reason or "no_investigation_progress"
        turn = None
        deferred_count = len(self.deferred_stages)
        if not reason:
            calls_before, tokens_before = self.calls, self.tokens
            turn = await self.call("investigate", state, BoundaryInvestigationTurn)
            self._trace_investigation(state, "llm->decision", action=turn.action if turn else "invalid_or_blocked",
                llm_calls=self.calls - calls_before, llm_tokens=self.tokens - tokens_before,
                delivered_evidence_ids=sorted(self._delivered_ids(state)))
            reason = self._task_stop or self.stop or "invalid_investigation_response"
        if turn and turn.action == "tools":
            self._trace_investigation(state, "investigate->tools", origin="model", queries=len(turn.queries))
            return {"pending_queries": turn.queries, "task_budget": state["task_budget"],
                "initial_evidence_loaded": True,
                "model_calls": self.calls, "consumption": self._consumption()}
        if turn:
            return self._close_investigation(state, turn.conclusion)
        # A malformed answer closes only this task. Provider/global failures
        # retain their stop reason and mark remaining tasks inconclusive without calls.
        if self.stop == "boundary_task_limit" or (self.stop in {"model_or_schema_error", "context_limit", "input_token_limit"}
                and len(self.deferred_stages) == deferred_count):
            self.stop = ""
        delivered = self._delivered_ids(state)
        refs = sorted((ref for ref in self.references() if ref.id in delivered), key=lambda ref: ref.kind != "source")[:80]
        examined_relationships = [row["id"] for key in state["active_query_keys"]
            if state["query_cache"][key]["tool_name"] == "list_relationships"
            for row in state["query_cache"][key].get("data", {}).get("items", [])]
        conclusion = BoundaryInvestigationResult(investigation_id=tasks[state["current_investigation"]].id,
            status="inconclusive", summary="Investigation could not reach a supported conclusion.",
            justification=f"Execution stopped for this task: {reason}.",
            components=list(dict.fromkeys(ref.path for ref in refs))[:40],
            symbol_ids=list(dict.fromkeys(symbol for ref in refs if ref.kind == "source" for symbol in ref.symbol_ids))[:80],
            relationship_ids=list(dict.fromkeys(examined_relationships))[:80], evidence_ids=[ref.id for ref in refs],
            limitations=[reason, *state["task_limitations"],
                *(["Task reference summary is bounded; the complete evidence ledger is retained in the output."] if len(delivered) > 80 else [])])
        return self._close_investigation(state, conclusion)

    async def execute_investigation_tools(self, state):
        task = state["plan"].investigations[state["current_investigation"]]
        cache, keys = dict(state["query_cache"]), list(state["active_query_keys"])
        limitations, new_results = list(state["task_limitations"]), 0
        allowed = self._allowed_files()
        symbols = {item.id: item.file_id for item in self.tools.accessible_snapshot.symbols}
        relationships = {item.id: item for item in self.tools.accessible_snapshot.relationships}
        for query in state["pending_queries"]:
            self.timing.check_cancellation()
            args, key = self._normalize_query(query, task)
            if key not in cache and query.tool == "get_source_excerpt":
                # Reuse a delivered covering range, retaining its original IDs.
                key = next((cached_key for cached_key, view in cache.items() if view["tool_name"] == query.tool
                    and view["status"] == "ok" and view.get("data", {}).get("path") == args["path"]
                    and view["data"]["start_line"] <= args["start_line"] and view["data"]["end_line"] >= args["end_line"]), key)
            cached = key in cache
            if not cached:
                if self.remaining_seconds() <= 0 or self._task_seconds(state["task_budget"]) <= 0:
                    limitations.append("investigation_time_limit")
                    break
                if state["task_budget"]["tool_end"] is not None and self.tools.budget_usage.tool_calls >= state["task_budget"]["tool_end"]:
                    limitations.append("investigation_tool_limit")
                    continue
                if len(self.references()) + self._new_evidence_bound(query.tool, args) > 400:
                    limitations.append("evidence_ledger_limit: reuse existing evidence or request a smaller page")
                    continue
                call_id = "boundary-investigate-" + uuid4().hex
                try:
                    response = self.tools.execute(query.tool, args, tool_call_id=call_id)
                except Exception as error:  # noqa: BLE001 - tool boundary; cancellation propagates
                    view = {"status": "error", "tool_name": query.tool, "tool_call_id": call_id,
                        "error": {"code": "tool_execution_error", "message": safe_diagnostic(error)}, "evidence": []}
                else:
                    view = self.tools.model_view(response) | {"tool_call_id": response.tool_call_id,
                        "snapshot_hash": response.snapshot_hash}
                if "items" in view.get("data", {}):
                    rows = view["data"]["items"]
                    def eligible(row, tool=query.tool):
                        if tool == "list_relationships":
                            rel = relationships.get(row.get("id"))
                            return rel is not None and all(symbols.get(entity, entity) in allowed
                                for entity in (rel.source_id, rel.target_id) if entity in symbols or entity in {f.id for f in self.tools.accessible_snapshot.files})
                        return row.get("file_id", row.get("id")) in allowed if tool != "get_infrastructure" else True
                    view["data"]["items"] = [row for row in rows if eligible(row)]
                    view["data"]["excluded_nonproduction_rows"] = len(rows) - len(view["data"]["items"])
                view["evidence"] = [record for record in view.get("evidence", []) if record["file_id"] in allowed]
                cache[key] = view
                if view["status"] != "error":
                    new_results += 1
            self._trace_investigation(state, "tool_result", tool=query.tool, cached=cached,
                tool_call_id=cache[key].get("tool_call_id"), status=cache[key]["status"],
                evidence_ids=[record["id"] for record in cache[key].get("evidence", [])])
            if cache[key]["status"] == "error":
                limitations.append("Tool query failed: " + cache[key]["error"]["code"])
            if key in keys:
                keys.remove(key)
            keys.append(key)
        self._trace_investigation(state, "tools->investigate", active_cached_views=len(keys))
        return {"query_cache": cache, "active_query_keys": keys, "pending_queries": [],
            "task_limitations": list(dict.fromkeys(limitations)), "tool_calls": self.tools.budget_usage.tool_calls,
            "evidence": self.references(), "consumption": self._consumption(),
            "no_progress_turns": 0 if new_results else state["no_progress_turns"] + 1}

    def route_investigation(self, state):
        if state["pending_queries"]:
            return "tools"
        return "investigate" if state["current_investigation"] < len(state["plan"].investigations) else "synthesis"

    def synthesis(self, state):
        candidates, origins = consolidate_candidates(state["investigation_results"])
        self.logger.info("boundary_synthesis %s", json.dumps({
            "original_candidates": sum(len(item.candidates) for item in state["investigation_results"]),
            "consolidated_candidates": len(candidates),
            "candidate_origins": {key: [origin.model_dump() for origin in value] for key, value in origins.items()},
        }, sort_keys=True))
        return {"candidates": candidates, "candidate_origins": origins, "next_phase": "finalize"}

    def finalize(self, state):
        # No model adjudication: expose candidates in the common finding envelope
        # as unreviewed, preserving their original confidence, severity and prose.
        ledger, mismatch = self.verify_references(self.references())
        references = {reference.id: reference for reference in ledger}
        criteria = {criterion.id: criterion for criterion in self.request.criteria}
        findings = [BoundaryFinding(
            **candidate.model_dump(exclude={"inferred_boundary", "contradictory_dependency", "technical_basis",
                "symbol_ids", "relationship_ids"}),
            criterion=criteria[candidate.criterion_id],
            evidence=[references[identifier] for identifier in candidate.evidence_ids],
            validation_status="insufficient_evidence",
            review_rationale="Provisional investigation candidate; no critical review or acceptance was performed.",
        ) for candidate in state["candidates"]]
        limitations = list(dict.fromkeys([*state["limitations"], *self.issues,
            *(limitation for item in state["investigation_results"] for limitation in item.limitations),
            "Coverage is bounded; absence of findings does not establish architectural compliance.",
            *(["Some retained evidence could not be attributed to the declared commit."] if mismatch else []),
            *([] if state["commit"] else ["No commit is available; evidence is attributed to retained snapshot bytes only."])]))
        missing = list(dict.fromkeys([*state["missing_information"],
            *(f"Investigation {item.investigation_id}: {limitation}"
                for item in state["investigation_results"] if item.status == "inconclusive" for limitation in item.limitations)]))
        usage = self._consumption()
        planning_usage = state["result"].consumption_by_phase["plan_investigation"]
        fields = tuple(planning_usage)
        investigation_usage = {field: usage[field] - planning_usage[field] for field in fields}
        result = self.result_schema(**(state["result"].model_dump() | {
            "findings": findings, "candidates": state["candidates"], "candidate_origins": state["candidate_origins"],
            "investigation_results": state["investigation_results"], "evidence": ledger,
            "missing_information": missing, "limitations": limitations, "next_phase": None,
            "termination_reason": state["termination_reason"], "iterations": state["iterations"],
            "model_calls": self.calls, "tool_calls": self.tools.budget_usage.tool_calls,
            "accounted_tokens": self.tokens, "estimated_tokens": self.estimates, "deferred_stages": self.deferred_stages,
            "consumption_by_phase": {
                "plan_investigation": planning_usage,
                "investigate": investigation_usage,
                "synthesis": dict.fromkeys(fields, 0), "finalize": dict.fromkeys(fields, 0)},
        }))
        return {"result": result, "evidence": ledger, "missing_information": missing, "limitations": limitations,
            "consumption": usage, "next_phase": None}
