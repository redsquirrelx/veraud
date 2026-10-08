"""First step of the pipeline: describe the repository, judge nothing.

The analyzer runs as a graph rather than one prompt because a repository does
not fit in a prompt. build123d has 246 modules and 226,000 lines, so a single
call can only ever see a file listing. The graph exists to narrow:

    collect -> hypothesize -> select -> read -> verify -> synthesize
                                ^                  |
                                +---- more rounds--+

    hypothesize  what is this, and what would confirm it?
    select       which files would confirm it?
    read         open those files
    verify       did the source agree? no -> pick different files and go again
    synthesize   write the description, confidence backed by what was read

Nothing here scores quality or assesses modularity. Those belong to the agents
that run after this one.
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
from ..base import BaseAgent
from . import facts as fact_tools
from . import parsing
from .evidence import MAX_CHARS_PER_RUN, read_excerpts, render_excerpts
from .schemas import ProjectDescription, ProjectInput

logger = get_logger("analyzer-agent")

# Budget for the condensed structure facts handed to the first prompt.
MAX_FACTS_CHARS = 24000

# How many entry point files the analyzer reads whatever the model asked for.
MIN_EVIDENCE_FILES = 3


class _State(TypedDict, total=False):
    """What flows between nodes."""

    input: ProjectInput
    root: str

    # Written by collect.
    facts: str
    known_files: set[str]
    entrypoints: list[str]

    # Written by hypothesize.
    hypothesis: dict
    pending: list[str]

    # Written by read. Excerpts accumulate so the final description is written
    # against everything that was read, not just the last round.
    read_paths: list[str]
    excerpts: str

    # Written by verify.
    confirmed: bool
    rounds: int
    fresh_reads: int

    # Written by synthesize.
    description: ProjectDescription


class ProjectAnalyzerAgent(BaseAgent[ProjectInput, ProjectDescription]):
    agent_type = "analyzer"
    input_schema = ProjectInput
    output_schema = ProjectDescription

    def __init__(self, *args, collection: CollectionService | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._collection = collection or CollectionService()
        self._graph = self._build_graph()

    async def run(self, input_data: ProjectInput) -> ProjectDescription:
        """Drive the graph and return the description it settles on."""
        state = await self._collect(input_data)
        final = await self._graph.ainvoke(state)

        description = final.get("description")
        if description is None:
            return parsing.unavailable("The analyzer graph produced no description.")

        logger.info(
            "run done: kind=%r confidence=%r files_read=%d rounds=%d confirmed=%s",
            description.kind, description.confidence,
            description.files_read, description.read_rounds,
            description.hypothesis_confirmed,
        )
        return description

    # -- graph wiring -------------------------------------------------------

    def _build_graph(self):
        graph = StateGraph(_State)

        graph.add_node("hypothesize", self._hypothesize)
        graph.add_node("select", self._select)
        graph.add_node("read", self._read)
        graph.add_node("verify", self._verify)
        graph.add_node("synthesize", self._synthesize)

        graph.set_entry_point("hypothesize")
        graph.add_edge("hypothesize", "select")
        graph.add_edge("select", "read")
        graph.add_edge("read", "verify")
        graph.add_conditional_edges("verify", _after_verify, {
            "again": "select",
            "done": "synthesize",
        })
        graph.add_edge("synthesize", END)

        return graph.compile()

    # -- nodes --------------------------------------------------------------

    async def _collect(self, input_data: ProjectInput) -> _State:
        """Gather the representations and condense them. No model involved."""
        logger.info(
            "run: describing root=%r max_depth=%d",
            input_data.root_path, input_data.max_depth,
        )

        collection = await self._collection.collect(CollectionInput(
            root_path=input_data.root_path,
            max_files=input_data.max_files,
            max_depth=input_data.max_depth,
        ))

        data = collection.model_dump()
        files = data.get("repo_map", {}).get("files", [])
        facts, trimmed = fact_tools.build_facts(data, MAX_FACTS_CHARS)

        logger.info(
            "run: %d files, %d chars of facts (trimmed=%s)",
            len(files), len(facts), trimmed,
        )

        return {
            "input": input_data,
            "root": collection.root,
            "facts": facts,
            "known_files": fact_tools.known_paths(files),
            "entrypoints": _evidence_floor(files),
            "read_paths": [],
            "excerpts": "",
            "rounds": 0,
            "fresh_reads": 0,
            "confirmed": False,
        }

    async def _hypothesize(self, state: _State) -> _State:
        """Guess the kind from the structure, and say what would confirm it."""
        answer = await self._ask_json(self._prompt("hypothesize", facts=state["facts"]))

        if answer is None:
            # Without a hypothesis there is nothing to confirm, but the entry
            # points are still worth reading, so the run continues.
            return {"hypothesis": {}, "pending": list(state["entrypoints"])}

        logger.info(
            "hypothesize: kind=%r reasoning=%r",
            parsing.read_kind(answer), parsing.read_text(answer, "reasoning")[:120],
        )

        # The model's picks come first: it knows what it wants to see. The entry
        # points follow as a floor so there is always something concrete to read.
        wanted = parsing.read_paths(answer, "would_confirm", state["known_files"])

        return {
            "hypothesis": answer,
            "pending": _take(wanted + state["entrypoints"], state["input"].max_files_per_round),
        }

    async def _select(self, state: _State) -> _State:
        """Later rounds: let the model redirect now that it has seen something."""
        if state["rounds"] == 0:
            # Round one already chose its files in the hypothesis step.
            return {}

        answer = await self._ask_json(self._prompt(
            "select",
            max_paths=state["input"].max_files_per_round,
            read_paths=_bullets(state["read_paths"]),
            excerpts=state["excerpts"] or NO_SOURCE_READ,
        ))

        if answer is None:
            return {"pending": []}

        # filters invalid paths
        chosen = parsing.read_paths(answer, "paths", state["known_files"])
        already = set(state["read_paths"])

        logger.info("select: %d paths requested", len(chosen))

        return {
            "pending": _take(
                [path for path in chosen if path not in already],
                state["input"].max_files_per_round,
            ),
        }

    async def _read(self, state: _State) -> _State:
        """Open the files the previous node picked."""
        paths = state.get("pending") or []
        budget = MAX_CHARS_PER_RUN - len(state["excerpts"])

        excerpts = read_excerpts(Path(state["root"]), paths, budget)
        rendered = render_excerpts(excerpts)
        combined = "\n\n".join(part for part in (state["excerpts"], rendered) if part)

        logger.info(
            "read: %d/%d files readable, %d chars total (round %d)",
            len(excerpts), len(paths), len(combined), state["rounds"] + 1,
        )

        return {
            "read_paths": [*state["read_paths"], *[e.path for e in excerpts]],
            "excerpts": combined,
            "fresh_reads": len(excerpts),
        }

    async def _verify(self, state: _State) -> _State:
        """Ask whether the source agreed, and count the round."""
        rounds = state["rounds"] + 1

        if not state["fresh_reads"]:
            # Nothing new was readable, so there is nothing to confirm.
            return {"confirmed": False, "rounds": rounds}

        answer = await self._ask_json(self._prompt(
            "verify",
            hypothesis=_dump(state["hypothesis"]),
            excerpts=state["excerpts"],
        ))

        confirmed = bool(answer and answer.get("confirmed"))

        logger.info(
            "verify: confirmed=%s rounds=%d | %s",
            confirmed, rounds, parsing.read_text(answer or {}, "reasoning")[:120],
        )

        return {"confirmed": confirmed, "rounds": rounds, "fresh_reads": 0}

    async def _synthesize(self, state: _State) -> _State:
        """Write the description from the structure and everything read."""
        files_read = len(state["read_paths"])

        answer = await self._ask_json(self._prompt(
            "synthesize",
            facts=state["facts"],
            excerpts=state["excerpts"] or NO_SOURCE_READ,
            read_paths=_bullets(state["read_paths"]),
            rounds=state["rounds"],
            files_read=files_read,
            verdict="confirmed" if state["confirmed"] else "not confirmed",
        ))

        if answer is None:
            return {"description": parsing.unavailable(
                "The model did not return a usable description of this repository.",
                files_read=files_read,
            )}

        return {"description": parsing.build_description(
            answer,
            files_read=files_read,
            read_rounds=state["rounds"],
            hypothesis_confirmed=state["confirmed"],
            known_files=state["known_files"],
        )}

    # -- helpers ------------------------------------------------------------

    def _prompt(self, name: str, **values: object) -> str:
        """The agent's role plus one node's task, ready to send.

        system.md holds the protocol that does not change between rounds: who
        the analyzer is, that it judges nothing, that answers are JSON and paths
        are copied. The node template holds only what this step asks for. Keeping
        them apart means rewriting one step does not rewrite the rules.
        """
        template = load_prompt(self.agent_type, name)
        _warn_if_empty(name, values)

        role = load_prompt(self.agent_type, "system")
        return f"{role}\n\n---\n\n{render_prompt(template, **values)}"

    async def _ask_json(self, prompt: str) -> dict | None:
        """One model call, returning None instead of raising.

        A model that is unreachable or answers with prose should end the run
        quietly, not take the request down with it.
        """
        try:
            response = await traced_generate(self.model, prompt)
            return parsing.parse_json(parsing.extract_text(response))
        except Exception as error:  # noqa: BLE001 - providers raise varied errors
            logger.warning("model gave no usable answer: %s", error)
            return None


NO_SOURCE_READ = "(no source code could be read)"


def _after_verify(state: _State) -> str:
    """Route on whether another read round is worth spending."""
    if state["confirmed"]:
        return "done"

    if state["rounds"] >= state["input"].max_read_rounds:
        return "done"

    if not state["known_files"]:
        return "done"

    if len(state["read_paths"]) >= len(state["known_files"]):
        # Everything in the repository has been read. Another round cannot
        # produce evidence that does not exist.
        return "done"

    return "again"


def _evidence_floor(files: list[dict]) -> list[str]:
    """Files the analyzer reads whatever the model asked for.

    Entry points are the cheapest possible evidence and the strongest signal for
    what a project is, so the model starts from them instead of from nothing.
    """
    markers = fact_tools.entrypoint_candidates(files)
    return _take(sorted(markers), MIN_EVIDENCE_FILES)


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


def _warn_if_empty(name: str, values: dict[str, object]) -> None:
    """Log any evidence the caller meant to supply but had none of.

    Templates silently drop values they do not declare, so a template that stops
    asking for the excerpts would quietly starve the model instead of failing.
    This is the only place that mismatch would show.
    """
    for key, value in values.items():
        if value in ("", (), [], {}):
            logger.warning("prompt %r got an empty %s", name, key)