"""LLM adapter for the TestabilityProbeAgent.

The LLM is the primary capability of this agent: it interprets findings,
investigates the code, plans verifications, authors pytest modules, evaluates
observed outcomes and repairs technical failures. Deterministic machinery
(LangGraph, budgets, workspace isolation, pytest execution, packaging) controls
everything around the model; there are NO rigid detectors or per-project rules.

Standalone runners resolve the repository root `.env` (`LLM_API_KEY`) and
`config/dev-agents.yaml` (default entry `dummy`). Production receives explicit
model settings and credentials from the verification-suite composition instead.
"""

import json
import re
from pathlib import Path
from typing import Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.agents.model import ModelCredentials, ModelSettings
from server.config.dev_agents_config import load_dev_agents_config
from server.config.settings import ENV_FILE
from server.infrastructure.llm.chat_factory import build_chat_model
from server.runtimes.investigation.provider import model_pacer

from .config import TestabilityProbeConfig

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_PROMPT_CACHE: dict[str, str] = {}


def load_prompt(name: str) -> str:
    if name not in _PROMPT_CACHE:
        _PROMPT_CACHE[name] = (_PROMPTS_DIR / name).read_text(encoding="utf-8")
    return _PROMPT_CACHE[name]


_FENCE_RE = re.compile(r"```(?:python|json|typescript|javascript|tsx|jsx|ts|js|mjs)?\s*(.*?)```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_code(text: str) -> str:
    match = _FENCE_RE.search(text)
    return (match.group(1) if match else text).strip() + "\n"


def extract_json_object(text: str) -> dict:
    """Parse the first JSON object in a model reply; tolerate code fences and prose."""

    fenced = _FENCE_RE.search(text)
    candidate = fenced.group(1).strip() if fenced else text.strip()
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        raise ValueError("The model reply contains no JSON object.")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise TypeError("The model reply JSON is not an object.")
    return parsed


def _response_text(response) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content if isinstance(content, list) else [content]:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(parts)


class ProbeLLMClient(Protocol):
    async def complete(self, node: str, prompt: str) -> str: ...
    def chat(self): ...
    @property
    def used_tokens(self) -> int: ...
    @property
    def calls(self) -> int: ...


class LLMBudgetExhausted(RuntimeError):
    """The configured model-call or token budget was reached."""


class RunnerCredentials(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_file_encoding="utf-8")
    llm_api_key: SecretStr = SecretStr("")


class ProviderProbeLLMClient:
    """Explicit production access or local dev entry, with shared RPM/TPM pacing."""

    def __init__(self, config: TestabilityProbeConfig, agent_config: str = "dummy", *,
                 settings: ModelSettings | None = None, credentials: ModelCredentials | None = None):
        if (settings is None) != (credentials is None):
            raise ValueError("Explicit model settings and credentials must be supplied together.")
        if settings is None:
            configurations = load_dev_agents_config()
            if agent_config not in configurations:
                raise ValueError(f"No agent configuration {agent_config!r} in config/dev-agents.yaml.")
            _, settings = configurations[agent_config]
            credentials = ModelCredentials(api_key=RunnerCredentials(_env_file=ENV_FILE).llm_api_key.get_secret_value().strip())
            if config.provider_temperature_override is not None:
                settings = settings.model_copy(update={"temperature": config.provider_temperature_override})
        if not credentials.api_key.strip():
            raise ValueError("A model API key is required (LLM_API_KEY for local runners).")
        self.settings = settings
        self.model = build_chat_model(settings, credentials)
        self.pacer = model_pacer(self.model, rate_limits=config.provider_rate_limits,
                                 interval=config.provider_request_interval_seconds,
                                 max_retries=config.max_provider_retries,
                                 backoff=config.provider_retry_backoff_seconds)
        self.max_output_tokens = settings.max_tokens
        self.max_model_calls = config.max_model_calls
        self.max_total_tokens = config.max_total_tokens
        self._calls = 0
        self._used_tokens = 0
        self._used_input_tokens = 0
        self._used_output_tokens = 0

    @property
    def calls(self) -> int:
        return self._calls

    @property
    def used_tokens(self) -> int:
        return self._used_tokens

    @property
    def used_input_tokens(self) -> int:
        return self._used_input_tokens

    @property
    def used_output_tokens(self) -> int:
        return self._used_output_tokens

    async def _precheck(self, estimate: int):
        if self._calls >= self.max_model_calls:
            raise LLMBudgetExhausted(f"Model-call cap ({self.max_model_calls}) reached.")
        if self._used_tokens >= self.max_total_tokens:
            raise LLMBudgetExhausted(f"Token cap ({self.max_total_tokens}) reached; accounted {self._used_tokens}.")
        return await self.pacer.acquire(estimate)

    async def _postcheck(self, reservation, prompt_or_estimate, spent: int, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self._used_tokens += spent or max(1, prompt_or_estimate)
        if spent:
            self._used_input_tokens += input_tokens
            self._used_output_tokens += output_tokens
        else:
            self._used_input_tokens += max(1, prompt_or_estimate)
        self._calls += 1
        self.pacer.settle(reservation, spent or max(1, prompt_or_estimate))

    async def complete(self, node: str, prompt: str) -> str:
        system_prompt = load_prompt("system.md") + f"\nCurrent stage: {node}."
        estimate = max(1, (len(prompt) + len(system_prompt)) // 4)
        reservation = await self._precheck(estimate)
        try:
            response = await self.model.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt),
            ])
            text = _response_text(response)
            usage = getattr(response, "usage_metadata", None) or {}
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            await self._postcheck(reservation, estimate, input_tokens + output_tokens, input_tokens, output_tokens)
            return str(text)
        except Exception:
            self.pacer.settle(reservation, 0)
            raise

    def chat(self):
        owner = self

        class PacedChat:
            def __init__(self, model):
                self.model = model

            def bind_tools(self, tools):
                return PacedChat(self.model.bind_tools(tools))

            async def ainvoke(self, messages):
                estimate = max(1, len(str(messages)) // 4)
                reservation = await owner._precheck(estimate)
                try:
                    response = await self.model.ainvoke(messages)
                    usage = getattr(response, "usage_metadata", None) or {}
                    await owner._postcheck(reservation, estimate,
                                           (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0),
                                           int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0))
                    return response
                except Exception:
                    owner.pacer.settle(reservation, 0)
                    raise

        return PacedChat(self.model)


class ScriptedProbeLLMClient:
    """Canned node responses for deterministic, offline acceptance runs.

    `responses` maps node name ("plan", "investigation", "generate", "evaluate",
    "repair") to a queue of raw replies. ``chat_model`` is returned by ``chat()``;
    pass None to exercise the no-tool investigation fallback.
    """

    def __init__(self, responses: dict[str, list[str]] | None = None, chat_model=None):
        self.responses = {key: list(value) for key, value in (responses or {}).items()}
        self.chat_model = chat_model
        self.calls: list[dict] = []
        self._used_tokens = 0

    @property
    def used_tokens(self) -> int:
        return self._used_tokens

    async def complete(self, node: str, prompt: str) -> str:
        self.calls.append({"node": node, "prompt_chars": len(prompt)})
        queue = self.responses.get(node) or []
        if queue:
            reply = queue.pop(0)
            self._used_tokens += max(1, (len(prompt) + len(reply)) // 4)
            return reply
        raise ValueError(f"No scripted reply for node {node!r}.")

    def chat(self):
        return self.chat_model
