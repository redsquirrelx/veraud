"""Second step of the pipeline: describe how the project is built.

The analyzer works out what a project IS; the architect works out how it is
put together, starting from the analyzer's output. It describes and reports
risks mapped to ISO/IEC 25010 maintainability, with evidence paths behind
every observation. It never scores: scoring belongs to the agents that run
after this one.

Phase 2 collects the representations and frames the architectural style. The
reading rounds and the full description land in phases 3-5.
"""

from ...config.logs import get_logger
from ...config.prompts import load_prompt, render_prompt
from ...config.tracing import traced_generate
from ...services.collection.schemas import CollectionInput
from ...services.collection.service import CollectionService
from ..analyzer import facts as analyzer_facts
from ..analyzer import parsing as analyzer_parsing
from ..base import BaseAgent
from .schemas import ArchitectInput, ArchitectureDescription

logger = get_logger("architect-agent")

# Budget for the condensed structure facts handed to the frame prompt.
MAX_FACTS_CHARS = 24000

# How many files the frame step may ask to confirm the style.
MAX_FILES_PER_ROUND = 8


class ArchitectureAgent(BaseAgent[ArchitectInput, ArchitectureDescription]):
    agent_type = "architect"
    input_schema = ArchitectInput
    output_schema = ArchitectureDescription

    def __init__(self, *args, collection: CollectionService | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._collection = collection or CollectionService()

    async def run(self, input_data: ArchitectInput) -> ArchitectureDescription:
        """Collect, frame the style, and return an empty description for now.

        The frame (style hypothesis plus the files that would confirm it) is
        the phase 2 outcome and is logged, not returned: the full description
        it feeds lands in phases 3-5.
        """
        collected = await self._collect(input_data)
        frame = await self._frame(collected, input_data)

        logger.info(
            "run done: style=%r pending=%s (description lands in phase 5)",
            frame.get("style", "unknown"), frame.get("pending", []),
        )
        return ArchitectureDescription()

    async def _collect(self, input_data: ArchitectInput) -> dict:
        """Gather the representations and condense them. No model involved."""
        logger.info("run: collecting root=%r", input_data.root_path)

        collection = await self._collection.collect(CollectionInput(
            root_path=input_data.root_path,
            max_files=500,
            max_depth=8,
        ))

        data = collection.model_dump()
        files = data.get("repo_map", {}).get("files", [])
        facts, trimmed = analyzer_facts.build_facts(data, MAX_FACTS_CHARS)

        logger.info(
            "run: %d files, %d chars of facts (trimmed=%s)",
            len(files), len(facts), trimmed,
        )

        return {
            "root": collection.root,
            "facts": facts,
            "known_files": analyzer_facts.known_paths(files),
        }

    async def _frame(self, collected: dict, input_data: ArchitectInput) -> dict:
        """Guess what the repo tries to be, and why it falls short.

        Returns the observed style, the intended style and the deviations,
        plus the files that would confirm the reading. Deviations feed the
        survey step (what is worth reading) and later the risks.
        """
        analysis = input_data.analysis
        prompt = (
            f"{load_prompt(self.agent_type, 'system')}\n\n---\n\n"
            f"{render_prompt(load_prompt(self.agent_type, 'frame'), facts=collected['facts'], kind=analysis.kind, summary=analysis.summary, styles=load_prompt(self.agent_type, 'styles'))}"
        )

        try:
            response = await traced_generate(self.model, prompt)
            answer = analyzer_parsing.parse_json(analyzer_parsing.extract_text(response))
        except Exception as error:  # noqa: BLE001 - providers raise varied errors
            logger.warning("frame: model gave no usable answer: %s", error)
            return {"style": "unknown", "intended_style": "unknown", "deviations": [], "pending": []}

        wanted = analyzer_parsing.read_paths(answer, "would_confirm", collected["known_files"])
        style = str(answer.get("style") or "unknown").strip().lower()
        intended = str(answer.get("intended_style") or "unknown").strip().lower()
        deviations = _read_deviations(answer, collected["known_files"])

        logger.info(
            "frame: style=%r intended=%r reasoning=%r pending=%d paths deviations=%d",
            style, intended, analyzer_parsing.read_text(answer, "reasoning")[:120],
            len(wanted), len(deviations),
        )

        return {
            "style": style,
            "intended_style": intended,
            "deviations": deviations,
            "pending": _take(
                wanted + [path for deviation in deviations for path in deviation["evidence"]],
                MAX_FILES_PER_ROUND,
            ),
        }


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
