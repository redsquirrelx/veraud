"""Operating specialization for one-pass documentary exploration."""

from typing import ClassVar

from config.agents import InvestigationConfig


class ArchitectureContextConfig(InvestigationConfig):
    defaults: ClassVar = {"max_iterations": 1}
