import json
import sys

from ...config.logs import get_logger
from ...services.collection.schemas import CollectionInput
from ...services.collection.service import CollectionService
from ..base import BaseAgent
from .schemas import ProjectDescription, ProjectInput

logger = get_logger("analyzer-agent")

# Rough token ceiling for the facts handed to the model. The map is trimmed to
# fit rather than truncated silently, so the model is told what it is missing.
MAX_PROMPT_CHARS = 24000

# A package __init__.py at least this long is treated as a public API. Chosen
# because build123d's is 289 lines of pure re-exports with zero defs of its own,
# and missing it made the analyzer report a library with no entry point at all.
MIN_PUBLIC_API_LINES = 60

# Standard library names. They are not project dependencies: every Python
# project imports them, so listing them only buries the third-party signal.
STDLIB = frozenset(sys.stdlib_module_names) | {"__future__"}

# Circular groups reported to the model. The graph computes all of them; this
# keeps a pathological repository from crowding out the rest of the facts.
MAX_REPORTED_CYCLES = 5


class ProjectAnalyzerAgent(BaseAgent[ProjectInput, ProjectDescription]):
    """First step of the pipeline: describe the repository, judge nothing.

    It collects the representations it needs, hands the facts to the model, and
    returns a description. It does not score quality, assess modularity or
    report findings: those belong to the agents that run after it.
    """

    agent_type = "analyzer"
    input_schema = ProjectInput
    output_schema = ProjectDescription

    def __init__(self, *args, collection: CollectionService | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._collection = collection or CollectionService()

    async def run(self, input_data: ProjectInput) -> ProjectDescription:
        logger.info(
            "run: describing root=%r max_depth=%d", input_data.root_path, input_data.max_depth
        )

        collection = await self._collection.collect(CollectionInput(
            root_path=input_data.root_path,
            max_files=input_data.max_files,
            max_depth=input_data.max_depth,
        ))

        facts, trimmed = self._build_facts(collection.model_dump())
        logger.info(
            "run: collected %d chars of facts (trimmed=%s)", len(facts), trimmed
        )

        prompt = f"{self.system_prompt()}\n\n{self.user_prompt(facts=facts)}"

        try:
            response = await self.model.generate(prompt)
            text = _extract_text(response)
            parsed = _parse_json(text)
        except Exception as error:  # noqa: BLE001 - providers raise varied errors
            # Matches the fail-soft rule the other agents follow: an
            # unreachable model, or an unusable answer, produces a description
            # saying so rather than a 500. Never raises.
            logger.warning("run: no usable description (%s)", error)
            return _unavailable()

        description = _build_description(parsed, collection.root)

        logger.info(
            "run done: kind=%r confidence=%r", description.kind, description.confidence
        )
        return description

    @staticmethod
    def _build_facts(collection: dict) -> tuple[str, bool]:
        """Condense the collection into the few facts that decide 'what is this'.

        The full dependency graph is not included on purpose: hundreds of edges
        do not help identify a project, and they crowd out the signals that do.
        """
        repo_map = collection.get("repo_map", {})
        graph = collection.get("dependency_graph", {})

        files = repo_map.get("files", [])

        payload = {
            "root": collection.get("root"),
            "stats": collection.get("stats", {}),
            "package_entrypoints": _package_entrypoints(files),
            "entrypoint_candidates": _entrypoint_candidates(files),
            "third_party_dependencies": _declared_dependencies(collection),
            "hub_modules": _hub_modules(graph.get("edges", []), limit=12),
            "circular_import_groups": _cycles(collection),
            "files": [
                {
                    "path": item.get("path"),
                    "language": item.get("language"),
                    "lines": item.get("lines"),
                    "symbols": len(item.get("symbols") or []),
                }
                for item in files
            ],
        }

        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if len(text) <= MAX_PROMPT_CHARS:
            return text, False

        # Structure outlives detail. Hubs go first, then the file list, but the
        # entry points always stay: they are the strongest single signal for
        # what kind of project this is.
        payload.pop("hub_modules", None)

        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if len(text) <= MAX_PROMPT_CHARS:
            return text, True

        payload.pop("files", None)
        payload["note"] = "File list omitted to fit the prompt; totals still apply."
        return json.dumps(payload, indent=2, ensure_ascii=False), True


def _package_entrypoints(files: list[dict]) -> list[str]:
    """Packages that export a public API, which is how a library is entered.

    A published library usually has no main.py at all: consumers import the
    package, so the package directory is the entry point.
    """
    packages = set()

    for item in files:
        path = item.get("path") or ""
        if not path.endswith("__init__.py"):
            continue
        package = path[: -len("/__init__.py")]

        if not package:
            continue
        if item.get("symbols") or (item.get("lines") or 0) >= MIN_PUBLIC_API_LINES:
            packages.add(package)

    return sorted(packages)


def _declared_dependencies(collection: dict) -> list[str]:
    """Third-party import names seen across the repo, stdlib excluded.

    Reads what the code imports rather than what pyproject declares, because the
    dependency graph is what the collection already has. Standard library names
    are dropped: every project imports os and json, so they say nothing about
    what the project is. Names are deduplicated and sorted so the same repo
    always produces the same prompt.
    """
    names = set()

    for edge in collection.get("dependency_graph", {}).get("edges", []):
        if edge.get("resolved"):
            continue
        specifier = (edge.get("specifier") or "").strip()
        # `from . import x` yields an empty base, and a bare `from . import x`
        # with no module. Neither names a dependency.
        if not specifier:
            continue
        head = specifier.split(".", 1)[0].strip()
        if head and head not in STDLIB and head not in names:
            names.add(head)

    return sorted(names)


def _cycles(collection: dict) -> list[list[str]]:
    """Circular import groups, already computed by the dependency graph.

    These are facts, not judgements: Tarjan found them. The model is told they
    exist so it can interpret them, not asked to re-derive them.
    """
    cycles = collection.get("dependency_graph", {}).get("stats", {}).get("cycles", [])

    if not cycles:
        return []

    # Largest first: a big cycle is the more meaningful structural fact, and the
    # list is capped so a pathological repo cannot crowd out the rest.
    ordered = sorted(cycles, key=len, reverse=True)
    return [sorted(group) for group in ordered[:MAX_REPORTED_CYCLES]]


def _entrypoint_candidates(files: list[dict]) -> list[str]:
    """Files whose name says execution starts there.

    A library has none of these: consumers import the package instead. That case
    is covered by `package_entrypoints`.
    """
    markers = ("main.py", "__main__.py", "app.py", "wsgi.py", "asgi.py", "manage.py", "cli.py")
    found: set[str] = set()

    for item in files:
        path = item.get("path") or ""
        name = path.rsplit("/", 1)[-1]

        if name in markers:
            found.add(path)
        elif name == "__init__.py" and (item.get("lines") or 0) >= MIN_PUBLIC_API_LINES:
            # A large package __init__ is a public API, even when it only
            # re-exports and defines no functions of its own.
            found.add(path)

    return sorted(found)


def _hub_modules(edges: list[dict], limit: int) -> list[dict]:
    """Files with the most internal edges: where the project holds together."""
    degrees: dict[str, dict[str, int]] = {}

    for edge in edges:
        target = edge.get("target")
        if not target:
            continue
        degrees.setdefault(edge["source"], {})["out"] = \
            degrees.setdefault(edge["source"], {}).get("out", 0) + 1
        degrees.setdefault(target, {})["in"] = \
            degrees.setdefault(target, {}).get("in", 0) + 1

    ranked = sorted(
        degrees.items(),
        key=lambda item: -(item[1].get("in", 0) + item[1].get("out", 0)),
    )

    return [
        {"path": path, "imported_by": data.get("in", 0), "imports": data.get("out", 0)}
        for path, data in ranked[:limit]
    ]


def _parse_json(text: str) -> dict:
    """Pull the first JSON object out of a model response."""
    if not text or not text.strip():
        raise ValueError("empty response")

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end <= start:
        raise ValueError("no JSON object in response")

    parsed = json.loads(text[start:end + 1])

    if not isinstance(parsed, dict):
        raise TypeError("response was not a JSON object")

    return parsed


def _unavailable() -> ProjectDescription:
    """What the agent returns when it could not describe the repository.

    Deliberately not a raising error: a description that says nothing was
    learned is more useful downstream than a failed request, because the next
    agent can still see which repository it was looking at.
    """
    return ProjectDescription(
        kind="unknown",
        summary="The model did not return a usable description of this repository.",
        primary_language="unknown",
        confidence="low",
    )


# Coarse categories the prompt asks for. The model may still invent one, so the
# value is checked rather than trusted.
KINDS = frozenset({
    "cli", "library", "web_service", "desktop_app",
    "data_pipeline", "script", "unknown",
})

CONFIDENCES = frozenset({"low", "medium", "high"})


def _build_description(parsed: dict, root: str) -> ProjectDescription:
    """Shape whatever the model returned into a valid description.

    The model is not trusted to honour the schema. A made-up kind or confidence
    is demoted to the conservative value rather than rejected: an off-vocabulary
    answer still tells the reader the model was unsure.
    """
    raw_kind = str(parsed.get("kind") or "").strip().lower()
    kind = raw_kind if raw_kind in KINDS else "unknown"

    raw_confidence = str(parsed.get("confidence") or "").strip().lower()
    confidence = raw_confidence if raw_confidence in CONFIDENCES else "low"

    summary = str(parsed.get("summary") or "").strip()
    if not summary:
        summary = "The model returned no summary for this repository."

    if kind == "unknown":
        confidence = "low"

    return ProjectDescription(
        kind=kind,
        summary=summary,
        primary_language=str(parsed.get("primary_language") or "unknown").strip() or "unknown",
        entrypoints=[str(item) for item in _as_list(parsed.get("entrypoints"))],
        key_components=[str(item) for item in _as_list(parsed.get("key_components"))],
        confidence=confidence,
    )


def _as_list(value: object) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _extract_text(response: object) -> str:
    """Normalize whatever the model client returns into a string."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response

    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )

    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text

    return str(response)