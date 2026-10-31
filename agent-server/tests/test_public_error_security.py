import asyncio
import json
import logging

import httpx
import pytest

from server.contracts.execution_error import ExecutionErrorDetail
from server.contracts.public_errors import HIDDEN_ERROR, MESSAGES
from server.infrastructure.callback.client import CallbackClient
from server.infrastructure.callback.schemas import (
    CallbackConfig,
    ExecutionOutcome,
    InvocationReceipt,
)

SECRETS = ["sk-proj-fake-key-only-for-tests", "password=fake-password-731",
    "Authorization: Bearer fake-bearer-942", "https://fake-user:fake-pass@provider.invalid?api_key=fake-query-315"]


@pytest.mark.parametrize("secret", SECRETS)
def test_callbacks_and_transport_logs_never_echo_error_payloads(secret, caplog):
    async def run():
        sent = []

        def respond(request):
            sent.append(json.loads(request.content))
            return httpx.Response(503, text=secret)

        detail = ExecutionErrorDetail(agent_id="security", invocation_id="child", code="execution_timeout",
            exception_type="TimeoutError", message=secret)
        assert detail.message == MESSAGES["execution_timeout"]
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = CallbackClient(CallbackConfig(backend_url="http://backend"), http)
            outcome = ExecutionOutcome(status="Failed", error=secret, error_detail=detail,
                result=json.dumps({"error": secret, "child": {"failure": {"code": "unknown", "summary": secret}}}),
                input_tokens=12, output_tokens=3)
            response = await client.complete(1, outcome)
            receipt = InvocationReceipt(invocation_id="child", agent_id="security", run_id="audit", status="failed",
                started_at="2026-10-30T12:00:00Z", error=secret, error_detail=detail)
            await client.invocation(1, receipt)
            assert secret not in str(response)
        assert secret not in json.dumps(sent)
        assert sent[0]["inputTokens"] == 12
        assert sent[0]["error"] == HIDDEN_ERROR

    caplog.set_level(logging.INFO)
    asyncio.run(run())
    assert secret not in caplog.text


def test_unknown_code_and_exception_names_are_not_public_channels():
    detail = ExecutionErrorDetail(agentId="sk-fake-key", invocationId="https://u:p@example.invalid",
        code="sk-private-code", exceptionType="fake-password", message="unrecognized payload")
    assert detail.agent_id is None and detail.invocation_id is None
    assert detail.code == "execution_failed" and detail.exception_type is None
