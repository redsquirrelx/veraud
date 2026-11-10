"""Resolve documented owners using actual indexed namespaces, never layer conventions."""

import re
from collections import defaultdict
from pathlib import PurePosixPath

# Bare generic business nouns name no component on their own. They only resolve
# when another exact reference in the same claim anchors their subproject;
# otherwise they stay ambiguous instead of matching an unrelated symbol.
_GENERIC_TERMS = frozenset({
    "queries", "query", "service", "services", "routes", "route", "handlers",
    "handler", "controllers", "controller", "repositories", "repository",
    "models", "model", "utils", "helper", "helpers", "lib", "db", "database",
    "prisma", "store", "stores", "api", "app", "components", "component",
    "modules", "module", "pages", "page", "hooks", "types", "constants",
    # Monetary/notice nouns are not code owners: "los importes" are amounts,
    # and "warning" in prose names no indexed declaration.
    "importe", "importes", "warning", "warnings",
})

# Path-like substrings carrying glob/brace/parameter syntax. Captured before
# plain tokenization so [id], {a,b} and ** keep their meaning.
_PATTERN_RE = re.compile(r"[\w@./~*+,-]*(?:/[\w@./~*\[\]{}+,-]+)+")
_ALIAS_PREFIXES = ("@/", "~/", "@")


def _pattern_regex(pattern):
    """Compile an indexed path pattern (glob, {a,b}, [param]) to a regex."""
    out, index = [], 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append(r"(?:[^/]+/)*")
            index += 3
        elif pattern.startswith("**", index):
            out.append(r".*")
            index += 2
        elif pattern[index] == "*":
            out.append(r"[^/]*")
            index += 1
        elif pattern[index] == "[":
            end = pattern.find("]", index)
            if end == -1:
                out.append(re.escape(pattern[index]))
                index += 1
            else:
                param = pattern[index + 1:end]
                out.append(r"[^/]+" if re.fullmatch(r"[A-Za-z_][\w]*", param) else re.escape(pattern[index:end + 1]))
                index = end + 1
        elif pattern[index] == "{":
            end = pattern.find("}", index)
            if end == -1:
                out.append(re.escape(pattern[index]))
                index += 1
            else:
                alternatives = pattern[index + 1:end].split(",")
                out.append("(?:" + "|".join(re.escape(item.strip()) for item in alternatives) + ")")
                index = end + 1
        elif pattern[index] == "?":
            out.append(r"[^/]")
            index += 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return re.compile("^" + "".join(out) + "$")


class DocumentCodeResolver:
    def __init__(self, files, symbols, check):
        self.files = files
        self.exact = defaultdict(set)
        self.suffixes = defaultdict(lambda: defaultdict(set))
        self.symbols = defaultdict(set)          # qualified names / ids (strong)
        self.bare_symbols = defaultdict(set)     # plain symbol names (weak)
        self.labels = {}
        self.file_projects = {}
        self.file_languages = {}
        for key, file in files.items():
            check()
            self.file_projects[key] = getattr(file, "project_id", "") or ""
            self.file_languages[key] = getattr(file, "language", "") or ""
            self.exact[file.path].add(key)
            self.exact[key].add(key)
            for path in [PurePosixPath(file.path), *PurePosixPath(file.path).parents]:
                if str(path) == ".":
                    continue
                directory = str(path) != file.path
                alias = str(path) + ("/" if directory else "")
                self.exact[alias].add(key)
                parts = path.parts
                # A unique omitted source root is corroborated by a real index
                # path. Two plausible roots remain ambiguous, even for directories.
                for start in range(1, len(parts) - (0 if directory else 1)):
                    suffix = "/".join(parts[start:]) + ("/" if directory else "")
                    self.suffixes[suffix][str(path)].add(key)
            if file.module_name:
                parts = file.module_name.split(".")
                for end in range(1, len(parts) + 1):
                    self.exact[".".join(parts[:end])].add(key)
        self.symbol_records = {symbol.id: symbol for symbol in symbols if symbol.file_id in files}
        for symbol in self.symbol_records.values():
            self.symbols[symbol.qualified_name].add(symbol.id)
            self.symbols[symbol.id].add(symbol.id)
            self.bare_symbols[symbol.name].add(symbol.id)
        # Directory forms for pattern matching, kept as plain strings.
        self._pattern_targets = set(self.exact)

    def _projects_of(self, ids):
        return {self.file_projects.get(item, "") for item in ids if self.file_projects.get(item, "")}

    def _languages_of(self, ids):
        return {self.file_languages.get(item, "") for item in ids if self.file_languages.get(item, "")}

    def _pattern_matches(self, text):
        """Match glob/brace/parameter paths against indexed paths only."""
        found = {}
        for raw in _PATTERN_RE.findall(text.replace("\\", "/")):
            # Never strip [] or {} here: they carry [param] and {a,b} meaning.
            candidate = raw.strip(" .,;:\"'()<>").strip("/")
            if not candidate or not any(char in raw for char in "*[{}"):
                continue
            forms = [candidate]
            stripped = candidate
            for prefix in _ALIAS_PREFIXES:
                if stripped.startswith(prefix):
                    stripped = stripped[len(prefix):]
                    forms.append(stripped)
                    forms.append("src/" + stripped)
                    break
            for form in forms:
                if form in self.exact:
                    # A literal indexed path wins over glob interpretation:
                    # app/api/roles/[id]/route.ts matches that file only,
                    # never an arbitrary single-segment directory.
                    found[candidate] = set(self.exact[form])
                    break
                regex = _pattern_regex(form)
                hits = {key for target in self._pattern_targets
                        for key in self.exact[target] if regex.match(target) or regex.match(target.rstrip("/"))}
                if hits:
                    found[candidate] = hits
                    break
        return found

    def resolve(self, text, *, include_labels=True):
        text = text.replace("\\", "/")
        terms = {item.rstrip(".") for item in re.findall(r"[\w./@-]+", text)}
        matches, unresolved, ambiguous, symbol_ids = {}, set(), set(), set()
        corroborated = False
        # Pass 1: patterns plus exact/module/suffix matches anchor subprojects.
        anchors, anchor_languages = set(), set()
        pattern_matches = self._pattern_matches(text)
        for term, hits in pattern_matches.items():
            matches[term] = set(hits)
            anchors |= self._projects_of(hits)
            anchor_languages |= self._languages_of(hits)
        for term in sorted(terms):
            if term in self.exact:
                matches[term] = set(self.exact[term])
                anchors |= self._projects_of(self.exact[term])
                anchor_languages |= self._languages_of(self.exact[term])
            elif (term.replace("/", ".") in self.exact or term.replace(".", "/") in self.exact
                  or term + ".py" in self.exact or term + ".ts" in self.exact):
                # Slash/dot and extensionless forms of the same indexed owner.
                for form in (term.replace("/", "."), term.replace(".", "/"),
                             term + ".py", term + ".ts", term + ".tsx", term + ".js"):
                    if form in self.exact:
                        matches[term] = set(self.exact[form])
                        anchors |= self._projects_of(self.exact[form])
                        anchor_languages |= self._languages_of(self.exact[form])
                        break
            elif term in self.suffixes or term + ".ts" in self.suffixes or term + ".py" in self.suffixes:
                # Extensionless import specifiers (e.g. @/lib/prisma) resolve
                # through the same indexed suffix rules, never invented paths.
                suffix = term if term in self.suffixes else (
                    term + ".ts" if term + ".ts" in self.suffixes else term + ".py")
                roots = self.suffixes[suffix]
                if anchors:
                    local = {root: value for root, value in roots.items()
                             if self._projects_of(value) & anchors}
                    if len(local) == 1:
                        roots = local
                if len(roots) == 1:
                    matches[term] = set(next(iter(roots.values())))
                    corroborated = True
                    anchors |= self._projects_of(matches[term])
                    anchor_languages |= self._languages_of(matches[term])
                else:
                    ambiguous.add(term)
            elif term.startswith(_ALIAS_PREFIXES):
                stripped = term
                for prefix in _ALIAS_PREFIXES:
                    if stripped.startswith(prefix):
                        stripped = stripped[len(prefix):]
                        break
                for form in (stripped, "src/" + stripped, stripped + ".ts", stripped + ".tsx",
                             stripped + ".js", stripped + ".py", "src/" + stripped + ".ts",
                             "src/" + stripped + ".py"):
                    if form in self.exact:
                        matches[term] = set(self.exact[form])
                        anchors |= self._projects_of(self.exact[form])
                        anchor_languages |= self._languages_of(self.exact[form])
                        corroborated = True
                        break
                    if form in self.suffixes:
                        roots = self.suffixes[form]
                        if len(roots) == 1:
                            matches[term] = set(next(iter(roots.values())))
                            anchors |= self._projects_of(matches[term])
                            anchor_languages |= self._languages_of(matches[term])
                            corroborated = True
                            break
                        ambiguous.add(term)
                        break
        # A directory term that is merely the prefix of a brace/glob/parameter
        # expression (app/api/ inside app/api/{a,b}) is not an independent
        # broad reference: the pattern alone defines the scope.
        for term in list(matches):
            if term in pattern_matches:
                continue
            prefix = term.rstrip("/") + "/"
            if any(candidate.startswith(prefix) for candidate in pattern_matches):
                matches.pop(term)
        # Pass 2: symbols are only matched inside anchored subprojects, and
        # only when unambiguous and non-generic without an anchor.
        for term in sorted(terms):
            if term in matches or term in ambiguous:
                continue
            if term in self.symbols:
                # A lowercase generic bare name is not a qualified reference,
                # even when the extractor stores it as the qualified name.
                # Capitalized names (Api, Store) are specific declarations.
                if term.islower() and term.casefold() in _GENERIC_TERMS and "." not in term and "/" not in term:
                    ambiguous.add(term)
                    continue
                candidates = self.symbols[term]
                if len(candidates) != 1:
                    ambiguous.add(term)
                    continue
                symbol_id = next(iter(candidates))
                file_key = self.symbol_records[symbol_id].file_id
                if anchors and self.file_projects.get(file_key, "") not in anchors:
                    ambiguous.add(term)
                    continue
                # An anchored TypeScript/JavaScript claim never resolves to a
                # Python declaration (and vice versa) by name similarity.
                if anchor_languages and self.file_languages.get(file_key, "") not in anchor_languages:
                    ambiguous.add(term)
                    continue
                matches[term] = {file_key}
                symbol_ids.add(symbol_id)
            elif term in self.bare_symbols:
                # Generic lowercase bare nouns never resolve on their own,
                # even with an anchor: only qualified names or explicit
                # paths are trusted. Capitalized declarations stay specific.
                if term.islower() and term.casefold() in _GENERIC_TERMS:
                    ambiguous.add(term)
                    continue
                candidates = self.bare_symbols[term]
                if len(candidates) != 1:
                    ambiguous.add(term)
                    continue
                if anchors:
                    candidates = {item for item in candidates
                                  if self.file_projects.get(self.symbol_records[item].file_id, "") in anchors}
                    if len(candidates) != 1:
                        ambiguous.add(term)
                        continue
                if anchor_languages:
                    candidates = {item for item in candidates
                                  if self.file_languages.get(self.symbol_records[item].file_id, "") in anchor_languages}
                    if len(candidates) != 1:
                        ambiguous.add(term)
                        continue
                symbol_id = next(iter(candidates))
                matches[term] = {self.symbol_records[symbol_id].file_id}
                symbol_ids.add(symbol_id)
            elif ("/" in term or "." in term) and term not in {"e.g", "i.e"} and term not in matches:
                unresolved.add(term)
        for label, ids in (self.labels.items() if include_labels else ()):
            if re.search(r"(?<![\w./])" + re.escape(label) + r"(?![\w./])", text, re.IGNORECASE):
                if ids is None:
                    ambiguous.add(label)
                else:
                    matches[label] = set(ids)
                    corroborated = True
        ids = set().union(*matches.values()) if matches else set()
        # A partially ambiguous claim keeps its resolved references; ambiguity
        # is reported separately and never discards the matched scope.
        basis = ("corroborated" if corroborated else "exact") if ids else (
            "ambiguous" if ambiguous else "unmapped")
        return {"ids": ids, "matches": matches, "unresolved": sorted(unresolved | ambiguous),
            "ambiguous": sorted(ambiguous), "symbols": symbol_ids, "basis": basis}

    def add_documented_labels(self, claims):
        for claim in sorted(claims, key=lambda item: item.model_dump_json()):
            if claim.certainty != "explicit" or claim.category not in {"components", "architectural_style", "responsibilities"} or not re.search(
                r"\b(source ownership|defined in|consists? of|owned by|located at|composed of|"
                r"ubicad[oa] en|definid[oa] en|pertenece a|propiedad de|se encuentra en|se ubica(?:n)? en|"
                r"corresponde a|comprende|comprenden|abarca|abarcan|incluye|incluyen|cubre|cubren|contiene|"
                r"configurad[oa] en|está ubicad[oa] en)\b", claim.statement, re.IGNORECASE
            ):
                continue
            if re.search(r"\b(proposed|hypothetical|for example|propuesto|propuesta|hipotético|ejemplo)\b",
                         claim.statement, re.IGNORECASE):
                continue
            result = self.resolve(claim.statement, include_labels=False)
            if not result["ids"] or result["ambiguous"]:
                continue
            original = claim.subject.strip()
            core = re.sub(r"^(?:la|el)\s+", "", original, flags=re.IGNORECASE)
            labels = {original, core,
                      re.sub(r"\s+layer$", "", core, flags=re.IGNORECASE),
                      re.sub(r"^capa\s+", "", core, flags=re.IGNORECASE),
                      re.sub(r"\s+capa$", "", core, flags=re.IGNORECASE)}
            ids = set(result["ids"])
            additive = bool(re.search(
                r"\b(incluye|incluyen|comprende|comprenden|abarca|abarcan|cubre|cubren|"
                r"includes?|comprises?|contains?)\b", claim.statement, re.IGNORECASE))
            for label in labels:
                existing = self.labels.get(label)
                if existing is None and label in self.labels:
                    continue
                if existing is None:
                    self.labels[label] = ids
                elif existing != ids:
                    # Complementary and subset declarations can extend a
                    # layer; conflicting exclusive locations stay ambiguous.
                    if additive or existing <= ids or ids <= existing:
                        self.labels[label] = set(existing) | ids
                    else:
                        self.labels[label] = None


def relation_applies(record, source_path, target_path):
    """Applicability of a directed navigation seed, never its conformance."""
    if {source_path, target_path} & set(record.excluded_paths):
        return False
    scope = set(record.scope_paths)
    subject = set(record.subject_paths)
    groups = [set(paths) for paths in record.owner_paths.values()]
    text = f"{record.claim.subject} {record.claim.statement}".casefold()
    if record.boundary_family == "encapsulation" and re.search(
            r"\b(outside|external|consumers|callers|fuera de|externo[s]?|consumidores|clientes|llamantes)\b", text):
        return target_path in scope and source_path not in scope
    if source_path not in scope or target_path not in scope:
        return False
    if subject and source_path not in subject:
        return False
    # A multi-owner rule addresses an interaction across the documented owners,
    # not an arbitrary internal edge in a directory covered by a broad prefix.
    disjoint = [(a, b) for a in groups for b in groups if not a & b]
    return not disjoint or any(source_path in a and target_path in b for a, b in disjoint)
