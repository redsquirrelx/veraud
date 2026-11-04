"""Backward-compatible import; commit verification is shared between auditors."""

from .....runtimes.investigation.provenance import matches_commit

__all__ = ["matches_commit"]
