"""LangGraph orchestration for the TestabilityProbeAgent.

Cycle: prepare_input -> plan_verifications -> investigate -> generate ->
execute_tests -> evaluate -> (repair -> execute_tests)* -> finalize.

The LLM is the primary capability: it interprets each finding, plans the
verifications, investigates the code with read-only tools, authors the pytest
modules, evaluates what the run means for the denounced condition, and repairs
technical failures within a per-verification budget. Deterministic machinery
(LangGraph, budgets, workspace isolation, pytest execution, packaging) controls
everything around the model. The probe never audits, never repairs the audited
repository, and never invents findings.
"""

import ast
import hashlib
import json
import re
import tempfile
import time
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from server.runtimes.invocation_reporting import phase_node
from server.runtimes.verification.checkout import check_checkout
from server.runtimes.verification.templates import node_runtime
from server.runtimes.verification.tools.audit_log import AuditLog
from server.runtimes.verification.tools.code_search import CodeSearch
from server.runtimes.verification.tools.package_discovery import dotted_module
from server.runtimes.verification.tools.repo_copy import copy_repository
from server.runtimes.verification.tools.repo_reader import PathSafetyError, RepoReader
from server.runtimes.verification.tools.sandbox import LocalSubprocessExecutor
from server.runtimes.verification.tools.suspicion import subject_tokens, suspicion_flags
from server.runtimes.verification.tools.test_runner import (
    CLASSIFICATION_PASS,
    CLASSIFICATION_TECHNICAL,
    CLASSIFICATION_TIMEOUT,
    CLASSIFICATION_TRIVIAL,
    CLASSIFICATION_VIOLATION,
    WorkspaceRunner,
    trivial_reason,
)
from server.runtimes.verification.tools.workspace_writer import WorkspaceWriter
from server.runtimes.verification.zip_pack import SUITE_ROOT_NAME

from .config import TestabilityProbeConfig
from .input_adapter import architecture_context_digest, load_probe_document
from .investigation import build_tools, run_investigation
from .llm_client import (
    LLMBudgetExhausted,
    extract_code,
    extract_json_object,
    load_prompt,
)
from .packaging import build_suite, resolve_suite_id
from .schemas import (
    PlannedVerification,
    ProbeRequest,
    ProbeResult,
    ValidationRecord,
    VerificationPlanItem,
    VerificationResult,
)
from .state import TestabilityProbeState

_EXCERPT_COMPONENT = 18_000
_EXCERPT_EVIDENCE = 1_500
_EXCERPT_TOTAL = 20_000

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class BudgetExhausted(Exception):
    """An LLM or tool-call budget was reached; the run degrades, it never fabricates."""


def _slug(text: str, *, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return (slug or fallback)[:48]


def _repo_layout(root: str | None, *, max_dirs: int = 40, max_files_per_dir: int = 12) -> str:
    if not root:
        return ""
    lines: list[str] = []
    root_path = Path(root)
    count = 0
    for current_dir, dirs, files in __import__("os").walk(root_path):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in {"node_modules", "__pycache__"})
        relative = Path(current_dir).relative_to(root_path).as_posix()
        if any(part.startswith(".") or part in {"node_modules", "__pycache__", ".venv"} for part in Path(relative).parts):
            dirs[:] = []
            continue
        file_names = sorted(files)[:max_files_per_dir]
        if file_names:
            lines.append(f"{relative}/: {', '.join(file_names)}")
            count += 1
        if count >= max_dirs:
            break
    return "\n".join(lines)


def _read_excerpt(root: str, rel_path: str, max_chars: int) -> str | None:
    candidate = (Path(root) / rel_path).resolve()
    try:
        candidate.relative_to(Path(root).resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    try:
        data = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return data[:max_chars]


def _evidence_excerpts(run_root: str, finding, *, max_entries: int = 6) -> str:
    chunks: list[str] = []
    for evidence in (finding.evidence or [])[:max_entries]:
        if not evidence.path:
            continue
        try:
            text = _read_excerpt(run_root, evidence.path, _EXCERPT_EVIDENCE * 4)
        except Exception:  # noqa: BLE001 - unreadable evidence degrades to a note, never to fabricated content
            text = None
        if text is None:
            chunks.append(f"# {evidence.path}: unreadable")
            continue
        lines = text.splitlines()
        start = max(1, evidence.start_line or 1)
        end = min(len(lines), evidence.end_line or len(lines))
        excerpt = "\n".join(lines[start - 1:end])[:_EXCERPT_EVIDENCE]
        chunks.append(f"# {evidence.path}:{start}-{end}\n{excerpt}")
    return "\n\n".join(chunks)


class TestabilityProbeExecution:
    """Builds the generation graph; owns tool wiring and budgets."""

    def __init__(self, config: TestabilityProbeConfig | None = None, llm_client=None):
        self.config = config or TestabilityProbeConfig()
        self.llm_client = llm_client
        self._audit_log: AuditLog | None = None
        self.graph = self._build_graph()

    # ------------------------------------------------------------- utilities
    def _resolve_output(self, request: ProbeRequest, repository_id: str, suite_id: str) -> Path:
        output = Path(request.output_path)
        if output.suffix == ".zip":
            return output
        slug = _slug(repository_id or "repo", fallback="repo")
        return output / f"{slug}-{suite_id}.zip"

    def _open_log(self, state: TestabilityProbeState) -> AuditLog | None:
        try:
            return self._open_log_inner(state)
        except Exception:  # noqa: BLE001 - telemetry must never fail the pipeline
            return None

    def _open_log_inner(self, state: TestabilityProbeState) -> AuditLog | None:
        request = state.get("request")
        if request is None:
            return None
        repository_id = state["document"].repository_id if state.get("document") else "unknown"
        output = Path(request.output_path)
        if output.suffix == ".zip":
            output = output.parent
        output.mkdir(parents=True, exist_ok=True)
        log_path = output / f"probe-{_slug(repository_id)}-{int(time.time())}-execution-log.jsonl"
        self._audit_log = AuditLog(log_path, truncate=True)
        state["log_path"] = str(log_path)
        return self._audit_log

    def _log(self, state: TestabilityProbeState, kind: str, **fields) -> None:
        log = self._open_log(state)
        if log is not None:
            log.record(kind, **fields)

    def _charge_tool_call(self, state: TestabilityProbeState, candidate: dict | None = None) -> None:
        state["tool_calls"] = state.get("tool_calls", 0) + 1
        if candidate is not None:
            candidate["tool_calls"] = candidate.get("tool_calls", 0) + 1
            if candidate["tool_calls"] > self.config.max_tool_calls_per_verification:
                raise BudgetExhausted(f"Verification {candidate['verification_id']} exceeded the tool-call budget.")

    def _note_llm(self, state: TestabilityProbeState, client) -> None:
        state["llm_calls"] = state.get("llm_calls", 0) + 1
        state["llm_tokens"] = getattr(client, "used_tokens", None)

    # ----------------------------------------------------------------- nodes
    def prepare_input(self, state: TestabilityProbeState):
        request = state["request"]
        limitations: list[str] = []
        warnings: list[str] = []
        errors: list[str] = []
        document, diagnostics = load_probe_document(request.findings_path)
        limitations.extend(diagnostics.limitations)
        warnings.extend(diagnostics.warnings)
        errors.extend(diagnostics.errors)
        merged: dict = {
            "document": document,
            "diagnostics": diagnostics,
            "limitations": limitations,
            "warnings": warnings,
            "errors": errors,
            "tool_calls": 0,
            "llm_calls": 0,
            "llm_tokens": None,
            "architecture_digest": architecture_context_digest(request.architecture_context_path),
        }
        repo_path = request.repo_path
        if repo_path is None or not Path(repo_path).is_dir():
            merged["errors"] = [*errors, f"Repository checkout not found: {repo_path}. --repo is required."]
            diagnostics.errors.append(merged["errors"][-1])
            merged["result"] = self._early_result({**state, **merged}, "input_invalid")
            return merged
        if document is not None:
            baseline_available, baseline_limits = check_checkout(repo_path, document.commit) if document.commit else (False, ["The findings document carries no commit; baseline validation is unavailable."])
            merged["baseline_available"] = baseline_available
            merged["limitations"] = [*merged["limitations"], *baseline_limits]
        if not diagnostics.ok:
            merged["result"] = self._early_result({**state, **merged}, "input_invalid")
            return merged
        # Disposable copy: investigations and pytest run here; the audited checkout is never modified.
        if document is not None and document.findings:
            try:
                temp_dir = Path(tempfile.mkdtemp(prefix="tallercito-probe-baseline-"))
                copy_repository(Path(repo_path), temp_dir, max_files=self.config.max_repo_copy_files,
                                max_bytes=self.config.max_repo_copy_bytes)
                merged["run_root"] = str(temp_dir)
            except Exception as error:  # noqa: BLE001 - blocked copy degrades honestly
                merged["limitations"] = [*merged["limitations"],
                                         f"Could not create the disposable repository copy ({error}); tests will not execute."]
                merged["run_root"] = None
        else:
            merged["run_root"] = None
        # Optional green control: a corrected checkout, used only as a counter-example workspace.
        green_dir = request.green_control_dir or self.config.green_control_dir
        if green_dir:
            try:
                temp_dir = Path(tempfile.mkdtemp(prefix="tallercito-probe-green-"))
                copy_repository(Path(green_dir), temp_dir, max_files=self.config.max_repo_copy_files,
                                max_bytes=self.config.max_repo_copy_bytes)
                merged["green_root"] = str(temp_dir)
            except Exception as error:  # noqa: BLE001
                merged["green_root"] = None
                merged["limitations"] = [*merged["limitations"],
                                         f"Green control unavailable ({error}); GREEN validation will be reported as not performed."]
        self._log({**state, **merged}, "prepare_input", ok=diagnostics.ok,
                  findings=len(document.findings) if document else 0,
                  commit=document.commit if document else None)
        return merged

    async def plan_verifications(self, state: TestabilityProbeState):
        if state.get("result") is not None:
            return {}
        document = state["document"]
        limitations = list(state.get("limitations", []))
        repo_layout = _repo_layout(state.get("run_root") or state["request"].repo_path)
        plans: list[PlannedVerification] = []
        sequence = 0
        budget_exhausted = False
        for finding in document.findings:
            if budget_exhausted or self.llm_client is None:
                limitations.append(f"{finding.id}: planning skipped (LLM budget exhausted or LLM unavailable).")
                continue
            prompt = (load_prompt("plan_verification.md")
                      .replace("__FINDING_JSON__", finding.model_dump_json(indent=2))
                      .replace("__ARCHITECTURE_DIGEST__", state.get("architecture_digest") or "(none)")
                      .replace("__REPO_LAYOUT__", repo_layout or "(unavailable)"))
            source_root = state.get("run_root") or state["request"].repo_path
            language = node_runtime.language_for(finding.components)
            if language != "python":
                prompt = prompt.replace(
                    "Python is the only guaranteed language/runtime here; prefer pytest.",
                    "Node/TypeScript is supported: use vitest for TS/TSX, React DOM and real imports; "
                    "node:test for standalone .mjs checks. Return framework='vitest' or 'node:test'.")
            prompt += (
                f"\nDetected component language: {language}. The layout above is TRUNCATED, not a file inventory. "
                "Never infer absence from it. These are independently read actual component contents:\n"
                + self._preloaded_context(source_root, finding, finding.components))
            try:
                reply = await self.llm_client.complete("plan", prompt)
                self._note_llm(state, self.llm_client)
            except LLMBudgetExhausted as error:
                limitations.append(f"LLM budget exhausted during planning: {error}")
                budget_exhausted = True
                continue
            except Exception as error:  # noqa: BLE001 - planning may fail per finding; never invent
                limitations.append(f"{finding.id}: planning failed ({type(error).__name__}: {error}); no verification planned for this finding.")
                self._log(state, "plan_failed", finding_id=finding.id, error=str(error))
                continue
            try:
                payload = extract_json_object(reply)
            except Exception as error:  # noqa: BLE001 - malformed plans are rejected per finding, never guessed
                self._persist(state, f"planning-{_slug(finding.id)}-invalid.json", {"reply": reply, "error": str(error)})
                try:
                    reply = await self.llm_client.complete("plan", prompt + (
                        "\nYour previous response was invalid JSON: " + str(error)
                        + "\nRegenerate the plan as strict JSON. Escape backslashes and newlines in strings. "
                        "Do not omit this finding because of the serialization error."))
                    self._note_llm(state, self.llm_client)
                    payload = extract_json_object(reply)
                except Exception as retry_error:  # noqa: BLE001 - preserve a failed plan without fabricating tests
                    limitations.append(f"{finding.id}: planning JSON repair failed ({retry_error}); generation failed for this finding.")
                    continue
            items = payload.get("verifications") or []
            notes = payload.get("notes") or []
            if not items:
                limitations.append(f"{finding.id}: no verification planned{' (' + '; '.join(map(str, notes)) + ')' if notes else ''}; recorded as not verifiable from the given evidence.")
                self._log(state, "plan_not_verifiable", finding_id=finding.id, notes=notes)
                continue
            existing_names = {plan.test_name for plan in plans}
            for item in items:
                try:
                    parsed = VerificationPlanItem.model_validate(item)
                except Exception as error:  # noqa: BLE001 - one bad item does not sink the finding
                    limitations.append(f"{finding.id}: a planned verification was rejected ({error}).")
                    continue
                sequence += 1
                verification_id = f"probe-{sequence:03d}"
                test_name = parsed.test_name if _IDENTIFIER_RE.match(parsed.test_name or "") else ""
                if not test_name:
                    test_name = f"test_{_slug(parsed.condition or parsed.title or finding.id)}_{sequence}"
                base_name = test_name
                serial = 2
                while test_name in existing_names:
                    test_name = f"{base_name}_{serial}"
                    serial += 1
                existing_names.add(test_name)
                file_slug = _slug(finding.id)
                framework = parsed.framework or ("pytest" if language == "python" else "vitest")
                if language != "python" and framework == "pytest":
                    framework = "vitest"
                extension = ".py" if framework == "pytest" else ".test.mjs" if framework == "node:test" else ".test.tsx"
                plans.append(PlannedVerification(
                    verification_id=verification_id,
                    finding_id=finding.id,
                    title=parsed.title or finding.title,
                    condition=parsed.condition or parsed.title or finding.description[:200],
                    strategy=parsed.strategy,
                    target_components=parsed.target_components or list(finding.components),
                    property=parsed.property or parsed.condition or finding.description[:300],
                    scenarios=parsed.scenarios or ["default scenario from the finding"],
                    violation_oracle=parsed.violation_oracle or "the denounced condition is present",
                    fixed_oracle=parsed.fixed_oracle or "the denounced condition is not observed within the declared scope",
                    limits=parsed.limits,
                    test_path=f"tests/test_{file_slug}_{sequence}{extension}",
                    test_name=test_name,
                    evidence_refs=list(finding.evidence_ids),
                    language=language, framework=framework,
                ))
        self._persist(state, "plans.json", [plan.model_dump() for plan in plans])
        return {"plans": plans, "limitations": limitations,
                "llm_calls": state.get("llm_calls", 0), "llm_tokens": state.get("llm_tokens"),
                "budget_exhausted": budget_exhausted}

    async def investigate(self, state: TestabilityProbeState):
        if state.get("result") is not None:
            return {}
        document = state["document"]
        run_root = state.get("run_root")
        notes: dict[str, str] = {}
        limitations = list(state.get("limitations", []))
        plans_by_finding: dict[str, list[PlannedVerification]] = {}
        for plan in state.get("plans", []):
            plans_by_finding.setdefault(plan.finding_id, []).append(plan)
        if state.get("budget_exhausted"):
            limitations.append("Investigation skipped: the LLM budget is exhausted.")
            return {"investigation_notes": {}, "limitations": limitations}
        if not plans_by_finding:
            return {"investigation_notes": {}}
        if run_root is None:
            limitations.append("Investigation skipped: no disposable repository copy is available.")
            return {"investigation_notes": {}, "limitations": limitations}
        reader = RepoReader(run_root, max_read_bytes_per_file=self.config.max_read_bytes_per_file,
                            max_files_read=self.config.max_files_read)
        searcher = CodeSearch(run_root)
        for finding in document.findings:
            finding_plans = plans_by_finding.get(finding.id)
            if not finding_plans:
                continue
            if self.llm_client is None:
                limitations.append(f"{finding.id}: investigation skipped (LLM unavailable); generation relies on preloaded evidence only.")
                notes[finding.id] = "(investigation unavailable: LLM client missing)"
                continue
            plan_json = json.dumps([plan.model_dump() for plan in finding_plans], ensure_ascii=False, indent=2)
            preloaded = self._preloaded_context(run_root, finding, finding_plans[0].target_components)
            prompt = (load_prompt("investigate_context.md")
                      .replace("__MAX_ITERATIONS__", str(self.config.max_investigation_iterations))
                      .replace("__FINDING_JSON__", finding.model_dump_json(indent=2))
                      .replace("__PLAN_JSON__", plan_json)
                      .replace("__PRELOADED__", preloaded))
            counters = {"tool_calls": 0, "tools": [], "model_calls": 0}

            def _on_model_call(_response):
                pass

            chat_model = self.llm_client.chat() if hasattr(self.llm_client, "chat") else None
            if chat_model is None:
                notes[finding.id] = f"(no tool loop; preloaded context only){preloaded[:2400]}"
                continue
            try:
                tools = build_tools(reader, searcher, counters)
                final_text, counters = await run_investigation(
                    chat_model, tools, prompt,
                    max_iterations=self.config.max_investigation_iterations,
                    on_model_call=_on_model_call,
                    counters=counters,
                )
                state["llm_calls"] = state.get("llm_calls", 0) + counters["model_calls"]
                state["tool_calls"] = state.get("tool_calls", 0) + counters["tool_calls"]
                state["llm_tokens"] = getattr(self.llm_client, "used_tokens", None)
                notes[finding.id] = (final_text or "").strip()[:4000] or "(investigation produced no fact pack)"
                self._log(state, "investigation", finding_id=finding.id, model_calls=counters["model_calls"],
                          tool_calls=counters["tool_calls"])
            except LLMBudgetExhausted as error:
                limitations.append(f"LLM budget exhausted during investigation of {finding.id}: {error}")
                state["budget_exhausted"] = True
                notes[finding.id] = "(investigation truncated: LLM budget exhausted)"
            except Exception as error:  # noqa: BLE001 - investigation degrades to preloaded context
                limitations.append(f"{finding.id}: investigation failed ({type(error).__name__}: {error}); generation relies on preloaded evidence.")
                notes[finding.id] = f"(investigation failed: {error}){preloaded[:2400]}"
        return {"investigation_notes": notes, "limitations": limitations,
                "tool_calls": state.get("tool_calls", 0),
                "llm_calls": state.get("llm_calls", 0),
                "llm_tokens": state.get("llm_tokens")}

    def _preloaded_context(self, run_root: str, finding, components: list[str]) -> str:
        budget = _EXCERPT_TOTAL
        chunks: list[str] = []
        evidence = _evidence_excerpts(run_root, finding)
        if evidence:
            chunks.append("## Evidence excerpts\n" + evidence)
            budget -= len(evidence)
        components = list(dict.fromkeys([*(components or []), *finding.components]))
        for component in components[:4]:
            if budget <= 600:
                break
            excerpt = _read_excerpt(run_root, component, min(_EXCERPT_COMPONENT, budget))
            if excerpt is None:
                chunks.append(f"## {component}: not readable")
                continue
            chunks.append(f"## {component}\n{excerpt}")
            budget -= len(chunks[-1])
        return "\n\n".join(chunks)

    def _python_structure_context(self, run_root: str, components: list[str], focus: str = "") -> str:
        """Compiler-derived facts for repairing source predicates, not finding verdicts."""
        chunks: list[str] = []
        for component in components[:4]:
            if Path(component).suffix != ".py":
                continue
            source = _read_excerpt(run_root, component, self.config.max_read_bytes_per_file)
            if source is None:
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            scopes = [node for node in ast.walk(tree)
                      if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                      and re.search(rf"\b{re.escape(node.name)}\b", focus)]
            # The usual head excerpt can omit the method under test in a long
            # file. Supply its real source, not an inference from missing text.
            for scope in sorted(scopes, key=lambda node: (node.end_lineno or node.lineno) - node.lineno):
                chunks.append(f"## Actual source: {component}:{scope.lineno} ({scope.name})\n"
                              + (ast.get_source_segment(source, scope) or "")[:3200])
            chunks.append(f"## Python assignment target ASTs: {component}")
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    chunks.append(f"line {node.lineno}: " + "; ".join(ast.dump(t) for t in targets))
        return "\n".join(chunks)[:4500]

    async def generate(self, state: TestabilityProbeState):
        if state.get("result") is not None:
            return {}
        document = state["document"]
        run_root = state.get("run_root")
        limitations = list(state.get("limitations", []))
        findings = {finding.id: finding for finding in document.findings}
        notes = state.get("investigation_notes", {})
        candidates: list[dict] = []
        for plan in state.get("plans", []):
            finding = findings[plan.finding_id]
            if state.get("budget_exhausted"):
                limitations.append(f"{plan.verification_id}: generation skipped (LLM budget exhausted).")
                candidate = self._candidate(plan, None, generated_by="none", detail="LLM budget exhausted")
                candidates.append(candidate)
                continue
            prompt = self._generation_prompt(state, plan, finding, findings, notes, run_root)
            try:
                reply = await self.llm_client.complete("generate", prompt)
                self._note_llm(state, self.llm_client)
            except LLMBudgetExhausted as error:
                limitations.append(f"{plan.verification_id}: LLM budget exhausted during generation: {error}")
                state["budget_exhausted"] = True
                candidates.append(self._candidate(plan, None, generated_by="none", detail=str(error)))
                continue
            except Exception as error:  # noqa: BLE001
                limitations.append(f"{plan.verification_id}: generation failed ({type(error).__name__}: {error}).")
                self._log(state, "generate_failed", verification_id=plan.verification_id, error=str(error))
                candidates.append(self._candidate(plan, None, generated_by="none", detail=str(error)))
                continue
            content = extract_code(reply)
            candidate = self._candidate(plan, content, generated_by="llm")
            try:
                flags = suspicion_flags(content, subject_tokens(
                    plan.target_components,
                    [dotted_module(c) for c in plan.target_components]))
            except Exception:  # noqa: BLE001 - advisory only
                flags = []
            if flags:
                candidate["suspicion"] = flags
                self._log(state, "suspicion", verification_id=plan.verification_id, flags=flags)
            candidates.append(candidate)
        self._log(state, "generate", candidates=len(candidates))
        return {"candidates": candidates, "limitations": limitations,
                "llm_calls": state.get("llm_calls", 0), "llm_tokens": state.get("llm_tokens"),
                "budget_exhausted": state.get("budget_exhausted", False)}

    @staticmethod
    def _candidate(plan: PlannedVerification, content: str | None, *, generated_by: str, detail: str = "") -> dict:
        return {"verification_id": plan.verification_id, "finding_id": plan.finding_id,
                "test_path": plan.test_path, "test_name": plan.test_name,
                "strategy": plan.strategy, "content": content, "framework": plan.framework,
                "tool_calls": 0, "generated_by": generated_by,
                "classification": None, "detail": detail, "attempts": 1,
                "verdict_key": None, "llm_verdict": None}

    def _generation_prompt(self, state: TestabilityProbeState, plan: PlannedVerification,
                           finding, findings, notes: dict[str, str], run_root: str | None,
                           *, restart: bool = False) -> str:
        preloaded = self._preloaded_context(run_root, finding, plan.target_components) if run_root else "(no repository copy available)"
        investigation_notes = notes.get(plan.finding_id, "(no fact pack)")
        excluded = {"violation_oracle", "fixed_oracle"}
        if restart:
            excluded |= {"property", "scenarios", "limits", "title"}
        return (load_prompt("generate_node_test.md" if plan.framework != "pytest" else "generate_test.md")
                .replace("__TEST_NAME__", plan.test_name)
                .replace("__PLAN_JSON__", plan.model_dump_json(
                    indent=2, exclude=excluded))
                .replace("__FINDING_JSON__", finding.model_dump_json(indent=2))
                .replace("__INVESTIGATION_NOTES__", investigation_notes)
                .replace("__PRELOADED__", preloaded + "\n" + (
                    self._python_structure_context(run_root, plan.target_components, plan.condition)
                    if run_root else "")))

    def _persist(self, state, name, payload):
        output = Path(state["request"].output_path)
        directory = output.parent if output.suffix == ".zip" else output
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _run_candidate(self, root, candidate, runner, state):
        if candidate.get("framework", "pytest") == "pytest":
            return runner.run_pytest(f"{SUITE_ROOT_NAME}/{candidate['test_path']}")
        from types import SimpleNamespace
        root = Path(root)
        if not (root / ".tallercito" / "node-install.json").is_file():
            receipt = node_runtime.prepare(root, self.config.install_timeout_seconds,
                                           self.config.auto_install_node_dependencies)
            self._persist(state, "node-install.json", receipt)
        observed = node_runtime.run(root, f".tallercito/{candidate['test_path']}", candidate["framework"],
                                    self.config.max_test_run_seconds)
        self._persist(state, f"{candidate['verification_id']}-attempt-{candidate.get('attempts', 1)}.json", observed)
        return SimpleNamespace(**observed)

    def execute_tests(self, state: TestabilityProbeState):
        if state.get("result") is not None:
            return {}
        candidates = list(state.get("candidates", []))
        limitations = list(state.get("limitations", []))
        run_root = state.get("run_root")
        outcomes: dict[str, str] = {}
        assertion_messages: dict[str, str | None] = {}
        for candidate in candidates:
            if not candidate.get("content"):
                candidate["classification"] = "not_generated" if candidate.get("generated_by") == "none" else CLASSIFICATION_TRIVIAL
                candidate["detail"] = candidate.get("detail") or "No test content was produced."
                outcomes[candidate["verification_id"]] = candidate["classification"]
                assertion_messages[candidate["verification_id"]] = None
                continue
            check_trivial = trivial_reason if candidate.get("framework", "pytest") == "pytest" else node_runtime.trivial_reason
            trivial = check_trivial(candidate["content"])
            if trivial:
                candidate["classification"] = CLASSIFICATION_TRIVIAL
                candidate["detail"] = f"Trivial test rejected before execution: {trivial}"
                outcomes[candidate["verification_id"]] = CLASSIFICATION_TRIVIAL
                assertion_messages[candidate["verification_id"]] = None
                continue
        executable = [c for c in candidates if c.get("content") and c["classification"] is None]
        if not self.config.allow_local_unsafe_execution:
            blocked = [c for c in candidates if c.get("content")]
            if blocked:
                blocked_limitations: list[str] = ["Test execution is disabled; results were not validated in this generation run."]
            else:
                blocked_limitations = []
            for candidate in candidates:
                if candidate.get("content") and candidate["classification"] is None:
                    candidate["classification"] = "environment_blocked"
                    candidate["detail"] = "Local execution is disabled (allow_local_unsafe_execution=False); the suite ships without in-loop validation."
                    outcomes[candidate["verification_id"]] = "environment_blocked"
                    assertion_messages[candidate["verification_id"]] = None
            return {"candidates": candidates, "outcomes": outcomes,
                    "assertion_messages": assertion_messages,
                    "limitations": [*limitations, *blocked_limitations]}
        if run_root is None:
            for candidate in candidates:
                if candidate.get("content") and candidate["classification"] is None:
                    candidate["classification"] = "execution_error"
                    candidate["detail"] = "No disposable repository copy available."
                    outcomes[candidate["verification_id"]] = "execution_error"
                    assertion_messages[candidate["verification_id"]] = None
            return {"candidates": candidates, "outcomes": outcomes, "assertion_messages": assertion_messages,
                    "limitations": limitations}
        writer = WorkspaceWriter(run_root, max_test_file_bytes=self.config.max_test_file_bytes,
                                 max_written_bytes=self.config.max_written_bytes)
        runner = WorkspaceRunner(Path(run_root), executor=LocalSubprocessExecutor(),
                                 timeout_seconds=self.config.max_test_run_seconds,
                                 max_output_bytes=self.config.max_captured_output_bytes)
        try:
            for candidate in executable:
                try:
                    self._charge_tool_call(state, candidate)
                    writer.write_test_file(f"{SUITE_ROOT_NAME}/{candidate['test_path']}", candidate["content"])
                except (PathSafetyError, BudgetExhausted) as error:
                    candidate["classification"] = "execution_error"
                    candidate["detail"] = str(error)
                    outcomes[candidate["verification_id"]] = "execution_error"
                    assertion_messages[candidate["verification_id"]] = None
                    continue
                try:
                    self._charge_tool_call(state, candidate)
                except BudgetExhausted as error:
                    candidate["classification"] = "execution_error"
                    candidate["detail"] = str(error)
                    outcomes[candidate["verification_id"]] = "execution_error"
                    assertion_messages[candidate["verification_id"]] = None
                    continue
                outcome = self._run_candidate(run_root, candidate, runner, state)
                candidate["classification"] = outcome.classification
                candidate["detail"] = outcome.detail
                candidate["assertion_message"] = (outcome.tests[0].get("message") if outcome.tests else None) or outcome.detail
                outcomes[candidate["verification_id"]] = outcome.classification
                assertion_messages[candidate["verification_id"]] = candidate["assertion_message"]
        except BudgetExhausted as error:
            limitations.append(f"Tool-call budget exhausted during execution: {error}")
            for candidate in candidates:
                if candidate["classification"] is None:
                    candidate["classification"] = "execution_error"
                    candidate["detail"] = str(error)
                    outcomes[candidate["verification_id"]] = "execution_error"
                    assertion_messages.setdefault(candidate["verification_id"], None)
        # GREEN control: same tests against the corrected checkout, when configured.
        green_outcomes: dict[str, str] = {}
        green_root = state.get("green_root")
        if green_root and self.config.allow_local_unsafe_execution:
            writer_g = WorkspaceWriter(green_root, max_test_file_bytes=self.config.max_test_file_bytes,
                                       max_written_bytes=self.config.max_written_bytes)
            runner_g = WorkspaceRunner(Path(green_root), executor=LocalSubprocessExecutor(),
                                       timeout_seconds=self.config.max_test_run_seconds,
                                       max_output_bytes=self.config.max_captured_output_bytes)
            for candidate in candidates:
                if candidate["classification"] == CLASSIFICATION_VIOLATION and candidate.get("content"):
                    try:
                        writer_g.write_test_file(f"{SUITE_ROOT_NAME}/{candidate['test_path']}", candidate["content"])
                        outcome = self._run_candidate(green_root, candidate, runner_g, state)
                        green_outcomes[candidate["verification_id"]] = outcome.classification
                    except Exception as error:  # noqa: BLE001
                        green_outcomes[candidate["verification_id"]] = "execution_error"
                        limitations.append(f"{candidate['verification_id']}: green control execution failed ({error})")
        self._log(state, "execute_tests", outcomes=outcomes, green=green_outcomes)
        return {"candidates": candidates, "outcomes": outcomes,
                "assertion_messages": assertion_messages, "green_outcomes": green_outcomes,
                "limitations": limitations,
                "tool_calls": state.get("tool_calls", 0)}

    async def evaluate(self, state: TestabilityProbeState):
        if state.get("result") is not None:
            return {}
        plans = {plan.verification_id: plan for plan in state.get("plans", [])}
        candidates = list(state.get("candidates", []))
        assertions = state.get("assertion_messages", {})
        green_outcomes = state.get("green_outcomes", {})
        limitations = list(state.get("limitations", []))
        results: list[VerificationResult] = []
        records: list[ValidationRecord] = []
        for candidate in candidates:
            vid = candidate["verification_id"]
            plan = plans[vid]
            classification = candidate.get("classification") or "execution_error"
            assert_message = assertions.get(vid) or candidate.get("assertion_message") or candidate.get("detail") or ""
            verdict_key = f"{classification}:{hashlib.sha1((candidate.get('content') or '').encode('utf-8')).hexdigest()}"
            cached = candidate.get("verdict_key") == verdict_key and candidate.get("llm_verdict")
            if classification in ("technical_failure", CLASSIFICATION_TIMEOUT, "execution_error", "environment_blocked", "not_generated"):
                outcome, llm_note = self._fallback_outcome(classification, assert_message)
            elif classification == CLASSIFICATION_TRIVIAL:
                outcome, llm_note = "invalid_test", "trivial test rejected before execution"
            elif classification == CLASSIFICATION_VIOLATION:
                if cached:
                    outcome, llm_note = candidate["llm_verdict"]["verdict"], candidate["llm_verdict"]["reason"]
                else:
                    outcome, llm_note = await self._llm_verdict(state, plan, candidate, classification, assert_message, limitations)
                    candidate["llm_verdict"] = {"verdict": outcome, "reason": llm_note}
                    candidate["verdict_key"] = verdict_key
            elif classification == CLASSIFICATION_PASS:
                # A RED-baseline passing test cannot discriminate presence from absence:
                # it is a weak or inverted (presence-asserting) oracle, so it is invalid
                # rather than evidence that the condition is gone.
                outcome, llm_note = "invalid_test", (
                    "Test passes at the violating baseline; its oracle cannot distinguish "
                    "the denounced condition from a corrected variant.")
            else:
                outcome, llm_note = "inconclusive", f"unclassified backend result: {classification}"
            candidate["outcome"] = outcome
            status = self._record_status(outcome, classification, green_outcomes.get(vid))
            detail = llm_note or classification
            results.append(VerificationResult(
                verification_id=vid,
                finding_id=candidate["finding_id"],
                condition=plan.condition,
                outcome=outcome,
                detail=str(detail)[:1000],
                assertion_message=(str(assert_message)[:1000] if assert_message else None),
                llm_assessment=(str(llm_note)[:1000] if llm_note else None),
                evidence_refs=list(plan.evidence_refs),
            ))
            records.append(ValidationRecord(
                verification_id=vid,
                finding_id=candidate["finding_id"],
                status=status,
                detail=f"{classification}: {str(assert_message)[:300]}" if assert_message else classification,
                attempts=candidate.get("attempts", 1),
            ))
            if outcome == "violation_present" and green_outcomes.get(vid) == CLASSIFICATION_PASS:
                limitations.append(f"{vid}: RED reproduced and GREEN confirmed at the green control checkout.")
            if outcome in ("invalid_test", "inconclusive"):
                limitations.append(f"{vid}: outcome={outcome}; the verification does not discriminate the denounced condition ({detail[:160]})")
        green_present = bool(green_outcomes)
        validation_status = self._validation_status(results, green_present)
        return {"candidates": candidates, "verification_results": results,
                "validation_records": records, "limitations": limitations,
                "validation_status": validation_status,
                "llm_calls": state.get("llm_calls", 0), "llm_tokens": state.get("llm_tokens")}

    @staticmethod
    def _fallback_outcome(classification: str, assert_message: str) -> tuple[str, str]:
        if classification == "environment_blocked":
            return "execution_error", "Local pytest execution was disabled; the suite was not executed in this run."
        if classification == "not_generated":
            return "not_verifiable", "No test content was produced for this verification."
        return "execution_error", f"{classification}: {assert_message[:200] or 'no diagnostic captured'}"

    async def _llm_verdict(self, state: TestabilityProbeState, plan: PlannedVerification, candidate: dict,
                           classification: str, assert_message: str, limitations: list[str]) -> tuple[str, str]:
        if self.llm_client is None:
            if classification == CLASSIFICATION_VIOLATION:
                return "violation_present", "LLM unavailable; RED classification taken from the backend oracle (AssertionError on the declared oracle)."
            return "inconclusive", "LLM unavailable and the backend reported no AssertionError-based violation."
        # Early plans may contain inverted executable oracle snippets. Assess the
        # actual condition and test, not conformity to an unvalidated snippet.
        prompt = (load_prompt("evaluate_outcome.md")
                  .replace("__PLAN_JSON__", plan.model_dump_json(
                      indent=2, exclude={"violation_oracle", "fixed_oracle"}))
                  .replace("__TEST_SOURCE__", (candidate.get("content") or "")[:12000])
                  .replace("__CLASSIFICATION__", classification)
                  .replace("__ASSERTION_MESSAGE__", (assert_message or "(empty)")[:2000]))
        try:
            reply = await self.llm_client.complete("evaluate", prompt)
            self._note_llm(state, self.llm_client)
            payload = extract_json_object(reply)
            verdict = str(payload.get("verdict", "")).strip().lower()
            if verdict not in {"violation_present", "invalid_test", "inconclusive"}:
                return "inconclusive", f"LLM returned an unrecognized verdict {verdict!r}; recorded as inconclusive."
            return verdict, str(payload.get("reason", "")).strip() or "(no reason supplied)"
        except LLMBudgetExhausted as error:
            limitations.append(f"{candidate['verification_id']}: LLM budget exhausted during evaluation: {error}")
            if classification == CLASSIFICATION_VIOLATION:
                return "violation_present", "LLM budget exhausted; RED classification taken from the backend oracle."
            return "inconclusive", "LLM budget exhausted before evaluation completed."
        except Exception as error:  # noqa: BLE001 - never invent an assessment
            limitations.append(f"{candidate['verification_id']}: LLM evaluation failed ({type(error).__name__}: {error}); falling back to the backend classification.")
            if classification == CLASSIFICATION_VIOLATION:
                return "violation_present", "LLM evaluation failed; RED classification taken from the backend oracle."
            return "inconclusive", "LLM evaluation failed; no reliable verdict."

    @staticmethod
    def _record_status(outcome: str, classification: str, green_classification: str | None) -> str:
        if outcome == "violation_present":
            return "validated_red_green" if green_classification == CLASSIFICATION_PASS else "validated_red"
        if outcome == "not_observed_within_scope":
            return "partially_validated"
        if outcome in ("invalid_test", "inconclusive"):
            return "invalid"
        if classification == "environment_blocked":
            return "environment_blocked"
        if outcome == "not_verifiable":
            return "not_generated"
        return "partially_validated"

    @staticmethod
    def _validation_status(results: list[VerificationResult], green_present: bool) -> str:
        if not results:
            return "not_applicable"
        outcomes = [item.outcome for item in results]
        if any(outcome == "invalid_test" for outcome in outcomes) and not any(
                outcome in {"violation_present", "not_observed_within_scope"} for outcome in outcomes):
            return "invalid"
        if any(outcome == "execution_error" for outcome in outcomes) and not any(
                outcome == "violation_present" for outcome in outcomes):
            return "environment_blocked" if all(outcome == "execution_error" for outcome in outcomes) else "partial"
        if green_present:
            if all(outcome in {"violation_present"} for outcome in outcomes):
                return "validated"
            return "partial"
        if all(outcome == "violation_present" for outcome in outcomes):
            return "validated"
        return "partial"

    async def repair(self, state: TestabilityProbeState):
        candidates = list(state.get("candidates", []))
        plans = {plan.verification_id: plan for plan in state.get("plans", [])}
        limitations = list(state.get("limitations", []))
        run_root = state.get("run_root")
        repaired = 0
        if run_root is None or not self.config.allow_local_unsafe_execution:
            return {"candidates": candidates, "limitations": limitations}
        writer = WorkspaceWriter(run_root, max_test_file_bytes=self.config.max_test_file_bytes,
                                 max_written_bytes=self.config.max_written_bytes)
        runner = WorkspaceRunner(Path(run_root), executor=LocalSubprocessExecutor(),
                                 timeout_seconds=self.config.max_test_run_seconds,
                                 max_output_bytes=self.config.max_captured_output_bytes)
        for candidate in candidates:
            vid = candidate["verification_id"]
            classification_now = candidate.get("classification")
            if not self._needs_repair(candidate):
                continue
            if candidate.get("generated_by") != "llm":
                continue
            if candidate.get("attempts", 1) > self.config.max_repairs_per_verification:
                continue
            plan = plans[vid]
            repair_prompt = load_prompt("repair_test.md")
            if plan.framework != "pytest":
                repair_prompt = ("Repair only this Node/TypeScript test using framework " + plan.framework
                                  + ". Preserve its intended property and test name; correct an inverted oracle. Never fix production. "
                                 "Return one TypeScript/JavaScript code fence.\n" + repair_prompt.replace(
                                     "```python", "```typescript"))
            prompt = (repair_prompt
                      .replace("__PLAN_JSON__", plan.model_dump_json(
                          indent=2, exclude={"violation_oracle", "fixed_oracle", "scenarios", "title", "limits"}))
                      .replace("__FINDING_JSON__", next(
                          f for f in state["document"].findings if f.id == plan.finding_id).model_dump_json(indent=2))
                      .replace("__TEST_SOURCE__", (candidate.get("content") or "")[:16000])
                      .replace("__FAILURE__", (
                          f"Backend classification: {classification_now}; evaluation: {candidate.get('outcome')}.\n"
                          + str(candidate.get("llm_verdict") or "") + "\n"
                          + (candidate.get("detail") or ""))[:4000])
                      .replace("__PRELOADED__", self._preloaded_context(
                          run_root, next(f for f in state["document"].findings if f.id == plan.finding_id),
                          plan.target_components) + "\n" + self._python_structure_context(
                              run_root, plan.target_components, plan.condition)))
            restart = (classification_now == CLASSIFICATION_TRIVIAL or (
                candidate.get("attempts", 1) >= 2
                and (classification_now == CLASSIFICATION_PASS
                     or candidate.get("outcome") in ("invalid_test", "inconclusive"))))
            if restart:
                # Repeated local edits can anchor the model to a fundamentally wrong
                # predicate. Re-author the same test from evidence, retaining its id
                # and history, but do not present the defective source as a template.
                findings = {finding.id: finding for finding in state["document"].findings}
                prompt = self._generation_prompt(
                    state, plan, findings[plan.finding_id], findings,
                    {}, run_root, restart=True)
                prompt += (
                    "\nREPAIR RESTART: previous revisions failed oracle validation. Re-author the SAME "
                    "test name and property from the actual source above, not a parameter-count heuristic. "
                    "Never skip or xfail. Missing subject is an explicit execution error. "
                    "Fix the executable predicate, not merely its documentation.\n"
                    f"Previous classification: {classification_now}; outcome: {candidate.get('outcome')}.\n"
                    "Do not reuse earlier test code or plan tactics. Use exactly these real target paths: "
                    + json.dumps(plan.target_components) + "\n"
                    + self._python_structure_context(run_root, plan.target_components, plan.condition))
            try:
                reply = await self.llm_client.complete("repair", prompt)
                self._note_llm(state, self.llm_client)
            except LLMBudgetExhausted as error:
                limitations.append(f"{vid}: LLM budget exhausted during repair: {error}")
                break
            except Exception as error:  # noqa: BLE001
                limitations.append(f"{vid}: repair failed ({type(error).__name__}: {error}); the diagnostic is preserved.")
                candidate.setdefault("history", []).append({
                    "attempt": candidate.get("attempts", 1),
                    "content": candidate.get("content"), "classification": classification_now,
                    "outcome": candidate.get("outcome"),
                    "repair_mode": "regenerate" if restart else "edit",
                    "repair_error": f"{type(error).__name__}: {error}",
                })
                candidate["attempts"] = candidate.get("attempts", 1) + 1
                continue
            content = extract_code(reply)
            candidate["attempts"] = candidate.get("attempts", 1) + 1
            candidate.setdefault("history", []).append({
                "attempt": candidate["attempts"] - 1,
                "content": candidate.get("content"),
                "classification": classification_now,
                "outcome": candidate.get("outcome"),
                "repair_mode": "regenerate" if restart else "edit",
                "detail": candidate.get("detail"),
            })
            candidate["content"] = content
            candidate["verdict_key"] = None
            try:
                self._charge_tool_call(state, candidate)
                writer.write_test_file(f"{SUITE_ROOT_NAME}/{candidate['test_path']}", content)
            except (PathSafetyError, BudgetExhausted) as error:
                candidate["classification"] = "execution_error"
                candidate["detail"] = f"Repaired test could not be written: {error}"
                continue
            invalid = (trivial_reason(content) if plan.framework == "pytest" else node_runtime.trivial_reason(content))
            if invalid:
                candidate["classification"] = CLASSIFICATION_TRIVIAL
                candidate["detail"] = invalid
                continue
            outcome = self._run_candidate(run_root, candidate, runner, state)
            candidate["classification"] = outcome.classification
            candidate["detail"] = outcome.detail
            candidate["assertion_message"] = (outcome.tests[0].get("message") if outcome.tests else None) or outcome.detail
            state["outcomes"] = {**(state.get("outcomes") or {}), vid: outcome.classification}
            state["assertion_messages"] = {**(state.get("assertion_messages") or {}), vid: candidate["assertion_message"]}
            green_root = state.get("green_root")
            if green_root:
                # Never reuse a control result measured on an older test revision.
                green = dict(state.get("green_outcomes") or {})
                green[vid] = "execution_error"
                try:
                    green_writer = WorkspaceWriter(green_root, max_test_file_bytes=self.config.max_test_file_bytes,
                                                   max_written_bytes=self.config.max_written_bytes)
                    green_writer.write_test_file(f"{SUITE_ROOT_NAME}/{candidate['test_path']}", content)
                    green_runner = WorkspaceRunner(Path(green_root), executor=LocalSubprocessExecutor(),
                                                   timeout_seconds=self.config.max_test_run_seconds,
                                                   max_output_bytes=self.config.max_captured_output_bytes)
                    green[vid] = self._run_candidate(green_root, candidate, green_runner, state).classification
                except (PathSafetyError, BudgetExhausted, OSError) as error:
                    limitations.append(f"{vid}: repaired GREEN control failed ({error}).")
                state["green_outcomes"] = green
            repaired += 1
        if repaired:
            self._log(state, "repair", repaired=repaired)
        return {"candidates": candidates, "outcomes": state.get("outcomes"),
                "green_outcomes": state.get("green_outcomes", {}),
                "assertion_messages": state.get("assertion_messages"),
                "limitations": limitations,
                "tool_calls": state.get("tool_calls", 0),
                "llm_calls": state.get("llm_calls", 0), "llm_tokens": state.get("llm_tokens")}

    def finalize(self, state: TestabilityProbeState):
        if state.get("result") is not None:
            return {}
        request = state["request"]
        document = state.get("document")
        plans: list[PlannedVerification] = state.get("plans", [])
        candidates: list[dict] = state.get("candidates", [])
        results: list[VerificationResult] = state.get("verification_results", [])
        records: list[ValidationRecord] = state.get("validation_records", [])
        limitations = list(dict.fromkeys(state.get("limitations", [])))
        repository_id = (document.repository_id if document else "") or "unknown"
        source_commit = (document.commit if document else "") or ""
        audit_id = request.audit_id
        if not audit_id:
            if repository_id and repository_id != "repository":
                audit_id = repository_id
            elif request.repo_path:
                audit_id = Path(request.repo_path).parent.name or repository_id
            else:
                audit_id = repository_id
        suite_id = resolve_suite_id(audit_id)
        zip_path = self._resolve_output(request, audit_id, suite_id)
        validation_status = state.get("validation_status") or ("not_applicable" if not plans else "partial")
        if not self.config.allow_local_unsafe_execution and plans:
            validation_status = "environment_blocked"
        # Not discriminating the condition, or never generated => must not ship.
        planned_total = len(plans)
        # Keep failed tests for diagnosis and further repair; only missing code
        # cannot be included as an executable module.
        non_shipping = {plan.verification_id for plan in plans
                         if not any(candidate["verification_id"] == plan.verification_id and candidate.get("content")
                                    for candidate in candidates)}
        if non_shipping:
            limitations = [*limitations,
                           "Not shipped (not discriminating the condition or never generated): "
                           + ", ".join(sorted(non_shipping))]
            plans = [plan for plan in plans if plan.verification_id not in non_shipping]
            candidates = [candidate for candidate in candidates if candidate["verification_id"] not in non_shipping]
        findings_count = len(document.findings) if document else 0
        termination = "no_findings" if findings_count == 0 else "suite_packaged"
        repaired = sum(1 for candidate in candidates if candidate.get("attempts", 1) > 1)
        metrics = {
            "findings": findings_count,
            "planned_verifications": planned_total,
            "shipped_verifications": len(plans),
            "generated_tests": sum(1 for candidate in candidates if candidate.get("content")),
            "executed_tests": sum(1 for candidate in candidates if candidate.get("classification") not in (None, "environment_blocked", "not_generated")),
            "repairs": repaired,
            "llm_calls": state.get("llm_calls", 0),
            "llm_tokens": state.get("llm_tokens"),
            "tool_calls": state.get("tool_calls", 0),
            "violation_present": sum(1 for item in results if item.outcome == "violation_present"),
            "not_observed_within_scope": sum(1 for item in results if item.outcome == "not_observed_within_scope"),
            "execution_error": sum(1 for item in results if item.outcome == "execution_error"),
            "inconclusive": sum(1 for item in results if item.outcome == "inconclusive"),
            "invalid_test": sum(1 for item in results if item.outcome == "invalid_test"),
            "green_validated": sum(1 for record in records if record.status == "validated_red_green"),
        }
        self._persist(state, "candidates.json", state.get("candidates", []))
        _, zip_path = build_suite(document, plans, candidates, records, limitations,
                                  zip_path, suite_id=suite_id, audit_id=audit_id, results=results)
        self._log(state, "finalize", termination_reason=termination, zip=str(zip_path),
                  validation_status=validation_status)
        result = ProbeResult(
            ok=True,
            termination_reason=termination,
            output_zip=str(zip_path),
            suite_id=suite_id,
            source_commit=source_commit or None,
            repository_id=audit_id,
            total_findings=findings_count,
            verifications=results,
            validation_records=records,
            validation_status=validation_status,
            metrics=metrics,
            limitations=limitations,
            warnings=state.get("warnings", []),
            errors=state.get("errors", []),
        )
        return {"result": result, "validation_status": validation_status}

    @staticmethod
    def _early_result(state: TestabilityProbeState, reason: str) -> ProbeResult:
        document = state.get("document")
        findings = len(document.findings) if document else 0
        return ProbeResult(
            ok=False,
            termination_reason=reason,
            source_commit=(document.commit if document else None),
            repository_id=(document.repository_id if document else "") or "",
            total_findings=findings,
            validation_status="not_run",
            metrics={},
            limitations=list(state.get("limitations", [])),
            warnings=list(state.get("warnings", [])),
            errors=list(state.get("errors", [])),
        )

    # --------------------------------------------------------------- routing
    @staticmethod
    def _needs_repair(candidate: dict) -> bool:
        return (candidate.get("classification") in (
            CLASSIFICATION_TECHNICAL, CLASSIFICATION_TIMEOUT,
            CLASSIFICATION_PASS, CLASSIFICATION_TRIVIAL, "execution_error")
            or candidate.get("outcome") in ("invalid_test", "inconclusive"))

    def _route_prepared(self, state: TestabilityProbeState) -> str:
        return "deliver" if state.get("result") is not None else "plan_verifications"

    def _route_evaluated(self, state: TestabilityProbeState) -> str:
        if not self.config.allow_local_unsafe_execution or state.get("run_root") is None:
            return "finalize"
        for candidate in state.get("candidates", []):
            if (self._needs_repair(candidate)
                    and candidate.get("generated_by") == "llm"
                    and candidate.get("attempts", 1) <= self.config.max_repairs_per_verification
                    and candidate.get("content")):
                return "repair"
        return "finalize"

    def _build_graph(self):
        graph = StateGraph(TestabilityProbeState)
        graph.add_node("prepare_input", phase_node("prepare_input", self.prepare_input))
        graph.add_node("plan_verifications", phase_node("plan_verifications", self.plan_verifications))
        graph.add_node("investigate", phase_node("investigate", self.investigate))
        graph.add_node("generate", phase_node("generate", self.generate))
        graph.add_node("execute_tests", phase_node("execute_tests", self.execute_tests))
        graph.add_node("evaluate", phase_node("evaluate", self.evaluate))
        graph.add_node("repair", phase_node("repair", self.repair))
        graph.add_node("finalize", phase_node("finalize", self.finalize))
        graph.add_edge(START, "prepare_input")
        graph.add_conditional_edges("prepare_input", self._route_prepared,
                                    {"plan_verifications": "plan_verifications", "deliver": END})
        graph.add_edge("plan_verifications", "investigate")
        graph.add_edge("investigate", "generate")
        graph.add_edge("generate", "execute_tests")
        graph.add_edge("execute_tests", "evaluate")
        graph.add_conditional_edges("evaluate", self._route_evaluated,
                                    {"repair": "repair", "finalize": "finalize"})
        graph.add_edge("repair", "evaluate")
        graph.add_edge("finalize", END)
        return graph.compile()
