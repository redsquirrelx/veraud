"""Compatibility alias for the agent token ledger."""

import sys

from server.agent_services.budgeting import shared_tokens

sys.modules[__name__] = shared_tokens
