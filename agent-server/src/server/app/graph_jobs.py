"""Bounded background Graphify jobs; no agents, models or Blackboard."""

from __future__ import annotations

import asyncio
import secrets

from server.agent_services.execution_tracking.callback.client import (
    CallbackClient,
    build_callback_config,
)
from server.agent_services.execution_tracking.observer import backend_url
from server.config.logs import get_logger
from server.config.settings import (
    GraphSettings,
    resolve_graphs_root,
    resolve_workspace_root,
)
from server.services.graph_extraction import (
    GraphExtractionError,
    GraphExtractionService,
)
from server.services.graphify import GraphifyAdapter, GraphifyError
from server.services.repository_structure import RepositoryStructureService

logger = get_logger("graph-jobs")


class GraphJobs:
    def __init__(self, service=None, callbacks=None, settings=None):
        self.settings = settings or GraphSettings()
        self.service = service or GraphExtractionService(
            resolve_workspace_root(), resolve_graphs_root(),
            RepositoryStructureService(GraphifyAdapter(timeout_seconds=self.settings.graph_timeout_seconds)),
        )
        self.callbacks = callbacks
        self.jobs = {}
        self.lock = asyncio.Semaphore(1)

    def start(self, request):
        current = self.jobs.get(request.task_id)
        if current:
            if current[0] != request:
                raise ValueError("Task ID already belongs to another request")
            return
        if len(self.jobs) >= self.settings.graph_max_pending:
            raise OverflowError("Graph extraction queue is full")
        self.service.repository(request.repository_path)
        url = backend_url()
        if self.callbacks is None and url is None:
            raise RuntimeError("Backend callbacks are unavailable")
        self.jobs[request.task_id] = (request, asyncio.create_task(self._run(request, url)))

    async def _run(self, request, url):
        client = self.callbacks or CallbackClient(build_callback_config(url))
        current_phase = "queued"

        async def report(phase, error_code=None):
            nonlocal current_phase
            current_phase = phase
            # Retrying terminal delivery is safe: the backend deduplicates it.
            for attempt in range(3):
                result = await client.graph_task(request.task_id, request.callback_token, phase, error_code)
                if result.acknowledged:
                    return
                await asyncio.sleep(0.25 * (attempt + 1))
            if phase in ("completed", "failed"):
                logger.warning("Graph terminal callback was not acknowledged task=%s", request.task_id)

        try:
            async with self.lock:
                async with asyncio.timeout(self.settings.graph_timeout_seconds + 65):
                    await self.service.extract(request, report)
                await report("completed")
        except asyncio.CancelledError:
            await report("failed", "interrupted")
            raise
        except Exception as error:  # noqa: BLE001 - Never expose repository paths, source or transport secrets.
            if isinstance(error, GraphExtractionError):
                code = error.code
            elif isinstance(error, GraphifyError):
                code = {"timeout": "timeout", "unavailable": "extractor_unavailable", "invalid_path": "snapshot_failed"}.get(error.code, "extraction_failed")
            elif isinstance(error, TimeoutError):
                code = "timeout"
            elif isinstance(error, OSError):
                code = "storage_failed"
            else:
                code = "extraction_failed"
            logger.warning("Graph extraction failed task=%s phase=%s code=%s exception_type=%s",
                           request.task_id, current_phase, code, type(error).__name__)
            await report("failed", code)
        finally:
            self.jobs.pop(request.task_id, None)
            if self.callbacks is None:
                await client.aclose()

    async def cancel(self, task_id, token):
        current = self.jobs.get(task_id)
        if current is None:
            return
        if not secrets.compare_digest(current[0].callback_token, token):
            raise PermissionError("Invalid graph token")
        current[1].cancel()
        await asyncio.gather(current[1], return_exceptions=True)
        self.jobs.pop(task_id, None)

    async def aclose(self):
        jobs = [task for _, task in list(self.jobs.values())]
        for task in jobs:
            task.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        self.jobs.clear()
