"""Human-readable identities from published metadata, without repository access."""

import re

OPAQUE_ID = re.compile(r"(?<![\w/])(?:[a-z][\w-]*:)?(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{20,64})(?![\w])")
ENTITY_ID = re.compile(r"(?:symbol|file|component|group|project|declaration):[\w-]+$")


class ReferenceCatalog:
    def __init__(self, data):
        self.labels = {}
        objects, strings = [], []

        def visit(value):
            if isinstance(value, dict):
                objects.append(value)
                for key, child in value.items():
                    if key != "content":
                        visit(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    visit(child)
            elif isinstance(value, str):
                strings.append(value)

        visit(data)

        def string(obj, *keys):
            return next((obj[key] for key in keys if isinstance(obj.get(key), str) and obj[key]), None)

        paths = {}
        for obj in objects:
            path = string(obj, "path", "file_path", "source")
            identifier = string(obj, "file_id") or (string(obj, "id") if obj.get("kind") == "file" else None)
            if isinstance(path, str) and isinstance(identifier, str):
                paths.setdefault(identifier, set()).add(path)
        file_paths = {key: next(iter(values)) for key, values in paths.items() if len(values) == 1}
        candidates = {}
        for obj in objects:
            identifier = string(obj, "symbol_id", "declaration_id", "component_id", "id")
            path = string(obj, "path", "file_path") or file_paths.get(string(obj, "file_id"))
            name = string(obj, "qualified_name", "symbol_name", "name")
            if isinstance(identifier, str) and ENTITY_ID.match(identifier) and (name or path):
                label = str(name or path)
                if name and path and name != path:
                    label += " — " + path
                if obj.get("start_line") and identifier.startswith(("symbol:", "declaration:")):
                    label += f":{obj['start_line']}–{obj.get('end_line') or obj['start_line']}"
                candidates.setdefault(identifier, set()).add(label)
            symbol_name = string(obj, "symbol_name")
            symbol_ids = obj.get("symbol_ids", [])
            if symbol_name and isinstance(symbol_ids, (list, tuple)) and len(symbol_ids) == 1 and isinstance(symbol_ids[0], str) and path:
                candidates.setdefault(symbol_ids[0], set()).add(f"{symbol_name} — {path}")
        self.labels.update(file_paths)
        for key, values in candidates.items():
            # Metadata with a line range refines the same named declaration;
            # conflicting names/locations must remain unresolved.
            longest = max(values, key=lambda value: (len(value), value))
            if all(longest == value or longest.startswith(value + ":") for value in values):
                self.labels[key] = longest
        group_number = 0
        for obj in objects:
            groups = obj.get("consolidated_findings")
            if not isinstance(groups, list):
                continue
            for group in groups:
                if not isinstance(group, dict) or not string(group, "id"):
                    continue
                parents = {string(obj, key) for key in ("id", "invocation_id", "assessment_id")} - {None}
                aliases = [f"{parent}/{group['id']}" for parent in sorted(parents)]
                if not aliases or any(alias in self.labels for alias in aliases):
                    continue
                group_number += 1
                title = string(group, "title", "statement", "summary")
                label = f"Grupo consolidado G{group_number:03d}" + (f" — {title}" if title else "")
                self.labels.update(dict.fromkeys(aliases, label))
        unknown = sorted({m.group() for value in strings for m in OPAQUE_ID.finditer(value)}
            | {value for value in strings if ENTITY_ID.match(value)})
        counters = {}
        for identifier in unknown:
            if identifier in self.labels:
                continue
            kind = identifier.split(":", 1)[0] if ":" in identifier else "reference"
            title, prefix = {"symbol": ("Símbolo", "S"), "declaration": ("Declaración", "D"),
                "file": ("Archivo", "F"), "component": ("Componente", "C"), "group": ("Grupo", "G"),
                "project": ("Proyecto", "P")}.get(kind, ("Referencia técnica", "T"))
            counters[prefix] = counters.get(prefix, 0) + 1
            self.labels[identifier] = f"{title} {prefix}{counters[prefix]:03d} — nombre no publicado"
        self.pattern = (re.compile(r"(?<![\w])(?:" + "|".join(re.escape(key) for key in
            sorted(self.labels, key=lambda key: (-len(key), key))) + r")(?![\w])") if self.labels else None)

    def resolve(self, value):
        if self.pattern is None:
            return value
        return self.pattern.sub(lambda match: self.labels[match.group()], value)
