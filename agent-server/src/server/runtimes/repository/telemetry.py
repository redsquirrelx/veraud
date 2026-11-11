"""Compatibility alias for always-on agent resource measurements."""

import sys

from server.agent_services.budgeting import telemetry

sys.modules[__name__] = telemetry
