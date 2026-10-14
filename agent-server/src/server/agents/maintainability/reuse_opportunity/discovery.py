"""Cheap bounded shortlist from existing symbols and retained source, not semantic proof.

No parser, embedding service or full-repository prompt is introduced. Identifier-erased
shapes catch renamed implementations; shared operation words offer different-syntax
candidates for semantic inspection. False positives are intentionally left to validation.
"""

import hashlib
import re
from itertools import combinations

from ...repository_runtime.access import repository_relative_path
from .schemas import CandidateLocation, DiscoveryCoverage, ReuseGroup

WORDS = re.compile(r"[A-Za-z_$][\w$]*")
TOKENS = re.compile(r"[A-Za-z_$][\w$]*|\d+(?:\.\d+)?|[^\s\w]", re.UNICODE)
STOP = frozenset([
    "def", "function", "return", "class", "self", "this", "const", "let", "var", "public", "private",
    "static", "async", "await", "export", "default", "import", "from", "if", "else", "for", "in", "of",
    "true", "false", "None", "null", "undefined", "void", "new",
])


def features(text, name):
    # Declaration/variable names are deliberately erased only in the shape channel.
    tokens = TOKENS.findall(text)
    shape = tuple("ID" if WORDS.fullmatch(t) and t not in STOP else t for t in tokens)
    words = {w.casefold() for w in WORDS.findall(text) if w not in STOP and len(w) > 2}
    words.discard(name.casefold())
    return shape, words


def discover(snapshot, request, config):
    targets = [repository_relative_path(t) for t in request.targets]
    files = {f.id: f for f in snapshot.files}

    def scoped(path):
        return not targets or any(path == t or path.startswith(t.rstrip("/") + "/") for t in targets)

    for target in targets:
        if not any(f.path == target or f.path.startswith(target.rstrip("/") + "/") for f in files.values()):
            raise ValueError(f"Target is not accessible in the snapshot: {target}")
    eligible = sorted((s for s in snapshot.symbols if s.kind in {"function", "method"}
                       and s.file_id in files and files[s.file_id].content and scoped(files[s.file_id].path)),
                      key=lambda s: (files[s.file_id].path, s.start_line, s.id))
    symbols = eligible[:config.max_discovery_symbols]
    vectors = {}
    locations = {}
    lines = {identifier: files[identifier].content.splitlines() for identifier in {s.file_id for s in symbols}}
    for s in symbols:
        f = files[s.file_id]
        text = "\n".join(lines[s.file_id][s.start_line - 1:s.end_line])[:config.max_feature_characters]
        vectors[s.id] = features(text, s.name)
        locations[s.id] = CandidateLocation(component_id=s.id, file_id=s.file_id, path=f.path,
            symbol=s.qualified_name, start_line=s.start_line, end_line=s.end_line, language=f.language)
    matches = []
    compared = 0
    for left, right in combinations(symbols, 2):
        # Nested/overlapping declarations are not independent implementations.
        if left.file_id == right.file_id and left.start_line <= right.end_line and right.start_line <= left.end_line:
            continue
        compared += 1
        a, wa = vectors[left.id]
        b, wb = vectors[right.id]
        shared = sorted(wa & wb)
        same_shape = a == b and len(a) >= 8
        # Navigation heuristic only, explicitly not a rubric for reuse quality.
        if not same_shape and len(shared) < 2:
            continue
        members = sorted([locations[left.id], locations[right.id]], key=lambda m: m.component_id)
        key = "\0".join(m.component_id for m in members)
        identifier = "ROG-" + hashlib.sha256(key.encode()).hexdigest()[:16]
        signals = (["identifier_erased_shape"] if same_shape else []) + (["shared_terms:" + ",".join(shared[:8])] if shared else [])
        group = ReuseGroup(id=identifier, members=members, discovery_signals=signals)
        matches.append((not same_shape, -len(shared), identifier, group))
    matches.sort(key=lambda m: m[:3])
    return DiscoveryCoverage(indexed_eligible_symbols=len(eligible), shortlisted_symbols=len(symbols),
        compared_pairs=compared, matching_pairs=len(matches), omitted_groups=max(0, len(matches) - config.max_groups),
        omitted_symbols=len(eligible) - len(symbols), selected_groups=[m[3] for m in matches[:config.max_groups]])
