from __future__ import annotations

import httpx

from ...config.logs import get_logger
from .schemas import CallbackConfig, CallbackResult, ExecutionOutcome

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

    async def mark_running(self, execution_id: int) -> CallbackResult:
        """Tell the backend the run started. Optional on the backend side."""
        return await self._post(f"/api/agent-executions/{execution_id}/running", {})

    async def complete(self, execution_id: int, outcome: ExecutionOutcome) -> CallbackResult:
        """Close the run with its outcome."""
        return await self._post(
            f"/api/agent-executions/{execution_id}/completion",
            outcome.model_dump(by_alias=True),
        )

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def _post(self, path: str, payload: dict) -> CallbackResult:
        url = f"{self._config.backend_url.rstrip('/')}{path}"
        headers: dict[str, str] = {}

        if self._config.shared_secret:
            headers["X-Agent-Secret"] = self._config.shared_secret

        client = self._client or httpx.AsyncClient(timeout=self._config.timeout_seconds)

        try:
            if self._client is None:
                async with client:
                    response = await client.post(url, json=payload, headers=headers)
            else:
                response = await client.post(url, json=payload, headers=headers)

        except Exception as error:  # noqa: BLE001 - any transport failure
            # The run itself already finished; failing loudly here would throw
            # away a completed analysis because the report did not land.
            logger.warning(
                "Callback to %s did not reach the backend: %s", url, error
            )
            return CallbackResult(acknowledged=False, error=str(error))

        acknowledged = response.is_success
        body = response.text

        if acknowledged:
            logger.info("Callback %s acknowledged (%s)", url, response.status_code)
        else:
            logger.warning(
                "Callback %s rejected with %s: %s",
                url, response.status_code, body[:300],
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