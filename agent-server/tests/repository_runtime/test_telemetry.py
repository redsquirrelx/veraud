"""Exact context accounting, content-free records, and usage completeness."""

import asyncio
import json
from types import SimpleNamespace

from server.runtimes.repository.model_runtime import ModelGateway
from server.runtimes.repository.telemetry import (
    TextCallObserver,
    measure_json,
    measured_prompt,
)


def test_serialized_partition_preserves_prompt_and_counts_escaped_source():
    source = 'def main():\n    return "secret λ" # {"content": "not another field"}\n'
    tool_text = json.dumps(
        {"status": "ok", "data": {"content": source, "path": "main.py"}},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    payload = {
        "objective": "Inspect main",
        "history": [
            {"role": "tool", "content": tool_text},
            {"role": "ai", "content": tool_text},
        ],
        "validation_errors": ["Inspect implementation."],
        "previous_findings": [{"id": "finding:prior"}],
    }
    text, sizes = measure_json(
        payload,
        fields={
            "history": "history",
            "previous_findings": "history",
            "validation_errors": "feedback",
        },
    )
    assert text == json.dumps(payload)
    assert sum(sizes.values()) == len(text)
    source_token = json.dumps(source, ensure_ascii=False)
    assert sizes["source"] == len(json.dumps(source_token)[1:-1])
    assert sizes["feedback"] > 0 and sizes["history"] > 0
    prompt = measured_prompt(
        [("INSTRUCTIONS\n", "instructions"), (text, sizes)],
        stage="investigation",
        correction=True,
        objective_id="investigation:main",
    )
    assert isinstance(prompt, str) and prompt == "INSTRUCTIONS\n" + json.dumps(payload)
    assert sum(part.characters for part in prompt.measurement.context) == len(prompt)
    assert source not in prompt.measurement.model_dump_json()


def test_measured_and_estimated_usage_are_separate_and_stage_totals_reconcile():
    class Model:
        async def generate(self, prompt):
            assert isinstance(prompt, str)
            return SimpleNamespace(
                content='{"ok": true}',
                usage_metadata={"input_tokens": 31, "output_tokens": 7},
            )

    gateway = ModelGateway(Model(), max_retries=0)

    async def scenario():
        for correction in (False, True):
            prompt = measured_prompt(
                [("PRIVATE INSTRUCTION", "instructions"), ("{}", "contracts")],
                stage="investigation",
                correction=correction,
            )
            await gateway(prompt)

    asyncio.run(scenario())
    telemetry = gateway.telemetry()
    stage = telemetry.stages[0]
    assert stage.calls == 2 and stage.correction_calls == 1
    assert stage.input_tokens == 62 and stage.output_tokens == 14
    assert stage.estimated_input_tokens == 12
    assert (
        sum(part.characters for part in stage.context) == stage.prompt_characters == 42
    )
    assert "PRIVATE INSTRUCTION" not in telemetry.model_dump_json()
    assert '"ok"' not in telemetry.model_dump_json()


def test_missing_provider_usage_is_not_replaced_by_estimates():
    class Model:
        async def generate(self, prompt):
            return "{}"

    gateway = ModelGateway(Model(), max_retries=0)
    asyncio.run(
        gateway(measured_prompt([("abcdefgh", "instructions")], stage="investigation"))
    )
    stage = gateway.telemetry().stages[0]
    assert stage.input_tokens is None and stage.output_tokens is None
    assert stage.estimated_input_tokens == 2
    assert stage.unknown_usage_attempts == 1
    assert gateway.usage_totals()["input_tokens"] is None


def test_google_sdk_receives_identical_wire_content_for_measured_and_plain_prompts():
    import httpx
    from google import genai
    from google.genai import types

    async def scenario():
        bodies = []

        def handle(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {"content": {"parts": [{"text": "{}"}], "role": "model"}}
                    ]
                },
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        client = genai.Client(
            api_key="offline-test",
            http_options=types.HttpOptions(httpx_async_client=http),
        )

        class Model:
            async def generate(self, prompt):
                assert type(prompt) is str
                return await client.aio.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    ),
                )

        try:
            text = "Inspect main: λ\nReturn JSON."
            await Model().generate(text)
            prompt = measured_prompt([(text, "instructions")], stage="investigation")
            gateway = ModelGateway(Model(), max_retries=0)
            assert await gateway(prompt) == "{}"
            assert bodies[0] == bodies[1]
            assert bodies[1]["contents"][0]["parts"][0]["text"] == text
            assert gateway.telemetry().model_calls[0].stage == "investigation"
            assert gateway.telemetry().model_calls[0].prompt_characters == len(text)
        finally:
            await client.aio.aclose()
            client.close()
            await http.aclose()

    asyncio.run(scenario())


def test_text_observer_strips_metadata_before_calling_delegate():
    async def generate(prompt):
        assert type(prompt) is str
        assert prompt == "Inspect main."
        return "{}"

    observer = TextCallObserver(generate)
    prompt = measured_prompt([("Inspect main.", "instructions")], stage="investigation")
    assert asyncio.run(observer(prompt)) == "{}"
    assert observer.telemetry().model_calls[0].stage == "investigation"
