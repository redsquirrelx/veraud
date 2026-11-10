"""Compatibility alias; agent tracking lives in server.agent_services."""

import sys

from server.agent_services.execution_tracking import events

sys.modules[__name__] = events
