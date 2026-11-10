"""Compatibility alias for agent token accounting and admission."""

import sys

from server.agent_services.budgeting import tokens

sys.modules[__name__] = tokens
