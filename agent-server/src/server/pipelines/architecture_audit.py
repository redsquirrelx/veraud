"""Analyzer then architect as one LangGraph pipeline: describe, then frame.

Composition, not a new agent: each node calls one agent's public `run()`,
so neither agent changes to take part and the per-agent HTTP contract stays
untouched. The shared state carries the analyzer's output into the architect,
which is the whole point of running them consecutively.

The graph is the only orchestrator. Side effects (reporting each stage back
to the backend) hang off it through `AuditHooks`: the demo runner passes no
hooks and gets a pure local run, while the pipeline service passes hooks that
close one backend row per stage. Nothing about the analyze -> describe order
lives anywhere else.

Deliberately demo-grade on collection: each agent collects its own
representations, so a large repository is walked twice. Sharing one
collection across both graphs is follow-up work, not this file.
"""

from typing import Protocol, TypedDict

from langgraph.graph import END, StateGraph

from ..agents.analyzer.agent import ProjectAnalyzerAgent
from ..agents.analyzer.schemas import ProjectDescription, ProjectInput
from ..agents.architect.agent import ArchitectureAgent
from ..agents.architect.schemas import ArchitectInput, ArchitectureDescription
from ..config.logs import get_logger
from ..config.tracing import traced_agent_run

logger = get_logger("pipeline.audit")


class AuditHooks(Protocol):
    """Side effects around each stage. All no-ops when no hooks are given."""

    async def on_analyzer_start(self) -> None:
        """The analyze node started: mark the analyzer row Running."""
        ...

    async def on_analysis(self, analysis: ProjectDescription) -> None:
        """The analyzer finished: close its row as Completed."""
        ...

    async def on_architect_start(self) -> None:
        """The describe node started: mark the architect row Running."""
        ...

    async def on_description(self, description: ArchitectureDescription) -> None:
        """The architect finished: close its row as Completed."""
        ...


class AuditState(TypedDict, total=False):
    """What flows between the pipeline steps."""

    root_path: str
    max_files: int
    max_depth: int
    max_read_rounds: int
    max_files_per_round: int

    # Written by analyze.
    analysis: dict

    # Written by describe.
    description: dict


class ArchitectureAuditPipeline:
    """Analyzer then architect, in one graph."""

    def __init__(
        self,
        analyzer: ProjectAnalyzerAgent,
        architect: ArchitectureAgent,
        hooks: AuditHooks | None = None,
    ) -> None:
        self._analyzer = analyzer
        self._architect = architect
        self._hooks = hooks
        self._graph = self._build_graph()

    async def run(
        self,
        root_path: str,
        max_files: int = 500,
        max_depth: int = 8,
        max_read_rounds: int = 3,
        max_files_per_round: int = 8,
    ) -> dict:
        """Run both agents and return their outputs as plain dicts."""
        logger.info("pipeline: auditing root=%r", root_path)

        final = await self._graph.ainvoke({
            "root_path": root_path,
            "max_files": max_files,
            "max_depth": max_depth,
            "max_read_rounds": max_read_rounds,
            "max_files_per_round": max_files_per_round,
        })

        logger.info("pipeline: done")
        return {"analysis": final.get("analysis", {}), "description": final.get("description", {})}

    def _build_graph(self):
        graph = StateGraph(AuditState)

        graph.add_node("analyze", self._analyze_node)
        graph.add_node("describe", self._describe_node)

        graph.set_entry_point("analyze")
        graph.add_edge("analyze", "describe")
        graph.add_edge("describe", END)

        return graph.compile()

    async def _analyze_node(self, state: AuditState) -> dict:
        """Describe what the project is."""
        if self._hooks is not None:
            await self._hooks.on_analyzer_start()

        analysis = await traced_agent_run(
            self._analyzer.run(ProjectInput(
                root_path=state["root_path"],
                max_files=state.get("max_files", 500),
                max_depth=state.get("max_depth", 8),
                max_read_rounds=state.get("max_read_rounds", 2),
                max_files_per_round=state.get("max_files_per_round", 8),
            )),
            name="analyzer",
            model=self._analyzer.model.settings.name,
        )

        logger.info("pipeline: analyzed kind=%r confidence=%r", analysis.kind, analysis.confidence)

        if self._hooks is not None:
            await self._hooks.on_analysis(analysis)

        return {"analysis": analysis.model_dump()}

    async def _describe_node(self, state: AuditState) -> dict:
        """Frame how the project is put together, from the analysis."""
        if self._hooks is not None:
            await self._hooks.on_architect_start()

        description = await traced_agent_run(
            self._architect.run(ArchitectInput(
                root_path=state["root_path"],
                analysis=state["analysis"],
                max_read_rounds=state.get("max_read_rounds", 3),
            )),
            name="architect",
            model=self._architect.model.settings.name,
        )

        logger.info("pipeline: described")

        if self._hooks is not None:
            await self._hooks.on_description(description)

        return {"description": description.model_dump()}
