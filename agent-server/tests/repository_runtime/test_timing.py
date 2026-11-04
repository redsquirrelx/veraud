import asyncio
from time import monotonic

import pytest

from server.runtimes.repository.timing import ActiveDeadline, within_deadline


def test_quota_waits_pause_active_time_but_never_extend_the_wall_deadline():
    now = [0.0]
    deadline = ActiveDeadline(10, wall_deadline=100, clock=lambda: now[0])
    now[0] = 2
    with deadline.quota_wait():
        now[0] = 32
        assert deadline.remaining == 8
        assert deadline.wall_remaining == 68
    now[0] = 35
    assert deadline.remaining == 5
    with deadline.quota_wait():
        now[0] = 101
        assert deadline.remaining == deadline.wall_remaining == 0


def test_parent_pauses_only_when_all_running_children_are_waiting():
    now = [0.0]
    parent = ActiveDeadline(50, wall_deadline=200, clock=lambda: now[0])
    first, second = parent.fork(20), parent.fork(20)
    with first.quota_wait():
        now[0] = 5
        assert parent.remaining == 45  # The other sibling is working.
        with second.quota_wait():
            now[0] = 15
            assert parent.remaining == 45
        now[0] = 20
        assert parent.remaining == 40
    assert first.remaining == 20 and second.remaining == 10
    first.close()
    second.close()
    now[0] = 25
    assert parent.remaining == 35 and not parent.children


def test_outer_timer_tracks_pause_transitions_and_keeps_wall_deadline():
    async def run():
        deadline = ActiveDeadline(0.15, wall_deadline=monotonic() + 2)

        async def work():
            with deadline.quota_wait():
                await asyncio.sleep(0.25)  # Longer than the individual active allowance.
            return "completed"

        assert await within_deadline(work(), deadline) == "completed"

        wall_limited = ActiveDeadline(10, wall_deadline=monotonic() + 0.05)
        cancelled = asyncio.Event()

        async def blocked():
            try:
                with wall_limited.quota_wait():
                    await asyncio.Event().wait()
            finally:
                cancelled.set()

        with pytest.raises(TimeoutError):
            await within_deadline(blocked(), wall_limited)
        assert cancelled.is_set()

    asyncio.run(run())


def test_slow_model_work_and_external_cancellation_remain_bounded():
    async def run():
        deadline = ActiveDeadline(0.03, wall_deadline=monotonic() + 5)
        with pytest.raises(TimeoutError):
            await within_deadline(asyncio.sleep(1), deadline)

        cancelled = asyncio.Event()
        waiting = asyncio.Event()
        deadline = ActiveDeadline(10, wall_deadline=monotonic() + 5)

        async def work():
            try:
                with deadline.quota_wait():
                    waiting.set()
                    await asyncio.Event().wait()
            finally:
                cancelled.set()

        task = asyncio.create_task(within_deadline(work(), deadline))
        await waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()

    asyncio.run(run())


def test_concurrent_observer_cannot_erase_another_timers_pause_notification():
    async def run():
        class DelayedObserverEvent(asyncio.Event):
            async def wait(self):
                # Allow a second timer to process/reset its notification first.
                await asyncio.sleep(0)
                return await super().wait()

        deadline = ActiveDeadline(0.15, wall_deadline=monotonic() + 2)
        deadline.changed = DelayedObserverEvent()
        original = deadline.changed

        async def other_timer():
            await asyncio.Event.wait(original)
            deadline.changed.clear()

        observer = asyncio.create_task(other_timer())
        await asyncio.sleep(0)

        async def work():
            with deadline.quota_wait():
                await asyncio.sleep(0.25)
            return "resumed"

        try:
            assert await within_deadline(work(), deadline) == "resumed"
        finally:
            observer.cancel()
            await asyncio.gather(observer, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize("external_cancel", [False, True])
def test_uncooperative_cancellation_cannot_hold_the_supervisor(external_cancel):
    async def run():
        release, started, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        deadline = ActiveDeadline(0.03, cancellation_grace_seconds=0.01)

        async def stubborn_child():
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()  # Simulates a transport stuck in asynchronous cleanup.
                raise

        child = asyncio.create_task(stubborn_child())
        supervisor = asyncio.create_task(within_deadline(child, deadline))
        try:
            await started.wait()
            if external_cancel:
                supervisor.cancel()
            await cancelled.wait()
            await asyncio.wait({supervisor}, timeout=0.4)
            assert supervisor.done(), "Supervisor waited past its cancellation grace period"
            with pytest.raises(asyncio.CancelledError if external_cancel else TimeoutError):
                await supervisor
            assert not child.done()
            assert not deadline.publication_allowed
            assert deadline.activity()[0]["status"] == "cancellation_pending"
        finally:
            release.set()
            await asyncio.gather(child, supervisor, return_exceptions=True)
        assert not deadline.activity()

    asyncio.run(run())
