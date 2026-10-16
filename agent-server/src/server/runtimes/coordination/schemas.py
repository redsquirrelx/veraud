"""Shared accounting contract, independent of any audit dimension."""

from config.agents import ConfigContract


class Consumption(ConfigContract):
    model_calls: int = 0
    tool_calls: int = 0
    accounted_tokens: int = 0
    estimated_tokens: int = 0
    model_calls_estimated: bool = False
