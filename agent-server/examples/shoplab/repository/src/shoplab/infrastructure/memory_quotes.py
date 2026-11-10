"""Quote recording adapter; scoped to one application process."""
from shoplab.application.contracts import StoredQuote


class MemoryQuoteRecorder:
    def __init__(self) -> None:
        self._quotes: dict[str, StoredQuote] = {}

    def save(self, quote: StoredQuote) -> None:
        self._quotes[quote.quote_id] = quote

    def get(self, quote_id: str) -> StoredQuote | None:
        return self._quotes.get(quote_id)
