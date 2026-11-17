"""LLM adapter: rule selection and test authoring.

One job delegated to the LLM: pick the correct registered rule and fill its
schema-validated parameters, then author the pytest module that verifies the
declared property for the given verification spec. The orchestrator runs the
produced module and reports structured diagnostics back to the repair loop.

Any failure path falls back to deterministic templates and then to an explicit
"not verifiable / environment blocked" diagnosis — never to a manufactured or
vacuous assertion.
"""

import ast
import json
import re
from pathlib import Path
from typing import Protocol

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.agents.model import ModelCredentials, ModelSettings
from server.agents.finding_test_generation.schemas import (
    AuditDocument,
    VerificationSpec,
)
from server.config.dev_agents_config import load_dev_agents_config
from server.config.settings import ENV_FILE
from server.infrastructure.llm.chat_factory import build_chat_model
from server.runtimes.investigation.provider import model_pacer

from .config import FindingTestConfig


class FindingLLMClient(Protocol):
    async def select_rule(self, prompt: str) -> str: ...
    async def plan_verifications(self, document: AuditDocument, context: dict) -> tuple[list[VerificationSpec], list[str]]: ...
    async def generate_test(self, spec: VerificationSpec, context: dict) -> str: ...
    async def repair_test(self, spec: VerificationSpec, content: str, failure: str, context: dict) -> str: ...


class ScriptedLLMClient:
    """Canned selections and contents for deterministic acceptance runs."""

    def __init__(self, selections: list[str] | None = None, generate: dict[str, str] | None = None, repair: dict[str, list[str]] | None = None):
        self.selections = list(selections or [])
        self.generate = dict(generate or {})
        self.repair = {key: list(value) for key, value in (repair or {}).items()}
        self.calls: list[dict] = []

    async def select_rule(self, prompt: str) -> str:
        self.calls.append({"node": "select_rule"})
        if self.selections:
            return self.selections.pop(0)
        return '{"rule_id": "", "parameters": {}, "confidence": "low", "reason": "no scripted selection"}'

    async def plan_verifications(self, document: AuditDocument, context: dict):
        from .planning import plan_verifications as deterministic_plan

        self.calls.append({"node": "plan_verifications"})
        return deterministic_plan(document)

    async def generate_test(self, spec: VerificationSpec, context: dict) -> str:
        self.calls.append({"node": "generate_test", "verification_id": spec.verification_id})
        content = self.generate.get(spec.verification_id)
        if content is None:
            raise ValueError(f"No scripted content for {spec.verification_id}")
        return content

    async def repair_test(self, spec: VerificationSpec, content: str, failure: str, context: dict) -> str:
        self.calls.append({"node": "repair_test", "verification_id": spec.verification_id})
        queue = self.repair.get(spec.verification_id) or []
        if not queue:
            raise ValueError(f"No scripted repair for {spec.verification_id}")
        return queue.pop(0)


class RunnerCredentials(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_file_encoding="utf-8")
    llm_api_key: SecretStr = SecretStr("")


class LLMBudgetExhausted(RuntimeError):
    """The configured model-call or token budget was reached."""


_FENCE_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


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


_LANG_PREAMBLES = {"typescript", "tsx", "ts", "javascript", "js", "jsx", "mjs", "python", "py"}


def _extract_code(text: str) -> str:
    match = _FENCE_RE.search(text)
    body = (match.group(1) if match else text).strip()
    first, break_, rest = body.partition("\n")
    if first.strip().lower() in _LANG_PREAMBLES and break_:
        body = rest.lstrip()
    return body.rstrip() + "\n"


class ProviderFindingLLMClient:
    """Explicit production access or local dev entry, with shared RPM/TPM pacing."""

    def __init__(self, config: FindingTestConfig, agent_config: str = "dummy", *,
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
        self.used_tokens = 0
        self.used_input_tokens = 0
        self.used_output_tokens = 0

    async def _invoke(self, prompt: str) -> str:
        estimate = max(1, len(prompt) // 4)
        if self._calls >= self.max_model_calls:
            raise LLMBudgetExhausted(f"Model-call cap ({self.max_model_calls}) reached.")
        if self.used_tokens >= self.max_total_tokens:
            raise LLMBudgetExhausted(f"Token cap ({self.max_total_tokens}) reached; accounted {self.used_tokens}.")
        reservation = await self.pacer.acquire(estimate)
        try:
            response = await self.model.ainvoke(prompt)
            text = _response_text(response)
            usage = getattr(response, "usage_metadata", None) or {}
            input_tokens = usage.get("input_tokens") or 0
            output_tokens = usage.get("output_tokens") or 0
            spent = input_tokens + output_tokens
            self.used_tokens += spent or estimate
            self.used_input_tokens += input_tokens if spent else estimate
            self.used_output_tokens += output_tokens
            self._calls += 1
            self.pacer.settle(reservation, spent or estimate)
            return str(text)
        except Exception:
            self.pacer.settle(reservation, 0)
            raise

    async def select_rule(self, prompt: str) -> str:
        return await self._invoke(prompt)

    async def plan_verifications(self, document: AuditDocument, context: dict):
        from .planning import plan_verifications as deterministic_plan

        return deterministic_plan(document)

    def _rule_knowledge(self, spec: VerificationSpec) -> str:
        slug = (spec.rule_kind or "unknown").lower()
        hints = {
            "layer_import": "STRATEGY: walk the module dependency graph (import statements / require calls). Test fails when a file in scope imports a forbidden root.",
            "restricted_import": "STRATEGY: walk the module graph; fail on any import outside the allowed roots.",
            "forbidden_framework_in_layer": "STRATEGY: find imports under the forbidden framework and fail.",
            "private_module_access": "STRATEGY: walk every module except the owning package; flag imports whose path begins with the private module.",
            "private_attribute_access": "STRATEGY: in each file outside the owning package, flag `_`-prefixed attribute access on private module paths.",
            "contract_states": "STRATEGY: parse the file; find classes/functions returning literal values; compare vocabularies across siblings. Intersection must be non-empty.",
            "contract_states_dynamic": "STRATEGY: import the real module with stubbed collaborators; assert a shared literal contract on return values.",
            "forbidden_call": "STRATEGY: instantiate the subject with mocked collaborators; call the target method; assert the forbidden collaborator was never called.",
            "one_class_per_module": "STRATEGY: parse the file; count top-level class declarations; fail when count > MAX_CLASSES in the spec.",
            "no_environ_in_scope": "STRATEGY: walk the scope for `os.environ`/`os.getenv` (Python) or `process.env` (JS/TS) reads.",
            "circular_import": "STRATEGY: resolve the per-module import graph; fail on any two-way cyclic import.",
        }
        extra = hints.get(slug)
        return f"\nRule-kind guidance for `{slug}`:\n{extra}\n" if extra else "\n"

    def _repo_layout_walk(self, repo: str | None) -> str:
        if not repo:
            return ""
        import os
        lines = []
        for current_dir, dirs, files in os.walk(repo):
            relative = Path(current_dir).relative_to(repo).as_posix()
            if not relative:
                continue
            file_set = sorted(files)[:30]
            if file_set:
                lines.append(f"{relative}/: {', '.join(file_set)}\n")
        return "".join(lines)

    def _language_block(self, spec: VerificationSpec) -> tuple[str, str, str]:
        """Return (syntax_label, import_block, runtime_hints) for the LLM generator.

        Kept narrow on purpose: only language-surface constraints, no rule- or
        project-specific hints that would overfit a single audit or layout.
        """
        if spec.language == "python":
            return (
                "pytest",
                (
                    "stdlib + pytest only; no other third-party imports.\n"
                    f"The test MUST be syntactically valid Python; it must contain exactly one function named {spec.test_name}.\n"
                    "Repository root MUST be a Path: pathlib.Path(os.environ.get('TALLERCITO_REPO_ROOT', str(pathlib.Path(__file__).resolve().parents[2])))"
                ),
                "The module is executed by an independent CI runner; it must work standalone.",
            )
        file_ext = ".test.mjs" if spec.language == "javascript" else ".test.tsx"
        return (
            f"vitest ({file_ext})",
            (
                "- Import `expect`, `it` (and optionally `describe`) from 'vitest'. Globals are intentionally disabled.\n"
                "- Use Node built-ins only: `node:fs`, `node:path`, `node:url`, `node:process` (accessed via `process`).\n"
                "- Resolve the repo root from `process.env.TALLERCITO_REPO_ROOT` and `node:path`; never rely on cwd.\n"
                f"- The test MUST be syntactically valid {spec.language.capitalize()}; it MUST export exactly one `it({spec.test_name!r}, ...)` block.\n"
                "- Use ESM `import ... from`; do not use `require` except through `createRequire` when unavoidable.\n"
            ),
            f"The module is executed by an independent Node/Vitest runner; it must work standalone in {file_ext} form.",
        )

    async def generate_test(self, spec: VerificationSpec, context: dict) -> str:
        repo = context.get("repo") if isinstance(context, dict) else None
        target = spec.target_components[0] if spec.target_components else None
        language_name = "Python" if spec.language == "python" else spec.language.capitalize()
        syntax_label, import_block, runtime_hints = self._language_block(spec)
        prompt = (
            f"You are the verification-test author of an auditing pipeline. Write ONE self-contained {syntax_label} module\n"
            f"that FAILS when the audit's property does not hold, and PASSES when it does.\n"
            f"{runtime_hints}\n\n"
            f"Property to verify: {spec.property}\n"
            + f"Finding: {spec.title}\n"
            + f"Candidate rule kind: {spec.rule_kind}\n"
            + f"Components referenced: {', '.join(spec.target_components)}\n"
            + f"Violation oracle: {spec.violation_oracle}\n"
            + f"Fixed oracle: {spec.fixed_oracle}\n"
            + f"Scenario scope: {spec.test_scenario_scope}\n"
            + f"Test name: {spec.test_name}\n\n"
            + "Execution context (the suite is extracted at <repo>/.tallercito/):\n"
            + "- Repository root is available via `process.env.TALLERCITO_REPO_ROOT` (absolute path).\n"
            + f"- {language_name} package dependencies live under <repo_root>/node_modules already; do not download anything.\n"
            + "- Build repository file paths as <repo_root>/<relative path> using the Components above.\n"
            + "- Read only what you need; no network, no subprocess, no writes to the repository.\n"
            + import_block.replace("import pathlib.Path", "").rstrip() + "\n"
            + "- The file you must verify is given below as Target file: use ONLY names, classes and functions that exist in it.\n"
            + "- Your assertion MUST FAIL at the violating commit and PASS at a corrected variant. Be specific.\n"
            + "- Never let 'no matches found' pass vacuously; assert the file exists and was actually analyzed.\n"
            + "- Never skip, xfail or weaken the oracle; keep exactly ONE assertion as the core of the test.\n"
            + "- ABSOLUTELY FORBIDDEN: tautologies; no-op detectors; if-self-only logic with no assertion.\n"
            + "- Assert on the oracle, not on implementation details: a reader must see why the assertion exists.\n\n"
            + "ORACLE PRIORITY: the original finding and documentary constraint below are authoritative.\n"
            + "The candidate rule, violation/fixed oracles and strategy are FALLIBLE planning suggestions.\n"
            + "Discard a suggestion when it does not actually measure the finding. Never introduce an undocumented requirement.\n"
            + "In particular, disjoint literal vocabularies do NOT establish single responsibility violations;\n"
            + "class counts do NOT establish mixed function responsibilities unless the documented rule requires class separation.\n"
            + "Prefer AST/import analysis for an explicitly forbidden dependency; use dynamic tests only when\n"
            + "the supplied real code establishes the constructor, method signature and collaborators.\n"
            + "Never invent a symbol, patch target, state vocabulary or constructor argument.\n"
            + "Mock collaborators only, invoke the REAL subject, and assert on effects of that invocation.\n"
            + "Do not freeze current literal data or ban substrings to force RED; a legitimate correction must pass\n"
            + "without knowing the evaluator's corrected implementation. Include a short docstring explaining\n"
            + "which documented constraint the assertion measures and why a compliant implementation passes.\n"
            + "If the property cannot be measured with the supplied evidence, throw new Error('NOT_VERIFIABLE: reason')\n"
            + "instead of inventing an oracle or using assert False.\n\n"
            + f"Original finding and documentary evidence:\n{json.dumps(context.get('finding'), ensure_ascii=False, default=str)[:18000]}\n"
            + f"{self._file_context(repo, target)}\n"
            + "Other referenced components (inspect the consumer as well as the dependency):\n"
            + "\n".join(self._file_context(repo, component, 8000) for component in spec.target_components[1:4]) + "\n"
            + "A component list may include both the violating consumer and its legitimate dependency.\n"
            + "Analyze the consumer's forbidden access; do not mistake the dependency's own internal code for a violation.\n"
            + f"Direct local dependencies (read-only source context):\n{self._dependency_context(repo, target, spec)}\n"
            + f"Repository layout (summary):\n{self._repo_layout_walk(repo)}\n"
            + f"{self._rule_knowledge(spec)}\n"
            + ("Reply with exactly one ```typescript code fence." if spec.language != "python" else "Reply with exactly one ```python code fence.")
        )
        return _extract_code(await self._invoke(prompt))

    @staticmethod
    def _dependency_context(repo: str | None, target: str | None, spec: VerificationSpec | None = None) -> str:
        """Bounded direct import context; never reads another checkout or executes imports."""
        if not repo or not target:
            return ""
        # Only Python targets today; TS AST parsing lives in ts_templates / helper-driven scans.
        if Path(target).suffix.lower() != ".py":
            return ""
        root = Path(repo).resolve()
        source = (root / target).resolve()
        if not source.is_relative_to(root):
            return ""
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeError):
            return ""
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                modules.append(node.module)
        chunks = []
        seen = set()
        for module in modules:
            relative = Path(*module.split("."))
            for base in (root / "src", root):
                for suffix in (relative.with_suffix(".py"), relative / "__init__.py"):
                    path = (base / suffix).resolve()
                    if path in seen or path == source or not path.is_relative_to(root) or not path.is_file():
                        continue
                    seen.add(path)
                    chunks.append(ProviderFindingLLMClient._file_context(str(root), path.relative_to(root).as_posix(), 5000))
                    if len(chunks) >= 4:
                        return "\n".join(chunks)
        return "\n".join(chunks)

    async def repair_test(self, spec: VerificationSpec, content: str, failure: str, context: dict) -> str:
        repo = context.get("repo") if isinstance(context, dict) else None
        target = spec.target_components[0] if spec.target_components else None
        syntax_label, import_block, _runtime_hints = self._language_block(spec)
        file_fence = "python" if spec.language == "python" else "typescript"
        prompt = (
            f"The following {syntax_label} module fails for a technical reason.\n"
            f"Property to verify: {spec.property}\n"
            f"Failure (last compiler/runner output):\n{failure}\n\n"
            f"Target file it must verify:\n{self._file_context(repo, target)}\n"
            f"Module:\n```{file_fence}\n{content}\n```\n"
            f"Return the corrected module in exactly one ```{file_fence} code fence.\n"
            f"Do not weaken the assertion; do not skip; do not mock the subject under test.\n"
            f"Only repair test-code defects, never the audited implementation. Preserve the documented property.\n"
            f"Fix the specific error shown above, e.g. missing/mismatched imports, wrong fence syntax, wrong file extension.\n"
            f"Repository root is available via `process.env.TALLERCITO_REPO_ROOT` (TS/JS) or\n"
            f"`pathlib.Path(os.environ.get('TALLERCITO_REPO_ROOT', str(pathlib.Path(__file__).resolve().parents[2])))` (Python).\n"
            f"If the code is TypeScript/JavaScript, the corrected module MUST import `expect` (and `it` when missing) from 'vitest'.\n"
            f"If TypeScript globals are missing, import them explicitly instead of assuming availability.\n"
            f"Concrete import block to honor:\n{import_block}\n"
            f"Use ONLY names, classes and functions that exist in the target file.\n"
        )
        return _extract_code(await self._invoke(prompt))

    @staticmethod
    def _file_context(repo: str | None, target: str | None, limit: int = 16000) -> str:
        if not repo or not target:
            return ""
        path = Path(repo) / target
        py_suffixes = {".py"}
        fence = "python" if path.suffix.lower() in py_suffixes else "text"
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return f"\nTarget file {target} could not be read from the repo.\n"
        if len(content) > limit:
            snippet = content[:limit]
            return f"\nTarget file {target} (truncated, {limit} of {len(content)} chars):\n```{fence}\n{snippet}\n```\n"
        return f"\nTarget file {target} (full content):\n```{fence}\n{content}\n```\n"
