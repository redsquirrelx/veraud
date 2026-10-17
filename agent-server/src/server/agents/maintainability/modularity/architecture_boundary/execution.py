"""Boundary-specific support requirements, distinct from citation/provenance validation."""

import json
from pathlib import Path
from types import SimpleNamespace

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic_core import PydanticCustomError

from .....runtimes.investigation.agent import InvestigationExecution
from .....runtimes.investigation.messages import compact_tool_history, empty_ai_message
from .....runtimes.investigation.provider import lean_schema
from ....schemes.investigator import (
    BoundaryEvaluation,
    BoundaryFinding,
    BoundaryFindingReview,
    BoundaryResult,
    BoundaryReview,
)
from .discovery import BoundaryDiscovery
from .support import supports_role

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
}
CLAIM_KINDS = tuple(CLAIM_REQUIREMENTS)
COVERAGE_DEMANDING = frozenset({"isolation", "absence_of_cycles"})

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
        self._evaluated_evidence = None
        self._preserved_valid_evaluation = False
        self.failed_evaluation_attempt = None
        self.discovery = BoundaryDiscovery(tools.accessible_snapshot)
        self._progress = None
        self._stale_turns = 0
        self._progress_warning = False
        self._closing_budget_reserved = False
        super().__init__(model, config, tools, request)

    def structured_schema(self, schema):
        # Provider generation uses a reduced schema; parse_structured still
        # validates the complete canonical contract and all local bounds.
        return lean_schema(schema) if isinstance(self.model, BaseChatModel) else schema

    def closing_token_reserve(self, node, request_reserve):
        if node == "investigate":
            reserve = min(self.token_limit // 3, 2 * request_reserve)
        elif node == "evaluate_evidence":
            reserve = min(self.token_limit // 6, request_reserve)
        else:
            return 0
        if self.tokens + request_reserve + reserve > self.token_limit:
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
        context["remaining_accounted_tokens"] = max(0, self.token_limit - self.tokens)
        context["closing_due_to_token_budget"] = self._closing_budget_reserved
        return context

    def provider_history(self, state, messages, *, overhead_characters=0, node=None):
        pinned = {identifier for item in state["hypotheses"] for identifier in item.evidence_ids}
        if state["evaluation"]:
            pinned.update(identifier for item in state["evaluation"].candidates for identifier in item.evidence_ids)
        used = len(json.dumps([item.model_dump() for item in messages], default=str)) + overhead_characters
        # Compact before hitting the hard cap, rather than repeatedly paying for
        # discovery inventories that are already represented in current state.
        allowance = max(0, int(self.config.max_context_characters * 0.4) - used)
        return compact_tool_history(state["messages"], allowance, pinned,
            compact_metadata=node in {"evaluate_evidence", "review_findings"})

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
        self._review_started_calls = None

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
        coverage = self.discovery.coverage(self.references())
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
        context["prioritized_source_reads"] = self.ranked_source_reads(texts, (), self.references(), limit=6)
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
        if state["review"]:
            context["prior_critical_review"] = state["review"].model_dump()
        return context

    async def evaluate_evidence(self, state):
        self._last_parsed_evaluation = None
        self._structure_issues = []
        closing_stop = self.stop if self._closing_budget_reserved and self.stop == "token_limit" else ""
        if closing_stop:
            self.stop = ""
        try:
            update = await super().evaluate_evidence(state)
        finally:
            if closing_stop and not self.stop:
                self.stop = closing_stop
        # A parsed but structurally unrepairable response remains useful partial
        # work; it must not lose all candidates merely because corrections ran out.
        if self.stop and self._last_parsed_evaluation and self._structure_issues:
            self.failed_evaluation_attempt = self._last_parsed_evaluation
            self._preserved_valid_evaluation = state["evaluation"] is not None
            partial = state["evaluation"] or self._last_parsed_evaluation.model_copy(update={"sufficient": False})
            update.update(evaluation=partial, hypotheses=state["hypotheses"] if self._preserved_valid_evaluation else partial.hypotheses,
                missing_information=list(dict.fromkeys([*partial.missing_information,
                    "Boundary claim-check structure could not be corrected within the available budget."])))
        if update["evaluation"] and not self.stop:
            self._evaluated_evidence = self.evidence_fingerprint()
        return update

    def evidence_fingerprint(self):
        return frozenset((record.file_id, record.content_hash, record.kind, record.start_line, record.end_line)
            for record in self.tools.retrieved_evidence)

    async def investigate(self, state):
        fingerprint = self.evidence_fingerprint()
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
        issues, roles, paths = self.scope_issues(subject, check), set(), set()
        for item in check.support:
            ref = references.get(item.evidence_id)
            if ref is None or item.evidence_id not in subject.evidence_ids:
                issues.append("boundary_support_not_cited")
                continue
            if ref.path not in check.scope_paths:
                issues.append("boundary_support_outside_declared_scope")
            key = (ref.file_id, ref.start_line, ref.end_line, item.role)
            if key not in self._support_cache:
                self._support_cache[key] = supports_role(files[ref.file_id], ref, item.role)
            if not self._support_cache[key]:
                issues.append("boundary_support_role_not_observed:" + item.role)
                continue
            roles.add(item.role)
            paths.add(ref.path)
        issues.extend("boundary_missing_role:" + role for role in sorted(CLAIM_REQUIREMENTS[check.claim_kind] - roles))
        if not set(check.scope_paths) <= paths:
            issues.append("boundary_scope_not_inspected")
        if check.claim_kind in COVERAGE_DEMANDING:
            if not check.coverage_complete or check.limitations:
                issues.append("boundary_coverage_incomplete")
            if len(paths) < 2:
                issues.append("boundary_endpoints_not_inspected")
            issues.extend(self.discovery.claim_issues(check, paths, references.values()))
        return list(dict.fromkeys(issues))

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
            if satisfied and len(satisfied) < len(CLAIM_KINDS):
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
                if check.claim_kind in {"isolation", "absence_of_cycles"} and (
                        "boundary_endpoints_not_inspected" in issues or task["required_roles"]):
                    task["endpoint_source_reads"] = self.endpoint_reads(
                        check.scope_paths, task["required_roles"] or NAVIGATION_ROLES, refs)
            if "boundary_scope_unrelated_to_subject" in issues:
                gaps.append(f"{kind} {subject.id}: boundary_scope_unrelated_to_subject. The declared scope "
                    f"{', '.join(check.scope_paths) if check else '(none)'} shares nothing with what this "
                    "question names. Inspect and cite the named scope, or narrow the conclusion to what the "
                    "inspected files actually cover.")
            narrowing = (f" The inspected support carries these claim kinds: {', '.join(satisfied)}. "
                "Re-declare the check with one of them, or inspect the missing roles before claiming a "
                "stronger kind." if satisfied and len(satisfied) < len(CLAIM_KINDS) else "")
            gaps.append(f"{kind} {subject.id}: {', '.join(issues)}.{narrowing} " + ("No delivered source evidence supports this "
                "subject; inspect the source and callers it requires or keep it inconclusive. A conclusion that was "
                "never read cannot be asserted." if unevidenced else "Inspect implementation/usage/composition as "
                "required, or narrow the actual conclusion and its claim_kind together. Comments are declarations "
                "of intent, not implementation evidence."))
        self.ground_unresolved_tasks(evaluation)
        return gaps

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
                if set(item.checked_evidence_ids) != expected or not expected:
                    codes.append("review_checked_evidence_incomplete")
                if item.unverified_claims:
                    codes.append("review_has_unverified_claims")
                if support_issues:
                    codes.extend(support_issues)
            if codes:
                self._review_repair_needed |= not support_issues
                issues.extend(f"{identifier}: {code}" for code in codes)
                item = item.model_copy(update={"status": "insufficient_evidence", "confidence": 0,
                    "scope_supported": False, "rationale": item.rationale + "\nHost review validation: " + ", ".join(codes),
                    "unverified_claims": list(dict.fromkeys([*item.unverified_claims, *support_issues]))})
            elif item.status in {"accepted", "rejected"}:
                self._valid_reviews[identifier] = item
            normalized.append(item)
        prior_issues = state["review"].validation_issues if isinstance(state["review"], BoundaryReview) else []
        return result.model_copy(update={"findings": normalized,
            "validation_issues": list(dict.fromkeys([*prior_issues, *result.validation_issues, *issues]))})

    def finalize(self, state):
        result = super().finalize(state)["result"]
        result = result.model_copy(update={"investigation_coverage": self.discovery.coverage(self.references())})
        evaluation = state["evaluation"]
        if evaluation is None:
            return {"result": result}
        findings, hypotheses = [], []
        gaps = list(result.missing_information)
        candidates = {item.id: item for item in evaluation.candidates}
        for finding in result.findings:
            check = self.claim_check(evaluation, "candidate", finding.id)
            issues = self.support_issues(candidates[finding.id], check)
            updates = {"claim_check": check, "validation_issues": issues}
            if issues:
                updates.update(validation_status="insufficient_evidence", confidence=0,
                    review_rationale="Boundary host validation failed: " + ", ".join(issues))
                gaps.append(f"Candidate {finding.id}: {', '.join(issues)}.")
            findings.append(finding.model_copy(update=updates))
        for hypothesis in result.hypotheses:
            if hypothesis.status in {"confirmed", "discarded"}:
                check = self.claim_check(evaluation, "hypothesis", hypothesis.id)
                issues = self.support_issues(hypothesis, check)
                if issues:
                    reason = ", ".join(issues)
                    hypothesis = hypothesis.model_copy(update={"status": "inconclusive",
                        "rationale": hypothesis.rationale + "\nBoundary host validation: " + reason})
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
        if self._review_started_calls is None:
            self._review_started_calls = self.calls
        update = await super().review_findings(state)
        if update["review"] is None and isinstance(state["review"], BoundaryReview):
            update["review"] = state["review"]
        review = update["review"]
        gaps = [f"Candidate {item.finding_id}: {claim}" for item in review.findings
            if item.status == "insufficient_evidence" for claim in item.unverified_claims] if review else []
        if gaps:
            update["missing_information"] = list(dict.fromkeys([*state["missing_information"], *gaps]))
            if state["evaluation"]:
                update["evaluation"] = state["evaluation"].model_copy(update={
                    "sufficient": False, "missing_information": update["missing_information"],
                })
        return update

    def route_review(self, state):
        review = state["review"]
        if (review and self._review_repair_needed and (not self.stop or self.can_review_stopped(state))
                and self.calls - self._review_started_calls < 1 + self.config.max_schema_retries
                and self.calls < self.call_limit and self.remaining_seconds() > 0):
            return "review_findings"
        actionable = review and any(item.status == "insufficient_evidence" and item.unverified_claims for item in review.findings)
        if (actionable and not self.stop and not self.provenance_blocked
                and state["iterations"] < self.config.max_iterations
                and self.calls < self.call_limit - self.closing_call_reserve
                and self.tools.budget_usage.tool_calls < self.tool_limit and self.remaining_seconds() > 0):
            return "investigate"
        return "finalize"
