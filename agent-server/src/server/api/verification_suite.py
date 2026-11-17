"""Verification suite endpoint: runs the finding-test-generation agent off an audit artifact.

Reads the artifact report (the same `report.json` consumed by ``/api/audits/{run_id}/report.json``),
routes the audit's findings through the dedicated-generation pipeline against the audited
repository, and stores the produced verification suite ZIP plus a compact summary next to the
artifact. No local execution is enabled unless requested in the body.
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from starlette.responses import FileResponse

from server.agents.finding_test_generation.agent import FindingTestGenerationAgent
from server.agents.finding_test_generation.config import FindingTestConfig
from server.agents.finding_test_generation.schemas import FindingTestGenerationRequest
from server.app.audit_artifacts import _safe_run_id, artifact_root
from server.app.verification_model_configuration import VerificationModelConfiguration

router = APIRouter(tags=["Audits"])


class VerificationSuiteRequest(BaseModel):
    config: VerificationModelConfiguration | None = Field(default=None, repr=False)
    target_commit: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{40}$")
    attempt_id: str | None = Field(default=None, max_length=64)
    llm: str = Field(default="provider", pattern="^(none|provider)$")
    allow_execution: bool = True
    action: str = Field(default="create", pattern="^(create|execute)$")
    green_control: str | None = None
    group: str | None = Field(default=None, pattern="^[A-Za-z0-9_-]{1,32}$")
    # Backend agent-execution row this build belongs to; gives the monitor its live view.
    execution_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_production_model(self):
        if self.action == "create" and self.llm == "provider" and self.config is None:
            raise ValueError("Configure the Verification Suite model and credential before generation.")
        return self


class VerificationSuiteResponse(BaseModel):
    suite_id: str | None = None
    suite_sha256: str | None = None
    baseline_commit: str | None = None
    target_commit: str | None = None
    checkout_commit: str | None = None
    attempt_id: str | None = None
    ok: bool
    run_id: str
    termination_reason: str
    zip_path: str | None = None
    verifications: list[dict] = []
    validation_status: str = "not_run"
    limitations: list[str] = []
    action: str | None = None
    green_control: str | None = None
    groups: list[dict] = []
    generators: list[str] = []
    selection: list[str] = []


def _safe(run_id: str) -> str:
    try:
        return _safe_run_id(run_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _artifact_root(run_id: str) -> Path:
    root = artifact_root() / _safe(run_id)
    if not root.is_dir():
        raise HTTPException(status_code=404, detail=f"Audit artifacts for run {_safe(run_id)!r} not found")
    return root


def _suite_path(run_id: str) -> Path:
    _artifact_root(run_id)  # validates existence with the proper HTTP error
    return artifact_root() / _safe(run_id) / "verification-suite.zip"


def _suite_summary_path(run_id: str) -> Path:
    return artifact_root() / _safe(run_id) / "verification-suite-summary.json"


# --- Live reporting (internal agent-executions) -------------------------------

def _suite_sink(execution_id):
    """Sink for lifecycle callbacks; None when tracking is unavailable/disabled."""
    if execution_id is None:
        return None
    from server.agent_services.execution_tracking.observer import default_callback_sink

    return default_callback_sink()


def _receipt(*, invocation_id, parent_invocation_id, agent_id, run_id, status, phase, started_at,
             finished_at=None, input_tokens=None, output_tokens=None, error=None, phase_sequence=0):
    from server.agent_services.execution_tracking.callback.schemas import (
        InvocationReceipt,
    )

    return InvocationReceipt(
        invocation_id=invocation_id,
        parent_invocation_id=parent_invocation_id,
        agent_id=agent_id,
        run_id=run_id,
        status=status,
        phase=phase,
        started_at=started_at,
        finished_at=finished_at,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        unknown_usage_attempts=0,
        error=error,
        phase_sequence=phase_sequence,
    )


def _suite_input_path(run_id: str) -> Path:
    return artifact_root() / _safe(run_id) / "verification-suite-input.json"


def _suite_output_dir(run_id: str) -> Path:
    return artifact_root() / _safe(run_id) / "verification-suite"


def _report_path(run_id: str) -> Path:
    return _artifact_root(run_id) / "report.json"


def _to_audit_id_int(value) -> int:
    try:
        return int(str(value).strip(), 0)
    except (TypeError, ValueError):
        return 1


def _adapt_input(report: dict) -> dict:
    identification = (report.get("identification") or {}) if isinstance(report, dict) else {}
    project_name = identification.get("repository_location")
    revisions = identification.get("revisions") or []
    commit = revisions[0].get("commit") if revisions and isinstance(revisions[0], dict) else None
    findings = (report.get("quality_results") or {}).get("findings") or []
    return {
        "auditId": _to_audit_id_int(identification.get("audit_id")),
        "commitHash": commit or "0" * 40,
        "project_name": project_name,
        "findings": findings,
    }


from server.runtimes.verification.merge import (
    AgentArtifact,
    build_empty_suite,
    load_agent_zip,
    merge_suite_zips,
)
from server.runtimes.verification.split import group_of, split_findings

_PROBE_STATUS_MAP = {
    "violation_present": "VIOLATION_PRESENT",
    "not_observed_within_scope": "EXECUTION_ERROR",
    "execution_error": "EXECUTION_ERROR",
    "invalid_test": "EXECUTION_ERROR",
    "inconclusive": "EXECUTION_ERROR",
    "not_verifiable": "EXECUTION_ERROR",
}


def _probe_status(outcome: str) -> str:
    return _PROBE_STATUS_MAP.get(outcome, "EXECUTION_ERROR")


async def _run_finding_test_generation(run_id: str, adapted: dict, findings: list[dict],
                                       repo_path: str, output_dir: Path,
                                       body: VerificationSuiteRequest, trackers: dict | None = None):
    from server.agents.finding_test_generation.config import FindingTestConfig
    from server.agents.finding_test_generation.llm_client import (
        ProviderFindingLLMClient,
    )

    ftg_dir = output_dir / "ftg"
    ftg_dir.mkdir(parents=True, exist_ok=True)
    input_path = output_dir / "ftg-input.json"
    payload = {**adapted, "findings": findings}
    input_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    config = FindingTestConfig(allow_local_unsafe_execution=body.allow_execution)
    llm_client = None
    if body.llm == "provider":
        settings, credentials = body.config.resolve(config)
        llm_client = ProviderFindingLLMClient(config, settings=settings, credentials=credentials)
    if trackers is not None:
        trackers["finding_test_generation"] = llm_client
    agent = FindingTestGenerationAgent(config=config, llm_client=llm_client)
    result = await asyncio.wait_for(
        agent.run(FindingTestGenerationRequest(findings_path=str(input_path),
                                               repo_path=str(repo_path),
                                               output_path=str(ftg_dir))),
        timeout=900,
    )
    return result


async def _run_probe(run_id: str, adapted: dict, findings: list[dict],
                     repo_path: str, output_dir: Path,
                     body: VerificationSuiteRequest, trackers: dict | None = None):
    from server.agents.testability_probe.agent import TestabilityProbeAgent
    from server.agents.testability_probe.audit_input import convert_audit_export
    from server.agents.testability_probe.config import TestabilityProbeConfig
    from server.agents.testability_probe.llm_client import ProviderProbeLLMClient
    from server.agents.testability_probe.schemas import ProbeRequest

    probe_dir = output_dir / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    input_path = output_dir / "probe-input.json"
    payload = convert_audit_export({**adapted, "findings": findings})
    input_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    config = TestabilityProbeConfig(allow_local_unsafe_execution=body.allow_execution)
    llm_client = None
    if body.llm == "provider":
        settings, credentials = body.config.resolve(config)
        llm_client = ProviderProbeLLMClient(config, settings=settings, credentials=credentials)
    agent = TestabilityProbeAgent(config, llm_client)
    if trackers is not None:
        trackers["testability_probe"] = llm_client
    result = await asyncio.wait_for(
        agent.run(ProbeRequest(findings_path=str(input_path),
                               repo_path=str(repo_path),
                               output_path=str(probe_dir),
                               audit_id=str(adapted.get("auditId")),
                               execution_id=f"{run_id}-probe")),
        timeout=3600,
    )
    return result


@router.post("/{run_id}/verification-suite", response_model=VerificationSuiteResponse)
async def build_verification_suite(run_id: str, body: VerificationSuiteRequest) -> VerificationSuiteResponse:
    safe_runner_id = run_id
    path = _report_path(safe_runner_id)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail=f"Audit artifact is unreadable: {error}") from error

    adapted = _adapt_input(report)
    repo_path = adapted.get("project_name")
    if not repo_path:
        raise HTTPException(status_code=422, detail="Audit artifact does not record a repository location")

    # Live reporting for the generation pass only (nothing reports during execute).
    execution_id = body.execution_id if body.action == "create" else None
    sink = _suite_sink(execution_id)
    root_id = None
    if sink is not None and execution_id is not None:
        root_id = f"{body.attempt_id or uuid4().hex}-suite"
        now = datetime.now(UTC)
        suite_started = now
        await sink.mark_running(execution_id)
        await sink.invocation(execution_id, _receipt(
            invocation_id=root_id, parent_invocation_id=None, agent_id="verification_suite",
            run_id=safe_runner_id, status="running", phase="generation", started_at=now, phase_sequence=0))

    adapted_path = _suite_input_path(safe_runner_id)
    adapted_path.parent.mkdir(parents=True, exist_ok=True)
    adapted_path.write_text(json.dumps(adapted, indent=2, ensure_ascii=False), encoding="utf-8")

    if body.action == "execute":
        if not body.allow_execution:
            raise HTTPException(status_code=403, detail="Local suite execution must be explicitly enabled")
        # Execute the already-built deliverable against the audited repository (+ optional green control). No LLM calls.
        from server.agents.finding_test_generation.validate_zip import (
            ValidationError,
            validate_zip,
        )
        destination = _suite_path(safe_runner_id)
        if not destination.is_file():
            raise HTTPException(status_code=409, detail="The verification suite ZIP has not been built yet; create it first.")
        green_path = Path(body.green_control) if body.green_control else None
        only = [body.group.lower()] if body.group else None
        try:
            result = await asyncio.to_thread(validate_zip, destination, Path(repo_path), green_path,
                                  FindingTestConfig(allow_local_unsafe_execution=body.allow_execution),
                                  target_commit=body.target_commit or adapted["commitHash"],
                                  only=only)
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=f"Suite execution failed: {error}") from error
        response_body = VerificationSuiteResponse(
            ok=True,
            run_id=safe_runner_id,
            termination_reason="suite_validated",
            attempt_id=body.attempt_id or uuid4().hex,
            zip_path=str(destination),
            verifications=result["verifications"],
            validation_status=result["validation_status"],
            limitations=result["limitations"],
            action="execute",
            green_control=str(green_path) if green_path is not None else None,
            suite_id=result["suite_id"], suite_sha256=result["suite_sha256"],
            baseline_commit=result["baseline_commit"], target_commit=result["target_commit"],
            checkout_commit=result["checkout_commit"],
            selection=result.get("selection", []),
        )
        executions = _artifact_root(safe_runner_id) / "verification-executions"
        executions.mkdir(exist_ok=True)
        (executions / f"{_safe(response_body.attempt_id)}.json").write_text(
            response_body.model_dump_json(indent=2) + "\n", encoding="utf-8")
        _suite_summary_path(safe_runner_id).write_text(
            response_body.model_dump_json(indent=2) + "\n", encoding="utf-8",
        )
        return response_body

    if body.group is not None:
        raise HTTPException(status_code=400,
                            detail="group filtering is only supported for action=execute")

    buckets = split_findings(adapted["findings"])
    ftg_findings = buckets["ftg"]
    probe_findings = buckets["probe"]
    unsupported = buckets["unsupported"]
    verification_groups = {str(f.get("id")): group_of(f) for f in adapted["findings"]}
    limitations_extra: list[str] = []
    if unsupported:
        limitations_extra.append(
            f"{len(unsupported)} finding(s) have no assigned verification agent "
            f"(unsupported subcharacteristic): "
            + ", ".join(str(f.get("id")) for f in unsupported[:12]))

    output_dir = _suite_output_dir(safe_runner_id)
    ftg_result = None
    probe_result = None
    errors: list[str] = []
    ftg_started = probe_started = None
    trackers: dict[str, object] = {}
    if sink is not None and (ftg_findings or probe_findings):
        now = datetime.now(UTC)
        if ftg_findings:
            ftg_started = now
            await sink.invocation(execution_id, _receipt(
                invocation_id=f"{body.attempt_id or root_id}-ftg", parent_invocation_id=root_id,
                agent_id="finding_test_generation", run_id=safe_runner_id, status="running",
                phase="generation", started_at=ftg_started, phase_sequence=0))
        if probe_findings:
            probe_started = now
            await sink.invocation(execution_id, _receipt(
                invocation_id=f"{body.attempt_id or root_id}-probe", parent_invocation_id=root_id,
                agent_id="testability_probe", run_id=safe_runner_id, status="running",
                phase="generation", started_at=probe_started, phase_sequence=0))
    if ftg_findings or probe_findings:
        tasks: list[tuple[str, object]] = []
        if ftg_findings:
            tasks.append(("finding_test_generation",
                          _run_finding_test_generation(safe_runner_id, adapted, ftg_findings, repo_path, output_dir, body, trackers=trackers)))
        if probe_findings:
            tasks.append(("testability_probe",
                          _run_probe(safe_runner_id, adapted, probe_findings, repo_path, output_dir, body, trackers=trackers)))
        gathered = await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
        for (generator, _), outcome in zip(tasks, gathered):
            if isinstance(outcome, BaseException):
                errors.append(f"{generator}: {type(outcome).__name__}: {outcome}")
            elif outcome is not None:
                if generator == "finding_test_generation":
                    ftg_result = outcome
                else:
                    probe_result = outcome
        if errors:
            limitations_extra.append("Verification-suite generators reported failures: " + "; ".join(errors))
        if sink is not None and execution_id is not None:
            from server.agent_services.execution_tracking.callback.schemas import (
                ExecutionProgress,
            )

            finished_now = datetime.now(UTC)
            input_total = output_total = 0
            children_completed = 0
            children_failed = 0
            for agent_id, result, started, receipt_id in (
                ("finding_test_generation", ftg_result, ftg_started, f"{body.attempt_id or root_id}-ftg"),
                ("testability_probe", probe_result, probe_started, f"{body.attempt_id or root_id}-probe"),
            ):
                if started is None:
                    continue
                client = trackers.get(agent_id)
                agent_input = getattr(client, "used_input_tokens", None) if client is not None else None
                agent_output = getattr(client, "used_output_tokens", None) if client is not None else None
                input_total += int(agent_input) if agent_input is not None else 0
                output_total += int(agent_output) if agent_output is not None else 0
                child_ok = bool(getattr(result, "ok", False)) if result is not None else False
                child_error = None
                if child_ok:
                    children_completed += 1
                else:
                    children_failed += 1
                    child_error = next((item for item in errors if item.startswith(agent_id)), f"{agent_id} failed")[:2000]
                await sink.invocation(execution_id, _receipt(
                    invocation_id=receipt_id, parent_invocation_id=root_id, agent_id=agent_id,
                    run_id=safe_runner_id, status="completed" if child_ok else "failed", phase="generation",
                    started_at=started, finished_at=finished_now,
                    input_tokens=int(agent_input) if agent_input is not None else None,
                    output_tokens=int(agent_output) if agent_output is not None else None,
                    error=child_error, phase_sequence=1))
            await sink.progress(execution_id, ExecutionProgress(
                inputTokens=input_total or None,
                outputTokens=output_total or None,
                estimatedTokens=0))

    destination = _suite_path(safe_runner_id)
    artifacts: list[AgentArtifact] = []
    ftg_results_by_id: dict[str, object] = {}
    if ftg_result is not None:
        ftg_zip = Path(ftg_result.output_zip) if getattr(ftg_result, "output_zip", None) else None
        if ftg_zip and ftg_zip.is_file():
            artifacts.append(load_agent_zip(
                ftg_zip, "finding_test_generation",
                termination_reason=ftg_result.termination_reason,
                validation_status=ftg_result.validation_status,
                limitations=ftg_result.limitations,
            ))
        else:
            errors.append("finding_test_generation: no output ZIP produced")
        ftg_results_by_id = {item.verification_id: item for item in getattr(ftg_result, "verification_results", [])}
    if probe_result is not None:
        probe_zip = Path(probe_result.output_zip) if getattr(probe_result, "output_zip", None) else None
        if probe_zip and probe_zip.is_file():
            artifacts.append(load_agent_zip(
                probe_zip, "testability_probe",
                termination_reason=probe_result.termination_reason,
                validation_status=probe_result.validation_status,
                limitations=probe_result.limitations,
            ))
        else:
            errors.append("testability_probe: no output ZIP produced")

    if not artifacts:
        if errors:
            raise HTTPException(status_code=500, detail="All verification-suite generators failed. " + "; ".join(errors))
        merged_manifest, merged_limitations = build_empty_suite(
            destination, audit_id=str(adapted.get("auditId") or ""),
            source_commit=str(adapted.get("commitHash") or ""))
        termination_reason = "no_findings"
        generators: list[str] = []
    else:
        merged_manifest, merged_limitations = merge_suite_zips(
            destination, artifacts,
            audit_id=str(adapted.get("auditId") or ""),
            source_commit=str(adapted.get("commitHash") or ""),
            verification_groups=verification_groups,
            extra_limitations=limitations_extra)
        termination_reason = "suite_packaged"
        generators = [artifact.generator for artifact in artifacts]

    limitations = list(dict.fromkeys(merged_limitations))

    verifications_out = []
    probe_results_by_id = ({item.verification_id: item for item in getattr(probe_result, "verifications", [])}
                           if probe_result is not None else {})
    artifact_by_vid: dict[str, AgentArtifact] = {}
    for artifact in artifacts:
        for verification in artifact.manifest.get("verifications", []):
            artifact_by_vid[verification.get("verification_id")] = artifact

    for verification in merged_manifest.get("verifications", []):
        vid = verification.get("verification_id")
        artifact = artifact_by_vid.get(vid)
        generator = (artifact.generator if artifact is not None else verification.get("generator"))
        results = (ftg_results_by_id if generator == "finding_test_generation" else probe_results_by_id)
        result = results.get(vid)
        if generator == "finding_test_generation":
            status = getattr(result, "status", None) or "not_run"
            summary = getattr(result, "summary", "") or ""
            rule_id = verification.get("rule_kind")
        else:
            status = _probe_status(getattr(result, "outcome", ""))
            summary = getattr(result, "llm_assessment", None) or getattr(result, "detail", "") or ""
            rule_id = None
        verifications_out.append({
            "verification_id": vid,
            "finding_id": verification.get("finding_id"),
            "rule_id": rule_id,
            "strategy": verification.get("strategy"),
            "covered_property": verification.get("covered_property"),
            "target_components": verification.get("target_components"),
            "generation_status": verification.get("generation_status", "generated"),
            "status": status,
            "summary": summary,
            "generated_by": verification.get("generated_by"),
            "group": verification.get("group"),
            "generator": generator,
        })

    groups_counts: dict[str, int] = {}
    for item in verifications_out:
        groups_counts[item["group"] or "other"] = groups_counts.get(item["group"] or "other", 0) + 1

    status_rank = {"validated": 3, "validated_red_green": 3, "partial": 2, "inconclusive": 2,
                   "environment_blocked": 1, "not_applicable": 1,
                   "not_run": 0, "invalid": 1}
    validation_status = "not_run"
    if artifacts:
        validation_status = str(min((a.validation_status for a in artifacts),
                                    key=lambda s: status_rank.get(s, 0)))

    ok = bool(artifacts) or not (ftg_findings or probe_findings)
    if sink is not None and execution_id is not None:
        from server.agent_services.execution_tracking.callback.schemas import (
            ExecutionOutcome,
        )

        finished_now = datetime.now(UTC)
        input_total = output_total = 0
        for agent_id in ("finding_test_generation", "testability_probe"):
            client = trackers.get(agent_id)
            input_total += int(getattr(client, "used_input_tokens", 0) or 0)
            output_total += int(getattr(client, "used_output_tokens", 0) or 0)
        any_child_failed = (ftg_result is not None and not getattr(ftg_result, "ok", False)) \
            or (probe_result is not None and not getattr(probe_result, "ok", False))
        child_outcomes = [getattr(result, "ok", False) for result in (ftg_result, probe_result) if result is not None]
        if child_outcomes and not any(child_outcomes):
            root_status = "failed"
        elif any_child_failed:
            root_status = "partial"
        else:
            root_status = "completed"
        await sink.invocation(execution_id, _receipt(
            invocation_id=root_id, parent_invocation_id=None, agent_id="verification_suite",
            run_id=safe_runner_id, status=root_status, phase="generation",
            started_at=suite_started, finished_at=finished_now,
            input_tokens=input_total or None, output_tokens=output_total or None,
            phase_sequence=2))
        await sink.complete(execution_id, ExecutionOutcome(
            status="Failed" if root_status == "failed" else "Completed",
            result=json.dumps({"run_id": safe_runner_id, "suite_id": None, "verifications": len(verifications_out),
                               "termination_reason": termination_reason}, ensure_ascii=False),
            error="; ".join(errors)[:2000] if any_child_failed else None,
            inputTokens=input_total, outputTokens=output_total, estimatedTokens=0,
            interruptionReason=None))
    response_body = VerificationSuiteResponse(
        ok=ok,
        run_id=safe_runner_id,
        termination_reason=termination_reason,
        zip_path=str(destination) if destination.is_file() else None,
        verifications=verifications_out,
        validation_status=validation_status,
        limitations=limitations,
        action="create",
        attempt_id=body.attempt_id,
        suite_id=merged_manifest.get("suite_id"),
        groups=[{"name": name, "count": count} for name, count in sorted(groups_counts.items())],
        generators=generators,
    )

    _suite_summary_path(safe_runner_id).write_text(
        response_body.model_dump_json(indent=2) + "\n", encoding="utf-8",
    )
    return response_body


@router.get("/{run_id}/verification-suite", response_model=VerificationSuiteResponse)
async def read_verification_suite(run_id: str) -> VerificationSuiteResponse:
    ok_path = _suite_summary_path(run_id)
    if not ok_path.is_file():
        raise HTTPException(status_code=404, detail="Verification suite artifact is not built yet")
    return VerificationSuiteResponse.model_validate_json(ok_path.read_text(encoding="utf-8"))


@router.get("/{run_id}/verification-suite.zip",
            responses={200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}}})
async def download_verification_suite(run_id: str) -> FileResponse:
    path = _suite_path(run_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Verification suite artifact is not built yet")
    return FileResponse(path, media_type="application/zip", filename="verification-suite.zip")
