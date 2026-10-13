import asyncio
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ..agents.architect.schemas import ArchitectureDescription, QualityNote
from ..agents.judge.agent import JudgeAgent
from ..agents.judge.schemas import JudgeInput
from ..api.schemas import ExecutionConfig
from ..app.execution_service import AgentExecutionService
from ..config.schemas import AgentSettings
from ..pipelines.architecture_audit import ArchitectureAuditPipeline
from ..services.repo_map.service import _collect_files
from .metrics import automatic_scores, citation_valid, judge_scores, review_template
from .pacing import RequestPacer
from .schemas import BenchmarkCase, BenchmarkSuite
from .telemetry import MeasuredCollection, MeasuredModel, call_metrics

SERVER_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = SERVER_ROOT.parent
DEFAULT_SUITE = SERVER_ROOT / "benchmarks" / "workspace.yaml"
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "appdata" / "workspace"


def load_suite(path: Path) -> BenchmarkSuite:
    return BenchmarkSuite.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True, timeout=30)
    return result.stdout.strip()


def fingerprint(paths: list[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        file_digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                file_digest.update(chunk)
        digest.update(file_digest.digest())
    return digest.hexdigest()


def validate_case(workspace: Path, case: BenchmarkCase) -> dict:
    root = (workspace / case.repository).resolve()
    if not root.is_relative_to(workspace.resolve()) or not (root / ".git").exists():
        raise ValueError(f"{case.id}: repository missing or outside workspace: {root}")
    commit = git(root, "rev-parse", "HEAD")
    if commit != case.commit:
        raise ValueError(f"{case.id}: expected commit {case.commit}, found {commit}")
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError(f"{case.id}: checkout has local changes; references require a clean checkout")
    paths = case.entrypoints + case.key_components
    citations = [entry for fact in [*case.expected_facts, *case.judge_claims] for entry in fact.evidence]
    for entry in paths + citations:
        if not citation_valid(root, entry):
            raise ValueError(f"{case.id}: invalid reference {entry!r}")
    files = _collect_files(root, 100)
    return {
        "root_path": str(root), "commit": commit,
        "input_sha256": fingerprint(files, root), "input_files": len(files),
    }


def environment(suite_path: Path, config: ExecutionConfig, options: dict) -> dict:
    source = SERVER_ROOT / "src" / "server"
    files = list(source.rglob("*.py")) + list(source.rglob("*.md")) + [SERVER_ROOT / "pyproject.toml", SERVER_ROOT / "uv.lock"]
    packages = {}
    for name in ("langgraph", "langchain-openai", "google-genai", "pydantic"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "started_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(), "platform": platform.platform(),
        "packages": packages,
        "code_sha256": fingerprint(files, SERVER_ROOT),
        "suite_sha256": hashlib.sha256(suite_path.read_bytes()).hexdigest(),
        "config_overrides": config.model_dump(exclude={"api_key"}),
        "options": options,
    }


def write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class ObservedAgent:
    """A pipeline-compatible wrapper; stage outputs survive downstream failure."""

    def __init__(self, agent, name: str, record: dict, input_price=None, output_price=None):
        self.agent = agent
        self.model = agent.model
        self.name = name
        self.record = record
        self.input_price = input_price
        self.output_price = output_price

    async def run(self, input_data):
        started = time.perf_counter()
        stage = {
            "status": "completed", "model": self.model.settings.model_dump(),
            "degradation_reasons": [],
        }
        self.record["stages"][self.name] = stage
        try:
            result = await self.agent.run(input_data)
            output = result.model_dump()
            self.record[{"analyzer": "analysis", "architect": "description", "judge": "grades", "judge_calibration": "calibration_report"}[self.name]] = output
            if self.name == "analyzer" and output.get("kind") == "unknown":
                stage["status"] = "degraded"
                stage["degradation_reasons"].append("no pudo clasificar el proyecto: kind=unknown")
            if self.name == "architect" and not any(item.get("responsibility") for item in output.get("components", [])):
                stage["status"] = "degraded"
                stage["degradation_reasons"].append("no describió la responsabilidad de ningún componente")
            return result
        except asyncio.CancelledError:
            stage["status"] = "timed_out"
            raise
        except Exception as error:
            stage.update(status="failed", error_type=type(error).__name__)
            raise
        finally:
            stage["seconds"] = time.perf_counter() - started
            stage["calls"] = self.model.calls
            stage["telemetry"] = call_metrics(self.model.calls, self.input_price, self.output_price)
            if stage["status"] in ("completed", "degraded"):
                failed = stage["telemetry"]["failed_calls"]
                invalid = stage["telemetry"]["invalid_json_calls"]
                if failed:
                    errors = Counter(
                        f"HTTP {call['http_status']}" if call.get("http_status") is not None
                        else call.get("error_type", "error desconocido")
                        for call in self.model.calls if call["status"] == "failed"
                    )
                    detail = ", ".join(f"{label}: {count}" for label, count in sorted(errors.items()))
                    stage["degradation_reasons"].append(
                        ("1 llamada al modelo falló" if failed == 1 else f"{failed} llamadas al modelo fallaron")
                        + f" [{detail}]"
                    )
                if invalid:
                    stage["degradation_reasons"].append(
                        "1 respuesta JSON inválida" if invalid == 1 else f"{invalid} respuestas JSON inválidas"
                    )
                if stage["degradation_reasons"]:
                    stage["status"] = "degraded"
            collection = getattr(self.agent, "_collection", None)
            if isinstance(collection, MeasuredCollection):
                stage["collections"] = collection.observations
            if self.name == "analyzer" and "analysis" in self.record:
                stage["files_read"] = self.record["analysis"]["files_read"]
                stage["read_rounds"] = self.record["analysis"]["read_rounds"]


def measured_agent(service, agent_type, config, record, prices, pacer=None, models=None):
    base, _ = service.build_agent(agent_type, config)
    if models is not None:
        models.append(base.model)
    model = MeasuredModel(base.model, pacer=pacer)
    agent = type(base)(settings=base.settings, model=model, collection=MeasuredCollection())
    return ObservedAgent(agent, agent_type, record, *prices), base.model


async def run_case(service, case, snapshot, repeat, config, options, pacer=None):
    models = []
    try:
        return await _run_case(service, case, snapshot, repeat, config, options, pacer, models)
    finally:
        # These clients belong to this case; release them on success, timeout or Ctrl+C.
        for model in models:
            try:
                client = getattr(model, "client", None)
                if client is not None and hasattr(client, "aio"):
                    await client.aio.aclose()
                    client.close()
                llm = getattr(model, "llm", None)
                async_client = getattr(llm, "root_async_client", None)
                if async_client is not None:
                    await async_client.close()
                sync_client = getattr(llm, "root_client", None)
                if sync_client is not None:
                    sync_client.close()
            except Exception as error:  # noqa: BLE001 - cleanup must preserve the measured result
                print(f"    cierre del cliente: {type(error).__name__}", flush=True)


async def _run_case(service, case, snapshot, repeat, config, options, pacer, models):
    record = {
        "run_id": f"{case.id}-{repeat:02d}", "case_id": case.id, "repeat": repeat,
        "snapshot": snapshot, "stages": {}, "analysis": {}, "description": {},
        "grades": {}, "calibration_items": [],
    }
    started = time.perf_counter()
    prices = options["input_price"], options["output_price"]
    pipeline_started = time.perf_counter()
    try:
        analyzer, _ = measured_agent(service, "analyzer", config, record, prices, pacer, models)
        architect, architect_model = measured_agent(service, "architect", config, record, prices, pacer, models)
        await asyncio.wait_for(
            ArchitectureAuditPipeline(analyzer, architect).run(
                snapshot["root_path"], max_files=options["max_files"], max_depth=options["max_depth"],
                max_read_rounds=options["rounds"], max_files_per_round=options["files_per_round"],
            ), options["timeout"],
        )
    except Exception as error:  # noqa: BLE001 - record provider/agent failures and continue the suite
        record["pipeline_error"] = type(error).__name__
        record["pipeline_status"] = "timed_out" if isinstance(error, TimeoutError) else "failed"
    else:
        record["pipeline_status"] = "completed"
    record["pipeline_seconds"] = time.perf_counter() - pipeline_started

    # Calibrate the judge even when the upstream pipeline fails.
    try:
        if "architect_model" not in locals():
            _, architect_model = service.build_agent("architect", config)
            models.append(architect_model)
        for name, description in (
            ("judge", ArchitectureDescription.model_validate(record["description"]) if record["description"] else None),
            ("judge_calibration", ArchitectureDescription(quality_notes=[
                QualityNote(characteristic="analysability", observation=claim.observation, evidence=claim.evidence)
                for claim in case.judge_claims
            ])),
        ):
            if description is None:
                record["stages"][name] = {"status": "skipped"}
                continue
            # Same underlying model as the architect, separate measurement scope.
            agent = JudgeAgent(settings=AgentSettings(agent_id="judge", timeout_seconds=options["judge_timeout"]), model=MeasuredModel(architect_model, pacer=pacer))
            observer = ObservedAgent(agent, name, record, *prices)
            try:
                result = await asyncio.wait_for(observer.run(JudgeInput(root_path=snapshot["root_path"], description=description)), options["judge_timeout"])
            except Exception as error:  # noqa: BLE001 - keep failed judge stages in the benchmark
                record[f"{name}_error"] = type(error).__name__
                continue
            if name == "judge_calibration":
                record["calibration_items"] = [
                    {"id": claim.id, "expected": claim.verdict, "predicted": grade.verdict, "reason": grade.reason, "evidence": grade.evidence}
                    for claim, grade in zip(case.judge_claims, result.grades, strict=True)
                ]
    except Exception as error:  # noqa: BLE001 - judge setup failures must not discard the pipeline output
        record["judge_setup_error"] = type(error).__name__
    for name in ("analyzer", "architect", "judge", "judge_calibration"):
        record["stages"].setdefault(name, {"status": "skipped"})
    record["total_seconds"] = time.perf_counter() - started
    record["automatic"] = automatic_scores(Path(snapshot["root_path"]), case, record["analysis"], record["description"])
    record["judge_calibration"] = judge_scores(record["calibration_items"])
    record["calibration_expected_items"] = len(case.judge_claims)
    for name in ("analyzer", "architect"):
        collections = record["stages"][name].get("collections", [])
        if collections:
            visible = set(collections[-1]["mapped_paths"])
            record["stages"][name]["reference_visibility"] = {
                "entrypoints": {path: path in visible for path in case.entrypoints},
                "key_components": {path: path in visible for path in case.key_components},
            }
    return record


async def run_benchmark(suite_path, workspace, output, case_ids, repeats, config, options):
    suite = load_suite(suite_path)
    cases = select_cases(suite, case_ids)
    snapshots = {case.id: validate_case(workspace, case) for case in cases}
    if output.exists():
        raise ValueError(f"Output directory already exists: {output}")
    output.mkdir(parents=True)
    (output / "runs").mkdir()
    (output / "reviews").mkdir()
    write_json(output / "suite.json", suite.model_dump())
    metadata = environment(suite_path, config, options)
    metadata["sampling"] = {
        "repeats": repeats, "case_ids": [case.id for case in cases],
        "planned_runs": repeats * len(cases),
    }
    write_json(output / "environment.json", metadata)
    service = AgentExecutionService()
    pacer = RequestPacer(
        interval=options.get("request_interval", 12.0),
        max_retries=options.get("max_retries", 3),
        backoff=options.get("retry_backoff", 30.0),
    )
    print(f"Ritmo del proveedor: pausa mínima de {pacer.interval:g}s entre llamadas; hasta {pacer.max_retries} reintentos por llamada.", flush=True)
    records = []
    try:
        for repeat in range(1, repeats + 1):
            for case in cases:
                print(f"[{repeat}/{repeats}] {case.id}", flush=True)
                record = await run_case(service, case, snapshots[case.id], repeat, config, options, pacer=pacer)
                current = validate_case(workspace, case)
                if current["input_sha256"] != snapshots[case.id]["input_sha256"]:
                    raise ValueError(f"{case.id}: input files changed during the benchmark")
                write_json(output / "runs" / f"{record['run_id']}.json", record)
                write_json(output / "reviews" / f"{record['run_id']}.json", review_template(record, case).model_dump())
                records.append(record)
                print(f"  pipeline={record['pipeline_status']}; tiempo total={record['total_seconds']:.1f}s", flush=True)
                for name, stage in record["stages"].items():
                    reasons = stage.get("degradation_reasons", [])
                    detail = f" ({'; '.join(reasons)})" if reasons else ""
                    print(f"    {name}={stage['status']}{detail}", flush=True)
                # Persist an aggregate after every run, so interruption loses no finished case.
                from .report import write_report
                write_report(output)
    finally:
        if records:
            from .report import write_report
            write_report(output)
    return output


def select_cases(suite: BenchmarkSuite, case_ids: list[str]):
    unknown = set(case_ids) - {case.id for case in suite.cases}
    if unknown:
        raise ValueError(f"Unknown case ids: {', '.join(sorted(unknown))}")
    return [case for case in suite.cases if not case_ids or case.id in case_ids]
