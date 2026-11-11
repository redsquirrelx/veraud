"""One always-accounted character ledger per repository execution hierarchy."""

from threading import RLock


class RetrievalBudget:
    def __init__(self, limit):
        self.limit = limit
        self.used = 0
        self.lock = RLock()
