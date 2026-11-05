"""Read a previously created quote through a repository port."""
from shoplab.application.contracts import QuoteRecorder, StoredQuote


class GetQuote:
    def __init__(self, quotes: QuoteRecorder) -> None:
        self._quotes = quotes

    def execute(self, quote_id: str) -> StoredQuote | None:
        if not quote_id.strip():
            raise ValueError("quote_id is required")
        return self._quotes.get(quote_id)
