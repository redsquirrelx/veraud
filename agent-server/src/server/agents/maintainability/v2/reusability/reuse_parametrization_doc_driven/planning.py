"""Deterministic, source-free parametrization planning.

The planner builds a bounded, deterministic menu of candidate variation
investigations over the structural index; documentation seeds only explicit
variation mappings. Reading source belongs to investigate. The model selects
from the menu; it never invents entities.
"""

import re
from collections import defaultdict
from pathlib import PurePosixPath

from server.contracts.audit import Hypothesis
from server.services.repository_analysis.context import create_identifier
from server.services.repository_analysis.testing import is_test_file

from .schemas import DocumentClaimRecord, ParametrizationCandidate, ParametrizationPlan

DIRECT_CATEGORIES = {"interfaces_and_contracts", "architectural_decisions", "components", "architectural_style"}
COMPLEMENTARY_CATEGORIES = {"relationships", "constraints"}
RELEVANT_CATEGORIES = DIRECT_CATEGORIES | COMPLEMENTARY_CATEGORIES
TESTING_MARKERS = ("vitest", "pytest", "fixture", "__tests__", "mock", "coverage")
COMMON_EVIDENCE = ["Contract and declarations in the primary component",
    "Implementations and consumers identified from indexed relationships",
    "Documented alternatives and constraints relevant to the variation capability"]


def _domain_tokens(text):
    return sorted({token.lower() for token in re.findall(r"[A-Za-z0-9]+", text.lower())
        if len(token) >= 4} - {"with", "from", "that", "this", "into", "para", "cada"})


def _domain_match(claim, files, symbols_by_file):
    tokens = _domain_tokens(claim.subject + " " + " ".join(claim.related_subjects or []))
    if not tokens:
        return None, "unmapped", "No domain tokens."
    matches = []
    for file in files.values():
        names = [symbol.name for symbol in symbols_by_file.get(file.id, [])]
        body = " ".join([file.path, file.module_name or "", *names]).lower()
        haystack = re.findall(r"[a-z0-9]+", body)
        if all(token in haystack for token in tokens):
            matches.append(file.path)
    matches = sorted(set(matches))
    if len(matches) == 1:
        return matches[0], "applicable", "Domain tokens resolve to one component."
    if len(matches) > 1:
        return None, "uncertain", "Domain maps to multiple components; no arbitrary attribution."
    return None, "unmapped", "No indexed component matches the domain."


def _documented_statements(statements):
    """Distinct complete documentary statements, never fragmented."""
    results, seen = [], set()
    for statement in statements:
        text = " ".join((statement or "").split())
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            results.append(text)
    return results[:3]


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


def _principal_statement(statement):
    """First complete sentence; other claims stay in document_claim_ids."""
    text = " ".join((statement or "").split())
    return re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()


def _explicit_match(claim, files, symbols_by_file):
    """Single primary file only on an explicit file/module/symbol reference.

    Token overlap never invents a correspondence. An ambiguous tie between
    equally explicit components leaves the claim without a candidate.
    Direct means the claim's own subject names the component; a match through
    related_subjects is documented context, not an owned variation surface.
    """
    own = [value.strip() for value in [claim.subject] if value.strip()]
    other = [value.strip() for value in (claim.related_subjects or []) if value.strip()]

    def score(file, subjects):
        symbols = symbols_by_file.get(file.id, [])
        strength = 0
        for subject in subjects:
            if len(subject) < 4:
                continue
            lowered = subject.lower()
            if any(symbol.name.lower() == lowered or symbol.qualified_name.lower() == lowered
                    or symbol.id.lower() == lowered for symbol in symbols):
                strength = max(strength, 3)
            elif file.module_name and lowered == file.module_name.lower():
                strength = max(strength, 2)
            elif re.search(rf"(?:^|/){re.escape(lowered)}(?:$|/)", file.path.lower()):
                strength = max(strength, 1)
        return strength

    scored = []
    for file in files.values():
        strength = max(score(file, own), score(file, other))
        if strength:
            scored.append((strength, score(file, own), file))
    if not scored:
        return None, "unmapped", "No explicit file, module or symbol reference.", False
    top = max(strength for strength, _own, _file in scored)
    best = sorted({file.path for strength, _own, file in scored if strength == top})
    if len(best) > 1:
        return None, "uncertain", "Multiple equally explicit components; no correspondence invented.", False
    primary = best[0]
    primary_file = next(file for _strength, _own, file in scored if file.path == primary)
    return primary, "applicable", "Explicit component reference with a single primary match.", score(primary_file, own) > 0


_AFFINITY_STOPWORDS = frozenset({
    "with", "from", "that", "this", "into", "your", "have", "some", "such", "does",
    "about", "between", "over", "under", "each", "other", "only", "when", "where",
    "while", "their", "there", "these", "those", "they", "them", "then", "than",
    "therefore", "thus", "hence", "also", "within", "across", "before", "after",
    "without", "around", "along", "among", "upon", "every", "both", "either",
    "para", "cada", "este", "esta", "estos", "estas", "esto", "puede", "pueden",
    "debe", "deben", "sobre", "entre", "donde", "cuando", "hacia", "como", "solo",
})
_AFFINITY_GENERIC = frozenset({
    "capability", "interface", "interfaces", "contract", "contracts", "component",
    "components", "responsibility", "responsibilities", "requirement", "requirements",
    "module", "modules", "system", "systems", "service", "services", "method",
    "methods", "function", "functions", "class", "classes", "package", "packages",
    "logic", "layer", "data", "model", "models", "process", "processing", "uses",
    "using", "based", "against", "ensures", "provide", "provides", "built", "implements", "behavior", "concern", "concerns", "single", "mixed",
    "implement", "implemented", "representation", "production",
    "taking", "takes", "produces", "handles", "handling", "support", "supports",
    "respective", "directly", "generally", "typically", "concrete", "concretes",
    "represent", "various", "certain", "particular",
})
GENERIC_PATH_TOKS = frozenset({"src", "lib", "app", "main", "core", "index", "module"})


def _singular(token):
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("es") and len(token) > 4 and not token.endswith(("ses", "xes", "zes")):
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss") and len(token) > 4:
        return token[:-1]
    return token


def _affinity_tokens(text):
    """Lowercase distinctive tokens from free text; never invents structure."""
    tokens = set()
    for chunk in re.split(r"[^A-Za-z0-9]+", text or ""):
        if not chunk:
            continue
        for part in re.findall(r"[A-Z]+(?=[A-Z][a-z0-9]|[0-9]|$)|[A-Z]?[a-z0-9]+|[0-9]+", chunk):
            token = part.lower()
            if len(token) < 4:
                continue
            token = _singular(token)
            if token in _AFFINITY_STOPWORDS or token in _AFFINITY_GENERIC or token in GENERIC_PATH_TOKS:
                continue
            tokens.add(token)
    return tokens


def _file_token_set(file, symbols):
    """Tokens that may evidence affinity for one file: path segments + symbols."""
    segments = [segment for segment in re.split(r"[/\\]", file.path) if segment]
    parents = segments[:-1]
    all_tokens = _affinity_tokens(" ".join(segments))
    directory_tokens = _affinity_tokens(" ".join(parents))
    for symbol in symbols:
        all_tokens |= _affinity_tokens(symbol.name)
    return {"all": all_tokens, "dirs": directory_tokens}


def _capability_affinity(claim, candidates, files, symbols_by_file):
    """Affinity of one explicit claim to the selected candidates.

    Returns [(candidate_id, score)] scored by shared distinctive tokens; one
    shared directory segment also binds. Claims remain orientation-only; they
    are never code evidence.
    """
    claim_tokens = _affinity_tokens(
        " ".join([claim.subject, claim.statement, *(claim.related_subjects or [])]))
    if not claim_tokens:
        return []
    attached = []
    files_by_path = {file.path: file for file in files.values()}
    for item in candidates:
        file = files_by_path.get(item.primary_component)
        if file is None:
            continue
        cached = _file_token_set(file, symbols_by_file.get(file.id, []))
        shared = claim_tokens & cached["all"]
        directories = claim_tokens & cached["dirs"]
        if len(shared) >= 2 or directories:
            attached.append((item.id, len(shared or directories)))
    return attached


def _base_token(base):
    return re.sub(r"\[.*?\]|<.*?>", "", str(base)).casefold().split(".")[-1].strip()


def _variation_surface_kind(symbol):
    """Recognize substitutable surfaces the index can see; not by name alone."""
    if symbol.kind == "interface":
        return "interface"
    if symbol.kind != "class":
        return None
    bases = {_base_token(base) for base in getattr(symbol, "base_names", ())}
    if bases & {"protocol"}:
        return "protocol"
    if bases & {"abc", "abcmeta"}:
        return "abstract class"
    return None


def _implementations(symbol, symbols):
    """Classes whose bases reference the surface; no invented heritage."""
    targets = {symbol.name.casefold(), symbol.qualified_name.casefold().split(".")[-1]}
    implementations = []
    for other in symbols.values():
        if other.id == symbol.id or other.kind != "class":
            continue
        bases = {_base_token(base) for base in getattr(other, "base_names", ())}
        if bases & targets:
            implementations.append(other)
    return implementations


def _documented_priority(capabilities, contexts, declarations, neighbors, direct_capabilities=0):
    if direct_capabilities >= 3 and (contexts >= 1 or declarations >= 8):
        return "high"
    if capabilities >= 2 or contexts >= 1:
        return "medium"
    return "low"


def _is_testing_claim(claim):
    text = (claim.subject + " " + claim.statement).lower()
    return any(marker in text for marker in TESTING_MARKERS)


def build_parametrization_plan(snapshot, request, *, check, max_investigations,
        max_documentary_claims_per_candidate=6):
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
    neighbor_dirs = defaultdict(set)
    for _relation, source, target in edges:
        neighbor_dirs[source].add(str(PurePosixPath(files[target].path).parent))
        neighbor_dirs[target].add(str(PurePosixPath(files[source].path).parent))
        if target in files and source in files:
            consumers_by_file[target].add(files[source].path)

    def consumers_of(file_key):
        return sorted(consumers_by_file.get(file_key, ()))

    candidates, document_claims = [], {}
    documented_by_primary = {}
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

    snapshot_hash = snapshot.repository.snapshot_hash
    document = getattr(request, "documented_architecture", None)
    if document is None:
        limitations.append("No documented architecture supplied; structural inventory is used alone.")
    else:
        for index, claim in enumerate(getattr(document, "knowledge", []) or []):
            check()
            claim_id = f"claim-{index}"
            section_paths = {key: document.section_paths[key] for key in claim.section_ids
                if key in getattr(document, "section_paths", {})}
            relevant = claim.category in RELEVANT_CATEGORIES
            if not relevant:
                document_claims[claim_id] = DocumentClaimRecord(
                    claim=claim, document_index=getattr(document, "document_index", None),
                    section_paths=section_paths, status="not_applicable",
                    reason="Category does not describe a variation capability or relevant context.", scope_paths=[])
                continue
            if _is_testing_claim(claim):
                document_claims[claim_id] = DocumentClaimRecord(
                    claim=claim, document_index=getattr(document, "document_index", None),
                    section_paths=section_paths, status="not_applicable",
                    reason="Testing procedure, not a variation capability.", scope_paths=[])
                continue
            primary, status, reason, direct = _explicit_match(claim, files, symbols_by_file)
            if not primary:
                primary, status, reason = _domain_match(claim, files, symbols_by_file)
                direct = False
            document_claims[claim_id] = DocumentClaimRecord(
                claim=claim, document_index=getattr(document, "document_index", None),
                section_paths=section_paths, status=status, reason=reason,
                scope_paths=[primary] if primary else [])
            if not primary:
                continue
            key = next(item_key for item_key, item in files.items() if item.path == primary)
            is_contextual = claim.category in COMPLEMENTARY_CATEGORIES or not direct
            if primary in documented_by_primary:
                item = documented_by_primary[primary]
                item["claims"].append(claim_id)
                item["context" if is_contextual else "direct"].append(claim.statement)
                item["related_subjects"].extend(claim.related_subjects or [])
            else:
                item = {"key": key, "claims": [claim_id], "direct": [],
                    "context": [], "related_subjects": list(claim.related_subjects or [])}
                item["context" if is_contextual else "direct"].append(claim.statement)
                documented_by_primary[primary] = item

    for primary, item in documented_by_primary.items():
        key = item["key"]
        anchor_symbol = None
        direct_subjects = [claim.subject for index, claim in enumerate(getattr(document, "knowledge", []) or [])
            if f"claim-{index}" in item["claims"]]
        for symbol in symbols_by_file[key]:
            if any(subject.casefold() == symbol.name.casefold() for subject in direct_subjects):
                anchor_symbol = symbol
                break
        declarations = symbols_by_file[key]
        direct = item["direct"]
        context = item["context"]
        statements = _documented_statements(direct) if direct else _documented_statements(context)
        synthesis = _principal_statement(direct[0]) if direct else (
            f"Context involving {primary}: {_principal_statement(context[0])}") if context else None
        indicators = [f"Documented variation: {synthesis}."]
        if context:
            indicators.append(f"{len(context)} complementary documented claims in context.")
        if len(direct) > 1:
            indicators.append(f"{len(direct)} direct documented claims grouped.")
        indicators.append(f"Explicit reference to {primary}.")
        consumers = consumers_of(key)
        # Fallback question only; plan LLM supplies the specific question.
        question = (f"Can callers of {primary} select the documented capability through its mechanism "
            f"without modifying {primary}'s implementation, or does selection force internal changes?")
        candidates.append(ParametrizationCandidate(
            id=create_identifier("investigation", snapshot_hash, "parametrization", primary,
                anchor_symbol.id if anchor_symbol is not None else "file", "documented-variation"),
            priority=_documented_priority(len(statements), len(context), len(declarations), len(neighbor_dirs[key]),
                len(_documented_statements(direct)) if direct else 0),
            scope=[primary, *consumers[:2]],
            primary_component=primary,
            symbol_id=anchor_symbol.id if anchor_symbol is not None else "",
            symbol_name=anchor_symbol.name if anchor_symbol is not None else None,
            symbol_kind=anchor_symbol.kind if anchor_symbol is not None else None,
            variation_mechanism="documented variation point",
            alternatives=[],
            documented_capability=synthesis,
            variation_basis="explicit" if direct else "inferred",
            initial_locations=list(dict.fromkeys([primary, *consumers]))[:10],
            observed_indicators=indicators,
            question=question,
            evidence_needed=[*COMMON_EVIDENCE,
                f"Contrast the documented capability with actual declarations and call sites in {primary}"],
            document_claim_ids=list(dict.fromkeys(item["claims"]))))

    structural_surfaces = []
    covered = {candidate.primary_component for candidate in candidates}
    for file_id in sorted(files, key=lambda key: files[key].path):
        check()
        for symbol in symbols_by_file[file_id]:
            kind = _variation_surface_kind(symbol)
            if kind is not None:
                structural_surfaces.append((symbol, kind))
    for symbol, kind in structural_surfaces:
        file = files[symbol.file_id]
        primary = file.path
        if primary in covered:
            continue
        implementations = _implementations(symbol, symbols)
        implementers = len(implementations)
        consumer_paths = consumers_of(symbol.file_id)
        consumers = len(consumer_paths)
        if implementers < 1 and consumers < 2:
            continue
        covered.add(primary)
        alternatives = sorted({item.name for item in implementations})[:6]
        question = (f"Does {symbol.name} in {primary} define a substitutable variation point with "
            f"indexed implementations that callers can select without modifying {primary}, "
            f"or do consumers depend on implementation details?")
        candidates.append(ParametrizationCandidate(
            id=create_identifier("investigation", snapshot_hash, "parametrization", primary, symbol.id,
                f"{kind}-substitution"),
            priority="medium" if implementers >= 2 else "low",
            scope=[primary, *consumer_paths[:2]],
            primary_component=primary,
            symbol_id=symbol.id,
            symbol_name=symbol.name,
            symbol_kind=symbol.kind,
            variation_mechanism=f"{kind} substitution",
            alternatives=alternatives,
            documented_capability=None,
            variation_basis="inferred",
            initial_locations=list(dict.fromkeys([primary, *consumer_paths]))[:10],
            observed_indicators=[
                f"{symbol.name} is a {kind} in {primary}.",
                *([f"{implementers} indexed implementation(s) reference {symbol.name}."] if implementers else []),
                *([f"{consumers} internal consumer file(s) import {primary}."] if consumers else [])],
            question=question,
            evidence_needed=[*COMMON_EVIDENCE,
                "Identify the indexed implementations that make the surface substitutable"],
            document_claim_ids=[]))

    documented = [item for item in candidates if item.document_claim_ids]
    structural = [item for item in candidates if not item.document_claim_ids]
    rank = {"high": 0, "medium": 1, "low": 2}
    sort_key = lambda item: (rank[item.priority], -len(item.document_claim_ids), item.primary_component, item.id)
    documented.sort(key=sort_key)
    structural.sort(key=sort_key)
    selected = (documented + structural)[:max_investigations]
    selected.sort(key=sort_key)
    total = len(candidates)
    discarded = max(0, total - len(selected))
    limitations.append(f"Planning diagnostics: generated={total}, shown={len(selected)}, discarded={discarded}; "
        "unresolved or ambiguous claims were not adjudicated.")
    candidates = selected[:max_investigations]
    phase1_dropped = 0
    for position, item in enumerate(candidates):
        kept = list(dict.fromkeys(item.document_claim_ids))[:max_documentary_claims_per_candidate]
        phase1_dropped += len(item.document_claim_ids) - len(kept)
        if len(kept) != len(item.document_claim_ids):
            candidates[position] = item.model_copy(update={"document_claim_ids": kept})
    if phase1_dropped:
        limitations.append(f"Documentation diagnostics: {phase1_dropped} phase-1 documented claim(s) dropped by "
            f"per-candidate cap {max_documentary_claims_per_candidate}.")
    affinity_unanchored = []
    affinity_bindings = 0
    affinity_culled = 0
    phase1_counts = {item.id: len(item.document_claim_ids) for item in candidates}
    affinity_kept: dict[str, list] = {item.id: [] for item in candidates}
    if document is not None:
        for index, claim in enumerate(getattr(document, "knowledge", []) or []):
            check()
            claim_id = f"claim-{index}"
            if any(claim_id in item.document_claim_ids for item in candidates):
                continue
            if claim.certainty != "explicit":
                continue
            if _is_testing_claim(claim):
                continue
            matches = _capability_affinity(claim, candidates, files, symbols_by_file)
            if not matches:
                affinity_unanchored.append(claim_id)
                continue
            for candidate_id, score in matches:
                affinity_kept[candidate_id].append((score, claim_id, claim, index))
        # Keep phase-1 anchors intact; fill the remaining per-candidate slots
        # with the strongest affinity claims (ties by documentary order).
        kept_claim_ids: dict[str, set] = {}
        for candidate in candidates:
            entries = affinity_kept[candidate.id]
            slots = max(0, max_documentary_claims_per_candidate - phase1_counts[candidate.id])
            kept = [entry for entry in sorted(entries, key=lambda entry: (-entry[0], entry[3]))[:slots]]
            affinity_culled += len(entries) - len(kept)
            affinity_kept[candidate.id] = kept
            for _score, claim_id, _claim, _index in kept:
                kept_claim_ids.setdefault(claim_id, set()).add(candidate.primary_component)
        for position, item in enumerate(candidates):
            kept = affinity_kept[item.id]
            if not kept:
                continue
            attached_ids = [entry[1] for entry in kept]
            affinity_bindings += len(attached_ids)
            candidates[position] = item.model_copy(update={"document_claim_ids": list(dict.fromkeys(
                [*item.document_claim_ids, *attached_ids]))})
        for claim_id, primaries in kept_claim_ids.items():
            claim = next(entry[2] for item in affinity_kept.values() for entry in item
                if entry[1] == claim_id)
            document_claims[claim_id] = DocumentClaimRecord(
                claim=claim, document_index=getattr(document, "document_index", None),
                section_paths={key: document.section_paths[key] for key in claim.section_ids
                    if key in getattr(document, "section_paths", {})},
                status="applicable",
                reason=(f"Capability affinity match: attached to {len(primaries)} selected "
                    "component(s) by shared domain tokens; no explicit index anchor."),
                scope_paths=sorted(primaries))
        if affinity_bindings or affinity_culled or affinity_unanchored:
            limitations.append(f"Documentation diagnostics: {affinity_bindings} capability-affinity binding(s)"
                + (f" ({affinity_culled} dropped by per-candidate cap {max_documentary_claims_per_candidate})" if affinity_culled else "")
                + f"; {len(affinity_unanchored)} explicit claim(s) unanchored without an indexable owner"
                + (f": {', '.join(affinity_unanchored[:8])}" if affinity_unanchored else "") + ".")
    if discarded:
        limitations.append(f"Candidate menu bounded: {discarded} opportunities omitted; not an exhaustive plan.")
    if not candidates:
        limitations.append("No sufficiently grounded candidate was found; an empty plan is valid.")

    objectives = [request.objective]
    hypotheses = [Hypothesis(id=item.id, question=item.question,
        criterion_id="parametrized-reuse", priority=item.priority,
        evidence_needed=item.evidence_needed) for item in candidates]
    components = list(dict.fromkeys(path for item in candidates for path in item.scope))
    return ParametrizationPlan(objectives=objectives, components=components, hypotheses=hypotheses,
        candidates=candidates, limitations=list(dict.fromkeys(limitations)),
        document_claims={key: document_claims[key] for item in candidates for key in item.document_claim_ids
            if key in document_claims})
