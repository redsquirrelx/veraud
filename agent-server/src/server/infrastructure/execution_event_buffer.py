"""Compatibility alias for the shared agent event outbox."""

import sys

from server.agent_services.execution_tracking import buffer

sys.modules[__name__] = buffer
