"""Compatibility alias for the unchanged tracking wire contracts."""

import sys

from server.agent_services.execution_tracking.callback import schemas

sys.modules[__name__] = schemas
