"""Demo pipeline: the analyzer describes, the architect frames. Back to back.

Composition, not a new agent: each node calls one agent's public `run()`,
so neither agent changes to take part and the per-agent HTTP contract stays
untouched. The shared state carries the analyzer's output into the architect,
which is the whole point of running them consecutively.

Deliberately demo-grade: each agent collects its own representations, so a
large repository is walked twice. Sharing one collection across both graphs
is follow-up work, not this file.
"""

from typing import TypedDict

from langgraph.graph import END, StateGraph

from ..agents.analyzer.agent import ProjectAnalyzerAgent
from ..agents.analyzer.schemas import ProjectInput
from ..agents.architect.agent import ArchitectureAgent
from ..agents.architect.schemas import ArchitectInput
from ..config.logs import get_logger

logger = get_logger("pipeline.audit")


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

    def __init__(self, analyzer: ProjectAnalyzerAgent, architect: ArchitectureAgent) -> None:
        self._analyzer = analyzer
        self._architect = architect
        self._graph = self._build_graph()

    async def run(
        self,
        root_path: str,
        max_files: int = 500,
        max_depth: int = 8,
        max_read_rounds: int = 2,
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
        analysis = await self._analyzer.run(ProjectInput(
            root_path=state["root_path"],
            max_files=state.get("max_files", 500),
            max_depth=state.get("max_depth", 8),
            max_read_rounds=state.get("max_read_rounds", 2),
            max_files_per_round=state.get("max_files_per_round", 8),
        ))

        logger.info("pipeline: analyzed kind=%r confidence=%r", analysis.kind, analysis.confidence)
        return {"analysis": analysis.model_dump()}

    async def _describe_node(self, state: AuditState) -> dict:
        """Frame how the project is put together, from the analysis."""
        description = await self._architect.run(ArchitectInput(
            root_path=state["root_path"],
            analysis=state["analysis"],
        ))

        logger.info("pipeline: described")
        return {"description": description.model_dump()}
