"""Directory-scoped Markdown indexing without models or agent dependencies."""

from .schemas import (
    DocumentRecord,
    DocumentSection,
    IndexReference,
    IndexResult,
    SearchHit,
)
from .service import DocumentIndexingService

__all__ = [
    "DocumentIndexingService",
    "DocumentRecord",
    "DocumentSection",
    "IndexReference",
    "IndexResult",
    "SearchHit",
]
