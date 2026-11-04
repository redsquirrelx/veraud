"""Content-free prompt, provider, and tool measurements for repository agents."""

import asyncio
import json
import math
import re
from collections import Counter
from time import monotonic
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal[
    "instructions", "contracts", "metadata", "source", "history", "feedback", "framing"
]
Stage = Literal["investigation", "unknown"]
ESTIMATE_METHOD = "ceil_characters_divided_by_4_not_provider_tokenization"


class Measurement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContextSize(Measurement):
    category: Category
    characters: int = Field(ge=0)


class PromptMeasurement(Measurement):
    stage: Stage
    correction: bool = False
    objective_id: str | None = None
    context: tuple[ContextSize, ...]
    prompt_characters: int = Field(ge=0)
    estimated_input_tokens: int = Field(ge=0)
    estimate_method: str = ESTIMATE_METHOD


class MeasuredPrompt(str):
    """A compatible text prompt carrying measurements, never another source copy."""

    def __new__(cls, text, measurement):
        value = super().__new__(cls, text)
        value.measurement = measurement
        return value


def source_in_tool_message(text):
    """Count serialized source string spans inside an outer JSON message string.

    Tools serialize source as content/text string values. Count their original
    JSON tokens including escaped outer-message representation, not raw lines.
    Strings elsewhere in the response and its envelope remain history overhead.
    """
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return 0
    if not isinstance(value, dict) or value.get("status") != "ok":
        return 0
    # Tokenize quoted strings so source containing JSON-looking text cannot be
    # mistaken for another response field. Only a token followed by ':' is a key.
    tokens = list(re.finditer(r'"(?:\\.|[^"\\])*"', text))
    count = 0
    for index, token in enumerate(tokens[:-1]):
        if json.loads(token.group()) not in ("content", "text"):
            continue
        following = tokens[index + 1]
        if text[token.end() : following.start()].strip() != ":":
            continue
        count += len(json.dumps(following.group())[1:-1])
    return count


def measure_json(value, category="metadata", *, fields=None):
    """Return the exact json.dumps text and a nonoverlapping character partition."""
    fields = fields or {}
    sizes = Counter()

    def encode(item, current, path=(), tool_content=False):
        if isinstance(item, dict):
            chunks = []
            sizes[current] += 2  # braces
            for index, (key, child) in enumerate(item.items()):
                if index:
                    sizes[current] += 2
                child_category = fields.get(key, current)
                prefix = json.dumps(key) + ": "
                sizes[child_category] += len(prefix)
                chunks.append(
                    prefix
                    + encode(
                        child,
                        child_category,
                        (*path, key),
                        tool_content=key == "content" and item.get("role") == "tool",
                    )
                )
            return "{" + ", ".join(chunks) + "}"
        if isinstance(item, (list, tuple)):
            sizes[current] += 2 + max(0, len(item) - 1) * 2
            return "[" + ", ".join(encode(child, current, path) for child in item) + "]"
        text = json.dumps(item)
        sizes[current] += len(text)
        if (
            tool_content
            and path
            and path[-1] == "content"
            and current == "history"
            and isinstance(item, str)
        ):
            source_size = source_in_tool_message(item)
            sizes[current] -= source_size
            sizes["source"] += source_size
        return text

    text = encode(value, category)
    return text, sizes


def measured_prompt(parts, *, stage, correction=False, objective_id=None):
    """Parts are (text, category or measured JSON partition); bytes stay unchanged."""
    sizes = Counter()
    text = ""
    for fragment, category in parts:
        text += fragment
        if isinstance(category, str):
            sizes[category] += len(fragment)
        else:
            sizes.update(category)
    if sum(sizes.values()) != len(text):
        raise ValueError(
            "Prompt measurement must partition every serialized character."
        )
    return MeasuredPrompt(
        text,
        PromptMeasurement(
            stage=stage,
            correction=correction,
            objective_id=objective_id,
            context=tuple(
                ContextSize(category=name, characters=count)
                for name, count in sorted(sizes.items())
            ),
            prompt_characters=len(text),
            estimated_input_tokens=math.ceil(len(text) / 4),
        ),
    )


class ModelCallMeasurement(PromptMeasurement):
    call: int
    status: str
    attempts: int
    seconds: float
    wait_seconds: float
    response_characters: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    unknown_usage_attempts: int = 0
    http_status: int | None = None
    error_type: str | None = None


class ToolMeasurement(Measurement):
    call_id: str
    tool: str
    request_sha256: str
    repeated: bool
    status: str
    seconds: float
    cache_hit: bool = False


class StageMeasurement(Measurement):
    stage: Stage
    calls: int
    correction_calls: int
    provider_attempts: int
    unknown_usage_attempts: int
    context: tuple[ContextSize, ...]
    prompt_characters: int
    estimated_input_tokens: int
    reported_input_tokens: int
    reported_output_tokens: int
    input_tokens: int | None
    output_tokens: int | None
    seconds: float


class TextCallObserver:
    """Observe the library text-model protocol without changing its behavior."""

    def __init__(self, generate):
        self.generate = generate
        self.measurements = []

    async def __call__(self, prompt):
        measurement = getattr(prompt, "measurement", None)
        if measurement is None:
            measurement = measured_prompt(
                [(prompt, "instructions")], stage="unknown"
            ).measurement
        started = monotonic()
        status, response_size = "failed", None
        try:
            response = await self.generate(str(prompt))
            status = "completed"
            response_size = len(response) if isinstance(response, str) else None
            return response
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        finally:
            self.measurements.append(
                ModelCallMeasurement(
                    **measurement.model_dump(),
                    call=len(self.measurements) + 1,
                    status=status,
                    attempts=1,
                    seconds=monotonic() - started,
                    wait_seconds=0,
                    response_characters=response_size,
                    unknown_usage_attempts=1,
                )
            )

    def telemetry(self, tool_requests=()):
        return execution_telemetry(self.measurements, tool_requests)


class ExecutionTelemetry(Measurement):
    estimate_method: str = ESTIMATE_METHOD
    model_calls: tuple[ModelCallMeasurement, ...] = ()
    tool_requests: tuple[ToolMeasurement, ...] = ()
    stages: tuple[StageMeasurement, ...] = ()
    repeated_tool_requests: int = 0


def execution_telemetry(calls=(), tool_requests=()):
    stages = []
    for stage in dict.fromkeys(call.stage for call in calls):
        selected = [call for call in calls if call.stage == stage]
        sizes = Counter()
        for call in selected:
            sizes.update({part.category: part.characters for part in call.context})
        reported_input = sum(call.input_tokens or 0 for call in selected)
        reported_output = sum(call.output_tokens or 0 for call in selected)
        complete_input = all(
            call.input_tokens is not None and not call.unknown_usage_attempts
            for call in selected
        )
        complete_output = all(
            call.output_tokens is not None and not call.unknown_usage_attempts
            for call in selected
        )
        stages.append(
            StageMeasurement(
                stage=stage,
                calls=len(selected),
                correction_calls=sum(call.correction for call in selected),
                provider_attempts=sum(call.attempts for call in selected),
                unknown_usage_attempts=sum(
                    call.unknown_usage_attempts for call in selected
                ),
                context=tuple(
                    ContextSize(category=name, characters=count)
                    for name, count in sorted(sizes.items())
                ),
                prompt_characters=sum(call.prompt_characters for call in selected),
                estimated_input_tokens=sum(
                    call.estimated_input_tokens * call.attempts for call in selected
                ),
                reported_input_tokens=reported_input,
                reported_output_tokens=reported_output,
                input_tokens=reported_input if complete_input else None,
                output_tokens=reported_output if complete_output else None,
                seconds=sum(call.seconds for call in selected),
            )
        )
    return ExecutionTelemetry(
        model_calls=tuple(calls),
        tool_requests=tuple(tool_requests),
        stages=tuple(stages),
        repeated_tool_requests=sum(request.repeated for request in tool_requests),
    )
