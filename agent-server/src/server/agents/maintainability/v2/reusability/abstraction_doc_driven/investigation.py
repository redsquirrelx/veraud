"""Iterative abstraction investigation (investigate/tools loop).

Separated from execution.py so plan selection stays independent. The graph
shape is unchanged: investigate <-> tools until each investigation closes.
Source-less metadata never closes an investigation; source is required.
"""

import json
import re
from uuid import uuid4

from pydantic import ValidationError
from pydantic_core import PydanticCustomError

from server.runtimes.investigation.structured import safe_diagnostic
from server.runtimes.repository.tools import TOOL_SCHEMAS, tool_signatures

from .documentary import documentary_context, pending_assessments
from .schemas import (
    AbstractionInvestigationResult,
    AbstractionInvestigationTurn,
    AbstractionToolQuery,
)


def _invalid(code):
    feedback = AbstractionInvestigationTurn.validation_feedback.get(code, code)
    return PydanticCustomError(code, feedback)


def _normalized_identifier(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


SUBSTITUTION_STEMS = ("substitut", "interchange", "drop-in", "drop.in", "drop_in", "swap",
    "portab", "intercambi")
GUARANTEE_STEMS = ("substitut", "encapsul", "extensib", "reus", "independ",
    "interchange", "drop-in", "substitu", "encapsulation", "extensibil", "reuse", "independent")


class AbstractionInvestigation:
    def route_investigation(self, state):
        if state["pending_queries"]:
            return "tools"
        return "investigate" if state["current_investigation"] < len(state["plan"].candidates) else "synthesis"

    def _current(self, state):
        return state["plan"].candidates[state["current_investigation"]]

    def _contract_spans(self, task):
        snapshot = self.tools.accessible_snapshot
        primary_file = next((item for item in snapshot.files if item.path == task.primary_component), None)
        identifiers = {_normalized_identifier(task.abstraction_name)} - {""}
        spans = [(symbol.start_line, symbol.end_line) for symbol in snapshot.symbols
            if primary_file and symbol.file_id == primary_file.id
            and ({_normalized_identifier(symbol.name), _normalized_identifier(symbol.qualified_name)}
                 & identifiers)]
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
        queries = [AbstractionToolQuery(tool="get_source_excerpt",
            arguments={"path": primary, "start_line": start, "end_line": end},
            reason="Inspect the contract declaration of the abstraction and its boundary.")]
        if file_id:
            queries.append(AbstractionToolQuery(tool="list_relationships",
                arguments={"source_id": file_id, "limit": 10},
                reason="Examine the indexed relationships of the primary component."))
            queries.append(AbstractionToolQuery(tool="find_symbols",
                arguments={"file_path": primary, "limit": 15},
                reason="Locate declarations inside the primary component."))
        related = list(candidate.related_components)[:3]
        for related_path in related:
            if related_path == primary:
                continue
            queries.append(AbstractionToolQuery(tool="get_source_excerpt",
                arguments={"path": related_path, "start_line": 1, "end_line": 60},
                reason="Inspect an indexed implementation or consumer of the abstraction."))
        return [query for query in queries if query.tool in self.config.tools]

    def _normalize_query(self, query, candidate):
        if query.tool not in self.config.tools:
            raise _invalid("disabled_tool")
        try:
            args = TOOL_SCHEMAS[query.tool].model_validate(query.arguments).model_dump()
        except ValidationError as error:
            required = sorted({item["loc"][0] for item in error.errors(include_context=False,
                include_url=False, include_input=False) if item["type"] == "missing"})
            hint = ", ".join(required) or "the documented fields of this tool"
            raise PydanticCustomError("tool_arguments_invalid", f"Tool {query.tool!r} requires argument(s): {hint}.")
        allowed = {candidate.primary_component, *candidate.related_components}
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

    @staticmethod
    def _has_stem(text, stems):
        lowered = (text or "").casefold()
        return any(stem in lowered for stem in stems)

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
        delivered["documented_purpose"] = task.documented_purpose
        delivered["purpose_basis"] = task.purpose_basis
        delivered["abstraction_name"] = task.abstraction_name
        delivered["related_components"] = task.related_components
        return delivered

    def _delivered_ranges(self, state):
        ranges = {}
        for view in state["query_cache"].values():
            if view["tool_name"] != "get_source_excerpt" or view["status"] != "ok":
                continue
            data = view.get("data", {})
            if not data.get("path"):
                continue
            start, end = data.get("start_line"), data.get("end_line")
            if start is not None and end is not None:
                ranges.setdefault(data["path"], []).append([int(start), int(end)])
        return {path: sorted(slices) for path, slices in ranges.items()}

    @staticmethod
    def _uncovered_lines(total, ranges):
        missing, covered_end = [], 0
        for start, end in sorted(ranges):
            if start > covered_end + 1:
                missing.append([covered_end + 1, start - 1])
            covered_end = max(covered_end, end or 0)
        if covered_end < int(total or 0):
            missing.append([covered_end + 1, int(total or 0)])
        return missing

    def _investigation_context(self, state):
        task = self._current(state)
        snapshot = self.tools.accessible_snapshot
        owners = {item.id: item.file_id for item in snapshot.symbols}
        paths = {item.id: item.path for item in snapshot.files}
        delivered_ranges = self._delivered_ranges(state)
        files_by_path = {item.path: item for item in snapshot.files}
        uninspected = {}
        for path, slices in delivered_ranges.items():
            target = files_by_path.get(path)
            if target and target.line_count:
                gaps = self._uncovered_lines(target.line_count, slices)
                if gaps:
                    uninspected[path] = gaps
        target = files_by_path.get(task.primary_component)
        if target and target.line_count:
            gaps = self._uncovered_lines(target.line_count, delivered_ranges.get(task.primary_component, []))
            if gaps:
                uninspected[task.primary_component] = gaps
        results_all = []
        inventory = []
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
                data = {"items": rows,
                    "total": data.get("total"), "next_offset": data.get("next_offset")}
            results_all.append({"tool_name": tool, "status": view["status"],
                **({"data": data} if view["status"] == "ok" else {"error": view["error"]})})
            try:
                args = json.loads(key)
            except (TypeError, ValueError):
                args = []
            inventory.append({"tool_name": tool, "arguments": args[1] if len(args) > 1 else {},
                "status": view["status"],
                "evidence_ids": [record["id"] for record in view.get("evidence", [])]})
        recent = results_all[-3:] if results_all else []
        reusable = [json.loads(key) for key in state["active_query_keys"][:-3]] if results_all else []
        references = [record for record in self.references() if record.id in self._delivered_ids(state)]
        inspected_paths = {record.path for record in references if record.kind == "source"}
        related = [path for path in task.related_components if path != task.primary_component]
        return {"investigation": {"id": task.id,
                "primary_component": task.primary_component,
                "abstraction_name": task.abstraction_name,
                "abstraction_kind": task.abstraction_kind,
                "related_components": task.related_components,
                "question": task.question,
                "documented_purpose": task.documented_purpose,
                "purpose_basis": task.purpose_basis,
                "evidence_needed": task.evidence_needed,
                "evidence_requirements": [{"requirement_index": index, "requirement": requirement}
                    for index, requirement in enumerate(task.evidence_needed)],
                "document_claim_ids": task.document_claim_ids},
            "criteria": state["criteria"], "commit": state["commit"],
            "snapshot_hash": self.tools.context.input.snapshot_hash,
            "implementations_and_consumers": {
                "related_components": related,
                "inspected": sorted(inspected_paths & set(related)),
                "uninspected": [path for path in related if path not in inspected_paths],
            },
            "delivered_ranges": delivered_ranges,
            "uninspected_primary_ranges": uninspected,
            "tools": {key: value for key, value in tool_signatures().items() if key in self.config.tools},
            "tool_results": recent,
            "query_inventory": inventory,
            "reusable_queries": reusable,
            "evidence": [{"id": record.id, "path": record.path, "kind": record.kind,
                "start_line": record.start_line, "end_line": record.end_line,
                "symbol_ids": record.symbol_ids} for record in references],
            "visible_symbol_ids": sorted({symbol for record in references for symbol in record.symbol_ids}),
            "coverage_gap": self._coverage_gap(state, task, references),
            "documentary_context": self._documentary_context(state),
            "limitations": state["task_limitations"]}

    def _coverage_gap(self, state, task, references):
        """Question-scoped sufficiency; whole-file coverage is never required."""
        source = [record for record in references if record.kind == "source"]
        if not source:
            return ["No source evidence delivered for the contract."]
        gaps = []
        primary_file, contract_spans = self._contract_spans(task)
        contract_delivered = False
        if contract_spans:
            contract_delivered = any(record.file_id == primary_file.id
                for pair in contract_spans
                for record in source
                if record.start_line is not None and record.end_line is not None
                and pair[0] <= record.end_line and record.start_line <= pair[1])
        elif primary_file is not None:
            contract_delivered = any(record.file_id == primary_file.id for record in source)
        if not contract_delivered:
            gaps.append(f"No delivered source covers the {task.abstraction_name} contract declaration in {task.primary_component}.")

        related = [path for path in task.related_components if path != task.primary_component]
        if related and not any(record.path in related for record in source):
            gaps.append(f"No source delivered for the related implementation or consumer files: {', '.join(related)}.")
        if not self._examined_relationships(state):
            gaps.append("No indexed relationships of the primary component examined.")
        return gaps

    def _validate_turn(self, turn, state):
        task = self._current(state)
        if turn.action == "tools":
            if not turn.queries or turn.conclusion is not None:
                raise _invalid("tools_requires_queries_without_conclusion")
            for query in turn.queries:
                self._normalize_query(query, task)
            return
        result = turn.conclusion
        if turn.queries or result is None or result.investigation_id != task.id:
            raise _invalid("close_requires_current_investigation_conclusion")
        if (result.status == "finding_candidate") != bool(result.candidates):
            raise _invalid("candidate_status_mismatch")
        if result.status == "inconclusive" and not result.limitations:
            raise _invalid("inconclusive_requires_limitations")
        if result.status == "no_finding" and task.primary_component not in result.components:
            raise _invalid("conclusion_requires_inspected_primary_component")
        references = {record.id: record for record in self.references() if record.id in self._delivered_ids(state)}
        if result.status != "inconclusive":
            gaps = self._coverage_gap(state, task, list(references.values()))
            if gaps:
                raise PydanticCustomError("coverage_incomplete",
                    "Insufficient evidence for the question: " + "; ".join(gaps)
                    + ". Inspect the missing evidence or close inconclusive.")
        if set(result.evidence_ids) - references.keys():
            raise _invalid("unknown_or_undelivered_evidence")
        snapshot = self.tools.accessible_snapshot
        symbols = {symbol.id: symbol for symbol in snapshot.symbols}
        examined = set(self._examined_relationships(state))
        for subject in [result, *result.candidates]:
            if set(subject.relationship_ids) - examined:
                raise _invalid("unexamined_relationship")
            if set(subject.evidence_ids) - set(result.evidence_ids):
                raise _invalid("candidate_evidence_not_in_conclusion")
            cited = [references[key] for key in subject.evidence_ids if key in references]
            if result.status != "inconclusive":
                if not any(record.kind == "source" for record in cited) or not subject.components:
                    raise _invalid("conclusion_requires_inspected_source_and_components")
                _evidence, issues = self.evidence_issues(subject.evidence_ids, references)
                if issues:
                    raise _invalid("unverified_source_provenance")
            inspected = {record.path for record in cited if record.kind == "source"}
            uninspected = sorted(set(subject.components) - inspected)
            if uninspected:
                raise PydanticCustomError("uninspected_component",
                    f"Components cited but not inspected: {', '.join(uninspected)}. "
                    "get_source_excerpt them or remove them from components.")
            for identifier in subject.symbol_ids:
                symbol = symbols.get(identifier)
                if symbol is None or not any(record.kind == "source" and record.file_id == symbol.file_id
                        and record.start_line is not None and record.start_line <= symbol.end_line
                        and record.end_line is not None and record.end_line >= symbol.start_line for record in cited):
                    raise _invalid("uninspected_symbol")
        self._validate_evidence_requirements(result, task, references)
        self._validate_claims(result, task, references)

    def _validate_evidence_requirements(self, result, task, references):
        assessments = result.evidence_assessments
        indices = [item.requirement_index for item in assessments]
        required = set(range(len(task.evidence_needed)))
        if len(indices) != len(set(indices)) or set(indices) - required:
            raise _invalid("evidence_requirements_unresolved")
        if result.status != "inconclusive" and (
            set(indices) != required or any(item.status == "inconclusive" for item in assessments)
        ):
            raise _invalid("evidence_requirements_unresolved")
        for assessment in assessments:
            if set(assessment.evidence_ids) - references.keys():
                raise _invalid("unknown_or_undelivered_evidence")
            if assessment.status == "inconclusive":
                continue
            source = [references[key] for key in assessment.evidence_ids
                if references[key].kind == "source"]
            if not source or not assessment.scope_paths or (
                set(assessment.scope_paths) - {record.path for record in source}
                or set(assessment.scope_paths) - set(result.components)
            ):
                raise _invalid("evidence_requirement_source_required")
            if self._has_stem(task.evidence_needed[assessment.requirement_index]
                    if 0 <= assessment.requirement_index < len(task.evidence_needed) else "",
                    SUBSTITUTION_STEMS):
                related = set(task.related_components or ())
                if not any(record.kind == "source" and record.path in related for record in source):
                    raise PydanticCustomError("substitution_assessment_requires_implementer_or_consumer_scope",
                        "Substitution-related evidence_assessments need source citations from an implementer or "
                        "consumer actually inspected, not the primary component alone.")
        if result.status == "no_finding" and self._has_stem(task.question, GUARANTEE_STEMS):
            related = set(task.related_components or ())
            reachable = any(any(path in related for path in assessment.scope_paths)
                for assessment in assessments if assessment.status == "resolved")
            if not reachable:
                raise PydanticCustomError("no_finding_guarantee_requires_reachable_scope",
                    "The question carries an architectural guarantee (substitution, encapsulation, extensibility, "
                    f"reuse or independence) and no resolved evidence assessment cites an implementer or consumer "
                    f"for the question {task.question!r}; reach it with tools or close inconclusive.")

    def _validate_claims(self, result, task, references):
        seen = set()
        for assessment in result.claim_assessments:
            key = assessment.claim_id
            if key not in task.document_claim_ids or key in seen:
                raise _invalid("invalid_document_claim_assessment")
            seen.add(key)
            if assessment.status == "not_applicable" and not assessment.rationale.strip():
                raise _invalid("claim_exclusion_requires_rationale")
            if result.status == "no_finding" and assessment.status == "inconclusive":
                raise _invalid("documentary_claims_unresolved")
            if result.status == "no_finding" and assessment.status == "contradicted":
                raise _invalid("no_finding_with_contradiction")
            if set(assessment.code_evidence_ids) - references.keys():
                raise _invalid("unknown_or_undelivered_evidence")
            if set(assessment.code_evidence_ids) - set(result.evidence_ids):
                raise _invalid("claim_evidence_not_in_conclusion")
            cited = [references[identifier] for identifier in assessment.code_evidence_ids if identifier in references]
            if assessment.status in {"supported", "contradicted"} or (
                assessment.status == "not_applicable" and assessment.code_evidence_ids
            ):
                if not any(record.kind == "source" for record in cited) or not assessment.scope_paths:
                    raise _invalid("claim_assessment_requires_source")
                abstraction_paths = {task.primary_component, *task.related_components}
                if not any(record.path in abstraction_paths for record in cited if record.kind == "source"):
                    raise _invalid("claim_evidence_not_specific")
                inspected_paths = {record.path for record in cited if record.kind == "source"}
                missing_scope = sorted(set(assessment.scope_paths) - inspected_paths)
                if missing_scope:
                    raise PydanticCustomError("claim_assessment_requires_uninspected_source",
                        "scope_paths not delivered as source in this investigation: "
                        f"{', '.join(missing_scope)}. "
                        "get_source_excerpt those paths with line ranges, or remove them from scope_paths.")
        for candidate in result.candidates:
            if any(key not in seen for key in candidate.document_claim_ids):
                raise _invalid("candidate_document_claim_unassessed")
            if candidate.document_claim_ids and not candidate.guarantees:
                raise _invalid("candidate_document_claim_mismatch")
        contradicted = {item.claim_id: item for item in result.claim_assessments if item.status == "contradicted"}
        favorable_resolution = bool(seen == set(task.document_claim_ids)) and all(
            item.status in {"supported", "not_applicable"} for item in result.claim_assessments)
        favorable_evidence = {evidence_id for item in result.claim_assessments
                              if item.status in {"supported", "not_applicable"}
                              for evidence_id in item.code_evidence_ids}
        if favorable_resolution:
            for candidate in result.candidates:
                if set(candidate.evidence_ids) & favorable_evidence and not set(candidate.document_claim_ids) & set(contradicted):
                    raise _invalid("candidate_document_claim_mismatch")
        linked = set()
        for candidate in result.candidates:
            if len(set(candidate.document_claim_ids)) != len(candidate.document_claim_ids):
                raise _invalid("candidate_document_claim_mismatch")
            for key in candidate.document_claim_ids:
                if key not in contradicted or set(contradicted[key].code_evidence_ids) - set(candidate.evidence_ids):
                    raise _invalid("candidate_document_claim_mismatch")
                linked.add(key)
        if result.status == "finding_candidate" and set(contradicted) - linked:
            raise _invalid("candidate_document_claim_mismatch")
        if result.status == "finding_candidate":
            for candidate in result.candidates:
                inspected = set(candidate.components)
                if not candidate.implementers and not candidate.consumers:
                    raise _invalid("finding_requires_implementer_or_consumer")
                if not set(candidate.implementers + candidate.consumers) & inspected:
                    raise _invalid("finding_requires_implementer_or_consumer")
        if result.status == "no_finding" and task.document_claim_ids and seen != set(task.document_claim_ids):
            raise _invalid("documentary_no_finding_requires_resolution")

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
            "deferred_stages": self.deferred_stages, "iterations": state["iterations"] + 1})
        return {"current_investigation": index, "investigation_results": results,
            "hypotheses": hypotheses,
            "pending_queries": [], "active_query_keys": [], "task_limitations": [],
            "initial_evidence_loaded": False, "result": result, "evidence": ledger,
            "limitations": limitations, "model_calls": self.calls,
            "tool_calls": self.tools.budget_usage.tool_calls,
            "iterations": state["iterations"] + 1, "termination_reason": reason}

    async def investigate(self, state):
        tasks = state["plan"].candidates
        if state["current_investigation"] >= len(tasks):
            return {"result": state["result"].model_copy(update={"termination_reason": self.stop or "investigations_completed"})}
        state = dict(state)
        if not state["initial_evidence_loaded"]:
            queries = self._initial_queries(self._current(state))
            if queries:
                return {"pending_queries": queries, "initial_evidence_loaded": True,
                    "model_calls": self.calls}
            state["initial_evidence_loaded"] = True
        turn = None
        deferred_count = len(self.deferred_stages)
        if not self.stop:
            turn = await self.call("investigate", state, AbstractionInvestigationTurn)
        if turn and turn.action == "tools":
            return {"pending_queries": turn.queries, "model_calls": self.calls}
        if turn and turn.conclusion is not None:
            return self._close_investigation(state, turn.conclusion)
        delivered = sorted((record for record in self.references() if record.id in self._delivered_ids(state)),
            key=lambda record: record.kind != "source")[:80]
        gaps = self._coverage_gap(state, self._current(state), delivered)
        if gaps and not state.get("coverage_recovery_done") and self.remaining_seconds() > 0:
            task = self._current(state)
            queries = []
            source = [record for record in delivered if record.kind == "source"]
            inspected_paths = {record.path for record in source}
            covered_end = max((record.end_line or 0) for record in source
                if record.path == task.primary_component) if source else 0
            target = next((item for item in self.tools.accessible_snapshot.files
                if item.path == task.primary_component), None)
            if target and target.line_count and covered_end < target.line_count and task.primary_component in self.config.tools:
                queries.append(AbstractionToolQuery(tool="get_source_excerpt",
                    arguments={"path": task.primary_component, "start_line": covered_end + 1,
                        "end_line": min(target.line_count, covered_end + 40)},
                    reason="Cover the remaining tail of the primary component."))
            uninspected = next((path for path in task.related_components
                if path not in inspected_paths and path in self.config.tools), None)
            if uninspected:
                queries.append(AbstractionToolQuery(tool="get_source_excerpt",
                    arguments={"path": uninspected, "start_line": 1, "end_line": 40},
                    reason="Inspect an unimplemented implementer/consumer required before concluding."))
            if queries:
                return {"pending_queries": queries, "coverage_recovery_done": True,
                    "initial_evidence_loaded": True, "task_limitations": [*state["task_limitations"],
                        f"Coverage recovery requested: {', '.join(gaps[:2])}"],
                    "model_calls": self.calls}
        if self.stop == "model_or_schema_error" and len(self.deferred_stages) == deferred_count:
            self.stop = ""
        delivered = sorted((record for record in self.references() if record.id in self._delivered_ids(state)),
            key=lambda record: record.kind != "source")[:80]
        gaps = self._coverage_gap(state, self._current(state), delivered)
        conclusion = AbstractionInvestigationResult(
            investigation_id=self._current(state).id, status="inconclusive",
            summary="Investigation could not reach a supported conclusion.",
            justification=f"Execution stopped for this task: {self.stop or 'invalid_investigation_response'}.",
            components=list(dict.fromkeys(record.path for record in delivered))[:40],
            symbol_ids=list(dict.fromkeys(symbol for record in delivered if record.kind == "source" for symbol in record.symbol_ids))[:80],
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
            call_id = "abstraction-investigate-" + uuid4().hex
            try:
                response = self.tools.execute(query.tool, args, tool_call_id=call_id)
            except Exception as error:  # noqa: BLE001 - tool boundary
                view = {"status": "error", "tool_name": query.tool, "tool_call_id": call_id,
                    "error": {"code": "tool_execution_error", "message": safe_diagnostic(error)}, "evidence": []}
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
