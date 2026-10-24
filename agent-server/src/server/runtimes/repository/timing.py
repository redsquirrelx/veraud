"""Active execution deadlines with quota pauses and an independent wall deadline."""

import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime
from time import monotonic

from config.agents.budgets import ExecutionTimingConfig

from ...config.logs import get_logger

logger = get_logger("execution-timing")
_pending_cancellations = set()


async def cancel_bounded(task, grace_seconds):
    """Keep a strong reference to late cleanup, but never wait indefinitely for it."""
    _pending_cancellations.add(task)

    def completed(child):
        _pending_cancellations.discard(child)
        if not child.cancelled():
            child.exception()

    task.add_done_callback(completed)
    if not task.done():
        task.cancel()
        await asyncio.wait({task}, timeout=grace_seconds)
    if task.done():
        return True
    logger.warning("child_cancellation_pending grace_seconds=%g", grace_seconds)
    return False


class ActiveDeadline:
    """A parent pauses only when all running child scopes are paused.

    This avoids discounting a quota wait while a sibling is still doing work.
    The absolute wall deadline is inherited and never extended.
    """

    def __init__(self, seconds, *, wall_deadline=None, parent=None, clock=monotonic, label=None, invocation_id=None,
                 cancellation_grace_seconds=None):
        self.seconds = seconds
        self.wall_deadline = float("inf") if wall_deadline is None else wall_deadline
        self.parent, self.clock = parent, clock
        self.changed = asyncio.Event()
        self.children = set()
        self.label, self.invocation_id = label, invocation_id
        self._waits = []
        self._waiting = 0
        self._paused = False
        self._spent = 0.0
        self._updated = clock()
        self.cancellation_grace_seconds = (ExecutionTimingConfig().cancellation_grace_seconds
            if cancellation_grace_seconds is None else cancellation_grace_seconds)
        self.cancelled = False
        self._activities = []
        self._cancellations = []
        self.last_progress_at = datetime.now(UTC).isoformat()
        if parent is not None:
            parent.children.add(self)
            parent._refresh(self._updated)

    def _refresh(self, now):
        if not self._paused:
            self._spent += now - self._updated
        self._updated = now
        self._paused = bool(self._waiting or self.children and all(child._paused for child in self.children))
        # Every observer keeps its own generation. Concurrent outer timers must
        # not clear a shared notification before another observer can see it.
        notification, self.changed = self.changed, asyncio.Event()
        notification.set()
        if self.parent is not None:
            self.parent._refresh(now)

    @property
    def wall_remaining(self):
        return max(0.0, self.wall_deadline - self.clock())

    @property
    def active_remaining(self):
        spent = self._spent + (0 if self._paused else self.clock() - self._updated)
        return max(0.0, self.seconds - spent)

    @property
    def remaining(self):
        return min(self.active_remaining, self.wall_remaining)

    @contextmanager
    def quota_wait(self, *, reason="quota_admission", seconds=None, source=None):
        wait = {"reason": reason, "source": source, "until": self.clock() + seconds if seconds is not None else None}
        self._waits.append(wait)
        self._waiting += 1
        self._refresh(self.clock())
        try:
            yield wait
        finally:
            self._waits.remove(wait)
            self._waiting -= 1
            self._refresh(self.clock())

    def fork(self, seconds, *, label=None, invocation_id=None, max_wall_time_seconds=None, cancellation_grace_seconds=None):
        wall = self.wall_deadline
        if max_wall_time_seconds is not None:
            wall = min(wall, self.clock() + max_wall_time_seconds)
        grace = self.cancellation_grace_seconds
        if cancellation_grace_seconds is not None:
            grace = min(grace, cancellation_grace_seconds)
        return ActiveDeadline(seconds, wall_deadline=wall, parent=self, clock=self.clock,
            label=label, invocation_id=invocation_id, cancellation_grace_seconds=grace)

    def touch(self):
        self.last_progress_at = datetime.now(UTC).isoformat()
        if self.parent is not None:
            self.parent.touch()

    @property
    def publication_allowed(self):
        return not self.cancelled and (self.parent is None or self.parent.publication_allowed)

    @contextmanager
    def stage(self, name):
        entry = {"agent_id": self.label, "invocation_id": self.invocation_id, "stage": name,
            "started_at": datetime.now(UTC).isoformat(), "started": self.clock(), "status": "running"}
        self._activities.append(entry)
        self.touch()
        try:
            yield
        finally:
            self._activities.remove(entry)
            self.touch()

    def activity(self):
        now = self.clock()
        entries = [dict(entry, elapsed_seconds=max(0, now - entry["started"]))
            for entry in [*self._activities, *self._cancellations]]
        for entry in entries:
            entry.pop("started")
        for child in tuple(self.children):
            entries.extend(child.activity())
        return entries

    def note_cancellation(self, task):
        root = self
        while root.parent is not None:
            root = root.parent
        entry = {"agent_id": self.label, "invocation_id": self.invocation_id, "stage": "cancellation",
            "started_at": datetime.now(UTC).isoformat(), "started": self.clock(), "status": "cancellation_pending"}
        root._cancellations.append(entry)
        task.add_done_callback(lambda _: root._cancellations.remove(entry))

    def waiting(self):
        result = [{"agent_id": self.label, "invocation_id": self.invocation_id,
            "reason": wait["reason"], "source": wait["source"],
            "retry_after_seconds": max(0, wait["until"] - self.clock()) if wait["until"] is not None else None}
            for wait in self._waits]
        for child in self.children:
            result.extend(child.waiting())
        return sorted(result, key=lambda wait: (wait["agent_id"] or "", wait["invocation_id"] or "", wait["reason"]))

    def close(self):
        if self.parent is not None:
            self.parent.children.discard(self)
            self.parent._refresh(self.clock())
            self.parent = None


async def within_deadline(awaitable, deadline):
    """Re-evaluate an outer timer when quota pauses start or end, including children."""
    task = asyncio.ensure_future(awaitable)
    try:
        while not task.done():
            notification = deadline.changed
            timeout = deadline.wall_remaining if deadline._paused else deadline.remaining
            if timeout <= 0:
                raise TimeoutError
            changed = asyncio.create_task(notification.wait())
            try:
                await asyncio.wait((task, changed), timeout=None if timeout == float("inf") else timeout,
                    return_when=asyncio.FIRST_COMPLETED)
                # Re-read the deadline even when the previous timer expired:
                # a concurrent pause may have made that timeout obsolete.
            finally:
                changed.cancel()
                await asyncio.gather(changed, return_exceptions=True)
        return task.result()
    finally:
        if not task.done():
            deadline.cancelled = True
            if not await cancel_bounded(task, deadline.cancellation_grace_seconds):
                deadline.note_cancellation(task)
