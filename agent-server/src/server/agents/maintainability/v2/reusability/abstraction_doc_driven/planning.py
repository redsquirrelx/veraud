"""Documentary normalization and bounded abstraction planning.

Planning is deterministic and source-free: documentation seeds only explicit
abstraction mappings; a plan proposes questions about abstraction purposes,
never findings. Reading source belongs to investigate.
"""

import re
from collections import defaultdict
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel

from server.agents.architecture_context.schemas import (
    ArchitectureContextResult,
    KnowledgeClaim,
    KnowledgeEvidence,
)
from server.contracts.audit import Hypothesis
from server.services.document_indexing import IndexReference
from server.services.repository_analysis.context import create_identifier
from server.services.repository_analysis.testing import is_test_file

from .schemas import AbstractionCandidate, AbstractionDocumentClaim, AbstractionPlan

DIRECT_CATEGORIES = {"interfaces_and_contracts", "architectural_decisions", "components", "architectural_style"}
COMPLEMENTARY_CATEGORIES = {"relationships", "constraints"}
RELEVANT_CATEGORIES = DIRECT_CATEGORIES | COMPLEMENTARY_CATEGORIES
TESTING_MARKERS = ("vitest", "pytest", "fixture", "__tests__", "mock", "coverage")
# Placeholder required by the AbstractionCandidate contract in the deterministic menu;
# replaced at selection fusion by the LLM's obligation-derived requirements.
COMMON_EVIDENCE = ["Contract and declarations in the primary component",
    "Implementations and consumers identified from indexed relationships",
    "Documented purpose and constraints relevant to the abstraction"]


# --- documentary normalization -----------------------------------------------

def _as_mapping(value: Any, *, context: str) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"{context} must be an ArchitectureContextResult or a mapping, not {type(value).__name__}.")


def normalize_knowledge(context: ArchitectureContextResult | Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize documentary knowledge without inventing identity.

    The stable record ID is positional within one committed `ArchitectureContextResult`:
    `{document_index.index_id}:{zero_based_position}`. It identifies the claim in that
    context revision; it is not a content hash and must not survive reindexing.
    """
    if context is None:
        return []
    data = _as_mapping(context, context="context")
    knowledge = list(data.get("knowledge") or [])
    if not knowledge:
        return []

    document_index = data.get("document_index")
    if document_index is None:
        raise ValueError("documented_architecture.document_index is required to normalize documentary knowledge.")
    index = _as_mapping(document_index, context="context.document_index")
    index_id = index.get("index_id")
    if not isinstance(index_id, str) or not index_id.strip():
        raise ValueError("documented_architecture.document_index.index_id must be a non-empty string.")

    claims: list[dict[str, Any]] = []
    document_index_raw = data.get("document_index")
    document_index = None
    if isinstance(document_index_raw, BaseModel):
        document_index_raw = document_index_raw.model_dump(mode="json")
    if isinstance(document_index_raw, Mapping):
        try:
            document_index = IndexReference.model_validate({field: document_index_raw.get(field)
                for field in ("index_id", "repository_id", "commit")})
        except Exception:  # noqa: BLE001 - malformed index reference is degraded honestly
            document_index = None
    section_paths = data.get("section_paths")
    if not isinstance(section_paths, Mapping):
        section_paths = {}
    for index, entry in enumerate(knowledge):
        claim = KnowledgeClaim.model_validate(entry)
        evidence = [KnowledgeEvidence.model_validate(item).model_dump(mode="json") for item in claim.evidence]
        claims.append({
            "id": f"{index_id}:{index}",
            "category": claim.category,
            "subject": claim.subject,
            "statement": claim.statement,
            "related_subjects": list(claim.related_subjects),
            "certainty": claim.certainty,
            "constraint": claim.constraint,
            "section_ids": list(claim.section_ids),
            "evidence": evidence,
            "document_index": document_index.model_dump(mode="json") if document_index else None,
            "section_paths": {section_id: section_paths[section_id] for section_id in claim.section_ids
                if section_id in section_paths},
        })
    return claims


def _principal_statement(statement):
    """First complete sentence; other claims stay in document_claim_ids."""
    text = " ".join((statement or "").split())
    return re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()


GENERIC_TOP = {"lib", "src", "app", "main", "core"}


def nonproduction_path(path):
    lowered = path.casefold().replace("\\", "/")
    parts = PurePosixPath(lowered).parts
    return (is_test_file(lowered) or PurePosixPath(lowered).name == "conftest.py"
        or any(re.search(r"(?:^|[._-])(?:tests?|specs?|fixtures?|mocks?)(?:[._-]|$)", part)
               for part in parts))


def _matches_selector(value, file, symbols):
    return (value in (file.id, file.path, file.module_name)
        or file.path.startswith(value.rstrip("/") + "/")
        or (value in symbols and symbols[value].file_id == file.id))


def _normalized_symbol(value):
    """Strip separators/case for exact symbolic identity; never fuzzy matching."""
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def _symbol_explicit_strength(value, symbol):
    """Explicit reference to a documentary subject: the same identifier.

    Matching is case-insensitive and ignores separators between identifier
    segments (`LLM Provider`, `llm_provider`, `src/llm/provider.llm_provider`),
    but it is not semantic: no prefix, suffix, token or similarity matching.
    """
    lowered = _normalized_symbol(value)
    if len(lowered) < 4:
        return 0
    qualified = symbol.qualified_name.casefold()
    identifiers = {_normalized_symbol(symbol.name),
        _normalized_symbol(qualified),
        _normalized_symbol(qualified.split(".")[-1]),
        _normalized_symbol(symbol.id)}
    return 3 if lowered in identifiers else 0


def _base_token(base):
    return re.sub(r"\[.*?\]|<.*?>", "", str(base)).casefold().split(".")[-1].strip()


def _abstraction_kind(symbol):
    """Recognize interface-like constructs the index can see; not by name alone."""
    if symbol.kind == "interface":
        return "interface"
    if symbol.kind != "class":
        return None
    bases = {_base_token(base) for base in getattr(symbol, "base_names", ())}
    if bases & {"protocol"}:
        return "protocol"
    if bases & {"abc", "abcmeta"}:
        return "abstract_class"
    return None


def _name_index(symbols):
    index = defaultdict(list)
    qualified = defaultdict(list)
    for symbol in symbols.values():
        index[symbol.name.casefold()].append(symbol.id)
        qualified[symbol.qualified_name.casefold()].append(symbol.id)
    return index, qualified


def _implementations(symbol, symbols):
    """Classes whose bases reference the abstraction; no invented heritage."""
    targets = {symbol.name.casefold(), symbol.qualified_name.casefold().split(".")[-1]}
    implementations = []
    for other in symbols.values():
        if other.id == symbol.id or other.kind != "class":
            continue
        bases = {_base_token(base) for base in getattr(other, "base_names", ())}
        if bases & targets:
            implementations.append(other)
    return implementations


def _consumers(file_key, files, consumers_by_file):
    return sorted(consumers_by_file.get(file_key, ()))


def build_abstraction_plan(snapshot, request, *, check, max_investigations):
    """Deterministic, source-free plan; reading source belongs to investigate."""
    check()
    all_files = {file.id: file for file in snapshot.files}
    all_symbols = {symbol.id: symbol for symbol in snapshot.symbols}
    try:
        test_paths = {path for testing in snapshot.testing for path in testing.file_paths}
    except AttributeError:
        test_paths = set()
    selectors = [value.replace("\\", "/").rstrip("/") or "." for value in (request.targets or [])]
    files = {key: file for key, file in all_files.items()
        if not (file.path in test_paths or nonproduction_path(file.path))
        or any(_matches_selector(value, file, all_symbols) for value in selectors)}
    symbols = {key: symbol for key, symbol in all_symbols.items() if symbol.file_id in files}
    owners = {**{key: key for key in files}, **{key: symbol.file_id for key, symbol in symbols.items()}}
    edges, unresolved = [], 0
    for relation in snapshot.relationships:
        check()
        source, target = owners.get(relation.source_id), owners.get(relation.target_id)
        if source in files and relation.resolution in {"unresolved", "dynamic"}:
            unresolved += 1
        if source and target and source != target and relation.resolution == "internal":
            edges.append((relation, source, target))
    symbols_by_file = defaultdict(list)
    for symbol in symbols.values():
        symbols_by_file[symbol.file_id].append(symbol)
    consumers_by_file = defaultdict(set)
    for _relation, source, target in edges:
        if target in files and source in files:
            consumers_by_file[target].add(files[source].path)

    implementation_cache = {}

    def implementations_of(symbol):
        if symbol.id not in implementation_cache:
            implementation_cache[symbol.id] = _implementations(symbol, symbols)
        return implementation_cache[symbol.id]

    # Candidate pool: recognizable abstractions plus explicitly promoted helpers
    # and type aliases (promoted only by an explicit documented reference).
    name_index, qualified_index = _name_index(symbols)
    document = getattr(request, "documented_architecture", None)

    limitations = [
        "Planning is deterministic and source-free; documentation is orientation, not a constraint.",
        "A plan proposes questions only; it never establishes a violation or a finding.",
    ]
    if unresolved:
        limitations.append(f"{unresolved} scoped dynamic/unresolved relationships are unavailable to the index.")
    try:
        if snapshot.coverage.unsupported_source_languages or snapshot.coverage.issues:
            limitations.append("Snapshot coverage is incomplete; absence of a signal is not proof.")
    except AttributeError:
        pass

    claims: list[dict[str, Any]] = []
    try:
        claims = normalize_knowledge(document)
    except (TypeError, ValueError) as error:
        claims = []
        limitations.append(f"Documentary normalization failed: {error}")

    if document is None:
        limitations.append("No documented architecture supplied; structural inventory is used alone.")

    snapshot_hash = snapshot.repository.snapshot_hash
    normalized_by_id = {claim["id"]: claim for claim in claims}

    promoted_ids = set()
    # Symbol-level promotion: does any documented term name this symbol?
    for claim in claims:
        if claim["category"] not in RELEVANT_CATEGORIES:
            continue
        tokens = [claim["subject"], *(claim["related_subjects"] or [])]
        for token in tokens:
            lowered = (token or "").strip().casefold()
            if not lowered:
                continue
            promoted_ids.update(name_index.get(lowered, []))
            promoted_ids.update(qualified_index.get(lowered, []))

    pool: dict[str, tuple[Any, str]] = {}
    for symbol in symbols.values():
        kind = _abstraction_kind(symbol)
        if kind is None:
            if symbol.id in promoted_ids and symbol.kind in {"function", "type_alias"}:
                kind = "documented_helper" if symbol.kind == "function" else "type_alias"
            else:
                continue
        # Helper/type_alias candidates require a documented reference; surfaces not.
        if kind in {"documented_helper", "type_alias"} and symbol.id not in promoted_ids:
            continue
        pool[symbol.id] = (symbol, kind)

    documented: dict[str, dict[str, Any]] = {}
    unmapped_claims, uncertain_claims, context_only_claims = 0, 0, 0
    if document is not None:
        for claim in claims:
            check()
            claim_id = claim["id"]
            if claim["category"] not in RELEVANT_CATEGORIES or _is_testing_claim(claim):
                continue
            scored = []
            for symbol_id, (symbol, _kind) in pool.items():
                own = _symbol_explicit_strength(claim["subject"], symbol)
                related = max(
                    (_symbol_explicit_strength(subject, symbol) for subject in claim["related_subjects"]),
                    default=0)
                # An own-subject reference outranks any related-subject reference.
                if own:
                    scored.append((3, symbol_id, own))
                elif related:
                    scored.append((2, symbol_id, related))
            if not scored:
                unmapped_claims += 1
                continue
            top = max(entry[0] for entry in scored)
            winners = [entry for entry in scored if entry[0] == top]
            if len(winners) != 1:
                # Tie between equally explicit candidates: never invent an owner.
                uncertain_claims += 1
                continue
            _, symbol_id, own = winners[0]
            is_direct = claim["category"] in DIRECT_CATEGORIES and own > 0
            entry = documented.setdefault(symbol_id, {"claims": [], "direct": [], "context": [],
                "related_subjects": []})
            if claim_id not in entry["claims"]:
                entry["claims"].append(claim_id)
            if is_direct:
                entry["direct"].append(claim["statement"])
            else:
                entry["context"].append(claim["statement"])
                if claim["category"] in DIRECT_CATEGORIES:
                    context_only_claims += 1
            entry["related_subjects"].extend(claim["related_subjects"] or [])

    if unmapped_claims:
        limitations.append(f"{unmapped_claims} documentary claims were not attributable to an identified abstraction; "
            "they were not adjudicated.")
    if uncertain_claims:
        limitations.append(f"{uncertain_claims} documentary claims were ambiguous between equally explicit components; "
            "no correspondence was invented.")
    if context_only_claims:
        limitations.append(f"{context_only_claims} claims mapped to components but not directly onto an abstraction purpose.")

    candidates, used_claim_ids = [], set()

    for symbol_id, (symbol, kind) in pool.items():
        file_id = symbol.file_id
        file = files[file_id]
        implementations = implementations_of(symbol)
        impl_paths = sorted({files[item.file_id].path for item in implementations})
        consumer_paths = _consumers(file_id, files, consumers_by_file)
        related = list(dict.fromkeys([*impl_paths, *consumer_paths]))[:3]
        implementers, consumers = len(implementations), len(consumer_paths)
        structural_links = implementers + consumers
        documentation = documented.get(symbol_id)

        if documentation:
            direct = documentation["direct"]
            context = documentation["context"]
            has_documentary_purpose = bool(direct or context)
            synthesis = _principal_statement(direct[0]) if direct else (
                f"Context involving {file.path}: {_principal_statement(context[0])}") if context else None
            indicators = []
            if synthesis:
                indicators.append(f"Documented purpose: {synthesis}")
            if context:
                indicators.append(f"{len(context)} complementary documented claims in context.")
            if len(direct) > 1:
                indicators.append(f"{len(direct)} direct documented claims grouped.")
            indicators.append(f"Explicit reference to {file.path} ({symbol.name}).")
            if implementers:
                indicators.append(f"{implementers} indexed implementation(s) reference {symbol.name}.")
            if consumers:
                indicators.append(f"{consumers} internal consumer file(s) import {file.path}.")
            priority = _priority(bool(direct), structural_links, has_documentary_purpose)
            question = (f"Does the abstraction '{symbol.name}' in {file.path} deliver a verifiable architectural "
                f"guarantee — substitution, independence, encapsulation, extensibility or reuse — for its "
                f"implementations and consumers, or do they depend on implementation details?")
            evidence_needed = list(COMMON_EVIDENCE)
        else:
            if kind not in {"interface", "protocol", "abstract_class"}:
                continue
            if implementers < 1 and consumers < 2:
                continue
            synthesis = None
            indicators = [f"{symbol.name} is a {kind.replace('_', ' ')} in {file.path}.",
                *( [f"{implementers} indexed implementation(s) reference {symbol.name}."] if implementers else []),
                *( [f"{consumers} internal consumer file(s) import {file.path}."] if consumers else [])]
            priority = "medium" if implementers >= 2 else "low"
            question = (f"Is there a verifiable abstraction purpose for '{symbol.name}' in {file.path}; "
                "and does it provide substitutability, independence, encapsulation, extensibility or reuse to its consumers?")
            evidence_needed = list(COMMON_EVIDENCE)

        candidate_id = create_identifier("investigation", snapshot_hash, "abstraction",
            file.path, getattr(symbol, "qualified_name", symbol.name))
        candidates.append(AbstractionCandidate(
            id=candidate_id, priority=priority, scope=[file.path, *related[:2]],
            primary_component=file.path,
            abstraction_name=symbol.name,
            abstraction_kind=kind,
            related_components=related,
            documented_purpose=synthesis,
            purpose_basis="explicit" if documentation and documentation["direct"] else (
                "inferred" if documentation else "unknown"),
            observed_indicators=indicators,
            question=question,
            evidence_needed=evidence_needed,
            document_claim_ids=list(dict.fromkeys(documentation["claims"])) if documentation else []))
        used_claim_ids.update(candidates[-1].document_claim_ids)

    documented_candidates = [c for c in candidates if c.document_claim_ids]
    structural_candidates = [c for c in candidates if not c.document_claim_ids]

    def rank(item):
        return ({"high": 0, "medium": 1, "low": 2}[item.priority],
                -len(item.document_claim_ids), item.primary_component, item.id)

    documented_candidates.sort(key=rank)
    structural_candidates.sort(key=rank)
    selected = (documented_candidates + structural_candidates)[:max_investigations]
    selected.sort(key=rank)
    total = len(candidates)
    discarded = max(0, total - len(selected))
    limitations.append(f"Planning diagnostics: generated={total}, shown={len(selected)}, discarded={discarded}; "
        "unresolved or ambiguous claims were not adjudicated.")
    if discarded:
        limitations.append(f"Candidate menu bounded: {discarded} opportunities omitted; not an exhaustive plan.")
    if not selected:
        limitations.append("No sufficiently grounded candidate was found; an empty plan is valid.")

    objectives = [request.objective]
    hypotheses = [Hypothesis(id=item.id, question=item.question,
        criterion_id="abstraction-purpose", priority=item.priority,
        evidence_needed=item.evidence_needed) for item in selected]
    components = list(dict.fromkeys(path for item in selected for path in item.scope))
    return AbstractionPlan(objectives=objectives, components=components, hypotheses=hypotheses,
        candidates=selected, limitations=list(dict.fromkeys(limitations)),
        document_claims={claim_id: AbstractionDocumentClaim.model_validate(normalized_by_id[claim_id])
            for claim_id in used_claim_ids if claim_id in normalized_by_id})


def _priority(direct, structural_links, documented):
    if direct and structural_links:
        return "high"
    if documented or structural_links >= 2:
        return "medium"
    return "low"


def _is_testing_claim(claim):
    """Claims about test procedures are not abstraction purposes."""
    text = f"{claim['subject']} {claim['statement']}".lower()
    return any(marker in text for marker in TESTING_MARKERS)
