"""LangGraph orchestration for the finding-test generation cycle.

Pipeline: prepare_input -> plan_tests -> generate_tests -> execute_tests ->
repair -> execute_tests(again) -> evaluate_results -> package_suite. LLM
participation, when enabled via ``--llm provider``, authors the verification
tests from the declared property; failures are reported and tests are
repaired within the configured per-verification budget. Every unit of work
is accounted in the audit log and the tool-call budgets; unrecovered
candidates degrade to EXECUTION_ERROR honestly.
"""

import tempfile
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from server.runtimes.invocation_reporting import phase_node
from server.runtimes.verification.tools.audit_log import AuditLog
from server.runtimes.verification.tools.package_discovery import dotted_module
from server.runtimes.verification.tools.repo_copy import copy_repository
from server.runtimes.verification.tools.repo_reader import PathSafetyError
from server.runtimes.verification.tools.sandbox import LocalSubprocessExecutor
from server.runtimes.verification.tools.suspicion import subject_tokens, suspicion_flags
from server.runtimes.verification.tools.test_runner import (
    CLASSIFICATION_ERROR,
    CLASSIFICATION_PASS,
    CLASSIFICATION_TECHNICAL,
    CLASSIFICATION_TIMEOUT,
    CLASSIFICATION_TRIVIAL,
    CLASSIFICATION_VIOLATION,
    WorkspaceRunner,
    trivial_reason,
)
from server.runtimes.verification.tools.workspace_writer import WorkspaceWriter

from .config import FindingTestConfig
from .input_adapter import check_checkout, load_audit_document
from .packaging import build_suite
from .planning import plan_verifications
from .schemas import (
    FindingTestGenerationRequest,
    FindingTestGenerationResult,
    ValidationRecord,
    VerificationResult,
    VerificationSpec,
)
from .selector import select_boundary_verification
from .state import FindingTestGenerationState
from .test_templates import render_helper, render_test_file


class BudgetExhausted(Exception):
    pass



class FindingTestGenerationExecution:
    """Builds the generation graph; owns tool wiring and budgets."""

    def __init__(self, config: FindingTestConfig | None = None, llm_client=None):
        self.config = config or FindingTestConfig()
        self.llm_client = llm_client
        self._audit_log: AuditLog | None = None
        self.graph = self._build_graph()

    # ------------------------------------------------------------- utilities
    def _resolve_output(self, request: FindingTestGenerationRequest, audit_id: int) -> Path:
        output = Path(request.output_path)
        return output if output.suffix == ".zip" else output / f"audit-{audit_id}-verification-suite.zip"

    def _open_log(self, state: FindingTestGenerationState) -> AuditLog | None:
        if self._audit_log is not None:
            return self._audit_log
        try:
            return self._open_log_inner(state)
        except Exception:  # noqa: BLE001 - telemetry must never fail the pipeline
            return None

    def _open_log_inner(self, state: FindingTestGenerationState) -> AuditLog | None:
        import time

        request = state.get("request")
        audit_id = state["document"].audit_id if state.get("document") else 0
        if request is None:
            return None
        zip_path = self._resolve_output(request, audit_id)
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        log_path = zip_path.parent / f"audit-{audit_id}-{int(time.time())}-generation-log.jsonl"
        self._audit_log = AuditLog(log_path, truncate=True)
        state["log_path"] = str(log_path)
        return self._audit_log

    def _log(self, state: FindingTestGenerationState, kind: str, **fields) -> None:
        log = self._open_log(state)
        if log is not None:
            log.record(kind, **fields)

    def _charge_tool_call(self, state: FindingTestGenerationState, candidate: dict | None = None) -> None:
        used = state.get("tool_calls", 0) + 1
        state["tool_calls"] = used
        if candidate is not None:
            candidate["tool_calls"] = candidate.get("tool_calls", 0) + 1
            if candidate["tool_calls"] > self.config.max_tool_calls_per_verification:
                raise BudgetExhausted(f"Verification {candidate['verification_id']} exceeded the tool-call budget.")

    # ----------------------------------------------------------------- nodes
    def prepare_input(self, state: FindingTestGenerationState):
        request = state["request"]
        document, diagnostics = load_audit_document(request.findings_path)
        limitations = list(diagnostics.limitations)
        warnings = list(diagnostics.warnings)
        errors = list(diagnostics.errors)
        baseline_available = False
        if document is not None:
            baseline_available, baseline_limits = check_checkout(request.repo_path, document.commit_hash)
            limitations.extend(baseline_limits)
        merged = {
            "document": document,
            "diagnostics": diagnostics,
            "limitations": limitations,
            "warnings": warnings,
            "errors": errors,
            "baseline_available": baseline_available,
            "tool_calls": 0,
            "llm_calls": 0,
            "llm_tokens": None,
        }
        if not diagnostics.ok:
            merged["result"] = self._early_result({**state, **merged}, "input_invalid")
        self._log({**state, **merged}, "prepare_input", ok=diagnostics.ok,
                  findings=len(document.findings) if document else 0)
        return merged

    def plan_tests(self, state: FindingTestGenerationState):
        if state.get("result") is not None:
            return {}
        specs, not_verifiable = plan_verifications(state["document"], llm=self.llm_client)
        self._log(state, "plan_tests", planned=len(specs))
        return {"specs": specs, "limitations": [*state.get("limitations", []), *not_verifiable]}

    async def generate_tests(self, state: FindingTestGenerationState):
        if state.get("result") is not None:
            return {}
        candidates = []
        llm = self.llm_client
        limitations = list(state.get("limitations", []))
        document = state.get("document")
        specs = list(state.get("specs", []))
        for index, spec in enumerate(specs):
            working_spec = spec
            if llm is not None and document is not None and getattr(llm, "select_rule", None) is not None:
                finding = next((item for item in document.findings if item.id == spec.finding_id), None)
                if finding is not None:
                    selection = await select_boundary_verification(spec, document, finding, llm)
                    state["llm_calls"] = state.get("llm_calls", 0) + 1
                    self._log(state, "rule_selection", verification_id=spec.verification_id,
                              applied=selection.applied, rule_id=selection.rule_id,
                              confidence=selection.confidence, reason=selection.reason)
                    if selection.applied_spec is not None:
                        working_spec = selection.applied_spec
                        specs[index] = working_spec
                    elif selection.reportable:
                        limitations.append(f"{spec.verification_id}: {selection.note}")
            content = None
            llm_write_used = False
            if llm is not None:
                llm_limit_note = None
                try:
                    source_finding = next((item for item in document.findings if item.id == spec.finding_id), None) if document else None
                    content = await llm.generate_test(working_spec, {
                        "repo": state["request"].repo_path,
                        "finding": source_finding.model_dump(mode="json") if source_finding else None,
                    })
                    state["llm_calls"] = state.get("llm_calls", 0) + 1
                    llm_write_used = True
                except Exception as error:  # noqa: BLE001 - LLM tool boundary; we degrade to template
                    llm_limit_note = (f"LLM-written test was rejected ({error}); deterministic template used instead."
                                      f" ({error})")
                    self._log(state, "generate_test_failed", verification_id=working_spec.verification_id,
                              error=type(error).__name__, message=str(error))
                    content = render_test_file(working_spec)[1]
                    if llm_limit_note:
                        limitations.append(f"{working_spec.verification_id}: {llm_limit_note}")
            else:
                content = render_test_file(working_spec)[1]
            candidate = self._candidate(working_spec, content)
            candidate["generated_by"] = "llm" if llm_write_used else "template"
            try:
                flags = suspicion_flags(content, subject_tokens(working_spec.target_components,
                                                                [dotted_module(part) for part in working_spec.target_components]))
            except Exception:  # noqa: BLE001 - suspicion is advisory; it must never break generation
                flags = []
            if flags:
                candidate["suspicion"] = flags
                self._log(state, "suspicion", verification_id=working_spec.verification_id, flags=flags)
            candidates.append(candidate)
        records = [ValidationRecord(
            verification_id=spec.verification_id,
            status=("generated" if next((c for c in candidates if c["verification_id"] == spec.verification_id), {}).get("content") else "invalid"),
            notes=["Reference template; see validation records for execution status."],
        ) for spec in specs]
        self._log(state, "generate_tests", candidates=len(candidates), llm_calls=state.get("llm_calls", 0),
                  used_tokens=getattr(llm, "used_tokens", None))
        return {"specs": specs, "candidates": candidates, "validation_records": records, "limitations": limitations,
                "llm_tokens": getattr(llm, "used_tokens", None)}

    @staticmethod
    def _candidate(spec: VerificationSpec, content: str, *, detail: str = "", error: bool = False) -> dict:
        return {"verification_id": spec.verification_id, "finding_id": spec.finding_id,
                "test_path": spec.test_path, "test_name": spec.test_name,
                "rule_kind": spec.rule_kind, "content": content, "language": spec.language,
                "tool_calls": 0,
                "classification": "execution_error" if error else None,
                "detail": detail}

    def _copy_source(self, source: Path, config, label: str) -> str:
        temp_dir = Path(tempfile.mkdtemp(prefix=f"tallercito-{label}-"))
        copy_report = copy_repository(source, temp_dir, max_files=config.max_repo_copy_files,
                                      max_bytes=config.max_repo_copy_bytes)
        self._log({}, "repo_copy", label=label, files=copy_report["files"], bytes=copy_report["bytes"])
        return str(temp_dir)

    def _run_pytest_phase(self, candidates: list[dict], run_root: str, config, state) -> dict:
        writer = WorkspaceWriter(run_root, max_test_file_bytes=config.max_test_file_bytes,
                                 max_written_bytes=config.max_written_bytes)
        helper_python, helper_python_content = render_helper("python")
        helper_node, helper_node_content = render_helper("typescript")
        has_python = any(candidate.get("language", "python") == "python" for candidate in candidates if candidate.get("content"))
        has_node = any(candidate.get("language", "python") != "python" for candidate in candidates if candidate.get("content"))
        try:
            if has_python:
                writer.write_test_file(f".tallercito/{helper_python}", helper_python_content)
            if has_node:
                writer.write_test_file(f".tallercito/{helper_node}", helper_node_content)
        except PathSafetyError as error:
            return {"candidates": candidates, "limitations": [*state.get("limitations", []), f"Could not write the suite helper: {error}"],
                    "outcomes": {}, "run_root": run_root}
        runner = WorkspaceRunner(Path(run_root), executor=LocalSubprocessExecutor(),
                                 timeout_seconds=config.max_test_run_seconds,
                                 max_output_bytes=config.max_captured_output_bytes)
        node_runtime = None
        node_receipt = None
        setup_limitations: list[str] = []
        if any(candidate.get("language", "python") != "python" for candidate in candidates):
            from server.runtimes.verification.templates import node_runtime
            try:
                node_receipt = node_runtime.prepare(str(run_root), config.max_test_run_seconds, True)
                self._log(state, "node_prepare", status=node_receipt.get("status"), harness=node_receipt.get("harness"))
                if node_receipt.get("harness") not in ("installed", "available"):
                    setup_limitations.append(f"Node harness is unavailable (status={node_receipt.get('status')}, harness={node_receipt.get('harness')}); TS verifications may not execute.")
            except Exception as error:  # noqa: BLE001 - TS setup failure degrades TS verifications honestly
                setup_limitations.append(f"Node harness setup failed; TS verifications will be EXECUTION_ERROR. ({error})")
        node_classify = {"pass": CLASSIFICATION_PASS, "violation": CLASSIFICATION_VIOLATION,
                         "timeout": CLASSIFICATION_TIMEOUT, "technical_failure": CLASSIFICATION_TECHNICAL,
                         "trivial": CLASSIFICATION_TRIVIAL, "execution_error": CLASSIFICATION_ERROR}
        outcomes: dict[str, str] = {}
        try:
            for candidate in candidates:
                language = candidate.get("language", "python")
                if candidate.get("content"):
                    trivial = (trivial_reason if language == "python" else node_runtime.trivial_reason if node_runtime else None)(candidate["content"])
                    if trivial:
                        candidate["classification"] = CLASSIFICATION_TRIVIAL
                        candidate["detail"] = f"Trivial test rejected before execution: {trivial}"
                        outcomes[candidate["verification_id"]] = CLASSIFICATION_TRIVIAL
                        continue
                    try:
                        self._charge_tool_call(state, candidate)
                        writer.write_test_file(f".tallercito/{candidate['test_path']}", candidate["content"])
                    except (PathSafetyError, BudgetExhausted) as error:
                        candidate["classification"] = "execution_error"
                        candidate["detail"] = str(error)
                        outcomes[candidate["verification_id"]] = candidate["classification"]
                        continue
                    self._charge_tool_call(state, candidate)
                    if language == "python":
                        outcome = runner.run_pytest(f".tallercito/{candidate['test_path']}")
                        candidate["classification"] = outcome.classification
                        candidate["detail"] = outcome.detail
                        outcomes[candidate["verification_id"]] = outcome.classification
                    else:
                        report = node_runtime.run(run_root, f".tallercito/{candidate['test_path']}",
                                                  framework="vitest", timeout=config.max_test_run_seconds)
                        outcome_class = node_classify.get(report.get("classification"), CLASSIFICATION_ERROR)
                        candidate["classification"] = outcome_class
                        candidate["detail"] = str(report.get("detail", ""))[:config.max_captured_output_bytes]
                        outcomes[candidate["verification_id"]] = outcome_class
        except BudgetExhausted as error:
            for candidate in candidates:
                outcomes.setdefault(candidate["verification_id"], candidate.get("classification") or "execution_error")
                candidate["classification"] = candidate.get("classification") or "execution_error"
                candidate["detail"] = (candidate.get("detail") or "") + f" [{error}]"
            return {"candidates": candidates,
                    "limitations": [*state.get("limitations", []), f"Tool-call budget exhausted: {error}"],
                    "outcomes": outcomes, "run_root": run_root}
        return {"candidates": candidates, "limitations": [*state.get("limitations", []), *setup_limitations], "outcomes": outcomes, "run_root": run_root}

    async def _attempt_repair(self, candidates, run_root, config, state):
        """Attempt to repair tests whose execution indicated a technical failure,
        within the configured per-verification tool-call budget.

        Both LLM-authored and deterministic-template-authored tests are eligible,
        so TS/JS and Python outputs alike can be salvaged into EXECUTION_ERRORs
        or before final RED/GREEN classification. Repair does not touch the
        audited implementation.
        """

        llm = self.llm_client
        if llm is None:
            return candidates
        specs = list(state.get("specs", []))
        spec_by_id = {spec.verification_id: spec for spec in specs}
        config_attempts = self.config.max_tool_calls_per_verification
        if config_attempts < 2:
            return candidates
        result_list = []
        for candidate in candidates:
            classification = candidate.get("classification")
            if classification not in (CLASSIFICATION_TECHNICAL, CLASSIFICATION_PASS, CLASSIFICATION_TRIVIAL):
                result_list.append(candidate)
                continue
            attempts = candidate.get("attempts", 0)
            if attempts >= config.max_repairs_per_verification:
                result_list.append(candidate)
                continue
            if not candidate.get("content"):
                result_list.append(candidate)
                continue
            # Only candidates with content participate, and templates no longer
            # auto-skip: a template-authored test that crashed or was trivial
            # is a valid repair target, not a foregone conclusion.
            if candidate.get("language", "python") != "python" and self.llm_client is None:
                result_list.append(candidate)
                continue
            spec = spec_by_id.get(candidate["verification_id"])
            if spec is None or not candidate.get("content"):
                result_list.append(candidate)
                continue
            try:
                file_fence = candidate.get("language", "python")
                failure_note = (
                    f"Test classification={classification}\n"
                    f"Failure output:\n{candidate.get('detail') or ''}\n"
                    "If the test passed at the audit baseline or was trivial, repair its oracle: "
                    "assert the intended invariant, not presence of the violation. Do not force RED "
                    "when source contradicts the finding. Preserve the property, not an inverted assertion. "
                    "Never hardcode source snapshots or project-specific rules. "
                    "Fix only test-code defects (imports, syntax, missing module references, wrong fence assumptions) "
                    f"and return a corrected {file_fence} module.\n"
                )
                repaired = await llm.repair_test(spec, candidate["content"], failure_note,
                                                 {"repo": state["request"].repo_path})
                if repaired and repaired != candidate["content"]:
                    candidate = dict(candidate)
                    candidate["repair_history"] = [*candidate.get("repair_history", []), {
                        "content": candidate.get("content"), "classification": classification,
                        "detail": candidate.get("detail"), "attempt": attempts,
                    }]
                    candidate["content"] = repaired
                    candidate["attempts"] = attempts + 1
                    candidate["history"] = (candidate.get("history", [])
                                            + [f"repair-{attempts + 1}: repaired by LLM"])
                    candidate["classification"] = None
                    candidate["detail"] = f"repaired by LLM (attempt {candidate['attempts']})"
                    state["llm_calls"] = state.get("llm_calls", 0) + 1
                else:
                    candidate = dict(candidate)
                    candidate["detail"] = (candidate.get("detail") or "") + " [repair returned identical/empty content]"
            except Exception as error:  # noqa: BLE001 - repair is best effort; diagnostics stay candid
                candidate = dict(candidate)
                candidate["detail"] = (candidate.get("detail") or "") + f" [repair failed: {error}]"
            result_list.append(candidate)
        return result_list

    async def execute_tests(self, state: FindingTestGenerationState):
        if state.get("result") is not None:
            return {}
        candidates = [dict(candidate) for candidate in state.get("candidates", [])]
        limitations = list(state.get("limitations", []))
        config = self.config
        if not config.allow_local_unsafe_execution:
            for candidate in candidates:
                candidate["classification"] = "environment_blocked"
                candidate["detail"] = "No local execution backend is configured; set allow_local_unsafe_execution=True for trusted fixtures."
            limitations.append(
                "Local execution is disabled; the suite is packaged without in-loop validation. "
                "Run it on the target machine with .tallercito/run.bat (or run.sh).")
            self._log(state, "execute_tests", blocked=len(candidates))
            return {"candidates": candidates, "limitations": limitations}
        try:
            run_root = state.get("run_root")
            if not run_root:
                source = Path(state["request"].repo_path)
                run_root = self._copy_source(source, config, "baseline")
        except (PathSafetyError, OSError) as error:
            for candidate in candidates:
                candidate["classification"] = "environment_blocked"
                candidate["detail"] = str(error)
            limitations.append(f"Disposable repository copy failed: {error}")
            self._log(state, "execute_tests", blocked=len(candidates), reason=str(error))
            return {"candidates": candidates, "limitations": limitations, "run_root": None}

        baseline = self._run_pytest_phase(candidates, run_root, config, state)
        candidates = baseline["candidates"]
        try:
            candidates = await self._attempt_repair(candidates, run_root, config, state)
            if any(c.get("attempts") for c in candidates):
                baseline = self._run_pytest_phase(candidates, run_root, config, state)
                candidates = baseline["candidates"]
        except Exception as error:  # noqa: BLE001 - repair is best effort; never block the cycle
            self._log(state, "repair_pass_failed", error=type(error).__name__, message=str(error))
        state_base_limitations = [*limitations, *baseline.get("limitations", [])]
        outcomes = baseline["outcomes"]
        limitations = state_base_limitations

        green_outcomes: dict[str, str] = {}
        green_root = state.get("green_root")
        if config.green_control_dir:
            if green_root is None:
                try:
                    green_root = self._copy_source(Path(config.green_control_dir), config, "green")
                except (PathSafetyError, OSError) as error:
                    limitations.append(f"Green-control copy failed; tests will not be counter-validated: {error}")
            if green_root:
                green_candidates = [dict(candidate) for candidate in state.get("candidates", [])]
                green_state = dict(state)
                green_state["limitations"] = list(state.get("limitations", []))
                green_phase = self._run_pytest_phase(green_candidates, green_root, config, green_state)
                green_limitations_before = len(green_state["limitations"])
                for i, candidate in enumerate(green_candidates):
                    candidates[i]["green_classification"] = candidate.get("classification")
                limitations.extend(green_state["limitations"][green_limitations_before:])
                green_outcomes = green_phase["outcomes"]
                limitations.append("Green-control counter-example run completed; tests must pass there too.")
        self._log(state, "execute_tests", outcomes=outcomes,
                  green_outcomes=green_outcomes or None)
        return {"candidates": candidates, "outcomes": outcomes, "green_outcomes": green_outcomes,
                "limitations": limitations, "run_root": run_root, "green_root": green_root}

    def evaluate_results(self, state: FindingTestGenerationState):
        if state.get("result") is not None:
            return {}
        has_green = bool(state.get("green_outcomes"))
        candidates = [dict(candidate) for candidate in state.get("candidates", [])]
        records = self._validation_records(candidates)
        results = self._verification_results(candidates)
        if has_green:
            # Only tests that pass against the corrected fixture count as rigorously validated.
            for candidate in candidates:
                if (candidate.get("classification") == CLASSIFICATION_VIOLATION
                        and state["green_outcomes"].get(candidate["verification_id"]) == CLASSIFICATION_PASS):
                    for record in records:
                        if record.verification_id == candidate["verification_id"]:
                            record.status = "validated_red_green"
                elif candidate.get("classification") == CLASSIFICATION_VIOLATION:
                    for record in records:
                        if record.verification_id == candidate["verification_id"]:
                            record.status = "partially_validated"
        limitations = list(state.get("limitations", []))
        trivial = [c for c in candidates if c.get("classification") == CLASSIFICATION_TRIVIAL]
        classes = [c.get("classification") for c in candidates]
        executed_ok = any(item in {CLASSIFICATION_VIOLATION, CLASSIFICATION_PASS} for item in classes)
        blocked_all = all(item in {"environment_blocked", "execution_error"} for item in classes)
        errors_present = any(item in {"execution_error", "environment_blocked", CLASSIFICATION_TECHNICAL} for item in classes)
        if blocked_all:
            validation_status = "environment_blocked"
        elif not executed_ok:
            validation_status = "partial" if classes else "invalid"
        elif errors_present:
            validation_status = "partial"
        elif trivial:
            validation_status = "invalid"
        elif records and all(item.status in {"validated_red", "validated_red_green"} for item in records):
            # Only oracle-confirmed red detections justify 'validated'; a pass at one
            # checkout by itself is not evidence that the condition is gone.
            validation_status = "validated"
        else:
            validation_status = "partial"
        if has_green and any(item.status != "validated_red_green"
                             for item in records
                             if item.status in {"validated_red", "validated_red_green"}):
            # With a green control present, unconfirmed verifications make the suite only 'partial'.
            validation_status = "partial"
        flagged = [c for c in candidates if c.get("suspicion")]
        technical_failed = [c for c in candidates if c.get("classification") == CLASSIFICATION_TECHNICAL]
        if flagged:
            flagged_notes = "; ".join(f"{c['verification_id']}=[{'; '.join(c['suspicion'])}]" for c in flagged)
            limitations.append(f"Suspicious test(s) for human review (kept; never auto-rejected): {flagged_notes}")
        if technical_failed:
            limitations.append(f"Technical failure(s) kept as diagnosis, never repaired: {', '.join(c['verification_id'] for c in technical_failed)}. Reported as EXECUTION_ERROR.")
        if trivial:
            limitations.append(f"Trivial assertion(s) rejected for: {', '.join(c['verification_id'] for c in trivial)}")
            for candidate in trivial:
                candidate["detail"] = (candidate.get("detail") or "") + " [trivial assertion rejected]"
        unexpected_pass = [c for c in candidates if c.get("classification") == CLASSIFICATION_PASS]
        if unexpected_pass:
            limitations.append(
                f"Passing test(s) at a known-violating baseline need review: {', '.join(c['verification_id'] for c in unexpected_pass)}.")
        self._log(state, "evaluate_results", decision="finalize", validation_status=validation_status,
                  outcomes={c["verification_id"]: c.get("classification") for c in candidates})
        return {"validation_records": records, "verification_results": results,
                "validation_status": validation_status, "limitations": limitations,
                "candidates": candidates}

    # ------------------------------------------------------------- packaging
    def package_suite(self, state: FindingTestGenerationState):
        if state.get("result") is not None:
            return {}
        candidates = [dict(candidate) for candidate in state.get("candidates", [])]
        specs = list(state.get("specs", []))
        dropped_limitations: list[str] = []
        if state.get("green_outcomes"):
            valid = {c["verification_id"] for c in candidates
                     if c.get("classification") == CLASSIFICATION_VIOLATION
                     and state["green_outcomes"].get(c["verification_id"]) == CLASSIFICATION_PASS}
            dropped = [s.verification_id for s in specs if s.verification_id not in valid]
            if dropped:
                dropped_limitations.append(f"Retained with failed oracle validation at green control: {', '.join(dropped)}.")
                for record in state.get("validation_records", []):
                    if record.verification_id not in valid:
                        record.status = "invalid"
        if not specs:
            return {"result": self._early_result({**state, "limitations": [*state.get("limitations", []), *dropped_limitations]},
                                                  "not_verifiable")}
        document = state["document"]
        source_limitations = state.get("limitations", [])
        limitations = list(dict.fromkeys([*dropped_limitations, *source_limitations]))
        zip_path = self._resolve_output(state["request"], document.audit_id)
        test_contents = {c["verification_id"]: c["content"] for c in candidates if c.get("content")}
        generation_sources = {c["verification_id"]: c.get("generated_by") for c in candidates if c.get("generated_by") is not None}
        try:
            manifest, zip_path = build_suite(document, specs, state.get("validation_records", []),
                                             limitations, zip_path, test_contents=test_contents,
                                             generation_sources=generation_sources)
        except OSError as error:
            return {"result": self._early_result({**state, "errors": [*state.get("errors", []), f"Could not build the suite ZIP: {error}"]}, "packaging_failed")}
        valid_records = [item for item in state.get("validation_records", [])
                         if item.verification_id in {c["verification_id"] for c in candidates}]
        valid_results = [item for item in state.get("verification_results", [])
                         if item.verification_id in {c["verification_id"] for c in candidates}]
        result = FindingTestGenerationResult(
            ok=True,
            termination_reason="suite_packaged",
            suite_id=manifest.suite_id,
            audit_id=document.audit_id,
            source_commit=document.commit_hash,
            output_zip=str(zip_path),
            specs=specs,
            validation_records=valid_records,
            verification_results=valid_results,
            validation_status=state.get("validation_status", "not_run"),
            limitations=limitations,
            warnings=state.get("warnings", []),
            errors=state.get("errors", []),
            baseline_available=state.get("baseline_available", False),
            llm_tokens=state.get("llm_tokens"),
        )
        self._log(state, "package_suite", zip=str(zip_path))
        return {"result": result}

    # ---------------------------------------------------------------- graph
    def _build_graph(self):
        graph = StateGraph(FindingTestGenerationState)
        graph.add_node("prepare_input", phase_node("prepare_input", self.prepare_input))
        graph.add_node("plan_tests", phase_node("plan_tests", self.plan_tests))
        graph.add_node("generate_tests", phase_node("generate_tests", self.generate_tests))
        graph.add_node("execute_tests", phase_node("execute_tests", self.execute_tests))
        graph.add_node("evaluate_results", phase_node("evaluate_results", self.evaluate_results))
        graph.add_node("package_suite", phase_node("package_suite", self.package_suite))
        graph.add_edge(START, "prepare_input")
        graph.add_conditional_edges("prepare_input", self._route_prepared, {"plan_tests": "plan_tests", "deliver": END})
        graph.add_edge("plan_tests", "generate_tests")
        graph.add_edge("generate_tests", "execute_tests")
        graph.add_edge("execute_tests", "evaluate_results")
        graph.add_edge("evaluate_results", "package_suite")
        graph.add_edge("package_suite", END)
        return graph.compile()

    @staticmethod
    def _route_prepared(state: FindingTestGenerationState) -> str:
        return "deliver" if state.get("result") is not None else "plan_tests"

    @staticmethod
    def _early_result(state: FindingTestGenerationState, reason: str) -> FindingTestGenerationResult:
        items = []
        document = state.get("document")
        for spec in state.get("specs", []):
            items.append(VerificationResult(verification_id=spec.verification_id,
                                            finding_id=spec.finding_id,
                                            status="NOT_VERIFIABLE",
                                            summary="Generation did not reach validation."))
        return FindingTestGenerationResult(
            ok=False,
            termination_reason=reason,
            audit_id=document.audit_id if document else None,
            source_commit=document.commit_hash if document else "",
            specs=state.get("specs", []),
            validation_records=state.get("validation_records", []),
            verification_results=items,
            validation_status="not_run",
            limitations=state.get("limitations", []),
            warnings=state.get("warnings", []),
            errors=state.get("errors", []),
            baseline_available=state.get("baseline_available", False),
            llm_tokens=state.get("llm_tokens"),
        )

    def initial_state(self, request: FindingTestGenerationRequest) -> FindingTestGenerationState:
        return {"request": request, "limitations": [], "warnings": [], "errors": [],
                "baseline_available": False, "tool_calls": 0, "llm_calls": 0,
                "llm_tokens": None,
                "candidates": [], "outcomes": {}}

    @staticmethod
    def _validation_records(candidates) -> list[ValidationRecord]:
        mapping = {CLASSIFICATION_VIOLATION: "validated_red", CLASSIFICATION_PASS: "partially_validated",
                   CLASSIFICATION_TECHNICAL: "environment_blocked", CLASSIFICATION_TRIVIAL: "invalid",
                   "execution_error": "environment_blocked", "environment_blocked": "environment_blocked"}
        records = []
        for candidate in candidates:
            status = mapping.get(candidate.get("classification"), "generated")
            records.append(ValidationRecord(verification_id=candidate["verification_id"], status=status,
                                            notes=[candidate.get("detail") or ""]))
        return records

    @staticmethod
    def _verification_results(candidates) -> list[VerificationResult]:
        mapping = {CLASSIFICATION_VIOLATION: "VIOLATION_PRESENT", CLASSIFICATION_PASS: "INCONCLUSIVE",
                   CLASSIFICATION_TECHNICAL: "EXECUTION_ERROR", CLASSIFICATION_TRIVIAL: "NOT_VERIFIABLE",
                   "execution_error": "EXECUTION_ERROR", "environment_blocked": "EXECUTION_ERROR"}
        results = []
        for candidate in candidates:
            status = mapping.get(candidate.get("classification"), "INCONCLUSIVE")
            if candidate.get("classification") == "environment_blocked":
                status = "EXECUTION_ERROR"
            results.append(VerificationResult(verification_id=candidate["verification_id"],
                                              finding_id=candidate["finding_id"],
                                              status=status,
                                              summary=(candidate.get("detail") or "")[:500],
                                              evidence=[candidate.get("test_path", "")]))
        return results
