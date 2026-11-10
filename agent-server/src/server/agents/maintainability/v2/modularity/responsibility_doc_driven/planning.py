"""Bounded responsibility planning over the structural index.

Deterministic and source-free: documentation seeds only explicit
responsibility mappings; coexistence of methods or relations never
implies a violation. Reading source belongs to investigate.
"""

import re
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from types import SimpleNamespace

from server.contracts.audit import Hypothesis
from server.services.repository_analysis.context import create_identifier
from server.services.repository_analysis.testing import is_test_file

from .schemas import DocumentClaimRecord, ResponsibilityCandidate, ResponsibilityPlan

RESPONSIBILITY_CATEGORIES = {"responsibilities", "components"}
COMPLEMENTARY_CATEGORIES = {"interfaces_and_contracts", "relationships"}
TESTING_MARKERS = ("vitest", "pytest", "fixture", "__tests__", "mock", "coverage")
COMMON_EVIDENCE = ["Declarations and responsibilities in the primary component",
    "Callers, dependencies and shared state from the indexed relationships",
    "Comparable groupings that might justify the observed structure"]


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


GENERIC_TOP = {"lib", "src", "app", "main", "core"}


def _functional_domain(primary, item, files):
    subjects = list(item.get("direct", [])) + list(item.get("context", []))
    tokens = Counter()
    for text in subjects:
        tokens.update(_domain_tokens(text))
    if tokens:
        return "_".join(sorted({token for token, _count in tokens.most_common(2)}))
    parts = [part for part in primary.replace("\\", "/").split("/") if part not in GENERIC_TOP]
    return parts[0] if parts else primary.split("/")[0]


def _resolve_related_subject(subject, files, symbols_by_file):
    generic = SimpleNamespace(subject=subject, related_subjects=[])
    primary, _status, _reason, _direct = _explicit_match(generic, files, symbols_by_file)
    return primary


def _collaborators(primary, item, files, symbols_by_file, neighbor_files, participations):
    wanted = []
    for subject in item.get("related_subjects", []):
        resolved = _resolve_related_subject(subject, files, symbols_by_file)
        if resolved and resolved != primary and resolved not in wanted:
            wanted.append(resolved)
    path_to_id = {item_file.path: key for key, item_file in files.items()}
    structural = sorted(neighbor_files[item["key"]], key=lambda path: (
        -participations.get(path_to_id.get(path, ""), 0), path))
    return (wanted + structural)[:3]


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


def _symbol_composition(symbols):
    counts = defaultdict(int)
    for symbol in symbols:
        counts[symbol.kind] += 1
    groups = sorted((f"{kind}×{count}" for kind, count in counts.items() if count >= 2))
    return groups, counts


def _explicit_match(claim, files, symbols_by_file):
    """Single primary file only on an explicit file/module/symbol reference.

    Token overlap never invents a correspondence. An ambiguous tie between
    equally explicit components leaves the claim without a candidate.
    Direct means the claim's own subject names the component; a match through
    related_subjects is documented context, not an owned responsibility.
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


def _documented_priority(capabilities, contexts, declarations, neighbors, direct_capabilities=0):
    if direct_capabilities >= 3 and (contexts >= 1 or declarations >= 8):
        return "high"
    if capabilities >= 2 or contexts >= 1:
        return "medium"
    return "low"


def _structural_priority(declarations, neighbors, groups):
    if (declarations >= 5 and neighbors >= 3) or len(groups) >= 2:
        return "medium"
    return "low"


def build_responsibility_plan(snapshot, request, *, check, max_investigations):
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
    neighbor_dirs, participations = defaultdict(set), defaultdict(int)
    neighbor_files = defaultdict(set)
    for _relation, source, target in edges:
        participations[source] += 1
        participations[target] += 1
        neighbor_dirs[source].add(str(PurePosixPath(files[target].path).parent))
        neighbor_dirs[target].add(str(PurePosixPath(files[source].path).parent))
        neighbor_files[source].add(files[target].path)
        neighbor_files[target].add(files[source].path)

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
            relevant = claim.category in RESPONSIBILITY_CATEGORIES or claim.category in COMPLEMENTARY_CATEGORIES
            if not relevant:
                document_claims[claim_id] = DocumentClaimRecord(
                    claim=claim, document_index=getattr(document, "document_index", None),
                    section_paths=section_paths, status="not_applicable",
                    reason="Category does not describe component responsibility or relevant context.", scope_paths=[])
                continue
            text = (claim.subject + " " + claim.statement).lower()
            if any(marker in text for marker in TESTING_MARKERS):
                document_claims[claim_id] = DocumentClaimRecord(
                    claim=claim, document_index=getattr(document, "document_index", None),
                    section_paths=section_paths, status="not_applicable",
                    reason="Testing procedure, not a functional component responsibility.", scope_paths=[])
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
                item = {"key": key, "claims": [claim_id], "direct": [], "related": [],
                    "context": [], "related_subjects": list(claim.related_subjects or [])}
                item["context" if is_contextual else "direct"].append(claim.statement)
                documented_by_primary[primary] = item

    for primary, item in documented_by_primary.items():
        key = item["key"]
        declarations = [symbol for symbol in symbols_by_file[key]
            if symbol.kind in {"class", "function", "interface", "method", "type_alias"}]
        direct = item["direct"]
        context = item["context"]
        statements = _documented_statements(direct) if direct else _documented_statements(context)
        if not declarations:
            continue
        synthesis = _principal_statement(direct[0]) if direct else f"Context involving {primary}: {_principal_statement(context[0])}"
        indicators = [f"Documented purpose: {synthesis}"]
        if context:
            indicators.append(f"{len(context)} complementary documented claims in context.")
        if len(direct) > 1:
            indicators.append(f"{len(direct)} direct documented claims grouped.")
        indicators.append(f"Explicit reference to {primary}.")
        # Fallback question only; plan LLM supplies the specific question.
        question = f"Does {primary} keep its documented purpose coherent, or does it mix independent reasons to change?"
        candidates.append(ResponsibilityCandidate(
            id=create_identifier("investigation", snapshot_hash, "documented", primary),
            priority=_documented_priority(len(statements), len(context), len(declarations), len(neighbor_dirs[key]),
                len(_documented_statements(direct)) if direct else 0),
            scope=[primary], primary_component=primary,
            collaborators=_collaborators(primary, item, files, symbols_by_file, neighbor_files, participations),
            documented_responsibility=synthesis,
            observed_indicators=indicators,
            question=question,
            evidence_needed=[*COMMON_EVIDENCE,
                "Contrast the documented purpose with actual declarations inside the primary component"],
            document_claim_ids=list(dict.fromkeys(item["claims"]))))

    structural = []
    covered = {candidate.primary_component for candidate in candidates}
    for file_id in sorted(files, key=lambda key: files[key].path):
        check()
        declarations = [symbol for symbol in symbols_by_file[file_id]
            if symbol.kind in {"class", "function", "interface", "method", "type_alias"}]
        neighbors = neighbor_dirs[file_id]
        if len(declarations) < 2 or participations[file_id] < 1 or len(neighbors) < 1:
            continue
        path = files[file_id].path
        if path in covered:
            continue
        covered.add(path)
        groups, _counts = _symbol_composition(symbols_by_file[file_id])
        question = (f"Does {path} keep one reason to change across the symbol composition "
            f"({', '.join(groups)}), or mix independent reasons to change?") if groups else (
            f"Does {path} keep one reason to change, or mix independent reasons to change?")
        candidates.append(ResponsibilityCandidate(
            id=create_identifier("investigation", snapshot_hash, "structural", path),
            priority=_structural_priority(len(declarations), len(neighbors), groups),
            scope=[path], primary_component=path,
            collaborators=sorted(neighbor_files[file_id], key=lambda value: (-participations.get(
                next(item_key for item_key, item_file in files.items() if item_file.path == value), 0), value))[:3],
            documented_responsibility=None,
            observed_indicators=[f"{len(declarations)} declarations in {path} (exploratory signal only).",
                f"{participations[file_id]} relationships across {len(neighbors)} neighbor directories.",
                *([f"Symbol composition: {', '.join(groups)}."] if groups else [])],
            question=question,
            evidence_needed=[*COMMON_EVIDENCE,
                "Check whether distinct neighbor directions share a contract or independent causes"],
            document_claim_ids=[]))

    documented = [item for item in candidates if item.document_claim_ids]
    structural = [item for item in candidates if not item.document_claim_ids]
    rank = {"high": 0, "medium": 1, "low": 2}
    sort_key = lambda item: (rank[item.priority], -len(item.document_claim_ids), item.primary_component, item.id)
    documented.sort(key=sort_key)
    structural.sort(key=sort_key)
    total_unique = len({candidate.primary_component for candidate in documented + structural})
    pool = documented + structural[:max(0, max_investigations * 3)]
    # Soft domain diversity: at most two investigations per leading domain in
    # the first pass; leftovers fill only if diversity cannot reach the cap.
    selected = []
    seen_domains = Counter()
    deferred = []
    for item in pool:
        domain = _functional_domain(item.primary_component, documented_by_primary.get(item.primary_component, {}), files) if item.document_claim_ids else _functional_domain(item.primary_component, {}, files)
        if seen_domains[domain] >= 3:
            deferred.append(item)
            continue
        selected.append(item)
        seen_domains[domain] += 1
        if len(selected) >= max_investigations:
            break
    if len(selected) < max_investigations:
        for item in deferred:
            selected.append(item)
            if len(selected) >= max_investigations:
                break
    selected.sort(key=sort_key)
    discarded = max(0, total_unique - len(selected))
    limitations.append(f"Planning diagnostics: generated={total_unique}, shown={len(selected)}, discarded={discarded}; "
        "unresolved or ambiguous claims were not adjudicated.")
    candidates = selected[:max_investigations]
    if discarded:
        limitations.append(f"Candidate menu bounded: {discarded} opportunities omitted; not an exhaustive plan.")
    if not candidates:
        limitations.append("No sufficiently grounded candidate was found; an empty plan is valid.")
    objectives = [request.objective]
    hypotheses = [Hypothesis(id=item.id, question=item.question,
        criterion_id="single-responsibility", priority=item.priority,
        evidence_needed=item.evidence_needed) for item in candidates]
    components = list(dict.fromkeys(path for item in candidates for path in item.scope))
    return ResponsibilityPlan(objectives=objectives, components=components, hypotheses=hypotheses,
        candidates=candidates, limitations=list(dict.fromkeys(limitations)),
        document_claims={key: document_claims[key] for item in candidates for key in item.document_claim_ids
            if key in document_claims})
