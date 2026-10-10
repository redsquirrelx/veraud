"""Second step of the pipeline: describe how the project is built.

The analyzer works out what a project IS; the architect works out how it is
put together, starting from the analyzer's output. It describes and reports
risks mapped to ISO/IEC 25010 maintainability, with evidence paths behind
every observation. It never scores: scoring belongs to the agents that run
after this one.

Phase 3 runs collect -> frame -> survey -> read -> characterize and returns
the frame plus one responsibility line per key component. Data flow, quality
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
from .schemas import ArchitectInput, ArchitectureDescription

logger = get_logger("architect-agent")

# Budget for the condensed structure facts handed to the frame prompt.
MAX_FACTS_CHARS = 24000

# How many files the survey step may ask to read.
MAX_FILES_PER_ROUND = 8

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

    # Written by frame.
    frame: dict
    pending: list[str]

    # Written by read. Excerpts accumulate so characterization is written
    # against everything that was read.
    read_paths: list[str]
    excerpts: str

    # Written by characterize.
    components: list[dict]

    # Written by connect.
    data_flow: str

    # Written by map25010.
    quality_notes: list[dict]
    risks: list[str]


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

        logger.info(
            "run done: style=%r intended=%r components=%d notes=%d risks=%d files_read=%d",
            frame.get("style", "unknown"), frame.get("intended_style", "unknown"),
            len(components), len(final.get("quality_notes") or []),
            len(final.get("risks") or []), len(final.get("read_paths") or []),
        )
        return ArchitectureDescription(
            style=str(frame.get("style") or "unknown"),
            intended_style=str(frame.get("intended_style") or "unknown"),
            deviations=frame.get("deviations") or [],
            components=components,
            data_flow=str(final.get("data_flow") or ""),
            third_party=final.get("third_party") or [],
            cycles=final.get("cycles") or [],
            quality_notes=final.get("quality_notes") or [],
            risks=final.get("risks") or [],
        )

    # -- graph wiring -------------------------------------------------------

    def _build_graph(self):
        graph = StateGraph(_State)

        graph.add_node("collect", self._collect)
        graph.add_node("frame", self._frame)
        graph.add_node("survey", self._survey)
        graph.add_node("read", self._read)
        graph.add_node("characterize", self._characterize)
        graph.add_node("connect", self._connect)
        graph.add_node("map25010", self._map25010)

        graph.set_entry_point("collect")
        graph.add_edge("collect", "frame")
        graph.add_edge("frame", "survey")
        graph.add_edge("survey", "read")
        graph.add_edge("read", "characterize")
        graph.add_edge("characterize", "connect")
        graph.add_edge("connect", "map25010")
        graph.add_edge("map25010", END)

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
            "read_paths": [],
            "excerpts": "",
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
                "deviations": deviations,
            },
            "pending": _take(
                wanted + [path for deviation in deviations for path in deviation["evidence"]],
                MAX_FILES_PER_ROUND,
            ),
        }

    async def _survey(self, state: _State) -> dict:
        """Pick what to read: deviation evidence first, then entry points."""
        frame = state.get("frame") or {}
        pending = state.get("pending") or []

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
        logger.info("characterize: %d/%d components described", sum(1 for path in key_components if by_path.get(path)), len(key_components))

        return {"components": [
            {"path": path, "responsibility": by_path.get(path, "")}
            for path in key_components
            if path in state["known_files"]
        ]}

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


def _survey_floor(state: _State) -> list[str]:
    """Deterministic fallback: deviation evidence, entry points, components."""
    frame = state.get("frame") or {}
    deviations = frame.get("deviations") or []
    evidence = [path for deviation in deviations if isinstance(deviation, dict) for path in deviation.get("evidence", [])]
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
    """Notes with a valid characteristic and existing evidence paths."""
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
        evidence = [
            path for path in analyzer_parsing.read_paths(item, "evidence", known_files)
        ]
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
    """Deviations with existing evidence paths, in the model's order."""
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
        evidence = [
            path for path in analyzer_parsing.read_paths(item, "evidence", known_files)
        ]
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
