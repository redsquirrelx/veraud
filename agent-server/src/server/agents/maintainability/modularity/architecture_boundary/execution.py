"""Boundary-specific support requirements, distinct from citation/provenance validation."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from pydantic_core import PydanticCustomError

from server.agents.maintainability.modularity.architecture_boundary.schemas import (
    BoundaryEvaluation,
    BoundaryFinding,
    BoundaryFindingReview,
    BoundaryHypothesisReview,
    BoundaryResult,
    BoundaryReview,
)
from server.contracts.audit import CandidateFinding, Hypothesis, InvestigationPlan

from .....config.token_budget import (
    effective_token_budget_policy,
    token_budget_exceeded,
)
from .....runtimes.investigation.agent import InvestigationExecution
from .....runtimes.investigation.messages import compact_tool_history, empty_ai_message
from .....runtimes.investigation.provider import lean_schema
from .claims import assertion_issues
from .discovery import BoundaryDiscovery
from .support import dependency_span, supports_role

# A subject with no delivered source must be read or stay unresolved; a check cannot stand in for evidence.
# Any admissible role is acceptable for a navigation hint; it is never evidence on its own.
NAVIGATION_ROLES = ("declaration", "implementation", "usage", "composition", "dependency")

# Evidence each claim kind requires. Isolation and absence-of-cycles additionally
# require complete coverage across at least two inspected endpoints. Ordered from the
# weakest evidentiary bar to the strongest, so guidance can name the nearest option.
CLAIM_REQUIREMENTS = {
    "declaration": frozenset({"declaration"}),
    "behavior": frozenset({"implementation"}),
    "dependency": frozenset({"dependency"}),
    "isolation": frozenset({"implementation", "usage", "composition"}),
    "absence_of_cycles": frozenset({"dependency"}),
    "deployment": frozenset({"declaration", "implementation", "usage", "composition"}),
}
CLAIM_KINDS = tuple(CLAIM_REQUIREMENTS)
COVERAGE_DEMANDING = frozenset({"isolation", "absence_of_cycles", "deployment"})

UNSUPPORTED_SUBJECT = [
    ("Deliver source evidence for this subject before asserting it. A resolved hypothesis or candidate without "
     "inspected source must remain inconclusive with sufficient=false, naming the missing inspection.")
]


class BoundaryExecution(InvestigationExecution):
    trace_name = "architecture-boundary"
    tool_prefix = "boundary"
    prompt_directory = Path(__file__).parent / "prompts"
    evaluation_schema = BoundaryEvaluation
    review_schema = BoundaryReview
    finding_schema = BoundaryFinding
    result_schema = BoundaryResult

    def __init__(self, model, config, tools, request):
        self._support_cache = {}
        self._structure_issues = []
        self._last_parsed_evaluation = None
        self._review_started_calls = None
        self._review_repair_needed = False
        self._valid_reviews = {}
        self._valid_hypothesis_reviews = {}
        self._review_gap_messages = []
        self._reviewed_evaluation_key = None
        self._evaluated_evidence = None
        self._preserved_valid_evaluation = False
        self.failed_evaluation_attempt = None
        self.discovery = BoundaryDiscovery(tools.accessible_snapshot)
        self._progress = None
        self._stale_turns = 0
        self._progress_warning = False
        self._closing_budget_reserved = False
        self._review_skipped_no_candidates = False
        self._prioritize_evaluation = False
        self._repair_source_ids = set()
        self._research_tasks = []
        self._round_progress = []
        self._phase_consumption = {}
        self._guided_rounds = set()
        self._guided_pending = False
        self._planned_hypotheses = {}
        self._baseline = request.continuation
        self._request_fingerprint = hashlib.sha256(json.dumps(request.model_dump(mode="json", exclude={"continuation"}),
            sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        if self._baseline is not None:
            snapshot = tools.accessible_snapshot
            if (self._baseline.snapshot_hash != snapshot.repository.snapshot_hash
                    or self._baseline.commit != snapshot.repository.commit
                    or self._baseline.repository_id != snapshot.repository.name
                    or self._baseline.objective != request.objective):
                raise ValueError("Boundary continuation requires the same repository, snapshot, commit and objective.")
            if self._baseline.request_fingerprint != self._request_fingerprint:
                raise ValueError("Boundary continuation request context and criteria must match the prior request fingerprint.")
            criteria = {item.id: item for item in request.criteria}
            if any(finding.criterion_id not in criteria or finding.criterion != criteria[finding.criterion_id]
                    for finding in self._baseline.findings):
                raise ValueError("Boundary continuation criteria do not match the prior result.")
            if self._baseline.plan is None:
                raise ValueError("Boundary continuation requires a previous investigation plan.")
        super().__init__(model, config, tools, request)

    async def provider_request(self, model, messages, overhead, node, schema, reserved_calls):
        before = (self.calls, self.tokens, self.estimates, self.reported_input_tokens, self.reported_output_tokens)
        try:
            return await super().provider_request(model, messages, overhead, node, schema, reserved_calls)
        finally:
            after = (self.calls, self.tokens, self.estimates, self.reported_input_tokens, self.reported_output_tokens)
            counters = self._phase_consumption.setdefault(node, dict.fromkeys((
                "model_calls", "accounted_tokens", "estimated_tokens", "reported_input_tokens", "reported_output_tokens",
                "prompt_characters"), 0))
            for key, old, new in zip(tuple(counters)[:5], before, after, strict=True):
                counters[key] += new - old
            counters["prompt_characters"] += (after[0] - before[0]) * (
                len(json.dumps([item.model_dump() for item in messages], default=str)) + len(overhead))

    def structured_schema(self, schema):
        # Provider generation uses a reduced schema; parse_structured still
        # validates the complete canonical contract and all local bounds.
        return lean_schema(schema) if isinstance(self.model, BaseChatModel) else schema

    async def plan_investigation(self, state):
        if self._baseline is None:
            update = await super().plan_investigation(state)
            self._planned_hypotheses = {item.id: item for item in update["hypotheses"]}
            return update
        # Re-deliver only cited source through the normal access/budget checks.
        # A serialized result is untrusted input, not a privileged evidence ledger.
        baseline = self._baseline
        needed = {item for subject in [*baseline.hypotheses, *baseline.findings] for item in subject.evidence_ids}
        needed.update(item.evidence_id for check in baseline.claim_checks for item in check.support)
        sources = {source.id: source for source in self.tools.accessible_snapshot.files}
        mapping, messages, delivered = {}, [], {}
        for ref in baseline.evidence:
            if ref.id not in needed or ref.kind != "source":
                continue
            source = sources.get(ref.file_id)
            if (source is None or ref.snapshot_hash != baseline.snapshot_hash or source.path != ref.path
                    or source.content_hash != ref.content_hash):
                raise ValueError("Continuation evidence does not match the retained snapshot.")
            key = (ref.path, ref.start_line, ref.end_line)
            if key in delivered:
                mapping[ref.id] = delivered[key]
                continue
            arguments = {"path": ref.path, "start_line": ref.start_line, "end_line": ref.end_line}
            call_id = "boundary-continuation-" + str(len(messages))
            response = self.tools.execute("get_source_excerpt", arguments, tool_call_id=call_id)
            if response.error:
                self.issues.append("Continuation source could not be re-delivered: " + ref.path)
                continue
            match = next((item for item in response.evidence if item.kind == "source"
                and item.start_line == ref.start_line and item.end_line == ref.end_line), None)
            if match is None:
                self.issues.append("Continuation source range was truncated; missing source must be inspected: " + ref.path)
                continue
            mapping[ref.id] = delivered[key] = match.id
            messages.extend([AIMessage(content="", tool_calls=[{
                "name": "get_source_excerpt", "args": arguments, "id": call_id}]),
                ToolMessage(content=json.dumps(self.tools.model_view(response), ensure_ascii=False),
                    name="get_source_excerpt", tool_call_id=call_id)])

        def remap(value):
            if isinstance(value, str):
                return mapping.get(value, value)
            if isinstance(value, list):
                return [remap(item) for item in value]
            if isinstance(value, dict):
                return {key: remap(item) for key, item in value.items()}
            return value

        hypotheses = [Hypothesis.model_validate(remap(item.model_dump())) for item in baseline.hypotheses]
        candidates = [CandidateFinding.model_validate(remap({key: value for key, value in item.model_dump().items()
            if key in CandidateFinding.model_fields})) for item in baseline.findings]
        evaluation = BoundaryEvaluation(sufficient=False, hypotheses=hypotheses, candidates=candidates,
            missing_information=baseline.missing_information,
            claim_checks=remap([item.model_dump() for item in baseline.claim_checks]))
        self.evaluation_evidence_gaps(evaluation)
        plan = InvestigationPlan.model_validate({**baseline.plan.model_dump(),
            "hypotheses": [item.model_dump() for item in hypotheses]})
        self._planned_hypotheses = {item.id: item for item in baseline.plan.hypotheses}
        return {"plan": plan, "hypotheses": hypotheses, "evaluation": evaluation,
            "missing_information": baseline.missing_information, "messages": messages,
            "evidence": self.references(), "tool_calls": self.tools.budget_usage.tool_calls, "model_calls": self.calls}

    def closing_token_reserve(self, node, request_reserve):
        if node == "investigate":
            reserve = min(self.token_limit // 3, 2 * request_reserve)
        elif node == "evaluate_evidence":
            # Evaluate pending evidence before reserving a review of older work.
            reserve = 0 if self._prioritize_evaluation else min(self.token_limit // 6, request_reserve)
        else:
            return 0
        if token_budget_exceeded(self.tokens + request_reserve + reserve, self.token_limit):
            self._closing_budget_reserved = True
        return reserve

    def model_context(self, node, state):
        context = self._context(state)
        # Hashes and commit attribution belong to the authoritative ledger, not
        # every generation. IDs/paths/ranges are sufficient for selecting citations.
        context["evidence"] = [{key: item[key] for key in (
            "id", "path", "file_id", "kind", "start_line", "end_line") if item.get(key) is not None}
            for item in context["evidence"]]
        if context["plan"]:
            context["plan"] = {key: value for key, value in context["plan"].items() if key != "hypotheses"}
        if context["evaluation"]:
            context["evaluation"] = {key: value for key, value in context["evaluation"].items() if key != "hypotheses"}
        if node in {"evaluate_evidence", "review_findings"}:
            for key in ("boundary_coverage", "prioritized_source_reads", "inventory"):
                context.pop(key, None)
        if node != "review_findings":
            context.pop("boundary_review_requirements", None)
            context.pop("boundary_hypothesis_review_requirements", None)
        context["remaining_accounted_tokens"] = (None if effective_token_budget_policy().unlimited_token_budget
            else max(0, self.token_limit - self.tokens))
        context["closing_due_to_token_budget"] = self._closing_budget_reserved
        source_ids = {ref.file_id for ref in self.references() if ref.kind == "source"}
        context["behavior_symbol_navigation"] = [{"symbol_id": symbol.id, "name": symbol.name,
            "file_id": symbol.file_id, "start_line": symbol.start_line, "end_line": symbol.end_line,
            "navigation_only": True} for symbol in self.tools.accessible_snapshot.symbols
            if symbol.file_id in source_ids and symbol.kind in {"function", "method"}][:80]
        return context

    def provider_history(self, state, messages, *, overhead_characters=0, node=None):
        pinned = {identifier for item in state["hypotheses"] for identifier in item.evidence_ids}
        pinned.update(self._repair_source_ids)
        if state["evaluation"]:
            pinned.update(identifier for item in state["evaluation"].candidates for identifier in item.evidence_ids)
            pinned.update(support.evidence_id for check in state["evaluation"].claim_checks for support in check.support)
        used = len(json.dumps([item.model_dump() for item in messages], default=str)) + overhead_characters
        # Compact before hitting the hard cap, rather than repeatedly paying for
        # discovery inventories that are already represented in current state.
        allowance = max(0, int(self.config.max_context_characters * 0.4) - used)
        return compact_tool_history(state["messages"], allowance, pinned,
            compact_metadata=node in {"evaluate_evidence", "review_findings"},
            focus_search_results=node in {"evaluate_evidence", "review_findings"})

    def claim_check(self, evaluation, subject_type, identifier):
        checks = [item for item in evaluation.claim_checks if item.subject_type == subject_type and item.subject_id == identifier]
        return checks[0] if len(checks) == 1 else None

    @staticmethod
    def cites_source(subject, references):
        """Whether a subject cites delivered source that a claim check could rest on."""
        return any(references[i].kind == "source" for i in subject.evidence_ids if i in references)

    def validate_evaluation(self, evaluation, state):
        super().validate_evaluation(evaluation, state)
        self._last_parsed_evaluation = evaluation
        self._structure_issues = []
        files = {source.path for source in self.tools.accessible_snapshot.files}
        references = {item.id: item for item in self.references()}
        required = {("candidate", item.id) for item in evaluation.candidates}
        # A resolved hypothesis citing no delivered source cannot support any check.
        # Demanding one anyway only invited an empty support list and consumed the
        # correction budget; evaluation_evidence_gaps reports the missing evidence.
        required |= {("hypothesis", item.id) for item in evaluation.hypotheses
            if item.status in {"confirmed", "discarded"} and self.cites_source(item, references)}
        known = required | {("hypothesis", item.id) for item in evaluation.hypotheses}
        for kind, identifier in sorted(required):
            checks = [item for item in evaluation.claim_checks if (item.subject_type, item.subject_id) == (kind, identifier)]
            if len(checks) != 1:
                self._structure_issues.append({"subject_type": kind, "subject_id": identifier,
                    "issue": "missing_claim_check" if not checks else "duplicate_claim_check"})
        for check in evaluation.claim_checks:
            if (check.subject_type, check.subject_id) not in known:
                self._structure_issues.append({"issue": "unknown_claim_check_subject"})
            if any(path not in files for path in check.scope_paths):
                self._structure_issues.append({"subject_type": check.subject_type, "subject_id": check.subject_id,
                    "issue": "scope_requires_exact_file_paths"})
        if self._structure_issues:
            code = "boundary_check_structure_invalid"
            raise PydanticCustomError(code, BoundaryEvaluation.validation_feedback[code])
        self._valid_reviews = {}
        self._valid_hypothesis_reviews = {}
        self._review_started_calls = None
        self._review_gap_messages = []
        self._reviewed_evaluation_key = None
        self._evaluated_evidence = self.evidence_fingerprint()

    def prepare_structured_input(self, node, value):
        """Discard claim checks that assert nothing, before canonical validation.

        The lean provider schema omits minItems, so `support: []` is schema-valid while
        the canonical contract rejects it as too_short. That rejection carries no usable
        feedback and consumed the whole correction budget in a real run. An empty check
        is not a malformed check; it states that no evidence was inspected. Dropping it
        lets validate_evaluation report the subject as missing, with exact subject IDs and
        delivered references, which is the correction the model can actually act on.
        """
        if not isinstance(value, dict) or not isinstance(value.get("claim_checks"), list):
            return value
        checks = value["claim_checks"]
        kept = [check for check in checks
            if isinstance(check, dict) and check.get("support") and check.get("scope_paths")]
        if len(kept) == len(checks):
            return value
        self.logger.info("%s: discarded %d claim checks without inspected scope or support",
            node, len(checks) - len(kept))
        return {**value, "claim_checks": kept}

    def structured_correction_context(self, node, state):
        if node != "evaluate_evidence" or not self._last_parsed_evaluation:
            return super().structured_correction_context(node, state)
        evaluation = self._last_parsed_evaluation
        return {"structural_issues": self._structure_issues,
            "candidate_ids": [item.id for item in evaluation.candidates],
            "resolved_hypothesis_ids": [item.id for item in evaluation.hypotheses if item.status in {"confirmed", "discarded"}],
            "delivered_source": [{"id": item.id, "file_path": item.path, "start_line": item.start_line,
                "end_line": item.end_line} for item in self.references() if item.kind == "source"]}

    def _context(self, state):
        context = super()._context(state)
        coverage = self.discovery.coverage(self.references(), self.tools.tool_measurements)
        context["boundary_coverage"] = {**coverage, "boundaries": [
            {**item, "endpoint_paths": item["endpoint_paths"][:8],
                "uninspected_paths": item["uninspected_paths"][:8],
                "omitted_endpoint_paths": max(0, len(item["endpoint_paths"]) - 8)}
            for item in coverage["boundaries"][:20]],
            "unresolved_dependency_paths": coverage["unresolved_dependency_paths"][:20],
            "omitted_unresolved_dependency_paths": max(0, len(coverage["unresolved_dependency_paths"]) - 20),
            "omitted_boundaries": max(0, coverage["boundary_count"] - 20)}
        texts = [self.request.objective, *[item.question for item in state["hypotheses"]
            if item.status in {"pending", "inconclusive"}]]
        targeted = [read for task in self._research_tasks for read in task.get("next_source_reads", [])]
        context["investigation_tasks"] = self._research_tasks[:6]
        context["prioritized_source_reads"] = (targeted[:6] if targeted else
            self.ranked_source_reads(texts, (), self.references(), limit=6))
        context["investigation_progress"] = {"stale_turns": self._stale_turns,
            "change_strategy": self._progress_warning}
        context["support_capabilities"] = {
            "source_roles": ["Python", "JavaScript", "TypeScript"],
            "declarations": ["TOML", "JSON", "YAML"],
            "unsupported": "Other source languages remain readable but cannot establish syntax-validated roles.",
            "architectural_rules": "Supply narrative rules as caller context; documentation is excluded by access policy."}
        evaluation = state["evaluation"]
        if evaluation:
            context["boundary_review_requirements"] = [{"candidate_id": candidate.id,
                "claim_check": check.model_dump() if check else None,
                "expected_checked_evidence_ids": sorted({item.evidence_id for item in check.support}) if check else [],
                "host_support_issues": self.support_issues(candidate, check),
            } for candidate in evaluation.candidates
                for check in [self.claim_check(evaluation, "candidate", candidate.id)]]
            context["boundary_hypothesis_review_requirements"] = [{"hypothesis_id": subject.id,
                "question": subject.question, "proposed_status": subject.status,
                "proposed_rationale": subject.rationale,
                "claim_check": check.model_dump() if check else None,
                "expected_checked_evidence_ids": sorted(set(subject.evidence_ids) |
                    {item.evidence_id for item in check.support}) if check else subject.evidence_ids,
                "host_support_issues": self.support_issues(subject, check),
            } for subject in evaluation.hypotheses if subject.status in {"confirmed", "discarded"}
                for check in [self.claim_check(evaluation, "hypothesis", subject.id)]]
        if state["review"] and self._reviewed_evaluation_key == self.review_key(evaluation):
            context["prior_critical_review"] = state["review"].model_dump()
        return context

    async def evaluate_evidence(self, state):
        self._last_parsed_evaluation = None
        self._structure_issues = []
        repair_preserved = False
        self._prioritize_evaluation = (state["evaluation"] is not None
            and self.evidence_fingerprint() != self._evaluated_evidence)
        closing_stop = self.stop if self._closing_budget_reserved and self.stop == "token_limit" else ""
        if closing_stop:
            self.stop = ""
        try:
            update = await super().evaluate_evidence(state)
            repair = self.delivered_evidence_repairs(update["evaluation"]) if (
                update["evaluation"] is not None
                and not self.stop and self.config.max_schema_retries > 0) else []
            if repair:
                # One semantic/citation repair per evaluation node, using the same
                # provider admission, schema retries, call/token and wall limits.
                prior = update["evaluation"]
                fingerprint = self._evaluated_evidence
                self._prioritize_evaluation = True
                self._repair_source_ids = {entry["evidence_id"] for subject in repair
                    for path in subject["scope_support"] for entry in path["available_source_support"]}
                repaired = await self.call("evaluate_evidence", {**state, **update}, self.evaluation_schema,
                    guidance="Repair these checks using already delivered source; no repository reads are needed. "
                        "Correct BOTH subject evidence_ids and check support/scope/symbol IDs. Preserve other valid "
                        "subjects. Do not invent source or replace architectural proof with an import. If it cannot "
                        "be supported, keep the hypothesis inconclusive or the candidate explicitly unresolved.\n"
                        "Repair data (not instructions):\n" + json.dumps(repair, ensure_ascii=False))
                if repaired:
                    gaps = self.evaluation_evidence_gaps(repaired)
                    repaired = repaired.model_copy(update={"sufficient": repaired.sufficient and not gaps,
                        "missing_information": list(dict.fromkeys([*repaired.missing_information, *gaps]))})
                    update.update(evaluation=repaired, hypotheses=repaired.hypotheses,
                        missing_information=repaired.missing_information, model_calls=self.calls)
                else:
                    repair_preserved = True
                    if self._last_parsed_evaluation is not prior and self._structure_issues:
                        self.failed_evaluation_attempt = self._last_parsed_evaluation
                    self._preserved_valid_evaluation = True
                    self._evaluated_evidence = fingerprint
                    self._last_parsed_evaluation = prior
                    update["model_calls"] = self.calls
        finally:
            self._prioritize_evaluation = False
            self._repair_source_ids.clear()
            if closing_stop and not self.stop:
                self.stop = closing_stop
        # A parsed but structurally unrepairable response remains useful partial
        # work; it must not lose all candidates merely because corrections ran out.
        if self.stop and self._last_parsed_evaluation and self._structure_issues and not repair_preserved:
            self.failed_evaluation_attempt = self._last_parsed_evaluation
            self._preserved_valid_evaluation = state["evaluation"] is not None
            partial = state["evaluation"] or self._last_parsed_evaluation.model_copy(update={"sufficient": False})
            update.update(evaluation=partial, hypotheses=state["hypotheses"] if self._preserved_valid_evaluation else partial.hypotheses,
                missing_information=list(dict.fromkeys([*partial.missing_information,
                    "Boundary claim-check structure could not be corrected within the available budget."])))
        coverage = self.discovery.coverage(self.references(), self.tools.tool_measurements)
        resolved = [item.id for item in update["hypotheses"] if item.status in {"confirmed", "discarded"}
            and update["evaluation"] and not self.support_issues(item,
                self.claim_check(update["evaluation"], "hypothesis", item.id))]
        self._round_progress.append({"round": update["iterations"], "resolved_hypothesis_ids": resolved,
            "pending_task_count": len(self._research_tasks), "excerpt_file_count": coverage["excerpt_file_count"],
            "source_lines_delivered": coverage["source_lines_delivered"], "model_calls": self.calls,
            "tool_calls": self.tools.budget_usage.tool_calls,
            "repeated_tool_requests": sum(item.repeated for item in self.tools.tool_measurements)})
        return update

    def delivered_evidence_repairs(self, evaluation):
        """Identify locally repairable metadata, never silently attach replacement citations."""
        references = {ref.id: ref for ref in self.references()}
        repairs = []
        subjects = [("candidate", item) for item in evaluation.candidates]
        subjects += [("hypothesis", item) for item in evaluation.hypotheses
            if item.status in {"confirmed", "discarded"}]
        for kind, subject in subjects:
            check = self.claim_check(evaluation, kind, subject.id)
            if check is None or check.claim_kind in COVERAGE_DEMANDING:
                continue
            issues = self.support_issues(subject, check)
            if not issues or any(issue in issues for issue in (
                    "boundary_scope_unrelated_to_subject", "boundary_no_delivered_source_evidence")):
                continue
            scope = self.scope_recovery(check, references)
            available = [entry for path in scope for entry in path["available_source_support"]]
            roles = {role for entry in available for role in entry["observed_roles"]}
            if not all(path["available_source_support"] for path in scope):
                continue
            if not CLAIM_REQUIREMENTS[check.claim_kind] <= roles:
                continue
            if check.claim_kind == "behavior":
                # Do not call a partial implementation a citation-only defect.
                symbols = [symbol for symbol in self.tools.accessible_snapshot.symbols
                    if symbol.kind in {"function", "method"}]
                if not any(any(ref.kind == "source" and ref.file_id == symbol.file_id
                        and ref.path in check.scope_paths and ref.start_line <= symbol.start_line
                        and ref.end_line >= symbol.end_line for ref in references.values()) for symbol in symbols):
                    continue
            repairs.append({"subject_type": kind, "subject_id": subject.id,
                "issues": issues, "scope_support": scope})
        return repairs

    def evidence_fingerprint(self):
        return frozenset((record.file_id, record.content_hash, record.kind, record.start_line, record.end_line)
            for record in self.tools.retrieved_evidence)

    async def investigate(self, state):
        if self._guided_pending:
            self._guided_pending = False
            return {"messages": [AIMessage(content="Bounded pending source reads delivered; re-evaluate their actual scope.")],
                "model_calls": self.calls}
        if self._baseline is not None and self._evaluated_evidence is None:
            # The existing investigate -> evaluate route revalidates restored work
            # before spending another discovery call; graph topology is unchanged.
            return {"model_calls": self.calls}
        fingerprint = self.progress_fingerprint(state)
        if self._progress == fingerprint:
            self._stale_turns += 1
        else:
            self._stale_turns = 0
            self._progress_warning = False
        self._progress = fingerprint
        if self._stale_turns >= 2 and state["evaluation"] is not None:
            self._progress_warning = True
        if self._stale_turns >= 4 and state["evaluation"] is not None:
            self.stop = "no_investigation_progress"
            self.issues.append("Repeated investigation turns delivered no new evidence; retained partial results for review.")
            return {"model_calls": self.calls}
        update = await super().investigate(state)
        if state["evaluation"] is None or self.stop:
            return update
        if not update.get("messages"):
            self.stop = "model_call_limit" if self.calls >= self.call_limit - self.closing_call_reserve else "tool_call_limit"
            return update
        answer = update["messages"][-1]
        if not answer.tool_calls and not empty_ai_message(answer) and state["iterations"] not in self._guided_rounds:
            reads = self.pending_source_batch(state["evaluation"])
            if reads:
                self._guided_rounds.add(state["iterations"])
                self._guided_pending = True
                self.logger.info("investigate: executing %d pending dependency/source reads before re-evaluation", len(reads))
                return {"messages": [AIMessage(content="Inspect the concrete pending source before closing this round.",
                    tool_calls=[{"id": f"boundary-guided-{self.calls}-{index}", "name": "get_source_excerpt",
                        "args": read["arguments"]} for index, read in enumerate(reads)])], "model_calls": self.calls}
        # A provider can answer 200 while converting its reply to no usable parts. That
        # is a transport artifact, not a decision that nothing remains, so spend one
        # corrective investigation call before concluding the audit cannot progress.
        if (empty_ai_message(update["messages"][-1]) and state["missing_information"]
                and self.evidence_fingerprint() == self._evaluated_evidence):
            retry = await self.call("investigate", state, guidance=self.recovery_guidance())
            if self.stop:
                return update
            if retry is None or empty_ai_message(retry):
                self.stop = "no_investigation_progress"
                self.issues.append("Investigation twice returned an empty answer without new evidence; "
                    "retained the prior evaluation for closing review.")
            else:
                return {"messages": [retry], "model_calls": self.calls}
        return update

    def pending_source_batch(self, evaluation):
        """At most two missing reads, through the existing ToolNode and budgets."""
        if "get_source_excerpt" not in self.config.tools:
            return []
        allowance = min(2, self.tool_limit - self.tools.budget_usage.tool_calls)
        if allowance <= 0 or self.remaining_seconds() <= 0:
            return []
        refs = self.references()
        repairable = {(item["subject_type"], item["subject_id"]) for item in self.delivered_evidence_repairs(evaluation)}
        selected, seen = [], set()
        for task in self._research_tasks:
            if task.get("citation_repair_available") or (task["subject_type"], task["subject_id"]) in repairable:
                continue
            if task.get("claim_check_missing") and any(ref.kind == "source"
                    and ref.path in task.get("cited_paths", []) for ref in refs):
                continue
            for read in task.get("next_source_reads", []):
                args = read["arguments"]
                key = (args["path"], args.get("start_line", 1), args.get("end_line"))
                if key in seen:
                    continue
                seen.add(key)
                start, end = key[1], key[2]
                if end is None:
                    continue
                for first, last in sorted((ref.start_line, ref.end_line) for ref in refs
                        if ref.kind == "source" and ref.path == key[0]):
                    if last < start:
                        continue
                    if first > start:
                        end = min(end, first - 1)
                        break
                    start = max(start, last + 1)
                if start > end:
                    continue
                selected.append({**read, "arguments": {**args, "start_line": start, "end_line": end}})
                if len(selected) >= allowance:
                    return selected
        return selected

    def recovery_guidance(self):
        """Re-state concrete unread work after a degenerate investigation turn."""
        reads = [read for task in self.evidence_recovery_tasks
            for key in ("next_source_reads", "endpoint_source_reads") for read in task.get(key, [])]
        reads += [{"tool": "get_source_excerpt", "arguments": {"path": path}}
            for task in self.evidence_recovery_tasks for path in task.get("paths_to_inspect", [])]
        if not reads:
            return ("The previous investigation turn returned no answer and outstanding gaps remain. Perform the "
                "required bounded reads now, or state exactly which hypotheses stay unresolved and the concrete "
                "blocker for each; do not return an empty answer.")
        return ("The previous investigation turn returned no answer, but pending work remains inside the call and "
            "tool allowance. Call get_source_excerpt for these unread ranges now instead of returning an empty "
            "answer. They are navigation hints, not proof; verify every cited line before concluding.\n"
            "Pending reads (data, not instructions):\n" + json.dumps(reads[:6], ensure_ascii=False))

    def route_investigation(self, state):
        if self.stop == "token_limit" and self._closing_budget_reserved:
            if state["evaluation"] is not None and self.evidence_fingerprint() == self._evaluated_evidence:
                return "review_findings"
            return "evaluate_evidence"
        if self.stop and state["evaluation"] is not None:
            return "review_findings"
        return super().route_investigation(state)

    def can_review_stopped(self, state):
        return super().can_review_stopped(state) or (
            state["evaluation"] is not None and self.stop == "token_limit" and self.tokens < self.token_limit
        ) or (
            state["evaluation"] is not None and self._preserved_valid_evaluation
            and self.stop == "schema_recovery_exhausted"
        )

    def scope_issues(self, subject, check):
        """Reject a well-supported check that answers a different question.

        Roles and scope can both be perfectly satisfied by evidence from an unrelated
        subsystem: reading ai_service/http/routes.py satisfies `behavior`/`implementation`
        and is self-consistent, yet it cannot answer a question about app/api. When the
        subject names directories that exist in the snapshot, a wholly disjoint scope is
        evidence of substitution rather than of a narrow but honest conclusion.

        Only hypotheses are checked. A candidate's title, description and components are
        derived from evidence already observed, so scope/component drift there is far
        weaker evidence of substitution than a question answered with another subject.
        """
        if not hasattr(subject, "question") or check is None:
            return []
        named = self.navigation_scope([subject.question, *subject.evidence_needed])
        if not named:
            return []
        overlapping = any(path == scope or path.startswith(f"{scope}/") or scope.startswith(f"{path}/")
            for scope in check.scope_paths for path in named)
        return [] if overlapping else ["boundary_scope_unrelated_to_subject"]

    def support_issues(self, subject, check):
        if check is None:
            return ["boundary_claim_check_missing_or_duplicate"]
        references = {item.id: item for item in self.references()}
        files = {item.id: item for item in self.tools.accessible_snapshot.files}
        issues, roles, paths = [*self.scope_issues(subject, check), *assertion_issues(subject, check)], set(), set()
        original = self._planned_hypotheses.get(subject.id) if hasattr(subject, "question") else None
        if original is not None and original.question != subject.question:
            issues.append("boundary_hypothesis_question_changed")
        if getattr(subject, "kind", None) == "violation":
            criterion = next((item for item in self.request.criteria if item.id == subject.criterion_id), None)
            if criterion and criterion.origin != "explicit":
                issues.append("violation_requires_explicit_criterion")
        for item in check.support:
            ref = references.get(item.evidence_id)
            cited = item.evidence_id in subject.evidence_ids
            if not cited or ref is None:
                issues.append("boundary_support_not_cited")
            if ref is None:
                continue
            if ref.path not in check.scope_paths:
                issues.append("boundary_support_outside_declared_scope")
            key = (ref.file_id, ref.start_line, ref.end_line, item.role)
            if key not in self._support_cache:
                self._support_cache[key] = supports_role(files[ref.file_id], ref, item.role)
            if not self._support_cache[key]:
                issues.append("boundary_support_role_not_observed:" + item.role)
                continue
            if cited and ref.path in check.scope_paths:
                roles.add(item.role)
                paths.add(ref.path)
            if check.claim_kind == "behavior" and item.role == "implementation":
                symbol = next((symbol for symbol in self.tools.accessible_snapshot.symbols
                    if symbol.id == item.symbol_id and symbol.file_id == ref.file_id
                    and symbol.kind in {"function", "method"}), None)
                if symbol is None:
                    issues.append("boundary_behavior_symbol_missing_or_invalid")
                elif not self.symbol_body_delivered(symbol, check, subject, references):
                    issues.append("boundary_behavior_body_not_inspected")
        issues.extend("boundary_missing_role:" + role for role in sorted(CLAIM_REQUIREMENTS[check.claim_kind] - roles))
        if not set(check.scope_paths) <= paths:
            issues.append("boundary_scope_not_inspected")
        if check.claim_kind in COVERAGE_DEMANDING:
            if not check.coverage_complete or check.limitations:
                issues.append("boundary_coverage_incomplete")
            if len(paths) < 2:
                issues.append("boundary_endpoints_not_inspected")
            issues.extend(self.discovery.claim_issues(check, paths, references.values()))
            issues.extend(self.coverage_obligations(subject, check, references))
        return list(dict.fromkeys(issues))

    def coverage_obligations(self, subject, check, references):
        """Validate concrete scope and proof obligations, not a model's coverage flag."""
        issues = []
        cited = {item.evidence_id for item in check.support} & set(subject.evidence_ids)
        refs = [references[item] for item in cited if item in references and references[item].kind == "source"]
        supported_paths = {ref.path for ref in refs}
        if check.claim_kind in {"isolation", "deployment"}:
            required = {"dependency_direction", "shared_resources", "composition"}
            if check.claim_kind == "deployment":
                required.add("deployment")
            verified = set()
            for item in check.verifications:
                if set(item.evidence_ids) <= {ref.id for ref in refs} and item.evidence_ids:
                    verified.add(item.dimension)
                else:
                    issues.append("boundary_verification_source_not_supported:" + item.dimension)
            issues.extend("boundary_verification_missing:" + name for name in sorted(required - verified))
        named = (self.navigation_scope([subject.question, *subject.evidence_needed], limit=40)
            if hasattr(subject, "question") else getattr(subject, "components", []))
        files = list(self.discovery.files.values())
        required_files = {source.path for source in files if source.path in check.scope_paths}
        for scope in named:
            members = {source.path for source in files if source.path == scope or source.path.startswith(scope + "/")}
            if members:
                required_files.update(members)
                if not members & supported_paths:
                    issues.append("boundary_named_component_not_inspected:" + scope)
        for path in sorted(required_files):
            source = next(source for source in files if source.path == path)
            cursor = 1
            for start, end in sorted((ref.start_line, ref.end_line) for ref in refs if ref.path == path):
                if start > cursor:
                    break
                cursor = max(cursor, end + 1)
            if not source.line_count or cursor <= source.line_count:
                issues.append("boundary_scope_coverage_not_demonstrated")
                break
        if check.claim_kind == "deployment":
            deployment_sources = [ref for ref in refs if any(item.dimension == "deployment" and ref.id in item.evidence_ids
                for item in check.verifications)]
            if not any("docker" in ref.path.lower() or "deploy" in ref.path.lower()
                    or Path(ref.path).name.lower().startswith("compose") or ref.path.startswith(".github/workflows/")
                    for ref in deployment_sources):
                issues.append("boundary_deployment_configuration_not_inspected")
        return issues

    @staticmethod
    def symbol_body_delivered(symbol, check, subject, references):
        """Check actual inspection of the named body, allowing bounded chunks.

        This does not prove that its behavior supports the model's prose.
        """
        ranges = sorted((ref.start_line, ref.end_line) for item in check.support
            if item.role == "implementation" and item.symbol_id == symbol.id
            and item.evidence_id in subject.evidence_ids
            and (ref := references.get(item.evidence_id)) is not None
            and ref.kind == "source" and ref.file_id == symbol.file_id)
        next_line = symbol.start_line
        for start, end in ranges:
            if start > next_line:
                break
            next_line = max(next_line, end + 1)
        return next_line > symbol.end_line

    def satisfied_claim_kinds(self, subject, check):
        """Claim kinds the subject's own cited line ranges could actually carry.

        The declared role of a support entry is the model's claim about that range, so it
        cannot be reused to test other kinds. This re-derives the roles the cited syntax
        actually shows, which is what makes a narrower claim discoverable: one read of a
        Python module usually carries declaration, dependency and behavior at once, so
        rejecting it as isolation hides that the same evidence already supports a valid
        finding. Naming the achievable kinds turns an unsatisfiable rejection into an
        achievable repair. The model still chooses; nothing here rewrites its claim.
        """
        if check is None:
            return []
        references = {item.id: item for item in self.references()}
        files = {item.id: item for item in self.tools.accessible_snapshot.files}
        observed, paths = set(), set()
        for item in check.support:
            ref = references.get(item.evidence_id)
            if ref is None or ref.file_id not in files or item.evidence_id not in subject.evidence_ids:
                continue
            paths.add(ref.path)
            observed.update(role for role in NAVIGATION_ROLES
                if supports_role(files[ref.file_id], ref, role))
        covered = set(check.scope_paths) <= paths
        satisfied = []
        for kind, required in CLAIM_REQUIREMENTS.items():
            if not required <= observed or not covered:
                continue
            if kind in COVERAGE_DEMANDING and not (
                    check.coverage_complete and not check.limitations and len(paths) >= 2):
                continue
            if kind in COVERAGE_DEMANDING and self.discovery.claim_issues(
                    check.model_copy(update={"claim_kind": kind}), paths, references.values()):
                continue
            satisfied.append(kind)
        return satisfied

    def evaluation_evidence_gaps(self, evaluation):
        gaps = super().evaluation_evidence_gaps(evaluation)
        subjects = [("candidate", item) for item in evaluation.candidates]
        subjects += [("hypothesis", item) for item in evaluation.hypotheses if item.status in {"confirmed", "discarded"}]
        refs = {item.id: item for item in self.references()}
        for kind, subject in subjects:
            check = self.claim_check(evaluation, kind, subject.id)
            unevidenced = not self.cites_source(subject, refs)
            issues = ["boundary_no_delivered_source_evidence"] if unevidenced else self.support_issues(subject, check)
            if not issues:
                continue
            self.provenance_blocked = False
            evidence = [refs[item] for item in subject.evidence_ids if item in refs]
            self.evidence_recovery_instruction(kind, subject.id, [], evidence, refs,
                question=getattr(subject, "question", getattr(subject, "description", "")),
                evidence_needed=(UNSUPPORTED_SUBJECT if unevidenced else
                    ["Supply a scoped claim_check with observed source support, required roles and coverage.", *issues]))
            task = self.evidence_recovery_tasks[-1]
            satisfied = self.satisfied_claim_kinds(subject, check) if check else []
            task.update(action="inspect_boundary_support_or_narrow_claim", issues=issues,
                claim_kind=check.claim_kind if check else None,
                declared_scope_paths=check.scope_paths if check else [])
            scope_unrelated = "boundary_scope_unrelated_to_subject" in issues
            if satisfied and len(satisfied) < len(CLAIM_KINDS) and not scope_unrelated:
                task["satisfiable_claim_kinds"] = satisfied
                task["action"] = "narrow_claim_kind_or_inspect_missing_roles"
            if check:
                invalid = {item.evidence_id for item in check.support if item.evidence_id in refs
                    and not self._support_cache.get((refs[item.evidence_id].file_id,
                        refs[item.evidence_id].start_line, refs[item.evidence_id].end_line, item.role), False)}
                task["available_source_evidence_ids"] = [identifier for identifier in task["available_source_evidence_ids"] if identifier not in invalid]
                task["invalid_support_evidence_ids"] = sorted(invalid)
                task["required_roles"] = [issue.split(":", 1)[1] for issue in issues if issue.startswith("boundary_missing_role:")]
                task["paths_to_inspect"] = list(dict.fromkeys([*task["paths_to_inspect"],
                    *(refs[identifier].path for identifier in invalid)]))
                task["next_source_reads"] = self.next_source_reads(check.scope_paths, task["required_roles"], refs)
                task["scope_support"] = self.scope_recovery(check, refs)
                if any(issue.startswith("boundary_behavior_") for issue in issues):
                    task["behavior_support_instruction"] = (
                        "Identify the actual function/method symbol_id implementing each claimed behavior, "
                        "deliver its body through bounded source reads, and explain how that body supports "
                        "the conclusion. Constants, comments and an unrelated utility do not establish domain rules.")
                    task["next_source_reads"] = self.next_source_reads(check.scope_paths, ["implementation"], refs)
                if "dependency" in task["required_roles"]:
                    reads, replacements = self.dependency_recovery(check, refs)
                    task["next_source_reads"] = reads + task["next_source_reads"]
                    task["replacement_support"] = replacements
                if check.claim_kind in {"isolation", "absence_of_cycles"} and (
                        "boundary_endpoints_not_inspected" in issues or task["required_roles"]):
                    task["endpoint_source_reads"] = self.endpoint_reads(
                        check.scope_paths, task["required_roles"] or NAVIGATION_ROLES, refs)
            if scope_unrelated:
                named = self.navigation_scope([subject.question, *subject.evidence_needed])
                task.update(action="inspect_question_scope_or_keep_inconclusive", navigation_scope_paths=named,
                    next_source_reads=self.next_source_reads(named, NAVIGATION_ROLES, refs))
                gaps.append(f"{kind} {subject.id}: boundary_scope_unrelated_to_subject. The declared scope "
                    f"{', '.join(check.scope_paths) if check else '(none)'} shares nothing with what this "
                    "question names. Inspect and cite the named scope or keep this hypothesis inconclusive. "
                    "Changing claim_kind does not repair unrelated scope; report other observations separately.")
                continue
            narrowing = (f" The inspected support carries these claim kinds: {', '.join(satisfied)}. "
                "Re-declare the check with one of them, or inspect the missing roles before claiming a "
                "stronger kind." if satisfied and len(satisfied) < len(CLAIM_KINDS) else "")
            gaps.append(f"{kind} {subject.id}: {', '.join(issues)}.{narrowing} " + ("No delivered source evidence supports this "
                "subject; inspect the source and callers it requires or keep it inconclusive. A conclusion that was "
                "never read cannot be asserted." if unevidenced else "Inspect implementation/usage/composition as "
                "required, or narrow the actual conclusion and its claim_kind together. Comments are declarations "
                "of intent, not implementation evidence."))
        self.ground_unresolved_tasks(evaluation)
        self._research_tasks = self.research_tasks(evaluation)
        return gaps

    def research_tasks(self, evaluation):
        """A bounded work queue tied to questions, not a repository-wide reading quota."""
        refs = self.references()
        known = {item.id: item for item in refs}
        subjects = {("hypothesis", item.id): item for item in evaluation.hypotheses}
        subjects.update({("candidate", item.id): item for item in evaluation.candidates})
        tasks = []
        for recovery in self.evidence_recovery_tasks:
            subject = subjects.get((recovery["subject_type"], recovery["id"]))
            if subject is None:
                continue
            question = getattr(subject, "question", getattr(subject, "description", ""))
            paths = [known[item].path for item in subject.evidence_ids if item in known]
            check = self.claim_check(evaluation, recovery["subject_type"], recovery["id"])
            if check:
                paths.extend(check.scope_paths)
            concrete = [source.path for source in self.discovery.files.values() if source.path.lower() in question.lower()]
            paths = list(dict.fromkeys([*paths, *concrete]))
            reads = self.discovery.dependency_reads(paths, refs, self.tools.limits.max_source_lines, limit=4)
            reads.extend(recovery.get("next_source_reads", []))
            reads.extend(recovery.get("endpoint_source_reads", []))
            if not reads:
                scope = self.navigation_scope([question, *recovery.get("evidence_needed", [])])
                reads = self.ranked_source_reads([question], scope, refs, limit=4)
            unique = {}
            for read in reads:
                unique.setdefault(json.dumps(read["arguments"], sort_keys=True), read)
            tasks.append({"subject_type": recovery["subject_type"], "subject_id": subject.id,
                "question": question, "priority": getattr(subject, "priority", "medium"),
                "action": recovery["action"], "issues": recovery.get("issues", []),
                "claim_check_missing": check is None, "cited_paths": recovery.get("cited_paths", []),
                "citation_repair_available": bool(recovery.get("available_source_evidence_ids")
                    and (check is None or recovery.get("replacement_support"))),
                "next_source_reads": list(unique.values())[:4],
                "completion": "Inspect both dependency endpoints and actual implementation. Re-evaluate only the demonstrated scope; otherwise state the concrete blocker.",
                "blocker": "" if unique else "No unread source range identified; search concrete imports, resource names or report unavailable evidence.",
                "navigation_only": True})
        order = {"high": 0, "medium": 1, "low": 2}
        return sorted(tasks, key=lambda item: (order[item["priority"]], item["subject_type"], item["subject_id"]))

    def progress_fingerprint(self, state):
        # Repeated searches producing different hit IDs are not new implementation
        # inspection. Resolution only counts if host support has actually passed.
        methods = {item.call_id: item.tool for item in self.tools.tool_measurements}
        source = frozenset((ref.file_id, ref.start_line, ref.end_line) for ref in self.references()
            if ref.kind == "source" and methods.get(ref.tool_call_id) == "get_source_excerpt")
        evaluation = state.get("evaluation")
        resolved = frozenset((item.id, item.status) for item in state["hypotheses"]
            if evaluation and item.status in {"confirmed", "discarded"}
            and not self.support_issues(item, self.claim_check(evaluation, "hypothesis", item.id)))
        return source, resolved

    def scope_recovery(self, check, references):
        """Describe citation/role gaps per file without changing a model conclusion."""
        files = {source.id: source for source in self.tools.accessible_snapshot.files}
        result = []
        for path in check.scope_paths:
            declared = [item for item in check.support if item.evidence_id in references
                and references[item.evidence_id].path == path]
            supported = [item.evidence_id for item in declared if self._support_cache.get((
                references[item.evidence_id].file_id, references[item.evidence_id].start_line,
                references[item.evidence_id].end_line, item.role), False)]
            available = []
            for ref in references.values():
                if ref.path != path or ref.kind != "source":
                    continue
                roles = []
                for role in NAVIGATION_ROLES:
                    key = (ref.file_id, ref.start_line, ref.end_line, role)
                    if key not in self._support_cache:
                        self._support_cache[key] = supports_role(files[ref.file_id], ref, role)
                    if self._support_cache[key]:
                        roles.append(role)
                if roles:
                    available.append({"evidence_id": ref.id, "start_line": ref.start_line,
                        "end_line": ref.end_line, "observed_roles": roles})
            # Prefer already delivered ranges carrying the missing claim roles.
            available.sort(key=lambda item: (-len(set(item["observed_roles"]) & CLAIM_REQUIREMENTS[check.claim_kind]),
                item["end_line"] - item["start_line"], item["start_line"]))
            result.append({"path": path, "supported_by_declared_citations": bool(supported),
                "declared_support_evidence_ids": [item.evidence_id for item in declared],
                "available_source_support": available[:3],
                "action": "retain_supported_scope" if supported else
                    "correct_subject_and_check_citations_or_narrow_conclusion" if available else "inspect_missing_scope",
                "navigation_only": True})
        return result

    def dependency_recovery(self, check, references):
        """Repair multiline imports before suggesting unrelated function bodies."""
        files = {source.id: source for source in self.tools.accessible_snapshot.files}
        reads, replacements = [], []
        for support in check.support:
            ref = references.get(support.evidence_id)
            if support.role != "dependency" or ref is None:
                continue
            span = dependency_span(files[ref.file_id], ref)
            if span is None:
                continue
            start, end = span
            if end - start + 1 > self.tools.limits.max_source_lines:
                continue
            available = [item.id for item in references.values()
                if item.kind == "source" and item.file_id == ref.file_id
                and item.start_line <= start and item.end_line >= end]
            if available:
                replacements.append({"invalid_evidence_id": ref.id, "available_evidence_ids": available,
                    "instruction": "Replace this citation in both the subject evidence_ids and its claim_check support."})
            else:
                read = {"tool": "get_source_excerpt", "arguments": {
                    "path": ref.path, "start_line": start, "end_line": end},
                    "navigation_only": True, "potential_roles": ["dependency"],
                    "replaces_evidence_id": ref.id}
                if read not in reads:
                    reads.append(read)
        return reads, replacements

    def ground_unresolved_tasks(self, evaluation):
        """Give an unresolvable recovery task something concrete to read.

        A subject citing only identifiers that were never delivered produces a task with
        no path, no available source and nothing actionable, which is how two hypotheses
        stayed uninspected through every iteration. Scope existence in the snapshot is
        verified navigation, exactly like next_source_reads, never evidence.
        """
        subjects = {("hypothesis", item.id): item for item in evaluation.hypotheses}
        subjects |= {("candidate", item.id): item for item in evaluation.candidates}
        references = {item.id: item for item in self.references()}
        for task in self.evidence_recovery_tasks:
            if task.get("paths_to_inspect") or task.get("next_source_reads") or task.get("endpoint_source_reads"):
                continue
            subject = subjects.get((task["subject_type"], task["id"]))
            if subject is None or task["action"] != "inspect_source_or_correct_citations":
                continue
            scope = self.navigation_scope([task["question"], *task["evidence_needed"],
                getattr(subject, "description", "")])
            if not scope:
                task["next_source_reads"] = self.ranked_source_reads(
                    [task["question"], *task["evidence_needed"]], (), references)
                continue
            task["navigation_scope_paths"] = scope
            task["next_source_reads"] = self.next_source_reads(scope, NAVIGATION_ROLES, references)

    def navigation_scope(self, texts, limit=6):
        """Snapshot directories the subject itself names. Existence is not evidence."""
        haystack = " ".join(str(text) for text in texts).lower()
        scopes = sorted((directory.path for directory in self.tools.accessible_snapshot.directories
            if len(directory.path) >= 4 and directory.path.lower() in haystack),
            key=lambda path: (-len(path), path))[:limit]
        if not scopes:
            scopes = [source.path for source in self.discovery.ranked_files(texts)
                if source.path.lower() in haystack][:limit]
        return scopes

    def unread_symbol_ranges(self, source, roles, references, limit=3):
        """Bounded unread function/method ranges of one file, by the roles they show."""
        suggestions = []
        for symbol in sorted((item for item in self.tools.accessible_snapshot.symbols if item.file_id == source.id),
                key=lambda item: item.start_line):
            if symbol.kind not in {"function", "method"}:
                continue
            start = symbol.start_line
            end = min(symbol.end_line, start + self.tools.limits.max_source_lines - 1)
            if any(ref.file_id == source.id and ref.kind == "source" and ref.start_line <= start and ref.end_line >= end
                   for ref in references.values()):
                continue
            span = SimpleNamespace(kind="source", start_line=start, end_line=end)
            observed = [role for role in roles if supports_role(source, span, role)]
            if observed:
                suggestions.append({"tool": "get_source_excerpt", "arguments": {
                    "path": source.path, "start_line": start, "end_line": end,
                }, "navigation_only": True, "potential_roles": observed})
            if len(suggestions) >= limit:
                break
        return suggestions

    def next_source_reads(self, paths, roles, references):
        """Symbol ranges are navigation hints, never additional source evidence.

        Scopes may be exact file paths or directory prefixes, because a subject that
        cannot cite anything still names the directories its question is about.
        """
        return self.ranked_source_reads([self.request.objective, *paths], paths, references, roles=roles)

    def ranked_source_reads(self, texts, paths, references, *, roles=NAVIGATION_ROLES, limit=3):
        references = list(references.values()) if isinstance(references, dict) else list(references)
        suggestions = []
        for source in self.discovery.ranked_files(texts, paths):
            if paths and not any(source.path == path or source.path.startswith(path + "/") for path in paths):
                continue
            reads = self.unread_symbol_ranges(source, roles, {item.id: item for item in references}, limit=1)
            # Module-level construction, imports and unsupported-language code have no function symbol.
            end = min(source.line_count or 1, self.tools.limits.max_source_lines)
            if not any(ref.kind == "source" and ref.file_id == source.id and ref.start_line <= 1
                       and ref.end_line >= end for ref in references):
                span = SimpleNamespace(kind="source", start_line=1, end_line=end)
                reads.append({"tool": "get_source_excerpt", "arguments": {
                    "path": source.path, "start_line": 1, "end_line": end}, "navigation_only": True})
                reads[-1]["potential_roles"] = [role for role in roles if supports_role(source, span, role)]
            suggestions.extend(reads[:1])
            if not reads:
                # Continue beyond headers and indexed functions: module-level code
                # and unsupported syntax still need bounded source inspection.
                covered = sorted((ref.start_line, ref.end_line) for ref in references
                    if ref.kind == "source" and ref.file_id == source.id)
                start = 1
                for first, last in covered:
                    if first > start:
                        break
                    start = max(start, last + 1)
                if start <= (source.line_count or 0):
                    suggestions.append({"tool": "get_source_excerpt", "arguments": {
                        "path": source.path, "start_line": start,
                        "end_line": min(source.line_count, start + self.tools.limits.max_source_lines - 1)},
                        "navigation_only": True})
            if len(suggestions) >= limit:
                break
        return suggestions

    def related_file_ids(self, file_ids):
        """Internal graph neighbours of the given files, as file identifiers."""
        snapshot = self.tools.accessible_snapshot
        owner = {symbol.id: symbol.file_id for symbol in snapshot.symbols}
        files = {source.id for source in snapshot.files}
        known = set(owner) | files
        neighbours = []
        for relationship in snapshot.relationships:
            if relationship.resolution != "internal":
                continue
            for origin, other in ((relationship.source_id, relationship.target_id),
                                  (relationship.target_id, relationship.source_id)):
                if origin in known and other in known and owner.get(origin, origin) in file_ids:
                    target = owner.get(other, other)
                    if target in files and target not in file_ids:
                        neighbours.append(target)
        return list(dict.fromkeys(neighbours))

    def endpoint_reads(self, scope_paths, roles, references):
        """Unread neighbours of the cited files.

        Isolation and absence-of-cycles evidence necessarily lives outside the declared
        scope, and scope can only widen once support exists. Without this the model names
        the composition site in prose and never reads it, which is exactly what the host
        then has to reject. These are navigation hints; they never widen scope_paths.
        """
        snapshot = self.tools.accessible_snapshot
        cited = {source.id for source in snapshot.files if source.path in scope_paths}
        if not cited:
            return []
        sources = {source.id: source for source in snapshot.files}
        suggestions = []
        for file_id in self.related_file_ids(cited):
            suggestions.extend(self.ranked_source_reads([self.request.objective], [sources[file_id].path],
                references, roles=roles, limit=3 - len(suggestions)))
            if len(suggestions) >= 3:
                break
        return suggestions

    def prepare_structured_result(self, node, result, state):
        if node != "review_findings" or not isinstance(result, BoundaryReview):
            return result
        evaluation = state["evaluation"]
        candidates = {item.id: item for item in evaluation.candidates} if evaluation else {}
        issues, normalized = [], []
        self._review_repair_needed = False
        if candidates and any(item.finding_id not in candidates for item in result.findings):
            issues.append("review_unknown_candidates")
            # Judging hypotheses instead of candidates is a metadata defect the host can
            # name exactly. One bounded correction is warranted even when the candidate
            # also has support issues, which would otherwise suppress every retry.
            self._review_repair_needed = True
        elif not candidates and result.findings:
            # Nothing was available to review; the stray judgments are dropped below
            # without misreporting them as unknown candidate identifiers.
            issues.append("review_judgments_without_candidates")
        for identifier, candidate in candidates.items():
            matches = [item for item in result.findings if item.finding_id == identifier]
            check = self.claim_check(evaluation, "candidate", identifier)
            expected = {support.evidence_id for support in check.support} if check else set()
            codes = []
            if not matches and identifier in self._valid_reviews:
                normalized.append(self._valid_reviews[identifier])
                continue
            if not matches:
                codes.append("review_missing_candidate")
                item = BoundaryFindingReview(finding_id=identifier, status="insufficient_evidence",
                    rationale=("No judgment was supplied for this candidate; the review answered other subjects."
                        if result.findings else "No review was supplied for this candidate."),
                    severity=candidate.severity, confidence=0)
            else:
                item = matches[0]
                if any(other != item for other in matches[1:]):
                    codes.append("review_conflicting_candidate_judgments")
                elif len(matches) > 1:
                    issues.append(f"{identifier}: review_duplicate_candidate_collapsed")
            support_issues = self.support_issues(candidate, check)
            if item.status == "accepted":
                if not item.scope_supported:
                    codes.append("review_scope_not_supported")
                if not expected or not expected <= set(item.checked_evidence_ids):
                    codes.append("review_checked_evidence_incomplete")
                if set(item.checked_evidence_ids) - {ref.id for ref in self.references()}:
                    codes.append("review_checked_evidence_unknown")
                if item.unverified_claims:
                    codes.append("review_has_unverified_claims")
                if support_issues:
                    codes.extend(support_issues)
            if codes:
                self._review_repair_needed |= not support_issues
                issues.extend(f"{identifier}: {code}" for code in codes)
                item = item.model_copy(update={"status": "insufficient_evidence", "confidence": 0,
                    "scope_supported": False, "rationale": "Unverified model judgment (not an audit conclusion): "
                        + item.rationale + "\nHost review validation: " + ", ".join(codes),
                    "unverified_claims": list(dict.fromkeys([*item.unverified_claims, *support_issues]))})
            elif item.status in {"accepted", "rejected"}:
                self._valid_reviews[identifier] = item
            normalized.append(item)
        hypotheses, hypothesis_issues = self.normalize_hypothesis_reviews(result, evaluation)
        issues.extend(hypothesis_issues)
        prior_issues = (state["review"].validation_issues if isinstance(state["review"], BoundaryReview)
            and self._reviewed_evaluation_key == self.review_key(evaluation) else [])
        self._reviewed_evaluation_key = self.review_key(evaluation)
        return result.model_copy(update={"findings": normalized, "hypotheses": hypotheses,
            "validation_issues": list(dict.fromkeys([*prior_issues, *result.validation_issues, *issues]))})

    @staticmethod
    def review_key(evaluation):
        if evaluation is None:
            return None
        return json.dumps({"candidates": [item.model_dump() for item in evaluation.candidates],
            "hypotheses": [item.model_dump() for item in evaluation.hypotheses],
            "claim_checks": [item.model_dump() for item in evaluation.claim_checks]}, sort_keys=True)

    def normalize_hypothesis_reviews(self, review, evaluation):
        """Syntax-valid imports cannot resolve a broader architectural question alone."""
        subjects = {item.id: item for item in evaluation.hypotheses
            if item.status in {"confirmed", "discarded"}} if evaluation else {}
        delivered = {ref.id for ref in self.references()}
        normalized, issues = [], []
        if any(item.hypothesis_id not in subjects for item in review.hypotheses):
            issues.append("review_unknown_hypotheses")
            self._review_repair_needed = True
        for identifier, subject in subjects.items():
            matches = [item for item in review.hypotheses if item.hypothesis_id == identifier]
            check = self.claim_check(evaluation, "hypothesis", identifier)
            support_issues = self.support_issues(subject, check)
            expected = set(subject.evidence_ids) | ({item.evidence_id for item in check.support} if check else set())
            if not matches and identifier in self._valid_hypothesis_reviews:
                normalized.append(self._valid_hypothesis_reviews[identifier])
                continue
            item = matches[0] if matches else BoundaryHypothesisReview(hypothesis_id=identifier,
                status="inconclusive", rationale="Semantic review of this hypothesis was not supplied.")
            codes = [] if matches else ["review_missing_hypothesis"]
            if any(other != item for other in matches[1:]):
                codes.append("review_conflicting_hypothesis_judgments")
            if item.status == "supported":
                if not item.scope_supported:
                    codes.append("review_hypothesis_scope_not_supported")
                if not expected or not expected <= set(item.checked_evidence_ids):
                    codes.append("review_hypothesis_evidence_incomplete")
                if set(item.checked_evidence_ids) - delivered:
                    codes.append("review_hypothesis_evidence_unknown")
                if item.unverified_claims:
                    codes.append("review_hypothesis_has_unverified_claims")
                codes.extend(support_issues)
            if codes:
                self._review_repair_needed |= not support_issues
                issues.extend(f"{identifier}: {code}" for code in codes)
                item = item.model_copy(update={"status": "inconclusive", "scope_supported": False,
                    "rationale": "Unverified model judgment (not an audit conclusion): " + item.rationale,
                    "unverified_claims": list(dict.fromkeys([*item.unverified_claims, *codes]))})
            else:
                self._valid_hypothesis_reviews[identifier] = item
            normalized.append(item)
        return normalized, issues

    def finalize(self, state):
        if state["review"] and self._reviewed_evaluation_key != self.review_key(state["evaluation"]):
            state = {**state, "review": None}
        result = super().finalize(state)["result"]
        evaluated, pending = [], []
        for ref in self.references():
            key = (ref.file_id, ref.content_hash, ref.kind, ref.start_line, ref.end_line)
            (evaluated if self._evaluated_evidence is not None and key in self._evaluated_evidence else pending).append(ref.id)
        status = "not_evaluated" if self._evaluated_evidence is None else "stale" if pending else "current"
        limitations = list(result.limitations)
        gaps = list(result.missing_information)
        if pending:
            message = "Retained evidence pending evaluation: " + ", ".join(pending) + ". Prior conclusions do not evaluate these excerpts."
            limitations.append(message)
            gaps.append(message)
        if self._review_skipped_no_candidates:
            limitations = [item for item in limitations if item != "Critical review was not completed; no candidate is accepted."]
            limitations.append("Candidate review was not requested because there were no candidates and no syntax-supported resolved hypotheses; this does not verify unresolved hypotheses.")
        result = result.model_copy(update={"investigation_coverage": self.discovery.coverage(
                self.references(), self.tools.tool_measurements),
            "request_fingerprint": self._request_fingerprint,
            "investigation_tasks": self._research_tasks, "investigation_progress": self._round_progress,
            "consumption_by_phase": self._phase_consumption,
            "continuation_usage": {key: getattr(self._baseline, key) + self._baseline.continuation_usage.get(key, 0) for key in (
                "model_calls", "tool_calls", "accounted_tokens", "estimated_tokens")} if self._baseline else {},
            "evaluation_evidence_status": status, "evaluated_evidence_ids": evaluated,
            "pending_evaluation_evidence_ids": pending, "missing_information": gaps, "limitations": limitations})
        evaluation = state["evaluation"]
        if evaluation is None:
            return {"result": result}
        findings, hypotheses = [], []
        gaps = list(result.missing_information)
        candidates = {item.id: item for item in evaluation.candidates}
        for finding in result.findings:
            check = self.claim_check(evaluation, "candidate", finding.id)
            issues = self.support_issues(candidates[finding.id], check)
            _, evidence_issues = self.evidence_issues(candidates[finding.id].evidence_ids,
                {ref.id: ref for ref in self.references()})
            criterion = next((item for item in self.request.criteria if item.id == finding.criterion_id), None)
            if candidates[finding.id].kind == "violation" and criterion and criterion.origin != "explicit":
                evidence_issues.append("violation_requires_explicit_criterion")
            issues = list(dict.fromkeys([*evidence_issues, *issues]))
            updates = {"claim_check": check, "validation_issues": issues}
            if issues:
                updates.update(validation_status="insufficient_evidence", confidence=0,
                    review_rationale=finding.review_rationale + "\nBoundary host validation failed: " + ", ".join(issues))
                gaps.append(f"Candidate {finding.id}: {', '.join(issues)}.")
            if issues or finding.validation_status == "insufficient_evidence":
                updates.update(description="Unverified candidate (not an audit conclusion): " + finding.description,
                    justification="Unverified model proposal: " + finding.justification,
                    modularity_impact="Unverified potential impact: " + finding.modularity_impact,
                    recommendation="Conditional proposal; verify the candidate before applying: " + finding.recommendation)
            findings.append(finding.model_copy(update=updates))
        for hypothesis in result.hypotheses:
            original = self._planned_hypotheses.get(hypothesis.id)
            if original is not None and original.question != hypothesis.question:
                hypothesis = hypothesis.model_copy(update={"question": original.question, "status": "inconclusive",
                    "rationale": "boundary_hypothesis_question_changed: Unverified reformulation of the original question: " + hypothesis.question
                        + "\n" + hypothesis.rationale})
                gaps.append(f"Hypothesis {hypothesis.id}: boundary_hypothesis_question_changed.")
            if hypothesis.status in {"confirmed", "discarded"}:
                check = self.claim_check(evaluation, "hypothesis", hypothesis.id)
                issues = self.support_issues(hypothesis, check)
                judgment = next((item for item in state["review"].hypotheses
                    if item.hypothesis_id == hypothesis.id), None) if state["review"] else None
                if judgment is None:
                    issues.append("boundary_hypothesis_semantic_review_missing")
                elif judgment.status != "supported":
                    issues.append("boundary_hypothesis_semantic_review_inconclusive")
                    issues.extend(judgment.unverified_claims)
                if issues:
                    reason = ", ".join(issues)
                    hypothesis = hypothesis.model_copy(update={"status": "inconclusive",
                        "rationale": "Unverified model proposal; this hypothesis remains inconclusive: "
                            + hypothesis.rationale + "\nBoundary host validation: " + reason
                            + ("\nSemantic review: " + judgment.rationale if judgment else "")})
                    gaps.append(f"Hypothesis {hypothesis.id}: {reason}.")
            hypotheses.append(hypothesis)
        termination = result.termination_reason
        if termination == "sufficient_evidence" and (gaps or any(item.validation_status == "insufficient_evidence" for item in findings)):
            termination = "evidence_validation_failed"
        return {"result": result.model_copy(update={"findings": findings, "hypotheses": hypotheses,
            "claim_checks": evaluation.claim_checks, "missing_information": list(dict.fromkeys(gaps)),
            "critical_review": state["review"],
            "failed_evaluation_attempt": self.failed_evaluation_attempt,
            "evaluation_attempt_issues": self._structure_issues if self.failed_evaluation_attempt else [],
            "limitations": [*result.limitations,
                "Boundary role checks verify cited Python/JS/TS syntax or TOML declarations, not runtime isolation. Unsupported syntax cannot establish a role; semantic scope remains subject to critical review."],
            "termination_reason": termination})}

    async def review_findings(self, state):
        if (state["evaluation"] is not None and not state["evaluation"].candidates
                and not any(item.status in {"confirmed", "discarded"}
                    and not self.support_issues(item, self.claim_check(state["evaluation"], "hypothesis", item.id))
                    for item in state["evaluation"].hypotheses)):
            self._review_skipped_no_candidates = True
            return {"review": None, "termination_reason": self.review_termination_reason(state), "model_calls": self.calls}
        if self._review_started_calls is None:
            self._review_started_calls = self.calls
        update = await super().review_findings(state)
        if (update["review"] is None and isinstance(state["review"], BoundaryReview)
                and self._reviewed_evaluation_key == self.review_key(state["evaluation"])):
            update["review"] = state["review"]
        review = update["review"]
        gaps = [f"Candidate {item.finding_id}: {claim}" for item in review.findings
            if item.status == "insufficient_evidence" for claim in item.unverified_claims] if review else []
        if review:
            gaps.extend(f"Hypothesis {item.hypothesis_id}: {claim}" for item in review.hypotheses
                if item.status == "inconclusive" for claim in (item.unverified_claims or [item.rationale]))
        update["missing_information"] = list(dict.fromkeys([
            *[item for item in state["missing_information"] if item not in self._review_gap_messages], *gaps]))
        self._review_gap_messages = gaps
        if review and state["evaluation"]:
            evaluation = state["evaluation"]
            refs = {ref.id: ref for ref in self.references()}
            for kind, subjects, judgments, key in (
                    ("candidate", evaluation.candidates, review.findings, "finding_id"),
                    ("hypothesis", evaluation.hypotheses, review.hypotheses, "hypothesis_id")):
                for subject in subjects:
                    judgment = next((item for item in judgments if getattr(item, key) == subject.id), None)
                    if judgment is None or judgment.status not in {"insufficient_evidence", "inconclusive"}:
                        continue
                    if not any(task["subject_type"] == kind and task["id"] == subject.id for task in self.evidence_recovery_tasks):
                        self.evidence_recovery_instruction(kind, subject.id, [],
                            [refs[item] for item in subject.evidence_ids if item in refs], refs,
                            question=getattr(subject, "question", getattr(subject, "description", "")),
                            evidence_needed=[judgment.rationale])
                        self.evidence_recovery_tasks[-1].update(action="inspect_semantic_review_gap",
                            issues=judgment.unverified_claims)
            self._research_tasks = self.research_tasks(evaluation)
        return update

    def route_review(self, state):
        review = state["review"]
        if (review and self._review_repair_needed and (not self.stop or self.can_review_stopped(state))
                and self.calls - self._review_started_calls < 1 + self.config.max_schema_retries
                and self.calls < self.call_limit and self.remaining_seconds() > 0):
            return "review_findings"
        actionable = review and (any(item.status == "insufficient_evidence" and item.unverified_claims for item in review.findings)
            or any(item.status == "inconclusive" and (not item.unverified_claims
                or any(not claim.startswith("review_") for claim in item.unverified_claims))
                for item in review.hypotheses))
        if (actionable and not self.stop and not self.provenance_blocked
                and state["iterations"] < self.config.max_iterations
                and self.calls < self.call_limit - self.closing_call_reserve
                and self.tools.budget_usage.tool_calls < self.tool_limit and self.remaining_seconds() > 0):
            return "investigate"
        return "finalize"
