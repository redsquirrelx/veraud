"""Bounded test-isolation planning over source inventory.

Candidate generation is deterministic and code-structure driven: an
isolation barrier can only be spotted by looking at how code constructs,
consumes or shares its dependencies. Documentation is orientation, not a
constraint: documentary claims bind candidates and are delivered to the
investigator, but a documented correct pattern never suppresses a
code-level indicator. Reading implementations in depth belongs to
investigate.
"""

import re
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from types import SimpleNamespace

from server.contracts.audit import Hypothesis
from server.services.repository_analysis.context import create_identifier
from server.services.repository_analysis.testing import is_test_file

from .schemas import DocumentClaimRecord, TestIsolationCandidate, TestIsolationPlan

TEST_ISOLATION_CATEGORIES = {"interfaces_and_contracts", "constraints", "architectural_decisions",
    "responsibilities", "components"}
COMPLEMENTARY_CATEGORIES = {"relationships"}
TESTING_MARKERS = ("vitest", "pytest", "coverage", "__tests__", "test suite")
COMMON_EVIDENCE = ["Concrete dependencies constructed inside the primary component and their effects",
    "Substitution seams of the primary component: constructor parameters, protocols, factories",
    "Module-level or shared state reached by the primary component",
    "Substitute implementations (fakes, memory adapters) declared elsewhere in the repository"]

GENERIC_TOP = {"lib", "src", "app", "main", "core"}

# Bound the deterministic indicators; the investigator decides legitimacy.
MAX_INDICATORS_PER_FILE = 12
MAX_INDICATORS_PER_CATEGORY = 3
MAX_SNIPPET = 160

# Capitalized constructors treated as benign values rather than dependencies.
_BENIGN_CONSTRUCTORS = frozenset({
    "Optional", "List", "Dict", "Set", "Tuple", "Deque", "DefaultDict", "Counter", "ChainMap",
    "Path", "PurePath", "PurePosixPath", "PureWindowsPath", "Decimal", "UUID", "Enum", "IntEnum",
    "IntFlag", "Flag", "NamedTuple", "BaseModel", "Field", "TypeVar", "ClassVar", "Final",
    "Datetime", "Date", "Time", "Timedelta", "TzInfo", "ZoneInfo", "Pattern", "Match",
    "Exception", "ValueError", "TypeError", "KeyError", "RuntimeError", "OSError", "StopIteration",
    "StringIO", "BytesIO", "TextIOWrapper", "TextIOBase",
})

# Symbols declared under these paths are domain values/errors, not dependencies.
_DOMAIN_PATH_TOKENS = frozenset({"domain", "models", "entities", "entity", "policies", "policy",
    "values", "value_objects", "valueobjects", "dto", "dtos", "value"})


def _domain_constructor_symbols(files, symbols):
    """Names of symbols declared in domain-ish paths; safe to construct freely."""
    domain_file_ids = set()
    for file_id, file in files.items():
        parts = [part.lower() for part in PurePosixPath(file.path.replace("\\", "/")).parts]
        if any(part in _DOMAIN_PATH_TOKENS for part in parts):
            domain_file_ids.add(file_id)
    return {symbol.name for symbol in symbols
        if symbol.file_id in domain_file_ids and symbol.kind in {"class", "type_alias", "enum"}}


def _boundary_adapter_hints(snapshot, files):
    """Orientation hint: this file is likely the boundary adapter, not its consumer.

    Fires when the file lies under an adapters/infrastructure directory, or when
    one of its classes shadows a Protocol declared in another file — both are
    deterministic structural signals, never proof of fitness or of a barrier.
    """
    port_names = {symbol.name for symbol in snapshot.symbols
        if symbol.kind == "class" and "Protocol" in symbol.base_names}
    all_files = {file.id: file for file in snapshot.files}
    hints = {}
    for symbol in snapshot.symbols:
        if symbol.kind != "class" or symbol.name in port_names:
            continue
        hits = [port for port in port_names if port and port in symbol.name]
        file = all_files.get(symbol.file_id)
        if file is not None:
            lowered = file.path.replace("\\", "/").lower()
            if any(part in {"adapters", "adapter", "infrastructure", "infra"}
                   for part in lowered.split("/")) or hits:
                hints[file.path] = hints.get(file.path, 0) + (len(hits) if hits else 1)
    return hints

# Per-line deterministic isolation-barrier indicators. Each compiled rule maps
# to a barrier category; a line keeps only its most specific match.
_LINE_RULES = [
    ("subprocess-boundary", re.compile(r"\b(?:subprocess\.(?:run|Popen|call|check_output|check_call)|os\.(?:system|popen)|Popen\()", re.IGNORECASE)),
    ("network-boundary", re.compile(r"\b(?:smtplib|poplib|imaplib|telnetlib|ftplib|socket\.|create_connection|requests\.|httpx|urllib\.request|aiohttp|boto3|grpc\.|KafkaProducer|KafkaConsumer|redis\.|pika\.|smtplib\.SMTP)")),
    ("configuration-boundary", re.compile(r"\b(?:os\.environ|os\.getenv|environ\.get|environ\[)")),
    ("uncontrolled-time", re.compile(r"\b(?:time\.sleep|datetime\.(?:now|utcnow|today)|time\.time|time\.time_ns|monotonic|perf_counter|time\.perf_counter|random\.(?:random|choice|randint|uniform|shuffle))")),
    ("async-control", re.compile(r"\b(?:Timer\(|threading\.|Thread\(|asyncio\.(?:run|run_coroutine_threadsafe)|run_until_complete|get_event_loop|new_event_loop)")),
    ("filesystem-boundary", re.compile(r"(?:\bopen\(|\.(?:read_text|write_text|read_bytes|write_bytes|read_csv|to_csv)\b|\bos\.(?:listdir|makedirs|replace|remove)\b|\bshutil\.|\bglob\.)")),
    ("adapter-internals", re.compile(r"\bself\.[A-Za-z_][A-Za-z0-9_]*\._[A-Za-z_][A-Za-z0-9_]*")),
    ("construction-side-effect", re.compile(r"\bself\.[A-Za-z_][A-Za-z0-9_]*\.(?:start|stop|run|connect|launch|open)\s*\(")),
]

# JavaScript/TypeScript families share the same machinery, with their own
# concrete-import and construction lexicon. The analysis language is decided by
# the snapshot's language field, never by filename inside this function.
_LINE_RULES_JS = [
    ("subprocess-boundary", re.compile(r"\b(?:child_process|execSync|spawnSync|execFileSync|execFile|exec\b(?=[\s(]))")),
    ("network-boundary", re.compile(r"\b(?:fetch\(|axios(?:\.\w+)?\.|node-fetch|https?\.(?:request|get)\(|WebSocket\(|EventSource\(|new Redis\(|ioredis|http2\b|createConnection\(|grpc\b)")),
    ("configuration-boundary", re.compile(r"\b(?:process\.env|import\.meta\.env)\b")),
    ("uncontrolled-time", re.compile(r"\b(?:Date\.now\(|new Date\(\s*\)|Math\.random|performance\.now|process\.hrtime|crypto\.getRandomValues|crypto\.randomUUID)")),
    ("async-control", re.compile(r"\b(?:setInterval\(|setTimeout\(|setImmediate\(|process\.nextTick|queueMicrotask|new Promise\()")),
    ("filesystem-boundary", re.compile(r"\b(?:readFileSync|readFile\(|writeFileSync|writeFile\(|appendFileSync|mkdirSync|rmSync|readdirSync|rmdirSync|existsSync|createReadStream|createWriteStream|fs\.promises|promises\.(?:readFile|writeFile|mkdir|rm|readdir))")),
    ("adapter-internals", re.compile(r"\bthis\.[A-Za-z_$][\w$]*\._[A-Za-z_$][\w$]*")),
    ("construction-side-effect", re.compile(r"\bthis\.[A-Za-z_$][\w$]*\.(?:start|stop|run|connect|launch|open|listen|write|end)\s*\(")),
]

_THIS_CONSTRUCTION = re.compile(r"\bthis\.[A-Za-z_$][\w$]*\s*=\s*new ([A-Za-z_$][\w$]*)\s*\(")
_MODULE_CONSTRUCTION_JS = re.compile(r"^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*new ([A-Za-z_$][\w$]*)\s*\(")
_LOCAL_CONSTRUCTION_JS = re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*new ([A-Za-z_$][\w$]*)\s*\(")
_MODULE_MUTABLE_JS = re.compile(r"^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:\[\]|\{\}|new Map\b|new Set\b|new WeakMap|new WeakSet|new RegExp)")
_NAMESPACE_CONSTRUCTION = re.compile(r"\bnew\s+(?:[a-z_$][\w$]*\.){1,3}[A-Z][\w$]*\s*\(")

_BENIGN_CONSTRUCTORS_JS = frozenset({
    "Error", "TypeError", "RangeError", "ReferenceError", "SyntaxError", "URIError", "AggregateError",
    "Array", "Map", "Set", "WeakMap", "WeakSet", "ArrayBuffer", "Uint8Array", "Intl",
    "Number", "String", "Boolean", "Symbol", "BigInt", "RegExp", "Promise", "Proxy",
    "URL", "URLSearchParams", "File", "Blob", "FormData", "Headers", "Request", "Response",
})

_LANGUAGE_FAMILIES = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "javascript",
    "tsx": "javascript",
}

_SELF_CONSTRUCTION = re.compile(r"\bself\.[A-Za-z_][A-Za-z0-9_]*\s*=\s*([A-Z][A-Za-z0-9_]*)\s*\(")
_LOCAL_CONSTRUCTION = re.compile(r"^\s*([a-z_][A-Za-z0-9_]*)\s*=\s*([A-Z][A-Za-z0-9_]*)\s*\(")
_MODULE_CONSTRUCTION = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?=\s*([A-Z][A-Za-z0-9_]*)\s*\(")
_MODULE_MUTABLE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*[^=]+)?=\s*(?:\[\]|\{\}|set\(\)|list\(\)|dict\(\))")
_GLOBAL_DECL = re.compile(r"^\s*global\s+[A-Za-z_]")


def _scan_source(path, content, domain_names=(), language="python"):
    """Deterministic barrier indicators for one source file.

    Returns a list of (category, line_number, snippet); never raises on
    unusual input. A line keeps only its most specific category. The scanning
    family follows the snapshot's language field (never filename).
    """
    family = _LANGUAGE_FAMILIES.get(str(language or "").lower())
    javascript = family == "javascript"
    rules = _LINE_RULES_JS if javascript else _LINE_RULES
    self_ctor = _THIS_CONSTRUCTION if javascript else _SELF_CONSTRUCTION
    module_ctor = _MODULE_CONSTRUCTION_JS if javascript else _MODULE_CONSTRUCTION
    local_ctor = _LOCAL_CONSTRUCTION_JS if javascript else _LOCAL_CONSTRUCTION
    module_mutable = _MODULE_MUTABLE_JS if javascript else _MODULE_MUTABLE
    comment_prefixes = ("//",) if javascript else ("#",)
    benign = (_BENIGN_CONSTRUCTORS_JS if javascript else _BENIGN_CONSTRUCTORS) | frozenset(domain_names)

    def is_benign(name):
        return name in benign or name.endswith(("Error", "Exception", "Warning"))

    hits = []
    seen = defaultdict(int)

    def record(category, line_number, snippet):
        if seen[category] >= MAX_INDICATORS_PER_CATEGORY:
            return
        seen[category] += 1
        hits.append((category, line_number, snippet.strip()[:MAX_SNIPPET]))

    for line_number, raw in enumerate(content.splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith(comment_prefixes):
            continue
        category = None
        for name, rule in rules:
            if rule.search(raw):
                category = name
                break
        if category:
            record(category, line_number, raw)
            continue
        match = self_ctor.search(raw)
        if match and not is_benign(match.group(1)):
            record("construction-coupling", line_number, raw)
            continue
        match = module_mutable.match(raw)
        if match:
            record("shared-mutable-state", line_number, raw)
            continue
        match = module_ctor.match(raw)
        if match and not is_benign(match.group(2)):
            record("global-state", line_number, raw)
            continue
        if _GLOBAL_DECL.match(raw):
            record("shared-mutable-state", line_number, raw)
            continue
        match = local_ctor.match(raw)
        if match and not is_benign(match.group(2)):
            record("construction-coupling", line_number, raw)
            continue
        if javascript and _NAMESPACE_CONSTRUCTION.search(raw):
            record("construction-coupling", line_number, raw)
    return hits[:MAX_INDICATORS_PER_FILE]


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


def _explicit_match(claim, files, symbols_by_file):
    """Single primary file only on an explicit file/module/symbol reference.

    Token overlap never invents a correspondence. An ambiguous tie between
    equally explicit components leaves the claim without a candidate.
    Direct means the claim's own subject names the component; a match through
    related_subjects is documented context, not an owned contract.
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
    "using", "based", "against", "ensures", "provide", "provides", "built", "implements", "behavior", "concern", "concerns",
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


def _documented_priority(capabilities, contexts, declarations, neighbors, direct_capabilities=0):
    if direct_capabilities >= 3 and (contexts >= 1 or declarations >= 8):
        return "high"
    if capabilities >= 2 or contexts >= 1:
        return "medium"
    return "low"


def _scan_priority(hits, documented=False):
    """Priority from indicator strength; documentation only promotes, never demotes."""
    categories = {hit[0] for hit in hits}
    severe = categories & {"subprocess-boundary", "network-boundary"}
    if len(hits) >= 4 or len(categories) >= 3 or (severe and len(hits) >= 2):
        return "high"
    if hits or documented:
        return "medium"
    return "low"


def build_test_isolation_plan(snapshot, request, *, check, max_investigations,
        max_documentary_claims_per_candidate=6):
    """Deterministic, code-structure plan; in-depth source reading belongs to investigate."""
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
        "Planning is deterministic and bounded; indicators are exploratory signals, never findings.",
        "A plan proposes questions only; it never establishes an isolation defect or a finding.",
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
        limitations.append("No documented architecture supplied; code indicators are used alone.")
    else:
        for index, claim in enumerate(getattr(document, "knowledge", []) or []):
            check()
            claim_id = f"claim-{index}"
            section_paths = {key: document.section_paths[key] for key in claim.section_ids
                if key in getattr(document, "section_paths", {})}
            relevant = claim.category in TEST_ISOLATION_CATEGORIES or claim.category in COMPLEMENTARY_CATEGORIES
            if not relevant:
                document_claims[claim_id] = DocumentClaimRecord(
                    claim=claim, document_index=getattr(document, "document_index", None),
                    section_paths=section_paths, status="not_applicable",
                    reason="Category does not describe component contracts, infrastructure substitution or isolation context.", scope_paths=[])
                continue
            text = (claim.subject + " " + claim.statement).lower()
            if any(marker in text for marker in TESTING_MARKERS):
                document_claims[claim_id] = DocumentClaimRecord(
                    claim=claim, document_index=getattr(document, "document_index", None),
                    section_paths=section_paths, status="not_applicable",
                    reason="Testing procedure claim, not an isolation contract.", scope_paths=[])
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

    # Code-indicator candidates: deterministic scan of retainable source files.
    domain_names = _domain_constructor_symbols(files, symbols.values())
    adapter_hints = _boundary_adapter_hints(snapshot, files)
    scan_by_primary = {}
    for file_id in sorted(files, key=lambda key: files[key].path):
        check()
        file = files[file_id]
        content = getattr(file, "content", None)
        if not content:
            continue
        family = _LANGUAGE_FAMILIES.get(str(getattr(file, "language", "") or "").lower())
        if family is None:
            continue  # Unsupported languages are skipped, never mis-scanned.
        hits = _scan_source(file.path, content, domain_names, language=getattr(file, "language", ""))
        if not hits:
            continue
        path = file.path
        scan_by_primary[path] = hits
        categories = Counter(hit[0] for hit in hits)
        indicators = [f"{category} (x{count})" for category, count in sorted(categories.items())]
        indicators.extend(f"{category} at line {line}: {snippet}" for category, line, snippet in hits[:6])
        if path in adapter_hints:
            indicators.append(f"boundary-adapter-likely: {adapter_hints[path]} class(es) shadowing a declared Protocol here; "
                "evaluate the consumer side and the wiring before attributing a barrier to this adapter.")
        dominant = categories.most_common(1)[0][0]
        candidates.append(TestIsolationCandidate(
            id=create_identifier("investigation", snapshot_hash, "scan", path),
            priority=_scan_priority(hits),
            scope=[path], primary_component=path,
            collaborators=sorted(neighbor_files[file_id], key=lambda value: (-participations.get(
                next(item_key for item_key, item_file in files.items() if item_file.path == value), 0), value))[:3],
            documented_isolation_contract=None,
            observed_indicators=indicators[:10],
            question=(f"Can {path} be isolated from its dependencies for independent testing, "
                "or do constructed dependencies, side effects, external resources or shared state block substitution?"),
            evidence_needed=[*COMMON_EVIDENCE,
                "Contrast each flagged line with the component's documented isolation contracts"],
            document_claim_ids=[],
            barrier_category=dominant))

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
        indicators = [f"Documented isolation contract: {synthesis}"]
        if context:
            indicators.append(f"{len(context)} complementary documented claims in context.")
        if len(direct) > 1:
            indicators.append(f"{len(direct)} direct documented claims grouped.")
        indicators.append(f"Explicit reference to {primary}.")
        if primary in scan_by_primary:
            hits = scan_by_primary[primary]
            indicators.append(f"{len(hits)} code-indicator(s) in this component ({', '.join(sorted({hit[0] for hit in hits}))}).")
            existing = next(candidate for candidate in candidates if candidate.primary_component == primary)
            candidates.remove(existing)
            candidates.append(existing.model_copy(update={
                "documented_isolation_contract": synthesis,
                "observed_indicators": [*existing.observed_indicators, *indicators][:10],
                "priority": _scan_priority(hits, documented=True),
                "document_claim_ids": list(dict.fromkeys([*existing.document_claim_ids, *item["claims"]]))}))
            continue
        candidates.append(TestIsolationCandidate(
            id=create_identifier("investigation", snapshot_hash, "documented", primary),
            priority=_documented_priority(len(statements), len(context), len(declarations), len(neighbor_dirs[key]),
                len(_documented_statements(direct)) if direct else 0),
            scope=[primary], primary_component=primary,
            collaborators=_collaborators(primary, item, files, symbols_by_file, neighbor_files, participations),
            documented_isolation_contract=synthesis,
            observed_indicators=indicators,
            question=(f"Does {primary} honor its documented isolation contract, or is a dependency constructed or "
                "effected in a way that blocks independent testing?"),
            evidence_needed=[*COMMON_EVIDENCE,
                "Contrast the documented contract with the actual constructor and call sites in the primary component"],
            document_claim_ids=list(dict.fromkeys(item["claims"]))))

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
    document = getattr(request, "documented_architecture", None)
    if document is not None:
        symbols_by_file = defaultdict(list)
        for symbol in symbols.values():
            symbols_by_file[symbol.file_id].append(symbol)
        for index, claim in enumerate(getattr(document, "knowledge", []) or []):
            check()
            claim_id = f"claim-{index}"
            if any(claim_id in item.document_claim_ids for item in candidates):
                continue
            if claim.certainty != "explicit":
                continue
            if any(marker in (claim.subject + " " + claim.statement).lower() for marker in TESTING_MARKERS):
                continue
            matches = _capability_affinity(claim, candidates, files, symbols_by_file)
            if not matches:
                affinity_unanchored.append(claim_id)
                continue
            for candidate_id, score in matches:
                affinity_kept[candidate_id].append((score, claim_id, claim, index))
        # Keep phase-1 anchors intact; fill the remaining per-candidate slots
        # with the strongest affinity claims (ties by documentary order).
        # Affinity claims are relevance hypotheses: at most two per candidate,
        # so documentary obligations never crowd out the code question.
        kept_claim_ids: dict[str, set] = {}
        for candidate in candidates:
            entries = affinity_kept[candidate.id]
            slots = max(0, min(2, max_documentary_claims_per_candidate - phase1_counts[candidate.id]))
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
        criterion_id="test-isolation", priority=item.priority,
        evidence_needed=item.evidence_needed) for item in candidates]
    components = list(dict.fromkeys(path for item in candidates for path in item.scope))
    return TestIsolationPlan(objectives=objectives, components=components, hypotheses=hypotheses,
        candidates=candidates, limitations=list(dict.fromkeys(limitations)),
        document_claims={key: document_claims[key] for item in candidates for key in item.document_claim_ids
            if key in document_claims})