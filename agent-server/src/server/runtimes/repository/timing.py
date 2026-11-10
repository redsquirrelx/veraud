"""Compatibility alias for agent execution timing and cancellation helpers."""

import sys

from server.agent_services.budgeting import timing

sys.modules[__name__] = timing
