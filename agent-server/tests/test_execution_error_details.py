import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from server.contracts.execution_error import ExecutionErrorDetail
from server.infrastructure.callback.client import CallbackClient
from server.infrastructure.callback.schemas import (
    CallbackConfig,
    ExecutionOutcome,
    InvocationReceipt,
)
from server.runtimes.invocation_reporting import (
    invocation_reporting,
    observe_invocation,
)
from server.services.execution_error_details import (
    capture_execution_errors,
    exception_error_detail,
)
from server.services.execution_failures import ExecutionFailure


@pytest.mark.parametrize("failure", [ValueError("secret-provider-payload"), TimeoutError("secret-token")])
def test_nested_exception_keeps_original_child_identity_time_and_safe_message(failure):
    async def run():
        receipts = []

        async def send(receipt):
            receipts.append(receipt)

        async def child():
            raise failure

        async def parent():
            return await observe_invocation(child(), agent_id="investigator", invocation_id="child", run_id="audit")

        before = datetime.now(UTC)
        with invocation_reporting(send), pytest.raises(type(failure)):
            await observe_invocation(parent(), agent_id="manager", invocation_id="parent", run_id="audit")
        terminal = [receipt for receipt in receipts if receipt["finished_at"]]
        original = terminal[0]["error_detail"]
        assert original["agentId"] == "investigator"
        assert original["invocationId"] == "child"
        assert original["exceptionType"] == type(failure).__name__
        assert original["code"] == ("execution_timeout" if isinstance(failure, TimeoutError) else "child_execution_error")
        assert before <= datetime.fromisoformat(original["occurredAt"]) <= datetime.now(UTC)
        assert terminal[1]["error_detail"] == original
        assert "secret" not in str(original)

    asyncio.run(run())


def test_handled_child_failure_propagates_without_relabelling_the_parent():
    async def run():
        receipts = []

        async def send(receipt):
            receipts.append(receipt)

        async def child():
            return SimpleNamespace(status="failed", failure=ExecutionFailure(code="result_contract_invalid",
                stage="validate_result", summary="Respuesta inválida.", exception_type="ValidationError"))

        async def parent():
            await observe_invocation(child(), agent_id="investigator", invocation_id="child", run_id="audit")
            return SimpleNamespace(status="partial")

        with invocation_reporting(send):
            await observe_invocation(parent(), agent_id="manager", invocation_id="parent", run_id="audit")
        terminal = [receipt for receipt in receipts if receipt["finished_at"]]
        assert terminal[0]["error_detail"]["message"] == "The received response did not satisfy the expected contract."
        assert terminal[1]["error_detail"] == terminal[0]["error_detail"]
        assert terminal[1]["status"] == "partial"

    asyncio.run(run())


@pytest.mark.parametrize("status", ["failed", "timeout", "partial", "cancelled", "completed"])
def test_result_without_exception_and_cancellation_are_distinguished(status):
    async def run():
        receipts = []

        async def send(receipt):
            receipts.append(receipt)

        async def operation():
            return SimpleNamespace(status=status)

        with invocation_reporting(send):
            await observe_invocation(operation(), agent_id="security", invocation_id="root", run_id="audit")
        assert ("error_detail" in receipts[-1]) == (status in {"failed", "timeout"})

    asyncio.run(run())


def test_cancellation_exception_never_creates_an_incident():
    async def run():
        receipts = []

        async def send(receipt):
            receipts.append(receipt)

        async def operation():
            raise asyncio.CancelledError

        with invocation_reporting(send), pytest.raises(asyncio.CancelledError):
            await observe_invocation(operation(), agent_id="security", invocation_id="root", run_id="audit")
        assert receipts[-1]["status"] == "cancelled"
        assert receipts[-1]["error"] is None
        assert "error_detail" not in receipts[-1]

    asyncio.run(run())


def test_callback_serialization_and_legacy_contracts():
    async def run():
        payloads = []

        def respond(request):
            import json
            payloads.append(json.loads(request.content))
            return httpx.Response(200)

        detail = exception_error_detail(ValueError("private input"), agent_id="child", invocation_id="c")
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = CallbackClient(CallbackConfig(backend_url="http://backend"), http)
            outcome = ExecutionOutcome(status="Failed", error="Safe error", error_detail=detail, input_tokens=9)
            assert (await client.complete(1, outcome)).acknowledged
            receipt = InvocationReceipt(invocation_id="c", agent_id="child", run_id="a", status="failed",
                started_at=datetime.now(UTC), error_detail=detail)
            assert (await client.invocation(1, receipt)).acknowledged
        assert payloads[0]["errorDetail"]["occurredAt"]
        assert payloads[0]["inputTokens"] == 9
        assert payloads[1]["error_detail"] == payloads[0]["errorDetail"]
        assert ExecutionErrorDetail.model_validate(payloads[0]["errorDetail"]) == detail
        assert ExecutionOutcome(status="Completed").error_detail is None
        assert receipt.model_copy(update={"error_detail": None}).error_detail is None

    asyncio.run(run())


def test_concurrent_audits_capture_handled_exceptions_without_a_callback_sink():
    async def run():
        async def audit(name):
            async def child():
                await asyncio.sleep(0)
                raise ValueError("private provider text")

            async def parent():
                try:
                    await observe_invocation(child(), agent_id=name, invocation_id=name, run_id=name)
                except ValueError:
                    return SimpleNamespace(status="partial")

            with capture_execution_errors() as incidents:
                await observe_invocation(parent(), agent_id="manager", invocation_id="root", run_id=name)
            assert incidents
            assert all(incident.agent_id == name and incident.invocation_id == name for incident in incidents)
            assert len({incident.occurred_at for incident in incidents}) == 1

        await asyncio.gather(audit("a"), audit("b"))

    asyncio.run(run())
