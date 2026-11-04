"""Volatile delivery buffer. Only the backend persists execution history."""

from copy import deepcopy
from datetime import UTC, datetime
from functools import lru_cache
from threading import Lock

from ..contracts.execution_event import ExecutionEvent


class ExecutionEventBuffer:
    def __init__(self, max_pending=10000):
        self._lock = Lock()
        self._sequences = {}
        self._pending = {}
        self.max_pending = max_pending

    def append(self, execution_id, stream_id, **values):
        values.setdefault("occurred_at", datetime.now(UTC))
        with self._lock:
            if len(self._pending) >= self.max_pending:
                raise BufferError("Execution event delivery buffer is full; backend acknowledgement required")
            sequence = self._sequences.get(stream_id, 0) + 1
            event = ExecutionEvent(stream_id=stream_id, sequence=sequence, **values)
            self._sequences[stream_id] = sequence
            self._pending[event.event_id] = (execution_id, event.model_dump(mode="json", by_alias=True))
        return event

    def pending(self, limit=1000):
        with self._lock:
            return [(event_id, target, deepcopy(payload)) for event_id, (target, payload) in list(self._pending.items())[:limit]]

    def acknowledge(self, event_ids):
        with self._lock:
            for event_id in event_ids:
                self._pending.pop(event_id, None)


@lru_cache(maxsize=1)
def execution_event_buffer():
    return ExecutionEventBuffer()


async def deliver_execution_events(buffer, sink):
    """Retry identical IDs while this process lives; remove only backend-acknowledged events."""
    groups = {}
    for event_id, execution_id, payload in buffer.pending():
        groups.setdefault(execution_id, []).append((event_id, payload))
    delivered = True
    for execution_id, records in groups.items():
        for start in range(0, len(records), 100):
            batch = records[start:start + 100]
            result = await sink.events(execution_id, [payload for _, payload in batch])
            if not result.acknowledged:
                delivered = False
                break
            buffer.acknowledge([event_id for event_id, _ in batch])
    return delivered


async def execution_event_delivery_worker(stop, sink_factory):
    import asyncio

    from ..config.logs import get_logger

    delay = 1
    while True:
        stopping = stop.is_set()
        sink = None
        try:
            sink = sink_factory()
            delivered = await deliver_execution_events(execution_event_buffer(), sink) if sink is not None else False
            delay = 1 if delivered else min(30, delay * 2)
        except Exception:  # noqa: BLE001 - keep events in memory, never log payloads
            get_logger("execution-events").warning("Execution event delivery deferred")
            delay = min(30, delay * 2)
        finally:
            if sink is not None:
                try:
                    await sink.aclose()
                except Exception:  # noqa: BLE001 - cleanup cannot stop retries
                    get_logger("execution-events").warning("Execution event callback cleanup deferred")
        if stopping:
            return  # One final best-effort batch during graceful shutdown.
        try:
            await asyncio.wait_for(stop.wait(), delay)
        except TimeoutError:
            pass
