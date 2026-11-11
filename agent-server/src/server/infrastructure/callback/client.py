"""Compatibility alias for the agent tracking HTTP transport."""

import sys

from server.agent_services.execution_tracking.callback import client

sys.modules[__name__] = client
