"""Per-audit cancellation admission and owned-task tracking, independent of HTTP."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar

_current = ContextVar("audit_cancellation", default=None)


class AuditCancellation:
    def __init__(self, on_idle):
        self.requested = False
        self.tasks = set()
        self.on_idle = on_idle

    def check(self):
        if self.requested:
            raise asyncio.CancelledError

    def request(self):
        """Return True only for the first request; repeated requests must not interrupt cleanup."""
        if self.requested:
            return False
        self.requested = True
        return True

    def track(self, task):
        if task in self.tasks:
            return
        self.tasks.add(task)
        task.add_done_callback(self._completed)

    def _completed(self, task):
        self.tasks.discard(task)
        if not self.tasks:
            self.on_idle()


def current_cancellation():
    return _current.get()


def check_cancellation():
    signal = current_cancellation()
    if signal is not None:
        signal.check()


@contextmanager
def cancellation_scope(signal):
    token = _current.set(signal)
    try:
        yield
    finally:
        _current.reset(token)
