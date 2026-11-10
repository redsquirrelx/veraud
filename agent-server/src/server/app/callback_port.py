"""Compatibility alias for the agent execution observer and callback port."""

import sys

from server.agent_services.execution_tracking import observer

sys.modules[__name__] = observer
