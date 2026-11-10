"""Compatibility alias for the global agent budgeting policy."""

import sys

from server.agent_services.budgeting import policy

sys.modules[__name__] = policy
