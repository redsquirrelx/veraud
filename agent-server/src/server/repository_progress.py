"""Flushed progress and cancellable wait heartbeats for repository runners."""

import asyncio
import json
import sys
from contextlib import suppress
from time import monotonic


def progress(event, values):
    details = " ".join(
        f"{key}={json.dumps(value, ensure_ascii=True)}" for key, value in values.items()
    )
    print(f"[{event}] {details}", file=sys.stderr, flush=True)


class ProgressReporter:
    def __init__(self, interval):
        self.interval = interval
        self.started = monotonic()
        self.active_event = "startup"
        self.active_since = self.started
        self.active_values = {}

    def __call__(self, event, values):
        self.active_event = event
        self.active_since = monotonic()
        self.active_values = dict(values)
        progress(
            event, {"elapsed_seconds": round(monotonic() - self.started, 1), **values}
        )

    async def heartbeat(self):
        while True:
            await asyncio.sleep(self.interval)
            details = {
                "activity": self.active_event,
                "activity_seconds": round(monotonic() - self.active_since, 1),
                "elapsed_seconds": round(monotonic() - self.started, 1),
            }
            for key in ("call", "attempt", "max_attempts", "reason", "http_status"):
                if key in self.active_values:
                    details[key] = self.active_values[key]
            if self.active_event == "provider_wait":
                total = self.active_values.get("wait_seconds", 0)
                details.update(
                    wait_total_seconds=round(total, 1),
                    wait_remaining_seconds=round(
                        max(0, total - (monotonic() - self.active_since)), 1
                    ),
                    next_action="send_provider_request",
                )
            progress("still_running", details)


async def with_progress(awaitable, reporter):
    if reporter is None:
        return await awaitable
    heartbeat = asyncio.create_task(reporter.heartbeat())
    try:
        return await awaitable
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
