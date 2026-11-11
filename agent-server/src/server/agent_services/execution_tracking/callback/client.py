from __future__ import annotations

import httpx

from server.config.logs import get_logger
from server.contracts.public_errors import public_error_fields

from .schemas import (
    CallbackConfig,
    CallbackResult,
    ExecutionOutcome,
    ExecutionProgress,
    InvocationReceipt,
)

logger = get_logger("infrastructure.callback")


class CallbackClient:
    """Reports agent progress back to the backend.

    The backend creates the `agent_execution` row when it invokes an agent and
    passes the id along. This client only updates that row: it never creates
    one, because the backend owns the id.

    Every method returns instead of raising. A callback that cannot be delivered
    must not take down the agent run it was reporting on, so failures come back
    as `acknowledged: false` with the reason filled in.
    """

    def __init__(
        self,
        config: CallbackConfig,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._owns_client = client is None
        # Reuse one pooled client across posts; agents issue many concurrent
        # callbacks to the same backend.
        self._pooled: httpx.AsyncClient | None = None

    async def mark_running(self, execution_id: int, run_id: str | None = None) -> CallbackResult:
        """Tell the backend the run started. Optional on the backend side."""
        return await self._post(f"/api/agent-executions/{execution_id}/running", {"runId": run_id} if run_id else {})

    async def complete(self, execution_id: int, outcome: ExecutionOutcome) -> CallbackResult:
        """Close the run with its outcome."""
        return await self._post(
            f"/api/agent-executions/{execution_id}/completion",
            outcome.model_dump(mode="json", by_alias=True),
        )

    async def progress(self, execution_id: int, usage: ExecutionProgress) -> CallbackResult:
        return await self._post(
            f"/api/agent-executions/{execution_id}/progress",
            usage.model_dump(by_alias=True),
        )

    async def invocation(self, execution_id: int, receipt: InvocationReceipt) -> CallbackResult:
        return await self._post(f"/api/agent-executions/{execution_id}/invocations", receipt.model_dump(mode="json", by_alias=True))

    async def events(self, execution_id: int, events: list[dict]) -> CallbackResult:
        return await self._post(f"/api/agent-executions/{execution_id}/events", {"events": events})

    async def graph_task(self, task_id: int, token: str, phase: str, error_code: str | None = None) -> CallbackResult:
        payload = {"phase": phase}
        if error_code is not None:
            payload["errorCode"] = error_code
        return await self._post(f"/api/tasks/{task_id}/graph-callback", payload, {"X-Graph-Token": token})

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
        if self._pooled is not None:
            await self._pooled.aclose()
            self._pooled = None

    async def _post(self, path: str, payload: dict, extra_headers: dict | None = None) -> CallbackResult:
        payload = public_error_fields(payload)
        url = f"{self._config.backend_url.rstrip('/')}{path}"
        headers: dict[str, str] = dict(extra_headers or {})

        if self._config.shared_secret:
            headers["X-Agent-Secret"] = self._config.shared_secret

        if self._client is not None:
            client = self._client
        elif self._pooled is not None:
            client = self._pooled
        else:
            self._pooled = httpx.AsyncClient(timeout=self._config.timeout_seconds)
            client = self._pooled

        try:
            response = await client.post(url, json=payload, headers=headers)

        except Exception:  # noqa: BLE001 - any transport failure
            # The run itself already finished; failing loudly here would throw
            # away a completed analysis because the report did not land.
            logger.warning("Execution callback did not reach the backend")
            return CallbackResult(acknowledged=False, error="Execution callback transport failed.")

        acknowledged = response.is_success
        body = None if acknowledged else "Execution callback rejected."

        if acknowledged:
            logger.info("Execution callback acknowledged (%s)", response.status_code)
        else:
            logger.warning(
                "Execution callback rejected with %s", response.status_code,
            )

        return CallbackResult(
            acknowledged=acknowledged,
            status_code=response.status_code,
            body=body,
        )


def build_callback_config(
    backend_url: str,
    shared_secret: str | None = None,
    timeout_seconds: float = 10.0,
) -> CallbackConfig:
    """Build the config from plain values, as settings.py would."""
    return CallbackConfig(
        backend_url=backend_url,
        shared_secret=shared_secret,
        timeout_seconds=timeout_seconds,
    )
