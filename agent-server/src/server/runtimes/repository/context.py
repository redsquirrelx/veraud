"""Snapshot identity and per-role elapsed time; clients remain caller-owned."""

from dataclasses import dataclass, field
from time import monotonic

from pydantic import BaseModel

from ...services.repository_analysis import RepositorySnapshot
from .schemas import RepositoryInput


def walk_contracts(value):
    if isinstance(value, BaseModel):
        yield value
        for name in type(value).model_fields:
            yield from walk_contracts(getattr(value, name))
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from walk_contracts(item)


@dataclass(frozen=True)
class RepositoryContext:
    snapshot: RepositorySnapshot = field(repr=False)
    input: RepositoryInput
    started_at: float = field(default_factory=monotonic, init=False)

    def __post_init__(self):
        self.require_snapshot(self.input.snapshot_hash)
        if self.input.snapshot_schema_version != self.snapshot.schema_version:
            raise ValueError("Unsupported or mismatched snapshot schema version.")

    def require_snapshot(self, snapshot_hash):
        if snapshot_hash != self.snapshot.repository.snapshot_hash:
            raise ValueError("Agent and repository snapshot hashes must match.")

    @property
    def elapsed_seconds(self):
        return monotonic() - self.started_at
