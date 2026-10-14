"""Bounded deterministic source/index hints, never proof of an adaptation defect."""

import re

from ...repository_runtime.access import repository_relative_path
from .schemas import AdaptabilityCoverage, ComponentTarget, DiscoverySignal

RULES = [
    ("infrastructure", "import_dependency", r"^\s*(?:from\s+\S+\s+import\b|import\s+\S+)|\b(?:require|import)\s*\("),
    ("environment", "environment_read", r"\b(?:getenv|environ)\b|process\.env"),
    ("infrastructure", "concrete_client", r"\b(?:connect|MongoClient|Redis|create_engine|Client)\s*\("),
    ("dependency_injection", "construction_or_locator", r"\b(?:new\s+\w+|[A-Z]\w*\s*\(|get_service\s*\(|resolve\s*\()"),
    ("global_state", "global_or_static", r"\b(?:global|static)\b|^\w+\s*=|^(?:export\s+)?(?:let|var)\s+"),
    ("framework", "framework_reference", r"\b(?:fastapi|flask|django|express|React|Request|HttpContext)\b|@(?:app|router)\."),
    ("configuration", "constant_or_endpoint", r"\b[A-Z][A-Z_]+\s*=|https?://|/var/|[A-Z]:\\"),
    ("side_effects", "io_or_mutation", r"\b(?:open|print|fetch|requests\.(?:get|post)|write|unlink|save)\s*\("),
    ("platform", "platform_api", r"\b(?:winreg|msvcrt|fork|uname|platform|os\.system)\b"),
    ("interface", "public_boundary", r"\b(?:export|public|Protocol|interface|abstract)\b"),
    ("data_schema", "schema_access", r"\[\s*['\"]\w+['\"]\s*\]|\b(?:SELECT|INSERT|schema|BaseModel)\b"),
]
COMPILED = [(kind, name, re.compile(pattern)) for kind, name, pattern in RULES]


def discover(snapshot, request, config):
    targets = [repository_relative_path(t) for t in request.targets]
    files = {f.id: f for f in snapshot.files}
    symbols = {s.id: s for s in snapshot.symbols}
    for target in targets:
        if not any(f.path == target or f.path.startswith(target.rstrip("/") + "/") for f in files.values()):
            raise ValueError(f"Target is not accessible: {target}")
    for identifier in request.component_ids:
        if identifier not in files and identifier not in symbols:
            raise ValueError(f"Unknown component ID: {identifier}")

    def scoped(path):
        return not targets or any(path == t or path.startswith(t.rstrip("/") + "/") for t in targets)

    candidates = []
    for f in files.values():
        if not scoped(f.path) or not f.content:
            continue
        top = [s for s in snapshot.symbols if s.file_id == f.id and s.parent_symbol_id is None
               and s.kind in {"function", "class", "interface"}]
        if request.component_ids:
            top = [s for s in snapshot.symbols if s.file_id == f.id and s.id in request.component_ids]
            if f.id not in request.component_ids and not top:
                continue
        if top and f.id not in request.component_ids:
            candidates.extend((s.id, f, s.qualified_name, s.start_line, s.end_line) for s in top)
        else:
            candidates.append((f.id, f, None, 1, f.line_count or 1))
    if set(request.component_ids) - {c[0] for c in candidates}:
        raise ValueError("Requested component is outside targets or lacks accessible source.")
    scan_files = sorted({c[1].id: c[1] for c in candidates}.values(), key=lambda f: f.path)
    scanned = {}
    truncated = []
    for f in scan_files[:config.max_scan_files]:
        text = f.content[:config.max_scan_characters_per_file]
        if len(text) < len(f.content):
            truncated.append(f.path)
        signals = []
        lines = text.splitlines()
        for line, content in enumerate(lines, 1):
            for kind, rule, pattern in COMPILED:
                if pattern.search(content):
                    signals.append(DiscoverySignal(constraint_type=kind, line=line, rule=rule))
                    if len(signals) >= config.max_signals_per_component * config.max_components:
                        break
            if len(signals) >= config.max_signals_per_component * config.max_components:
                if line < len(lines) and f.path not in truncated:
                    truncated.append(f.path)
                break
        scanned[f.id] = signals
    ranked = []
    for identifier, f, name, start, end in candidates:
        signals = scanned.get(f.id, [])
        local = [s for s in signals if start <= s.line <= end]
        # Module-level assumptions remain navigation hints for class/function targets.
        chosen = (local + [s for s in signals if s.line < start])[:config.max_signals_per_component]
        item = ComponentTarget(component_id=identifier, file_id=f.id, path=f.path, symbol=name,
            start_line=start, end_line=end, signals=chosen)
        ranked.append((-len(local), f.path, start, identifier, item))
    ranked.sort(key=lambda r: r[:4])
    return AdaptabilityCoverage(selected_components=[r[4] for r in ranked[:config.max_components]],
        eligible_components=len(candidates), omitted_components=max(0, len(candidates) - config.max_components),
        scanned_files=len(scanned), omitted_scan_files=max(0, len(scan_files) - len(scanned)), scan_truncated_paths=truncated)
