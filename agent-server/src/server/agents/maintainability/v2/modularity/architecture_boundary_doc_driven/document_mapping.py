"""Resolve documented owners using actual indexed namespaces, never layer conventions."""

import re
from collections import defaultdict
from pathlib import PurePosixPath

# Lowercase common narrative words are never technical symbol references by
# themselves.  Such words may still designate a file/module when they are
# written as explicit paths instead.
_GENERIC_BARE_TERMS = frozenset({
    "can", "queries", "query", "warning", "warnings", "importes", "importe",
    "must", "should", "only", "route", "routes", "service", "services",
    "handler", "handlers", "helper", "helpers", "store", "stores", "model",
    "models", "utils", "lib", "db", "api", "users", "user", "data",
})
# Path-like substrings carrying glob/brace/parameter syntax.  Captured before
# plain tokenization so [id], {a,b}, *, ** and aliases keep their meaning.
_PATTERN_RE = re.compile(r"[\w@./~*+,\[\]{}-]+(?:/[\w@./~*+,\[\]{}-]+)+")
_ALIAS_PREFIXES = ("@/", "~/", "@")
_SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py")


def _pattern_regex(pattern):
    """Compile an indexed path pattern (glob, {a,b}) to a regex.

    A bracketed segment such as ``[id]`` is not a wildcard in this project:
    it is matched only by an exactly literal indexed path elsewhere in this
    resolver.  Returning ``None`` prevents ``[^/]+``-style overreach.
    """
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
            return None
        elif pattern[index] == "{":
            end = pattern.find("}", index)
            if end == -1:
                return None
            alternatives = [part.strip() for part in pattern[index + 1:end].split(",")]
            if not alternatives or any(not alternative for alternative in alternatives):
                return None
            out.append("(?:" + "|".join(re.escape(alternative) for alternative in alternatives) + ")")
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
        self.file_projects = {}
        self.file_languages = {}
        self.exact = defaultdict(set)
        self.path_targets = set()
        self.suffixes = defaultdict(lambda: defaultdict(set))
        # Qualified references are strong; a bare symbol name is deliberately
        # weaker and is considered only for an explicitly delimited reference.
        self.qualified_symbols = defaultdict(set)
        self.bare_symbols = defaultdict(set)
        self.labels = {}
        for key, file in files.items():
            check()
            self.file_projects[key] = getattr(file, "project_id", "") or ""
            self.file_languages[key] = getattr(file, "language", "") or ""
            self.exact[file.path].add(key)
            self.exact[key].add(key)
            self.path_targets.add(file.path)
            for path in [PurePosixPath(file.path), *PurePosixPath(file.path).parents]:
                if str(path) == ".":
                    continue
                directory = str(path) != file.path
                alias = str(path) + ("/" if directory else "")
                self.exact[alias].add(key)
                if directory:
                    self.path_targets.add(alias)
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
            self.qualified_symbols[symbol.qualified_name].add(symbol.id)
            self.qualified_symbols[symbol.id].add(symbol.id)
            self.bare_symbols[symbol.name].add(symbol.id)

    def _projects_of(self, ids):
        return {self.file_projects.get(item, "") for item in ids if self.file_projects.get(item, "")}

    def _languages_of(self, ids):
        return {self.file_languages.get(item, "") for item in ids if self.file_languages.get(item, "")}

    @staticmethod
    def _clean_pattern_candidate(raw):
        candidate = raw.strip(" \t\r\n\"'`<>")
        candidate = candidate.rstrip(".,;:")
        return candidate.strip("/")

    def _pattern_matches(self, text):
        """Match glob/brace/parameter expressions against indexed paths only."""
        found = {}
        for raw in _PATTERN_RE.findall(text.replace("\\", "/")):
            candidate = self._clean_pattern_candidate(raw)
            if not candidate or not any(char in candidate for char in "*[{}"):
                continue
            forms = [candidate]
            stripped = candidate
            for prefix in _ALIAS_PREFIXES:
                if stripped.startswith(prefix):
                    stripped = stripped[len(prefix):]
                    forms.extend([stripped, "src/" + stripped])
                    break
            for form in forms:
                if form in self.exact:
                    # A literal indexed path wins over glob interpretation.
                    found[candidate] = set(self.exact[form])
                    break
                regex = _pattern_regex(form)
                if regex is None:
                    continue
                hits = {
                    key for target in self.path_targets
                    for key in self.exact[target]
                    if regex.match(target) or regex.match(target.rstrip("/"))
                }
                if hits:
                    found[candidate] = hits
                    break
        return found

    @staticmethod
    def _bare_reference_is_explicit(term, text, explicit_terms):
        """Whether a bare name is a technical reference rather than narrative."""
        if term in explicit_terms:
            return True
        if term[0].isupper() or term.isupper():
            return True
        return term + "(" in text or term + "::" in text

    def resolve(self, text, *, include_labels=True):
        text = text.replace("\\", "/")
        terms = {item.rstrip(".") for item in re.findall(r"[\w./@-]+", text)}
        explicit_terms = set(re.findall(r"[`'\"]\s*([\w.]+)\s*[`'\"]", text))
        matches, unresolved, ambiguous, symbol_ids = {}, set(), set(), set()
        corroborated = False
        anchors, anchor_languages = set(), set()
        pattern_matches = self._pattern_matches(text)
        for term, hits in pattern_matches.items():
            # A relative textual reference that reaches several subprojects is
            # not silently disambiguated by dictionary order.
            if len(self._projects_of(hits)) > 1:
                ambiguous.add(term)
                continue
            matches[term] = set(hits)
            anchors |= self._projects_of(hits)
            anchor_languages |= self._languages_of(hits)
        for term in sorted(terms):
            if term in matches or term in ambiguous:
                continue
            if term in self.exact:
                hits = set(self.exact[term])
                if len(self._projects_of(hits)) > 1:
                    ambiguous.add(term)
                    continue
                matches[term] = hits
                anchors |= self._projects_of(hits)
                anchor_languages |= self._languages_of(hits)
            if term in matches or term in ambiguous:
                continue
            # Exact aliases and slash/dot/extensionless variants of the same
            # indexed owner are explicit references, not nearest-name guesses.
            if term not in matches and term not in ambiguous:
                stripped = term
                for prefix in _ALIAS_PREFIXES:
                    if stripped.startswith(prefix):
                        stripped = stripped[len(prefix):]
                        break
                forms = []
                for value in (term, stripped, "src/" + stripped,
                              term.replace(".", "/"), term.replace("/", "."),
                              *(value + suffix for value in (term, stripped, "src/" + stripped)
                                for suffix in _SOURCE_SUFFIXES)):
                    if value and value not in forms:
                        forms.append(value)
                resolved = False
                for form in forms:
                    if form in self.exact:
                        hits = set(self.exact[form])
                        if len(self._projects_of(hits)) > 1:
                            ambiguous.add(term)
                            resolved = True
                            break
                        matches[term] = hits
                        anchors |= self._projects_of(hits)
                        anchor_languages |= self._languages_of(hits)
                        if form != term:
                            corroborated = True
                        resolved = True
                        break
                    if form in self.suffixes:
                        roots = self.suffixes[form]
                        if anchors:
                            local = {root: value for root, value in roots.items()
                                     if self._projects_of(value) & anchors}
                            if len(local) == 1:
                                roots = local
                        if len(roots) == 1:
                            hits = set(next(iter(roots.values())))
                            matches[term] = hits
                            anchors |= self._projects_of(hits)
                            anchor_languages |= self._languages_of(hits)
                            corroborated = True
                        else:
                            ambiguous.add(term)
                        resolved = True
                        break
                if resolved:
                    continue
            # Qualified symbols and IDs are strong references; bare names are
            # considered only when explicitly delimited or Pascal/ALL caps.
            if term in self.qualified_symbols:
                candidates = set(self.qualified_symbols[term])
                if len(candidates) != 1:
                    ambiguous.add(term)
                    continue
                symbol_id = next(iter(candidates))
                file_key = self.symbol_records[symbol_id].file_id
                if anchors and self.file_projects.get(file_key, "") not in anchors:
                    ambiguous.add(term)
                    continue
                if anchor_languages and self.file_languages.get(file_key, "") not in anchor_languages:
                    ambiguous.add(term)
                    continue
                matches[term] = {file_key}
                symbol_ids.add(symbol_id)
            elif term in self.bare_symbols:
                if term.casefold() in _GENERIC_BARE_TERMS or not self._bare_reference_is_explicit(term, text, explicit_terms):
                    continue
                candidates = set(self.bare_symbols[term])
                if anchors or anchor_languages:
                    candidates = {
                        item for item in candidates
                        if (not anchors or self.file_projects.get(self.symbol_records[item].file_id, "") in anchors)
                        and (not anchor_languages or self.file_languages.get(self.symbol_records[item].file_id, "") in anchor_languages)
                    }
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
        # The directory prefix of a brace/glob expression is not a separate
        # broad reference (app/api/ inside app/api/{tables,…}).
        for term in list(matches):
            if term in pattern_matches:
                continue
            prefix = term.rstrip("/") + "/"
            if any(candidate.startswith(prefix) for candidate in pattern_matches):
                matches.pop(term)
        ids = set().union(*matches.values()) if matches else set()
        # Partially resolved references remain usable: record ambiguity and
        # unresolved portions instead of discarding everything matched.
        basis = ("corroborated" if corroborated else "exact") if ids else (
            "ambiguous" if ambiguous else "unmapped")
        return {"ids": ids, "matches": matches, "unresolved": sorted(unresolved | ambiguous),
            "ambiguous": sorted(ambiguous), "symbols": symbol_ids, "basis": basis}

    def add_documented_labels(self, claims):
        for claim in sorted(claims, key=lambda item: item.model_dump_json()):
            if claim.certainty != "explicit":
                continue
            text = " ".join([
                claim.subject, claim.statement,
                *(evidence.quote for evidence in (claim.evidence or ())),
            ])
            parenthetical = re.search(
                r"\b((?:capa|layer)\s+\w+|\w+\s+(?:layer|capa))\s*\(([^)]+)\)",
                text, re.IGNORECASE)
            explicit_membership = bool(parenthetical) or bool(re.search(
                r"\b(source ownership|defined in|consists? of|owned by|located at|composed of|"
                r"ubicad[oa] en|definid[oa] en|pertenece a|propiedad de|se encuentra en|se ubica(?:n)? en|"
                r"corresponde a|comprende|comprenden|abarca|abarcan|incluye|incluyen|cubre|cubren|contiene|"
                r"includes?|comprises?|contains?)\b", text, re.IGNORECASE
            ))
            if not explicit_membership:
                continue
            if re.search(r"\b(proposed|hypothetical|for example|propuesto|propuesta|hipotético|ejemplo)\b",
                         text, re.IGNORECASE):
                continue
            if parenthetical:
                # Resolve only the parenthesised location pattern, never other
                # paths mentioned for responsibilities, helpers or dependencies.
                resolution_text = parenthetical.group(0)
            else:
                membership = re.search(
                    r"\b(source ownership|defined in|consists? of|owned by|located at|composed of|"
                    r"ubicad[oa] en|definid[oa] en|pertenece a|propiedad de|se encuentra en|se ubica(?:n)? en|"
                    r"corresponde a|comprende|comprenden|abarca|abarcan|incluye|incluyen|cubre|cubren|contiene|"
                    r"includes?|comprises?|contains?)\b",
                    text, re.IGNORECASE)
                location = text[membership.end():] if membership else ""
                resolution_text = re.split(r'[,;.]|\s+(?:y|or|and)\s+', location, flags=re.IGNORECASE, maxsplit=1)[0]
            result = self.resolve(resolution_text, include_labels=False)
            if not result["ids"] or result["ambiguous"]:
                continue
            ids = set(result["ids"])
            original = claim.subject.strip()
            parsed = (parenthetical.group(1) if parenthetical else original)
            core = re.sub(r"^(?:la|el)\s+", "", parsed.split("(", 1)[0].strip(), flags=re.IGNORECASE)
            labels = {parsed, original, core,
                      re.sub(r"\s+layer$", "", core, flags=re.IGNORECASE),
                      re.sub(r"^capa\s+", "", core, flags=re.IGNORECASE),
                      re.sub(r"\s+capa$", "", core, flags=re.IGNORECASE)}
            additive = bool(re.search(
                r"\b(incluye|incluyen|comprende|comprenden|abarca|abarcan|cubre|cubren|includes?|"
                r"comprises?|contains?)\b", text, re.IGNORECASE))
            for label in labels:
                existing = self.labels.get(label)
                if existing is None and label in self.labels:
                    continue
                if existing is None:
                    self.labels[label] = ids
                elif existing != ids:
                    # Complementary and subset declarations may extend a
                    # layer; conflicting exclusive locations remain ambiguous.
                    if additive or existing <= ids or ids <= existing:
                        self.labels[label] = set(existing) | ids
                    else:
                        self.labels[label] = None


_DEPENDENCY_VERB_RE = re.compile(
    r"\b(?:imports?|imported|importing|importar|importa(?:n)?|importen|importo|"
    r"dependen(?:cy|cies)?|dependen|depende|dependan|dependa|dependencia(?:s)?|"
    r"depends?|depended|depending|uses?|using|used|utiliza(?:r|n)?)\b",
    re.IGNORECASE,
)


def _explicit_destination_paths(record):
    """Paths explicitly designated as the restricted resource, if recoverable.

    Only the grammatical fragment following an import/dependency verb is
    searched, so a destination is not inferred from unrelated code names
    elsewhere in the claim.  The result is interpreted as a navigation
    predicate, never as an observed dependency.
    """
    text = " ".join((
        record.claim.subject or "",
        record.claim.statement or "",
        *getattr(record.claim, "related_subjects", []),
    ))
    match = _DEPENDENCY_VERB_RE.search(text)
    fragment = text[match.end():] if match else text
    destinations = set()
    for alias, paths in record.owner_paths.items():
        pattern = re.compile(
            r"(?<![\w./@])" + re.escape(alias) + r"(?![\w./@])",
            re.IGNORECASE)
        if pattern.search(fragment):
            destinations.update(paths)
    for path in record.scope_paths:
        if path in fragment:
            destinations.add(path)
    destinations.difference_update(record.subject_paths)
    destinations.difference_update(record.excluded_paths)
    return destinations


def relation_applies(record, source_path, target_path):
    """Applicability of a directed navigation seed, never its conformance."""
    if {source_path, target_path} & set(record.excluded_paths):
        return False
    scope = set(record.scope_paths)
    subject = set(record.subject_paths)
    text = f"{record.claim.subject} {record.claim.statement}".casefold()
    if record.boundary_family == "encapsulation" and re.search(r"\b(outside|external|consumers|callers|fuera de|externo[s]?|consumidores|clientes|llamantes)\b", text):
        return target_path in scope and source_path not in scope
    if source_path not in scope or target_path not in scope:
        return False
    if subject and source_path not in subject:
        return False
    if record.boundary_family == "dependency":
        destinations = _explicit_destination_paths(record)
        # An explicit restricted resource is required to call a directed
        # interaction pertinent. Without one, allow local exploration of the
        # regulated subject, but do not fabricate a pertinence verdict.
        return bool(destinations and target_path in destinations)
    if record.boundary_family == "acyclicity":
        # Cycles are relations among the documented owners themselves; an
        # unrelated external destination does not establish the cycle.
        groups = [set(paths) for paths in record.owner_paths.values()]
        disjoint = [(a, b) for a in groups for b in groups if not a & b]
        return not disjoint or any(source_path in a and target_path in b for a, b in disjoint)
    if record.boundary_family == "integration" and subject:
        return source_path in subject
    return False
