"""Iterative reuse-parametrization investigation (investigate/tools loop).

Separated from execution.py so planning stays independent. Reading source belongs
to investigate. A close must be supported by the untrusted delivered evidence, never
by the plan alone.
"""

import json
import sys
from uuid import uuid4

from pydantic_core import PydanticCustomError

from server.runtimes.investigation.structured import safe_diagnostic
from server.runtimes.repository.tools import TOOL_SCHEMAS, tool_signatures

from .documentary import documentary_context, pending_assessments
from .schemas import (
    ParametrizationInvestigationResult,
    ParametrizationInvestigationTurn,
    ParametrizationToolQuery,
)


def _invalid(code):
    feedback = ParametrizationInvestigationTurn.validation_feedback.get(code, code)
    return PydanticCustomError(code, feedback)


def _normalized_identifier(value):
    return "".join(character for character in (value or "").casefold() if character.isalnum())


# A not_applicable exclusion is only accepted without source when the obligation
# itself does not ask for code inspection. These terms keep that escape hatch from
# bypassing source-backed obligations.
_CODE_DEPENDENT_REQUIREMENT_TERMS = (
    "source", "implementation", "implement", "consumer", "caller", "call site",
    "contract", "declaration", "behaviour", "behavior", "selection", "selector",
    "wiring", "registry", "factory", "configur", "alternative", "guarantee",
    "return", "branch", "class", "function", "method", "module", "file", "code",
)


def _requirement_requires_code(requirement):
    lowered = (requirement or "").casefold()
    return any(term in lowered for term in _CODE_DEPENDENT_REQUIREMENT_TERMS)


def _concrete_rationale(value):
    """Reject empty or restated exclusions without attempting semantic scoring."""
    text = " ".join((value or "").split())
    return len(text) >= 40 and len(text.split()) >= 6


class ParametrizationInvestigation:
    def route_investigation(self, state):
        if state["pending_queries"]:
            return "tools"
        return "investigate" if state["current_investigation"] < len(state["plan"].candidates) else "end"

    def _current(self, state):
        return state["plan"].candidates[state["current_investigation"]]

    def _scope_paths(self, candidate):
        return list(dict.fromkeys(candidate.initial_locations or candidate.scope))

    def _contract_spans(self, task):
        snapshot = self.tools.accessible_snapshot
        primary_file = next((item for item in snapshot.files if item.path == task.primary_component), None)
        symbol_id = getattr(task, "symbol_id", "") or None
        symbol_name = getattr(task, "symbol_name", None)
        names = {_normalized_identifier(symbol_name)} - {""} if symbol_name else set()
        spans = []
        for symbol in snapshot.symbols:
            if primary_file is not None and symbol.file_id != primary_file.id:
                continue
            if symbol_id:
                if symbol.id == symbol_id:
                    spans.append((symbol.start_line, symbol.end_line))
            elif names and names & {_normalized_identifier(symbol.name), _normalized_identifier(symbol.qualified_name)}:
                spans.append((symbol.start_line, symbol.end_line))
        return primary_file, spans

    def _initial_queries(self, candidate):
        primary = candidate.primary_component
        target, spans = self._contract_spans(candidate)
        file_id = target.id if target else None
        if spans:
            start = max(1, min(span[0] for span in spans) - 5)
            end = min(max(span[1] for span in spans) + 5, start + 59)
            if target and target.line_count:
                end = min(end, target.line_count)
        else:
            start, end = 1, 60
        queries = [ParametrizationToolQuery(tool="get_source_excerpt",
            arguments={"path": primary, "start_line": start, "end_line": end},
            reason="Inspect the primary capability and its selection surface.")]
        if file_id:
            queries.append(ParametrizationToolQuery(tool="list_relationships",
                arguments={"source_id": file_id, "limit": 10},
                reason="Examine the indexed inputs and dependents of the capability owner."))
            queries.append(ParametrizationToolQuery(tool="find_symbols",
                arguments={"file_path": primary, "limit": 15},
                reason="Locate the declarations relevant to the variation capability."))
        for related_path in candidate.initial_locations[1:4]:
            if related_path == primary:
                continue
            queries.append(ParametrizationToolQuery(tool="get_source_excerpt",
                arguments={"path": related_path, "start_line": 1, "end_line": 60},
                reason="Inspect a supplied implementation or selection site for the capability."))
        return [query for query in queries if query.tool in self.config.tools]

    def _normalize_query(self, query, candidate):
        if query.tool not in self.config.tools:
            raise _invalid("disabled_tool")
        try:
            args = TOOL_SCHEMAS[query.tool].model_validate(query.arguments).model_dump()
        except Exception as error:
            invalid = getattr(error, "errors", lambda **_kwargs: [])()
            required = sorted({item["loc"][0] for item in invalid if item.get("type") == "missing"})
            hint = ", ".join(required) or "the documented fields of this tool"
            raise PydanticCustomError("tool_arguments_invalid",
                f"Tool {query.tool!r} requires argument(s): {hint}.") from error
        allowed = set(self._scope_paths(candidate))
        if query.tool == "get_source_excerpt" and args["path"] not in allowed and not query.scope_expansion.strip():
            raise _invalid("scope_expansion_reason_required")
        if query.tool == "find_symbols" and args.get("file_path") and args["file_path"] not in allowed and not query.scope_expansion.strip():
            raise _invalid("scope_expansion_reason_required")
        if query.tool == "get_source_excerpt":
            start = args["start_line"]
            args["end_line"] = min(args["end_line"] or start + 59, start + 59)
            for file in self.tools.accessible_snapshot.files:
                if file.path == args["path"] and file.line_count:
                    args["end_line"] = min(args["end_line"], file.line_count)
                    break
        return args, json.dumps([query.tool, args], sort_keys=True)

    def _delivered_ids(self, state):
        return {record["id"] for key in state["active_query_keys"]
                for record in state["query_cache"][key].get("evidence", [])}

    def _examined_relationships(self, state):
        indexed = {item.id: item for item in self.tools.accessible_snapshot.relationships}
        result = {}
        for key in state["active_query_keys"]:
            view = state["query_cache"][key]
            if view["tool_name"] != "list_relationships" or view["status"] != "ok":
                continue
            for row in view.get("data", {}).get("items", []):
                item = indexed.get(row.get("id"))
                if item and (row.get("source_id"), row.get("target_id")) == (item.source_id, item.target_id):
                    result[item.id] = item
        return result

    def _documentary_context(self, state):
        task = self._current(state)
        plan = state["plan"]
        try:
            cap = min(self.config.max_context_characters,
                2 * self.tools.context.input.budget.max_input_tokens_per_call) // 4
        except AttributeError:
            cap = getattr(self.config, "max_context_characters", 100_000) // 4
        context = getattr(getattr(self, "request", None), "documented_architecture", None)
        try:
            delivered = documentary_context(task, plan, self.tools.accessible_snapshot, context, cap)
        except AttributeError:
            delivered = {"document_claim_ids": list(task.document_claim_ids),
                "claims": {},
                "unavailable_claims": dict.fromkeys(task.document_claim_ids,
                    "Documentary context unavailable: snapshot repository or commit is missing."),
                "scope_notice": "Local portions only. Planned associations and mappings are provisional; no whole-claim conformance is established."}
        delivered["variation_mechanism"] = task.variation_mechanism
        delivered["variation_basis"] = task.variation_basis
        delivered["documented_capability"] = task.documented_capability
        delivered["alternatives"] = list(task.alternatives)
        return delivered

    def _investigation_context(self, state):
        task = self._current(state)
        owners = {item.id: item.file_id for item in self.tools.accessible_snapshot.symbols}
        paths = {item.id: item.path for item in self.tools.accessible_snapshot.files}
        related = [path for path in self._scope_paths(task) if path != task.primary_component]
        results_all = []
        query_history = []
        for key in state["active_query_keys"]:
            view = state["query_cache"][key]
            tool = view["tool_name"]
            data = view.get("data", {})
            if tool == "get_source_excerpt" and isinstance(data, dict):
                data = {field: data[field] for field in ("path", "start_line", "end_line", "content", "truncated",
                    "requested_end_line") if field in data}
            elif tool == "list_relationships" and isinstance(data, dict):
                rows = []
                for row in data.get("items", []):
                    if row.get("id") not in self._examined_relationships(state):
                        continue
                    rows.append({"id": row.get("id"), "kind": row.get("kind"),
                        "source_path": paths.get(owners.get(row.get("source_id"), row.get("source_id"))),
                        "target_path": paths.get(owners.get(row.get("target_id"), row.get("target_id")))})
                data = {"items": rows, "total": data.get("total"), "next_offset": data.get("next_offset")}
            results_all.append({"tool_name": tool, "status": view["status"],
                **({"data": data} if view["status"] == "ok" else {"error": view["error"]})})
            try:
                args = json.loads(key)
            except (TypeError, ValueError):
                args = []
            query_history.append({"t": tool, "a": args[1] if len(args) > 1 else {},
                "s": view["status"],
                "e": [record["id"] for record in view.get("evidence", [])]})
        recent = results_all[-2:] if results_all else []
        references = [record for record in self.references() if record.id in self._delivered_ids(state)]
        inspected = {record.path for record in references if record.kind == "source"}
        recent_keys = state["active_query_keys"][-2:]
        recent_ids = {record["id"] for key in recent_keys
            for record in state["query_cache"].get(key, {}).get("evidence", [])}
        recoverable = [{"id": record.id, "path": record.path, "start_line": record.start_line,
            "end_line": record.end_line, "tool": "get_source_excerpt",
            "arguments": {"path": record.path, "start_line": record.start_line, "end_line": record.end_line}}
            for record in references if record.kind == "source" and record.id not in recent_ids][:20]
        criteria = [
            ({"id": criterion.get("id"), "description": criterion.get("description")}
             if isinstance(criterion, dict) else
             {"id": getattr(criterion, "id", ""), "description": getattr(criterion, "description", "")})
            for criterion in state["criteria"]
        ]
        context = {"investigation": {"id": task.id,
                "primary_component": task.primary_component,
                "symbol_id": getattr(task, "symbol_id", ""),
                "symbol_name": getattr(task, "symbol_name", None),
                "variation_mechanism": task.variation_mechanism,
                "alternatives": list(task.alternatives),
                "question": task.question,
                "documented_capability": task.documented_capability,
                "variation_basis": task.variation_basis,
                "evidence_needed": task.evidence_needed,
                "evidence_requirements": [[index, requirement]
                    for index, requirement in enumerate(task.evidence_needed)],
                "document_claim_ids": task.document_claim_ids},
            "criteria": criteria, "commit": state["commit"],
            "related_locations": related,
            "inspected_locations": sorted(inspected & set(related)),
            "uninspected_related_locations": [path for path in related if path not in inspected],
            "tools": {key: value for key, value in tool_signatures().items() if key in self.config.tools},
            "tool_results": recent,
            "query_history": query_history,
            "evidence": [[record.id, record.path, record.kind, record.start_line, record.end_line,
                record.symbol_ids] if record.kind == "source" else [record.id, record.path, record.kind]
                for record in references],
            "recoverable_evidence": recoverable,
            "coverage_gap": self._coverage_gap(state, task, references),
            "documentary_context": self._documentary_context(state),
            "limitations": state["task_limitations"]}
        tool_results_bytes = len(json.dumps(recent, ensure_ascii=False, default=str))
        source_results_bytes = len(json.dumps([item for item in recent
            if item["tool_name"] == "get_source_excerpt"], ensure_ascii=False, default=str))
        print(
            f"[DEBUG_INVESTIGATE_CONTEXT] investigation_index={state['current_investigation'] + 1} "
            f"human_context_bytes={len(json.dumps(context, ensure_ascii=False, default=str))} "
            f"tool_results_bytes={tool_results_bytes} source_results_bytes={source_results_bytes} "
            f"evidence_count={len(references)} query_history_count={len(query_history)} "
            f"documentary_context_bytes={len(json.dumps(context['documentary_context'], ensure_ascii=False, default=str))}",
            file=sys.stderr,
        )
        return context

    def _coverage_gap(self, state, task, references):
        source = [record for record in references if record.kind == "source"]
        if not source:
            return ["No source evidence delivered for the capability owner."]
        gaps = []
        primary_file, spans = self._contract_spans(task)
        delivered_primary = [record for record in source
            if primary_file is not None and record.file_id == primary_file.id]
        if spans:
            covered = any(record.start_line is not None and record.end_line is not None
                and span[0] <= record.end_line and record.start_line <= span[1]
                for span in spans for record in delivered_primary)
            if not covered:
                gaps.append(f"No delivered source covers the {task.variation_mechanism} frontier in {task.primary_component}.")
        elif not delivered_primary:
            gaps.append(f"No source delivered for {task.primary_component}.")
        related = [path for path in self._scope_paths(task) if path != task.primary_component]
        if related and not any(record.path in related for record in source):
            gaps.append(f"No source delivered for the related implementation or selection site(s): {', '.join(related)}.")
        if not self._examined_relationships(state):
            gaps.append("No indexed relationships of the capability owner examined.")
        return gaps

    def _record_error(self, errors, code, field, index=None, message=None):
        entry = {"code": code, "field": field,
            "message": message or ParametrizationInvestigationTurn.validation_feedback.get(code, code)}
        if index is not None:
            entry["index"] = index
        errors.append(entry)

    def _raise_errors(self, errors):
        self._last_validation_errors = list(errors)
        codes = sorted({item["code"] for item in errors})
        code = codes[0] if len(codes) == 1 else "investigation_validation"
        raise PydanticCustomError(code, ParametrizationInvestigationTurn.validation_feedback.get(
            code, "Correct the listed investigation fields."))

    def _validate_turn(self, turn, state):
        task = self._current(state)
        self._last_validation_errors = []
        errors = self._last_validation_errors
        if turn.action == "tools":
            if turn.conclusion is not None:
                self._record_error(errors, "tools_requires_queries_without_conclusion", "conclusion")
            if not turn.queries:
                self._record_error(errors, "tools_requires_queries_without_conclusion", "queries")
            accepted, rejected = [], []
            for index, query in enumerate(turn.queries):
                try:
                    self._normalize_query(query, task)
                except PydanticCustomError as error:
                    rejected.append((index, error.type, query.tool))
                else:
                    accepted.append(query)
            if rejected:
                self.issues.append("Query scope/tool validation discarded invalid query (" + ", ".join(
                    f"{index}:{tool}: {code}" for index, code, tool in rejected[:4]) + "); kept " + str(len(accepted)) + " valid query(s).")
            if not accepted:
                for index, code, _tool in rejected:
                    self._record_error(errors, code, "queries", index)
                if rejected:
                    self._record_error(errors, "invalid_queries_only", "queries")
                self._raise_errors(errors)
            if errors:
                self._raise_errors(errors)
            return turn.model_copy(update={"queries": accepted})
        result = turn.conclusion
        if turn.queries:
            self._record_error(errors, "close_requires_current_investigation_conclusion", "queries")
        if result is None:
            self._record_error(errors, "close_requires_current_investigation_conclusion", "conclusion")
            self._raise_errors(errors)
        if result.investigation_id != task.id:
            self._record_error(errors, "close_requires_current_investigation_conclusion", "conclusion.investigation_id")
        if (result.status == "finding_candidate") != bool(result.candidates):
            self._record_error(errors, "candidate_status_mismatch", "conclusion.candidates")
        if result.status == "inconclusive" and not result.limitations:
            self._record_error(errors, "inconclusive_requires_limitations", "conclusion.limitations")
        if result.status == "no_finding" and task.primary_component not in result.components:
            self._record_error(errors, "conclusion_requires_inspected_primary_component", "conclusion.components")
        references = {record.id: record for record in self.references() if record.id in self._delivered_ids(state)}
        if result.status != "inconclusive":
            gaps = self._coverage_gap(state, task, list(references.values()))
            if gaps:
                self._record_error(errors, "coverage_incomplete", "conclusion",
                    message="Insufficient evidence for the question: " + "; ".join(gaps)
                    + ". Inspect the missing evidence or close inconclusive.")
        if set(result.evidence_ids) - references.keys():
            self._record_error(errors, "unknown_or_undelivered_evidence", "conclusion.evidence_ids")
        snapshot = self.tools.accessible_snapshot
        symbols = {symbol.id: symbol for symbol in snapshot.symbols}
        examined = set(self._examined_relationships(state))
        for subject_index, subject in enumerate([result, *result.candidates]):
            field = "conclusion" if subject_index == 0 else f"conclusion.candidates[{subject_index - 1}]"
            if set(subject.relationship_ids) - examined:
                self._record_error(errors, "unexamined_relationship", field + ".relationship_ids", subject_index)
            if set(subject.evidence_ids) - set(result.evidence_ids):
                self._record_error(errors, "candidate_evidence_not_in_conclusion", field + ".evidence_ids", subject_index)
            cited = [references[key] for key in subject.evidence_ids if key in references]
            if result.status != "inconclusive":
                if not any(record.kind == "source" for record in cited) or not subject.components:
                    self._record_error(errors, "conclusion_requires_inspected_source_and_components", field + ".components", subject_index)
                _evidence, issues = self.evidence_issues(list(subject.evidence_ids), references)
                if issues:
                    self._record_error(errors, "unverified_source_provenance", field + ".evidence_ids", subject_index)
            inspected = {record.path for record in cited if record.kind == "source"}
            uninspected = sorted(set(subject.components) - inspected)
            if uninspected:
                self._record_error(errors, "uninspected_component", field + ".components", subject_index,
                    message=f"Components cited but not inspected: {', '.join(uninspected)}. "
                    "get_source_excerpt them or remove them from components.")
            for symbol_index, identifier in enumerate(subject.symbol_ids):
                symbol = symbols.get(identifier)
                if symbol is None or not any(record.kind == "source" and record.file_id == symbol.file_id
                        and record.start_line is not None and record.start_line <= symbol.end_line
                        and record.end_line is not None and record.end_line >= symbol.start_line
                        for record in cited):
                    self._record_error(errors, "uninspected_symbol", field + ".symbol_ids", symbol_index)
        self._validate_evidence_requirements(result, task, references, errors)
        self._validate_claims(result, task, references, errors)
        if result.status == "finding_candidate":
            self._validate_finding_scope(result, task, references, errors)
        self._validate_selection(result, references, errors)
        if errors:
            self._raise_errors(errors)
        return turn

    def _validate_finding_scope(self, result, task, references, errors):
        for index, candidate in enumerate(result.candidates):
            field = f"conclusion.candidates[{index}]"
            inspected = {references[identifier].path for identifier in candidate.evidence_ids
                if identifier in references and references[identifier].kind == "source"}
            primary_inspected = (task.primary_component in inspected
                and task.primary_component in candidate.components)
            variation_inspected = bool((set(candidate.implementations) | set(candidate.consumers)) & inspected)
            if not (primary_inspected or variation_inspected):
                self._record_error(errors, "finding_requires_variation_scope", field + ".components", index)
            uninspected_scope = sorted((set(candidate.implementations) | set(candidate.consumers)) - inspected)
            if uninspected_scope:
                self._record_error(errors, "uninspected_variation_scope", field + ".implementations", index,
                    message="Implementations/consumers not delivered as inspected source: "
                    + ", ".join(uninspected_scope) + ". Inspect them or remove them from the finding.")
            if not candidate.selected_alternatives:
                self._record_error(errors, "finding_requires_variation_scope", field + ".selected_alternatives", index)

    def structured_correction_context(self, node, state):
        if node == "investigate" and getattr(self, "_last_validation_errors", None):
            return {"validation_errors": self._last_validation_errors,
                "instruction": "Correct only the rejected fields/indices; preserve valid evidence IDs and unchanged fields."}
        return super().structured_correction_context(node, state)


    def _validate_selection(self, result, references, errors):
        if result.status == "inconclusive":
            return
        if result.selection_phase == "unknown" or not result.selection_sites:
            self._record_error(errors, "selection_phase_unresolved", "conclusion.selection_phase")
        source_paths = {record.path for record in references.values() if record.kind == "source"}
        uninspected = sorted(set(result.selection_sites) - source_paths)
        if uninspected or set(result.selection_sites) - set(result.components):
            self._record_error(errors, "selection_phase_uninspected", "conclusion.selection_sites")
        if result.status == "finding_candidate" and result.consumer_impact == "not_verified":
            self._record_error(errors, "consumer_impact_unresolved", "conclusion.consumer_impact")

    def _validate_evidence_requirements(self, result, task, references, errors):
        assessments = result.evidence_assessments
        indices = [item.requirement_index for item in assessments]
        required = set(range(len(task.evidence_needed)))
        if len(indices) != len(set(indices)) or set(indices) - required:
            self._record_error(errors, "evidence_requirements_unresolved", "conclusion.evidence_assessments")
        if result.status != "inconclusive" and (
            set(indices) != required or any(item.status == "inconclusive" for item in assessments)
        ):
            self._record_error(errors, "evidence_requirements_unresolved", "conclusion.evidence_assessments")
        for index, assessment in enumerate(assessments):
            field = f"conclusion.evidence_assessments[{index}]"
            if set(assessment.evidence_ids) - references.keys():
                self._record_error(errors, "unknown_or_undelivered_evidence", field + ".evidence_ids", index)
            if assessment.status == "inconclusive":
                continue
            source = [references[key] for key in assessment.evidence_ids
                if key in references and references[key].kind == "source"]
            scope_valid = bool(assessment.scope_paths) and not (
                set(assessment.scope_paths) - {record.path for record in source})
            if assessment.status == "resolved":
                if not source or not scope_valid:
                    self._record_error(errors, "evidence_requirement_source_required", field, index)
                continue
            if not _concrete_rationale(assessment.rationale):
                self._record_error(errors, "evidence_requirement_explanation_required", field + ".rationale", index)
            if assessment.exclusion_basis is None:
                self._record_error(errors, "evidence_requirement_exclusion_basis_required", field + ".exclusion_basis", index)
                continue
            if (assessment.exclusion_basis == "code_verified" or assessment.evidence_ids
                    or assessment.scope_paths) and (not source or not scope_valid):
                self._record_error(errors, "evidence_requirement_source_required", field, index)
            requirement = (task.evidence_needed[assessment.requirement_index]
                if assessment.requirement_index < len(task.evidence_needed) else "")
            if assessment.exclusion_basis == "not_code_dependent" and _requirement_requires_code(requirement):
                self._record_error(errors, "evidence_requirement_not_applicable_unjustified", field, index)

    def _validate_claims(self, result, task, references, errors):
        seen = set()
        for index, assessment in enumerate(result.claim_assessments):
            field = f"conclusion.claim_assessments[{index}]"
            key = assessment.claim_id
            if key not in task.document_claim_ids or key in seen:
                self._record_error(errors, "invalid_document_claim_assessment", field + ".claim_id", index)
            seen.add(key)
            if result.status == "no_finding" and assessment.status == "inconclusive":
                self._record_error(errors, "documentary_claims_unresolved", field, index)
            if result.status == "no_finding" and assessment.status == "contradicted":
                self._record_error(errors, "no_finding_with_contradiction", field, index)
            if set(assessment.code_evidence_ids) - references.keys():
                self._record_error(errors, "unknown_or_undelivered_evidence", field + ".code_evidence_ids", index)
            if set(assessment.code_evidence_ids) - set(result.evidence_ids):
                self._record_error(errors, "claim_evidence_not_in_conclusion", field + ".code_evidence_ids", index)
            cited = [references[identifier] for identifier in assessment.code_evidence_ids if identifier in references]
            if assessment.status in {"supported", "contradicted"} or (
                assessment.status == "not_applicable" and assessment.code_evidence_ids
            ):
                if not any(record.kind == "source" for record in cited) or not assessment.scope_paths:
                    self._record_error(errors, "claim_assessment_requires_source", field, index)
                inspected_paths = {record.path for record in cited if record.kind == "source"}
                missing_scope = sorted(set(assessment.scope_paths) - inspected_paths)
                if missing_scope:
                    self._record_error(errors, "claim_assessment_requires_uninspected_source", field + ".scope_paths", index)
        for index, candidate in enumerate(result.candidates):
            field = f"conclusion.candidates[{index}]"
            if any(key not in seen for key in candidate.document_claim_ids):
                self._record_error(errors, "candidate_document_claim_unassessed", field + ".document_claim_ids", index)
            if candidate.document_claim_ids and not candidate.evidence_ids:
                self._record_error(errors, "candidate_document_claim_mismatch", field + ".evidence_ids", index)
        if result.status == "no_finding" and task.document_claim_ids and seen != set(task.document_claim_ids):
            self._record_error(errors, "documentary_no_finding_requires_resolution", "conclusion.claim_assessments")

    def _investigation_diagnostics(self, diagnostics, termination_reason):
        updated = dict(diagnostics)
        updated["executed_plan_stages"] = list(dict.fromkeys([
            *updated.get("executed_plan_stages", []),
            "investigate",
        ]))
        updated["investigate"] = {
            "termination_reason": termination_reason,
            "status": "completed",
            "source_inspection": "bounded delivered repository evidence only",
        }
        updated["planning"] = (
            "deterministic menu, model selection; bounded reusability investigation; "
            "no synthesis, finalization or findings are produced"
        )
        return updated

    def _close_investigation(self, state, conclusion):
        task = self._current(state)
        documentary = self._documentary_context(state)
        conclusion = conclusion.model_copy(update={"document_claim_delivery": {
            key: "unavailable" if key in documentary["unavailable_claims"] else
                "delivered" if key in documentary["claims"] else "not_delivered"
            for key in task.document_claim_ids}})
        conclusion = conclusion.model_copy(update={"claim_assessments": pending_assessments(
            task, conclusion.claim_assessments, documentary["unavailable_claims"])})
        conclusion = conclusion.model_copy(update={"limitations": list(dict.fromkeys([*conclusion.limitations,
            *(f"Document claim {key}: {reason}" for key, reason in documentary["unavailable_claims"].items())]))[:40]})
        results = [*state["investigation_results"], conclusion]
        status_map = {"finding_candidate": "confirmed", "no_finding": "discarded", "inconclusive": "inconclusive"}
        hypotheses = []
        for hypothesis in state["hypotheses"]:
            if hypothesis.id == conclusion.investigation_id:
                hypotheses.append(hypothesis.model_copy(update={
                    "status": status_map.get(conclusion.status, "inconclusive"),
                    "evidence_ids": list(conclusion.evidence_ids),
                    "rationale": conclusion.justification or conclusion.summary}))
            else:
                hypotheses.append(hypothesis)
        index = state["current_investigation"] + 1
        done = index >= len(state["plan"].candidates)
        ledger, _mismatch = self.verify_references(self.references())
        reason = self.stop or ("investigations_completed" if done else "investigating")
        limitations = list(dict.fromkeys([*state["limitations"], *conclusion.limitations, *self.issues]))
        result = state["result"].model_copy(update={"investigation_results": results,
            "hypotheses": hypotheses, "termination_reason": reason, "limitations": limitations,
            "evidence": ledger, "model_calls": self.calls, "tool_calls": self.tools.budget_usage.tool_calls,
            "accounted_tokens": self.tokens, "estimated_tokens": self.estimates,
            "iterations": state["iterations"] + 1,
            "planning_diagnostics": self._investigation_diagnostics(
                state["result"].planning_diagnostics, reason),
            "status": "investigation_completed"})
        return {"current_investigation": index, "investigation_results": results,
            "hypotheses": hypotheses,
            "pending_queries": [], "active_query_keys": [], "task_limitations": [],
            "initial_evidence_loaded": False, "coverage_recovery_done": False, "result": result,
            "evidence": ledger,
            "limitations": limitations, "model_calls": self.calls,
            "tool_calls": self.tools.budget_usage.tool_calls,
            "iterations": state["iterations"] + 1, "termination_reason": reason}

    def _coverage_recovery_queries(self, state, delivered):
        if "get_source_excerpt" not in self.config.tools:
            return []
        task = self._current(state)
        queries = []
        source = [record for record in delivered if record.kind == "source"]
        inspected_paths = {record.path for record in source}
        target, _spans = self._contract_spans(task)
        delivered_primary = [record for record in source if record.file_id == (target.id if target else None)]
        covered_end = max((record.end_line or 0) for record in delivered_primary) if delivered_primary else 0
        if target and target.line_count and covered_end < target.line_count:
            queries.append(ParametrizationToolQuery(tool="get_source_excerpt",
                arguments={"path": task.primary_component, "start_line": covered_end + 1,
                    "end_line": min(target.line_count, covered_end + 40)},
                reason="Cover the declaring frontier after the delivered portion."))
        uninspected = next((path for path in task.initial_locations[1:] if path not in inspected_paths), None)
        if uninspected:
            queries.append(ParametrizationToolQuery(tool="get_source_excerpt",
                arguments={"path": uninspected, "start_line": 1, "end_line": 60},
                reason="Inspect a capability selection site before concluding."))
        return queries

    def _resolve_evidence_query(self, tool, arguments):
        """Model-facing get_evidence re-reads delivered source instead of snapshot metadata."""
        if tool != "get_evidence" or "get_source_excerpt" not in self.config.tools:
            return tool, arguments
        evidence_id = arguments.get("evidence_id")
        record = next((item for item in self.tools.retrieved_evidence if item.id == evidence_id), None)
        if record is None or record.kind != "source" or not record.start_line or not record.end_line:
            return tool, arguments
        source = next((item for item in self.tools.accessible_snapshot.files if item.id == record.file_id), None)
        if source is None:
            return tool, arguments
        return "get_source_excerpt", {"path": source.path, "start_line": record.start_line,
            "end_line": record.end_line}

    async def investigate(self, state):
        tasks = state["plan"].candidates
        if state["current_investigation"] >= len(tasks):
            reason = self.stop or "investigations_completed"
            return {"result": state["result"].model_copy(update={
                "termination_reason": reason,
                "planning_diagnostics": self._investigation_diagnostics(
                    state["result"].planning_diagnostics, reason),
                "status": "investigation_completed",
            })}
        state = dict(state)
        if not state["initial_evidence_loaded"]:
            candidate = self._current(state)
            queries = self._initial_queries(candidate)
            cached_keys = []
            all_cached = bool(queries)
            for query in queries:
                _arguments, key = self._normalize_query(query, candidate)
                cached = state["query_cache"].get(key, {})
                if cached.get("status") != "ok":
                    all_cached = False
                    break
                cached_keys.append(key)
            if all_cached and cached_keys:
                return {"pending_queries": [],
                    "active_query_keys": cached_keys,
                    "initial_evidence_loaded": True,
                    "model_calls": self.calls}
            if queries:
                return {"pending_queries": queries, "initial_evidence_loaded": True,
                    "model_calls": self.calls}
            state["initial_evidence_loaded"] = True
        turn = None
        deferred_count = len(self.deferred_stages)
        if not self.stop:
            turn = await self.call("investigate", state, ParametrizationInvestigationTurn)
        if turn and turn.action == "tools":
            return {"pending_queries": turn.queries, "model_calls": self.calls}
        if turn and turn.conclusion is not None:
            return self._close_investigation(state, turn.conclusion)
        delivered = sorted((record for record in self.references() if record.id in self._delivered_ids(state)),
            key=lambda record: record.kind != "source")[:80]
        gaps = self._coverage_gap(state, self._current(state), delivered)
        if gaps and not state.get("coverage_recovery_done") and self.remaining_seconds() > 0:
            queries = self._coverage_recovery_queries(state, delivered)
            if queries:
                return {"pending_queries": queries, "coverage_recovery_done": True,
                    "initial_evidence_loaded": True,
                    "task_limitations": [*state["task_limitations"],
                        f"Coverage recovery requested: {', '.join(gaps[:2])}"],
                    "model_calls": self.calls}
        if self.stop == "model_or_schema_error" and len(self.deferred_stages) == deferred_count:
            self.stop = ""
        delivered = sorted((record for record in self.references() if record.id in self._delivered_ids(state)),
            key=lambda record: record.kind != "source")[:80]
        gaps = self._coverage_gap(state, self._current(state), delivered)
        conclusion = ParametrizationInvestigationResult(
            investigation_id=self._current(state).id, status="inconclusive",
            summary="Investigation could not reach a supported conclusion.",
            justification=f"Execution stopped for this task: {self.stop or 'invalid_investigation_response'}.",
            components=list(dict.fromkeys(record.path for record in delivered))[:40],
            symbol_ids=list(dict.fromkeys(symbol for record in delivered if record.kind == "source"
                for symbol in record.symbol_ids))[:80],
            relationship_ids=list(dict.fromkeys(self._examined_relationships(state)))[:80],
            evidence_ids=[record.id for record in delivered],
            limitations=[self.stop or "invalid_investigation_response", *state["task_limitations"], *gaps])
        return self._close_investigation(state, conclusion)

    async def execute_investigation_tools(self, state):
        task = self._current(state)
        cache, keys = dict(state["query_cache"]), list(state["active_query_keys"])
        limitations = list(state["task_limitations"])
        failures = getattr(self, "_tool_failures", None)
        if failures is None:
            failures = self._tool_failures = {}
        for query in state["pending_queries"]:
            args, key = self._normalize_query(query, task)
            tool, tool_args = self._resolve_evidence_query(query.tool, args)
            if failures.get(key, 0) >= 2:
                limitations.append("Tool query failed: retries_exhausted")
                continue
            cached = key in cache and cache[key].get("status") != "error"
            if cached:
                if key in keys:
                    keys.remove(key)
                keys.append(key)
                continue
            cache.pop(key, None)
            if self.remaining_seconds() <= 0:
                limitations.append("investigation_time_limit")
                break
            if len(self.references()) >= 400:
                limitations.append("evidence_ledger_limit")
                continue
            call_id = "reuse-parametrization-investigate-" + uuid4().hex
            try:
                response = self.tools.execute(tool, tool_args, tool_call_id=call_id)
            except Exception as error:  # noqa: BLE001 - tool boundary
                view = {"status": "error", "tool_name": tool, "tool_call_id": call_id,
                    "error": {"code": "tool_execution_error", "message": safe_diagnostic(error)},
                    "evidence": []}
            else:
                view = self.tools.model_view(response) | {"tool_call_id": response.tool_call_id,
                    "snapshot_hash": response.snapshot_hash}
            if view["status"] != "error":
                cache[key] = view
                keys.append(key)
            else:
                failures[key] = failures.get(key, 0) + 1
                limitations.append("Tool query failed: " + view["error"]["code"])
        return {"query_cache": cache, "active_query_keys": keys, "pending_queries": [],
            "task_limitations": list(dict.fromkeys(limitations)),
            "tool_calls": self.tools.budget_usage.tool_calls, "evidence": self.references()}
