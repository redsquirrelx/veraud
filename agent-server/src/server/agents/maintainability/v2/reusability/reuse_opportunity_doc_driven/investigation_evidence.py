"""Deterministic admissibility checks, not an automatic semantic-equivalence oracle."""

from pydantic_core import PydanticCustomError

from server.runtimes.repository.access import (
    RepositoryAccessError,
    repository_relative_path,
)

from .investigation_workspace import missing_ranges
from .schemas import ReuseInvestigationTurn


def invalid(code):
    return PydanticCustomError(code, ReuseInvestigationTurn.validation_feedback.get(code, code))


class ReuseEvidenceGate:
    def _active_references(self, state):
        delivered = self._delivered_ids(state)
        return {record.id: record for record in self.references() if record.id in delivered}

    def _symbol_map(self):
        return self._indexes()[2]

    @staticmethod
    def _symbol_covered(symbol, references):
        ranges = [(ref.start_line, ref.end_line) for ref in references if ref.kind == "source"
            and ref.file_id == symbol.file_id and ref.start_line is not None and ref.end_line is not None]
        return not list(missing_ranges(symbol.start_line, symbol.end_line, ranges))

    def _resolve_implementation(self, value):
        parts = value.split("#", 1)
        try:
            path = repository_relative_path(parts[0])
        except RepositoryAccessError:
            raise invalid("candidate_independent_implementation") from None
        file = next((item for item in self.tools.accessible_snapshot.files if item.path == path), None)
        if file is None or (len(parts) == 2 and not parts[1].strip()):
            raise invalid("candidate_independent_implementation")
        symbols = [item for item in self.tools.accessible_snapshot.symbols if item.file_id == file.id]
        if len(parts) == 2:
            # No suffix/fuzzy matching: a valid-looking but different symbol is not sufficient.
            symbols = [item for item in symbols if parts[1] in {item.id, item.name, item.qualified_name}]
            if len(symbols) != 1:
                raise invalid("candidate_independent_implementation")
        return path, {symbol.id for symbol in symbols}

    def _validate_comparisons(self, comparisons, state):
        references, symbols = self._active_references(state), self._symbol_map()
        for comparison in comparisons:
            if (comparison.shared_symbol_id == comparison.other_symbol_id
                    or comparison.shared_symbol_id not in symbols or comparison.other_symbol_id not in symbols):
                raise invalid("comparison_invalid")
            if set(comparison.shared_evidence_ids + comparison.other_evidence_ids) - references.keys():
                raise invalid("unknown_or_undelivered_evidence")
            # Coverage of the cited symbol bodies is an evidence gate below,
            # not a structural error that should consume a schema-only retry.
            if (comparison.outcome == "correct_reuse" and comparison.other_role != "consumer"
                    or comparison.outcome == "equivalent_shareable" and comparison.other_role != "independent_implementation"):
                raise invalid("comparison_invalid")

    def _validate_turn(self, turn, state):
        task = self._current(state)
        self._validate_comparisons(turn.comparisons, state)
        if set(turn.read_document_claim_ids) - self._documentary_context(state)["claims"].keys():
            raise invalid("claim_evidence_not_in_conclusion")
        if turn.action == "tools":
            if (not turn.queries and not turn.read_document_claim_ids) or turn.conclusion is not None:
                raise invalid("tools_requires_queries_without_conclusion")
            for query in turn.queries:
                self._normalize_query(query, task)
            return
        result = turn.conclusion
        if turn.queries or turn.read_document_claim_ids or result is None or result.investigation_id != task.id:
            raise invalid("close_requires_current_investigation_conclusion")
        if (result.status == "reuse_opportunity") != bool(result.candidates):
            raise invalid("candidate_status_mismatch")
        if result.status == "inconclusive" and not result.limitations:
            raise invalid("inconclusive_requires_reason")
        self._validate_comparisons(result.comparisons, state)
        references, symbols = self._active_references(state), self._symbol_map()
        files = {file.path: file for file in self.tools.accessible_snapshot.files}
        examined = self._examined_relationships(state)
        for subject in [result, *result.candidates]:
            if set(subject.evidence_ids) - references.keys():
                raise invalid("unknown_or_undelivered_evidence")
            if set(subject.components) - files.keys():
                raise invalid("candidate_component_uninspected")
            if set(subject.components) - set(result.components):
                raise invalid("candidate_component_uninspected")
            if set(subject.relationship_ids) - examined.keys():
                raise invalid("unexamined_relationship")
            if set(subject.symbol_ids) - symbols.keys():
                raise invalid("uninspected_symbol")
            if set(subject.evidence_ids) - set(result.evidence_ids):
                raise invalid("unknown_or_undelivered_evidence")
            if result.status == "inconclusive":
                paths = {references[key].path for key in subject.evidence_ids if references[key].kind == "source"}
                if set(subject.components) - paths:
                    raise invalid("uninspected_component")
        seen = set()
        allowed_claims = self._documentary_context(state)["claims"]
        for assessment in result.claim_assessments:
            if assessment.claim_id in seen or assessment.claim_id not in allowed_claims:
                raise invalid("duplicate_claim_assessment")
            seen.add(assessment.claim_id)
            if set(assessment.code_evidence_ids) - set(result.evidence_ids):
                raise invalid("claim_evidence_not_in_conclusion")
        for candidate in result.candidates:
            if candidate.criterion_id not in {item.id for item in self.request.criteria}:
                raise invalid("comparison_invalid")
            if set(candidate.document_claim_ids) - seen:
                raise invalid("candidate_document_claim_unassessed")
            shared_path, shared_locations = self._resolve_implementation(candidate.shared_component)
            shared, independent = set(candidate.shared_symbol_ids), set(candidate.independent_symbol_ids)
            if shared & independent or not (shared | independent) <= symbols.keys():
                raise invalid("candidate_symbol_mismatch")
            if shared_path not in candidate.components:
                raise invalid("candidate_shared_component")
            if not shared <= shared_locations:
                raise invalid("candidate_shared_component")
            for identifier in shared:
                if symbols[identifier].file_id != files[shared_path].id:
                    raise invalid("candidate_shared_component")
            matched = set()
            for value in candidate.independent_implementations:
                path, identifiers = self._resolve_implementation(value)
                if path not in candidate.components or not identifiers & independent:
                    raise invalid("candidate_independent_implementation")
                matched.update(identifiers & independent)
            if matched != independent:
                raise invalid("candidate_independent_implementation")

    def _coverage_gap(self, state, task, references, conclusion=None):
        source = [ref for ref in references if ref.kind == "source"]
        gaps = []
        workspace = state.get("investigation_workspace", {})
        symbols = self._symbol_map()
        entities = workspace.get("entities", {})
        provider_symbols = [symbols[key] for key, entity in entities.items()
            if key in symbols and "provider" in entity["roles"]]
        if not source:
            gaps.append("provider_source_missing")
        elif provider_symbols and not any(self._symbol_covered(symbol, source) for symbol in provider_symbols):
            gaps.append("provider_behavior_incomplete")
        others = [symbol for key, entity in entities.items() if (symbol := symbols.get(key))
            and symbol.id not in {item.id for item in provider_symbols}
            and any(role in entity["roles"] for role in ("consumer", "alternative"))]
        if not any(self._symbol_covered(symbol, source) for symbol in others):
            gaps.append("consumer_or_alternative_source_missing")
        comparisons = workspace.get("comparisons", [])
        if not comparisons:
            gaps.append("functional_comparison_missing")
        if conclusion is None or conclusion.status == "inconclusive":
            return gaps
        cited = self._active_references(state)
        cited = {key: cited[key] for key in conclusion.evidence_ids if key in cited}
        exposed = workspace.get("exposed_source_ids", [])
        if conclusion.scope != "inspected":
            gaps.append("scope_not_supported")
        inspected_paths = {ref.path for ref in cited.values() if ref.kind == "source"}
        scope = set(conclusion.inspected_scope or conclusion.components)
        if not scope or scope - inspected_paths or set(conclusion.components) - scope:
            gaps.append("scope_not_supported")
        for path in conclusion.components:
            if path not in inspected_paths:
                gaps.append("component_source_missing:" + path)
        gaps.extend("source_provenance:" + issue for issue in self.evidence_issues(conclusion.evidence_ids, cited)[1])
        for identifier in conclusion.symbol_ids:
            if not self._symbol_covered(symbols[identifier], cited.values()):
                gaps.append("symbol_behavior_incomplete:" + identifier)
        usable = []
        for comparison in comparisons:
            pair_refs = comparison["shared_evidence_ids"] + comparison["other_evidence_ids"]
            if set(pair_refs) - cited.keys():
                continue
            if set(pair_refs) - set(exposed):
                continue
            if comparison["outcome"] == "insufficient":
                continue
            if all(self._symbol_covered(symbols[identifier], [cited[key] for key in evidence_ids])
                    for identifier, evidence_ids in [(comparison["shared_symbol_id"], comparison["shared_evidence_ids"]),
                        (comparison["other_symbol_id"], comparison["other_evidence_ids"])]):
                usable.append(comparison)
        if not usable:
            gaps.append("functional_comparison_missing")
        # Once an explicit full-source comparison exists, it supplies roles more
        # precisely than structural discovery hints (which can be ambiguous).
        else:
            gaps = [gap for gap in gaps if gap not in {
                "provider_behavior_incomplete", "consumer_or_alternative_source_missing", "functional_comparison_missing"}]
        for assessment in conclusion.claim_assessments:
            evidence = [cited[key] for key in assessment.code_evidence_ids if key in cited]
            paths = {ref.path for ref in evidence if ref.kind == "source"}
            needs_source = assessment.status in {"supported", "contradicted"} or (
                assessment.status == "not_applicable" and assessment.code_evidence_ids)
            if assessment.status == "inconclusive":
                gaps.append("claim_unresolved:" + assessment.claim_id)
            elif needs_source and (
                    not paths or not assessment.scope_paths or set(assessment.scope_paths) - paths):
                gaps.append("claim_source_missing:" + assessment.claim_id)
        if conclusion.status == "reuse_opportunity":
            for candidate in conclusion.candidates:
                source_refs = [cited[key] for key in candidate.evidence_ids if key in cited]
                for identifier in candidate.shared_symbol_ids + candidate.independent_symbol_ids:
                    if not self._symbol_covered(symbols[identifier], source_refs):
                        gaps.append("candidate_symbol_unread:" + identifier)
                for independent in candidate.independent_symbol_ids:
                    if not any(item["shared_symbol_id"] in candidate.shared_symbol_ids
                            and item["other_symbol_id"] == independent
                            and item["other_role"] == "independent_implementation"
                            and item["outcome"] == "equivalent_shareable" for item in usable):
                        gaps.append("independent_behavior_not_demonstrated:" + independent)
                issues = self.evidence_issues(candidate.evidence_ids, cited)[1]
                if issues:
                    gaps.extend("candidate_provenance:" + issue for issue in issues)
        elif any(item["outcome"] == "equivalent_shareable" for item in usable):
            gaps.append("unresolved_shareable_comparison")
        return list(dict.fromkeys(gaps))
