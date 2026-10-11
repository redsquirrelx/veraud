"""Second step of the pipeline: describe how the project is built.

The analyzer works out what a project IS; the architect works out how it is
put together, starting from the analyzer's output. It describes and reports
risks mapped to ISO/IEC 25010 maintainability, with evidence paths behind
every observation. It never scores: scoring belongs to the agents that run
after this one.

Phase 3 runs collect -> frame -> survey -> read -> characterize and returns
the frame plus one responsibility line per key component. Characterization
loops back through survey until every key component is described or the read
budget runs out, mirroring the analyzer's read rounds. Data flow, quality
notes and the full description land in phases 4-5.
"""

import json
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, StateGraph

from ...config.logs import get_logger
from ...config.prompts import load_prompt, render_prompt
from ...config.tracing import traced_generate
from ...services.collection.schemas import CollectionInput
from ...services.collection.service import CollectionService
from ..analyzer import facts as analyzer_facts
from ..analyzer import parsing as analyzer_parsing
from ..analyzer.evidence import MAX_CHARS_PER_RUN, read_excerpts, render_excerpts
from ..base import BaseAgent
from .diagrams import build_diagrams
from .schemas import ArchitectInput, ArchitectureDescription

logger = get_logger("architect-agent")

# Budget for the condensed structure facts handed to the frame prompt.
MAX_FACTS_CHARS = 24000

# How many files the survey step may ask to read.
MAX_FILES_PER_ROUND = 8

# Containers the model may group files into. More would atomize the
# diagram back into a file listing, which the repo map already is.
MAX_CONTAINERS = 5

# External groups cap for the same reason: a diagram with twenty third-party
# boxes says nothing. The model picks the roles that matter.
MAX_EXTERNAL_GROUPS = 6

# Risks reported at most. A longer list stops being read, and the loudest
# structural risks fit comfortably.
MAX_RISKS = 10

# ISO/IEC 25010 maintainability sub-characteristics. Anything else the model
# writes is dropped: quality notes outside this vocabulary cannot be compared.
QUALITY_CHARACTERISTICS = frozenset({
    "modularity", "analysability", "modifiability", "testability",
})


class _State(TypedDict, total=False):
    """What flows between nodes."""

    input: ArchitectInput
    root: str

    # Written by collect.
    facts: str
    directory_profiles: str
    known_files: set[str]
    entrypoints: list[str]
    derived_key_components: list[str]

    # Written by collect. Derived once, read by map25010 and run().
    third_party: list[str]
    cycles: list[list[str]]

    # Written by collect. Raw material for the diagram assembler: the
    # internal import edges plus per-file top-level symbol names.
    dep_edges: list[dict]
    file_symbols: dict

    # Written by frame.
    frame: dict
    pending: list[str]

    # Written by read. Excerpts accumulate so characterization is written
    # against everything that was read.
    read_paths: list[str]
    excerpts: str
    fresh_reads: int

    # Written by characterize.
    components: list[dict]

    # Written by verify_coverage.
    rounds: int
    coverage_ratio: float
    coverage_stalled: bool

    # Written by connect.
    data_flow: str

    # Written by map25010.
    quality_notes: list[dict]
    risks: list[str]

    # Written by group.
    containers: list[dict]
    externals: list[dict]

    # Written by diagram.
    diagram_containers: str
    diagram_components: str


class ArchitectureAgent(BaseAgent[ArchitectInput, ArchitectureDescription]):
    agent_type = "architect"
    input_schema = ArchitectInput
    output_schema = ArchitectureDescription

    def __init__(self, *args, collection: CollectionService | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._collection = collection or CollectionService()
        self._graph = self._build_graph()

    async def run(self, input_data: ArchitectInput) -> ArchitectureDescription:
        """Drive the graph and return what it settles on."""
        final = await self._graph.ainvoke({"input": input_data})

        frame = final.get("frame") or {}
        components = _ordered_components(
            final.get("components") or [],
            final.get("derived_key_components") or [],
        )
        notes = final.get("quality_notes") or []
        risks = final.get("risks") or []
        intended = str(frame.get("intended_style") or "unknown")

        logger.info(
            "run done: style=%r intended=%r components=%d notes=%d risks=%d files_read=%d rounds=%d coverage=%.2f",
            frame.get("style", "unknown"), intended,
            len(components), len(notes),
            len(risks), len(final.get("read_paths") or []),
            final.get("rounds", 0), final.get("coverage_ratio", 0.0),
        )
        externals = final.get("externals") or []
        logger.info("run done: containers=%d external_groups=%d", len(final.get("containers") or []), len(externals))
        return ArchitectureDescription(
            style=str(frame.get("style") or "unknown"),
            style_explanation=str(frame.get("reasoning") or ""),
            intended_style=intended,
            intended_explanation=str(frame.get("intended_reasoning") or ""),
            deviations=frame.get("deviations") or [],
            components=components,
            containers=final.get("containers") or [],
            externals=externals,
            diagram_containers=str(final.get("diagram_containers") or ""),
            diagram_components=str(final.get("diagram_components") or ""),
            data_flow=str(final.get("data_flow") or ""),
            third_party=final.get("third_party") or [],
            cycles=final.get("cycles") or [],
            quality_notes=notes,
            risks=risks,
            confidence=_calibrate_confidence(components, notes, intended),
            confidence_explanation=_explain_confidence(components, notes, intended),
        )

    # -- graph wiring -------------------------------------------------------

    def _build_graph(self):
        graph = StateGraph(_State)

        graph.add_node("collect", self._collect)
        graph.add_node("frame", self._frame)
        graph.add_node("survey", self._survey)
        graph.add_node("read", self._read)
        graph.add_node("characterize", self._characterize)
        graph.add_node("verify_coverage", self._verify_coverage)
        graph.add_node("group", self._group)
        graph.add_node("connect", self._connect)
        graph.add_node("map25010", self._map25010)
        graph.add_node("diagram", self._diagram)

        graph.set_entry_point("collect")
        graph.add_edge("collect", "frame")
        graph.add_edge("frame", "survey")
        graph.add_edge("survey", "read")
        graph.add_edge("read", "characterize")
        graph.add_edge("characterize", "verify_coverage")
        graph.add_conditional_edges("verify_coverage", _after_cover, {
            "again": "survey",
            "done": "group",
        })
        graph.add_edge("group", "connect")
        graph.add_edge("connect", "map25010")
        graph.add_edge("map25010", "diagram")
        graph.add_edge("diagram", END)

        return graph.compile()

    # -- nodes --------------------------------------------------------------

    async def _collect(self, state: _State) -> dict:
        """Gather the representations and condense them. No model involved."""
        input_data = state["input"]
        logger.info("run: collecting root=%r", input_data.root_path)

        collection = await self._collection.collect(CollectionInput(
            root_path=input_data.root_path,
            max_files=500,
            max_depth=8,
        ))

        data = collection.model_dump()
        files = data.get("repo_map", {}).get("files", [])
        edges = data.get("dependency_graph", {}).get("edges", [])
        facts, trimmed = analyzer_facts.build_facts(data, MAX_FACTS_CHARS)
        profiles = analyzer_facts.directory_profiles(files, edges)

        logger.info(
            "run: %d files, %d chars of facts (trimmed=%s), %d directory profiles",
            len(files), len(facts), trimmed, len(profiles),
        )

        return {
            "root": collection.root,
            "facts": facts,
            "directory_profiles": _dump(profiles),
            "known_files": analyzer_facts.known_paths(files),
            "entrypoints": sorted(analyzer_facts.entrypoint_candidates(files)),
            "derived_key_components": analyzer_facts.derived_key_components(edges, files),
            "third_party": analyzer_facts.third_party_dependencies(data),
            "cycles": analyzer_facts.cycles(data),
            "dep_edges": [
                {
                    "source": edge.get("source"),
                    "target": edge.get("target"),
                    "specifier": edge.get("specifier"),
                    "resolved": edge.get("resolved"),
                }
                for edge in edges
                if isinstance(edge, dict) and edge.get("source")
            ],
            "file_symbols": {
                item["path"]: [
                    str(symbol.get("name", "")).strip()
                    for symbol in (item.get("symbols") or [])
                    if isinstance(symbol, dict) and str(symbol.get("name", "")).strip()
                ]
                for item in files
                if isinstance(item, dict) and item.get("path")
            },
            "read_paths": [],
            "excerpts": "",
            "fresh_reads": 0,
            "rounds": 0,
        }

    async def _frame(self, state: _State) -> dict:
        """Guess what the repo tries to be, and why it falls short.

        Returns the observed style, the intended style and the deviations,
        plus the files that would confirm the reading. Deviations feed the
        survey step (what is worth reading) and later the risks.
        """
        analysis = state["input"].analysis
        prompt = (
            f"{load_prompt(self.agent_type, 'system')}\n\n---\n\n"
            f"{render_prompt(load_prompt(self.agent_type, 'frame'), facts=state['facts'], kind=analysis.kind, summary=analysis.summary, styles=load_prompt(self.agent_type, 'styles'), directory_profiles=state['directory_profiles'])}"
        )

        try:
            response = await traced_generate(self.model, prompt)
            answer = analyzer_parsing.parse_json(analyzer_parsing.extract_text(response))
        except Exception as error:  # noqa: BLE001 - providers raise varied errors
            logger.warning("frame: model gave no usable answer: %s", error)
            return {"frame": {}, "pending": list(state["entrypoints"])}

        wanted = analyzer_parsing.read_paths(answer, "would_confirm", state["known_files"])
        style = str(answer.get("style") or "unknown").strip().lower()
        intended = str(answer.get("intended_style") or "unknown").strip().lower()
        deviations = _read_deviations(answer, state["known_files"])

        logger.info(
            "frame: style=%r intended=%r reasoning=%r pending=%d paths deviations=%d",
            style, intended, analyzer_parsing.read_text(answer, "reasoning")[:120],
            len(wanted), len(deviations),
        )

        return {
            "frame": {
                "style": style,
                "intended_style": intended,
                "reasoning": analyzer_parsing.read_text(answer, "reasoning"),
                "intended_reasoning": analyzer_parsing.read_text(answer, "intended_reasoning"),
                "deviations": deviations,
            },
            "pending": _take(
                wanted + [path for deviation in deviations for path in deviation["evidence"]],
                MAX_FILES_PER_ROUND,
            ),
        }

    async def _survey(self, state: _State) -> dict:
        """Pick what to read: deviation evidence first, then entry points.

        On later rounds the still-undescribed components jump the queue: the
        loop exists to cover them, so the model is told exactly which ones
        are missing.
        """
        frame = state.get("frame") or {}
        pending = state.get("pending") or []
        undescribed = _undescribed(state)

        if not pending:
            return {"pending": _survey_floor(state)}

        answer = await self._ask_json(self._prompt(
            "survey",
            frame=_dump(frame),
            facts=state["facts"],
            directory_profiles=state["directory_profiles"],
            max_paths=MAX_FILES_PER_ROUND,
            style=frame.get("style", "unknown"),
            intended=frame.get("intended_style", "unknown"),
            undescribed=_bullets(undescribed),
        ))

        if answer is None:
            return {"pending": _survey_floor(state)}

        chosen = analyzer_parsing.read_paths(answer, "paths", state["known_files"])
        already = set(state["read_paths"])
        logger.info("survey: %d paths requested", len(chosen))

        picked = _take([path for path in chosen if path not in already], MAX_FILES_PER_ROUND)
        return {"pending": picked or _survey_floor(state)}

    async def _read(self, state: _State) -> dict:
        """Open the files the survey picked."""
        paths = state.get("pending") or []

        excerpts = read_excerpts(Path(state["root"]), paths, MAX_CHARS_PER_RUN)
        rendered = render_excerpts(excerpts)
        combined = "\n\n".join(part for part in (state["excerpts"], rendered) if part)

        logger.info("read: %d/%d files readable, %d chars total", len(excerpts), len(paths), len(combined))

        return {
            "read_paths": [*state["read_paths"], *[e.path for e in excerpts]],
            "excerpts": combined,
            "fresh_reads": len(excerpts),
        }

    async def _characterize(self, state: _State) -> dict:
        """Write one responsibility line per key component, from what was read."""
        key_components = state["derived_key_components"]

        if not state["excerpts"]:
            logger.info("characterize: nothing was read, components stay undescribed")
            return {"components": [{"path": path, "responsibility": ""} for path in key_components]}

        answer = await self._ask_json(self._prompt(
            "characterize",
            components=_bullets(key_components),
            excerpts=state["excerpts"],
        ))

        if answer is None:
            return {"components": [{"path": path, "responsibility": ""} for path in key_components]}

        by_path = {
            str(item.get("path", "")).strip(): analyzer_parsing.read_text(item, "responsibility")
            for item in answer.get("components", [])
            if isinstance(item, dict)
        }
        previous = {
            str(item.get("path", "")).strip(): str(item.get("responsibility", "") or "")
            for item in state.get("components") or []
            if isinstance(item, dict)
        }
        logger.info("characterize: %d/%d components described", sum(1 for path in key_components if by_path.get(path) or previous.get(path)), len(key_components))

        # Earlier rounds keep what they described: a later round that skips a
        # component must not undescribe it.
        return {"components": [
            {"path": path, "responsibility": by_path.get(path) or previous.get(path, "")}
            for path in key_components
            if path in state["known_files"]
        ]}

    async def _verify_coverage(self, state: _State) -> dict:
        """Count the round and say how much is described."""
        rounds = state.get("rounds", 0) + 1
        ratio = _coverage_ratio(
            state.get("components") or [], state["derived_key_components"]
        )
        previous = state.get("coverage_ratio")
        stalled = previous is not None and ratio <= previous

        logger.info("verify_coverage: ratio=%.2f rounds=%d stalled=%s", ratio, rounds, stalled)

        return {"coverage_ratio": ratio, "rounds": rounds, "coverage_stalled": stalled}

    async def _group(self, state: _State) -> dict:
        """Group the important files into named containers (C4 level 2).

        Membership is model judgment over everything read; validation is
        mechanical. Invented members are dropped, and a container left with
        nothing real is dropped whole. With no described components there is
        nothing worth grouping, so the model is not even asked.
        """
        key_components = state["derived_key_components"]

        if not key_components:
            return {"containers": [], "externals": []}

        answer = await self._ask_json(self._prompt(
            "group",
            facts=state["facts"],
            directory_profiles=state["directory_profiles"],
            components=_bullets(key_components),
            third_party=_bullets(state.get("third_party") or []),
            excerpts=state["excerpts"] or NO_SOURCE_READ,
            max_containers=MAX_CONTAINERS,
            max_external_groups=MAX_EXTERNAL_GROUPS,
        ))

        if answer is None:
            return {"containers": [], "externals": []}

        known = state["known_files"]
        containers = _read_containers(answer, known)[:MAX_CONTAINERS]
        externals = _read_externals(answer, state.get("third_party") or [])[:MAX_EXTERNAL_GROUPS]
        logger.info("group: %d containers, %d external groups", len(containers), len(externals))

        return {"containers": containers, "externals": externals}

    async def _connect(self, state: _State) -> dict:
        """Trace execution flow from the entry points, in prose."""
        frame = state.get("frame") or {}

        answer = await self._ask_json(self._prompt(
            "connect",
            frame=_dump(frame),
            entrypoints=_bullets(state["entrypoints"]),
            components=_bullets(state["derived_key_components"]),
            excerpts=state["excerpts"] or NO_SOURCE_READ,
        ))

        data_flow = analyzer_parsing.read_text(answer or {}, "data_flow")
        logger.info("connect: %d chars of flow", len(data_flow))

        return {"data_flow": data_flow}

    async def _map25010(self, state: _State) -> dict:
        """Report maintainability notes and risks, all with evidence."""
        frame = state.get("frame") or {}

        answer = await self._ask_json(self._prompt(
            "map25010",
            frame=_dump(frame),
            data_flow=state.get("data_flow") or "(no flow traced)",
            cycles=_dump(state.get("cycles") or []),
            third_party=_dump(state.get("third_party") or []),
            excerpts=state["excerpts"] or NO_SOURCE_READ,
        ))

        if answer is None:
            floor = _risks_floor(state)
            logger.info("map25010: model gave nothing, %d floor risks", len(floor))
            return {"quality_notes": [], "risks": floor}

        notes = _read_quality_notes(answer, state["known_files"])
        risks = _read_risks(answer)
        logger.info("map25010: %d notes, %d risks", len(notes), len(risks))

        return {"quality_notes": notes, "risks": risks}

    async def _diagram(self, state: _State) -> dict:
        """Assemble the Mermaid blocks from grouping plus derived structure.

        Pure assembly, no model involved: names and membership are the group
        node's judgment, every arrow and interface is derived. With no
        containers and no components there is nothing to draw.
        """
        diagrams = build_diagrams(
            system_name=Path(state["root"]).name,
            edges=state.get("dep_edges") or [],
            file_symbols=state.get("file_symbols") or {},
            containers=state.get("containers") or [],
            externals=state.get("externals") or [],
            components=state.get("components") or [],
            entrypoints=state.get("entrypoints") or [],
            cycles=state.get("cycles") or [],
            third_party=state.get("third_party") or [],
        )
        logger.info(
            "diagram: containers=%d chars components=%d chars truncated=%s",
            len(diagrams["containers"]), len(diagrams["components"]), diagrams["truncated"],
        )

        return {
            "diagram_containers": diagrams["containers"],
            "diagram_components": diagrams["components"],
        }

    # -- helpers ------------------------------------------------------------

    def _prompt(self, name: str, **values: object) -> str:
        """The agent's role plus one node's task, ready to send."""
        template = load_prompt(self.agent_type, name)
        role = load_prompt(self.agent_type, "system")
        return f"{role}\n\n---\n\n{render_prompt(template, **values)}"

    async def _ask_json(self, prompt: str) -> dict | None:
        """One model call, returning None instead of raising."""
        try:
            response = await traced_generate(self.model, prompt)
            return analyzer_parsing.parse_json(analyzer_parsing.extract_text(response))
        except Exception as error:  # noqa: BLE001 - providers raise varied errors
            logger.warning("model gave no usable answer: %s", error)
            return None


NO_SOURCE_READ = "(no source code could be read)"


def _ordered_components(described: list[dict], key_components: list[str]) -> list[dict]:
    """Described components in derived order, so the list is stable."""
    by_path = {
        str(item.get("path", "")).strip(): str(item.get("responsibility", "") or "")
        for item in described
        if isinstance(item, dict)
    }
    return [{"path": path, "responsibility": by_path.get(path, "")} for path in key_components]


def _calibrate_confidence(components: list[dict], notes: list[dict], intended: str) -> str:
    """Confidence from evidence, not from the model claiming it.

    High needs everything described, at least one evidenced note, and a known
    intention. Medium needs at least half described plus something backing it.
    Anything less is low: the description admits its gaps.
    """
    if not components:
        return "low"

    described = sum(1 for component in components if component.get("responsibility"))
    ratio = described / len(components)
    backed = len(notes) > 0
    known_intent = intended not in ("", "unknown")

    if ratio == 1.0 and backed and known_intent:
        return "high"
    if ratio >= 0.5 and (backed or known_intent):
        return "medium"
    return "low"


def _explain_confidence(components: list[dict], notes: list[dict], intended: str) -> str:
    """Why the confidence level holds, from the same evidence that sets it.

    Derived, never model-written: it must stay consistent with the level even
    when the model would rather sound sure. Names the gaps, so a low
    confidence tells the reader exactly what is missing.
    """
    total = len(components)
    missing = [
        str(component.get("path", "")).strip()
        for component in components
        if not str(component.get("responsibility", "") or "").strip()
    ]
    parts = (
        [f"{total - len(missing)}/{total} components described"]
        if total else ["no key components found"]
    )
    if missing:
        shown = ", ".join(missing[:5])
        parts.append(f"undescribed: {shown}" + (f" and {len(missing) - 5} more" if len(missing) > 5 else ""))
    parts.append(
        f"{len(notes)} quality note(s) with evidence" if notes
        else "no quality notes with evidence"
    )
    parts.append(
        f"intended style known ({intended})" if intended not in ("", "unknown")
        else "intended style unknown"
    )
    return "; ".join(parts) + "."


def _undescribed(state: _State) -> list[str]:
    """Key components with no responsibility line yet, in derived order."""
    described = {
        str(item.get("path", "")).strip()
        for item in state.get("components") or []
        if isinstance(item, dict) and str(item.get("responsibility", "") or "").strip()
    }
    return [path for path in state["derived_key_components"] if path not in described]


def _coverage_ratio(components: list[dict], key_components: list[str]) -> float:
    """Share of key components carrying a responsibility line."""
    if not key_components:
        return 1.0

    by_path = {
        str(item.get("path", "")).strip(): str(item.get("responsibility", "") or "")
        for item in components
        if isinstance(item, dict)
    }
    described = sum(1 for path in key_components if by_path.get(path, "").strip())
    return described / len(key_components)


def _after_cover(state: _State) -> str:
    """Route on whether another read round is worth spending."""
    if state.get("coverage_ratio", 0.0) >= 1.0:
        return "done"

    if state.get("rounds", 0) >= state["input"].max_read_rounds:
        return "done"

    if not state.get("known_files"):
        return "done"

    if len(state.get("read_paths", [])) >= len(state["known_files"]):
        # Everything in the repository has been read. Another round cannot
        # produce evidence that does not exist.
        return "done"

    if state.get("rounds", 0) > 1 and not state.get("fresh_reads"):
        # The last round opened nothing new, so there is nothing new to
        # characterize against.
        return "done"

    if state.get("coverage_stalled", False):
        # Coverage did not grow: more reading is not turning into
        # descriptions, so further rounds would only spend model calls.
        return "done"

    return "again"


def _read_containers(answer: dict, known_files: set[str]) -> list[dict]:
    """Containers with real members, in the model's order.

    Names and responsibilities are judgment; membership is checked. Invented
    members are dropped, and a container left empty is dropped whole: an
    empty box on a diagram is worse than no box.
    """
    found: list[dict] = []
    raw = answer.get("containers")

    if not isinstance(raw, list):
        return found

    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        files = [
            path for path in analyzer_parsing.read_paths(item, "files", known_files)
        ]
        if not files:
            continue
        found.append({
            "name": name,
            "responsibility": analyzer_parsing.read_text(item, "responsibility"),
            "files": files,
        })

    return found


def _read_externals(answer: dict, third_party: list[str]) -> list[dict]:
    """External groups with real members, in the model's order.

    Members must come from the collected third-party list verbatim: an
    invented dependency would put a fantasy box on the diagram. A group left
    empty is dropped whole, like containers.
    """
    known = set(third_party)
    found: list[dict] = []
    raw = answer.get("externals")

    if not isinstance(raw, list):
        return found

    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        members = []
        for value in item.get("members", []):
            member = str(value).strip() if isinstance(value, str) else ""
            if member and member in known and member not in members:
                members.append(member)
        if not members:
            continue
        found.append({"name": name, "members": members})

    return found


def _survey_floor(state: _State) -> list[str]:
    """Deterministic fallback: deviation evidence, entry points, components.

    On later rounds the still-undescribed components jump the queue, for the
    same reason the survey prompt names them: the loop exists to cover them.
    """
    frame = state.get("frame") or {}
    deviations = frame.get("deviations") or []
    evidence = [path for deviation in deviations if isinstance(deviation, dict) for path in deviation.get("evidence", [])]
    if state.get("rounds", 0) > 0:
        wanted = evidence + _undescribed(state) + list(state["entrypoints"]) + state["derived_key_components"]
    else:
        wanted = evidence + list(state["entrypoints"]) + state["derived_key_components"]
    already = set(state["read_paths"])
    return _take([path for path in wanted if path not in already], MAX_FILES_PER_ROUND)


def _risks_floor(state: _State) -> list[str]:
    """Risks without a model: deviations plus detected cycles, capped."""
    frame = state.get("frame") or {}
    risks: list[str] = []

    for deviation in frame.get("deviations") or []:
        if not isinstance(deviation, dict):
            continue
        observation = analyzer_parsing.read_text(deviation, "observation")
        if not observation:
            continue
        evidence = ", ".join(
            path for path in deviation.get("evidence", []) if isinstance(path, str)
        )
        risks.append(f"{observation} ({evidence})" if evidence else observation)

    for group in state.get("cycles") or []:
        members = sorted(str(path) for path in group if path)
        if len(members) > 1:
            risks.append(f"Circular imports: {' ↔ '.join(members)}")

    seen: set[str] = set()
    unique = [risk for risk in risks if risk not in seen and not seen.add(risk)]
    return unique[:MAX_RISKS]


def _read_quality_notes(answer: dict, known_files: set[str]) -> list[dict]:
    """Notes with a valid characteristic and ranged evidence.

    Every evidence entry must name its line intervals: a bare path proves
    nothing precise enough to keep, so notes citing only bare paths are
    dropped with it. Evidence keeps its raw `path:L1-L2` form so the judge
    can re-read exactly what was cited.
    """
    notes: list[dict] = []
    raw = answer.get("quality_notes")

    if not isinstance(raw, list):
        return notes

    for item in raw:
        if not isinstance(item, dict):
            continue
        characteristic = str(item.get("characteristic") or "").strip().lower()
        if characteristic not in QUALITY_CHARACTERISTICS:
            continue
        observation = analyzer_parsing.read_text(item, "observation")
        if not observation:
            continue
        evidence = analyzer_parsing.read_evidence(item, "evidence", known_files, require_ranges=True)
        if not evidence:
            continue
        notes.append({
            "characteristic": characteristic,
            "observation": observation,
            "evidence": evidence,
        })

    return notes


def _read_risks(answer: dict) -> list[str]:
    """Non-empty risk strings, capped."""
    raw = answer.get("risks")

    if not isinstance(raw, list):
        return []

    risks = [str(item).strip() for item in raw if isinstance(item, str) and str(item).strip()]
    return risks[:MAX_RISKS]


def _read_deviations(answer: dict, known_files: set[str]) -> list[dict]:
    """Deviations with ranged evidence, in the model's order.

    Like quality notes, every entry must name line intervals: bare paths are
    dropped. An empty evidence list still passes, for deviations that report
    an absence (a missing boundary cites nothing because there is nothing).
    Evidence keeps its raw `path:L1-L2` form.
    """
    found: list[dict] = []
    raw = answer.get("deviations")

    if not isinstance(raw, list):
        return found

    for item in raw:
        if not isinstance(item, dict):
            continue
        observation = analyzer_parsing.read_text(item, "observation")
        if not observation:
            continue
        evidence = analyzer_parsing.read_evidence(item, "evidence", known_files, require_ranges=True)
        found.append({"observation": observation, "evidence": evidence})

    return found


def _take(paths: list[str], limit: int) -> list[str]:
    """First `limit` distinct paths, order preserved."""
    seen: set[str] = set()
    chosen: list[str] = []

    for path in paths:
        if path and path not in seen:
            seen.add(path)
            chosen.append(path)
        if len(chosen) == limit:
            break

    return chosen


def _bullets(paths: list[str]) -> str:
    return "\n".join(f"- {path}" for path in paths) or "(none)"


def _dump(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)
