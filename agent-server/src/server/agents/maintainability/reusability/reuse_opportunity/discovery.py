"""Cheap bounded shortlist from existing symbols and retained source, not semantic proof.

No parser service, embedding service or full-repository prompt is introduced. Identifier-erased
shapes catch renamed implementations; shared operation words offer different-syntax
candidates for semantic inspection. False positives are intentionally left to validation.
"""

import ast
import hashlib
import re
from itertools import combinations
from textwrap import dedent

from .....runtimes.repository.access import repository_relative_path
from .schemas import CandidateLocation, DiscoveryCoverage, ReuseGroup

WORDS = re.compile(r"[A-Za-z_$][\w$]*")
TOKENS = re.compile(r"[A-Za-z_$][\w$]*|\d+(?:\.\d+)?|[^\s\w]", re.UNICODE)
STOP = frozenset([
    "def", "function", "return", "class", "self", "this", "const", "let", "var", "public", "private",
    "static", "async", "await", "export", "default", "import", "from", "if", "else", "for", "in", "of",
    "true", "false", "None", "null", "undefined", "void", "new",
    "str", "int", "float", "bool", "list", "dict", "tuple", "set", "Sequence", "Optional",
    "Any", "NoneType", "super", "__init__",
])


def features(text, name):
    # Declaration/variable names are deliberately erased only in the shape channel.
    tokens = TOKENS.findall(text)
    shape = tuple("ID" if WORDS.fullmatch(t) and t not in STOP else t for t in tokens)
    words = {w.casefold() for w in WORDS.findall(text) if w not in STOP and len(w) > 2}
    words.discard(name.casefold())
    return shape, words


def source_characteristics(symbol, source, symbols):
    """Conservative navigation labels, not a semantic or quality verdict."""
    parent = symbols.get(symbol.parent_symbol_id)
    contract = bool(parent and (parent.kind in {"interface", "protocol"} or any(
        base.rsplit(".", 1)[-1] == "Protocol" for base in parent.base_names)))
    contract |= any("abstractmethod" in decorator for decorator in symbol.decorators)
    plumbing = False
    if source.language.casefold() == "python":
        text = "\n".join(source.content.splitlines()[symbol.start_line - 1:symbol.end_line])
        try:
            tree = ast.parse(dedent(text))
            node = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
            body = list(node.body) if node else []
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                body.pop(0)
            stub = lambda n: isinstance(n, ast.Pass) or (
                isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and n.value.value is Ellipsis) or (
                isinstance(n, ast.Raise) and isinstance(n.exc, (ast.Name, ast.Call))
                and (n.exc.id if isinstance(n.exc, ast.Name) else getattr(n.exc.func, "id", "")) == "NotImplementedError")
            contract |= bool(body) and all(stub(n) for n in body)
            def simple_assignment(statement):
                if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    return False
                value = statement.value
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                plain_value = isinstance(value, (ast.Name, ast.Constant)) or (
                    isinstance(value, (ast.List, ast.Tuple, ast.Set)) and not value.elts) or (
                    isinstance(value, ast.Dict) and not value.keys)
                return plain_value and all(isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                    and target.value.id == "self" for target in targets)
            if symbol.name == "__init__" and 0 < len(body) <= 2:
                plumbing = all(simple_assignment(n) or (
                    isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                    and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == "__init__"
                    and isinstance(n.value.func.value, ast.Call) and isinstance(n.value.func.value.func, ast.Name)
                    and n.value.func.value.func.id == "super"
                    and all(isinstance(arg, (ast.Name, ast.Constant)) for arg in n.value.args)
                    and not n.value.keywords) for n in body)
            elif len(body) == 1 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Call):
                call = body[0].value
                plumbing = (isinstance(call.func, ast.Attribute) and call.func.attr == "append" and len(call.args) == 1
                    and isinstance(call.args[0], (ast.Name, ast.Constant)) and not call.keywords)
        except (SyntaxError, ValueError, RecursionError):
            pass  # Truncated/unsupported source stays an unclassified navigation candidate.
    return bool(contract), plumbing


def discover(snapshot, request, config):
    targets = [repository_relative_path(t) for t in request.targets]
    files = {f.id: f for f in snapshot.files}
    by_id = {s.id: s for s in snapshot.symbols}

    def scoped(path):
        return not targets or any(path == t or path.startswith(t.rstrip("/") + "/") for t in targets)

    for target in targets:
        if not any(f.path == target or f.path.startswith(target.rstrip("/") + "/") for f in files.values()):
            raise ValueError(f"Target is not accessible in the snapshot: {target}")
    eligible = sorted((s for s in snapshot.symbols if s.kind in {"function", "method"}
                       and s.file_id in files and files[s.file_id].content and scoped(files[s.file_id].path)),
                       key=lambda s: (s.name in {"__init__", "constructor"}, s.start_line == s.end_line,
                                      files[s.file_id].path, s.start_line, s.id))
    symbols = eligible[:config.max_discovery_symbols]
    vectors = {}
    locations = {}
    characteristics = {}
    lines = {identifier: files[identifier].content.splitlines() for identifier in {s.file_id for s in symbols}}
    for s in symbols:
        f = files[s.file_id]
        text = "\n".join(lines[s.file_id][s.start_line - 1:s.end_line])[:config.max_feature_characters]
        vectors[s.id] = features(text, s.name)
        characteristics[s.id] = source_characteristics(s, f, by_id)
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
        contract, plumbing = (any(characteristics[s.id][index] for s in (left, right)) for index in (0, 1))
        if contract:
            group.discovery_signals.append("contract_only_navigation")
        if plumbing:
            group.discovery_signals.append("trivial_plumbing_navigation")
        # Real operation vocabulary outranks shape-only plumbing and declaration pairs.
        matches.append((contract, plumbing, -len(shared), not same_shape, identifier, group))
    matches.sort(key=lambda m: m[:5])
    committed = {i for c in request.follow_up for i in c.subject_ids}
    matches.sort(key=lambda item: item[5].id not in committed)
    return DiscoveryCoverage(indexed_languages=sorted({files[s.file_id].language for s in eligible}),
        indexed_eligible_symbols=len(eligible), shortlisted_symbols=len(symbols),
        compared_pairs=compared, matching_pairs=len(matches), omitted_groups=max(0, len(matches) - config.max_groups),
        omitted_symbols=len(eligible) - len(symbols), selected_groups=[m[5] for m in matches[:config.max_groups]])
