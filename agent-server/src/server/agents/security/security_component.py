"""Compatibility import for the security supervisor's former module path."""

from .security_manager import SecuritySupervisorAgent

SecurityComponentAgent = SecuritySupervisorAgent

__all__ = ["SecurityComponentAgent"]
