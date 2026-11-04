"""Concrete quote identifier provider."""
from uuid import uuid4


class UuidQuoteIds:
    def new_id(self) -> str:
        return f"Q-{uuid4().hex[:12].upper()}"
