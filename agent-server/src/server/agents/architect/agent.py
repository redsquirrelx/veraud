"""Second step of the pipeline: describe how the project is built.

The analyzer works out what a project IS; the architect works out how it is
put together, starting from the analyzer's output. It describes and reports
risks mapped to ISO/IEC 25010 maintainability, with evidence paths behind
every observation. It never scores: scoring belongs to the agents that run
after this one.

Phase 1 is a skeleton only: it compiles, registers and returns a valid empty
description. Collection, reading rounds and prompts land in phases 2-5.
"""

from ...config.logs import get_logger
from ..base import BaseAgent
from .schemas import ArchitectInput, ArchitectureDescription

logger = get_logger("architect-agent")


class ArchitectureAgent(BaseAgent[ArchitectInput, ArchitectureDescription]):
    agent_type = "architect"
    input_schema = ArchitectInput
    output_schema = ArchitectureDescription

    async def run(self, input_data: ArchitectInput) -> ArchitectureDescription:
        """Return an empty description. The graph lands in later phases."""
        logger.info(
            "run: root=%r kind=%r (skeleton, no collection yet)",
            input_data.root_path, input_data.analysis.kind,
        )
        return ArchitectureDescription()
