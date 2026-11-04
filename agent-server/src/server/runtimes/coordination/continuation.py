"""Host-owned, same-run continuation; never a model-supplied persisted baseline."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CoordinatorContinuation:
    assessment: Any
    gap_ids: tuple[str, ...]
    publication: Any = None
