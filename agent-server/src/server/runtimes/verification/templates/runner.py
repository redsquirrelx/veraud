"""Tallercito verification-suite runner.

Portable, stdlib-only entry point for the exported suite. Resolves every path
relative to its own location, never to the caller's working directory, and
writes results inside ``.tallercito/results`` only.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

SUITE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SUITE_ROOT.parent
MANIFEST_PATH = SUITE_ROOT / "manifest.json"
RESULTS_DIR = SUITE_ROOT / "results"
TEST_TIMEOUT_SECONDS = 600

VERIFICATION_VIOLATION = "VIOLATION_PRESENT"
VERIFICATION_FIXED = "VERIFIED_FIXED"
VERIFICATION_INCONCLUSIVE = "INCONCLUSIVE"
VERIFICATION_ERROR = "EXECUTION_ERROR"
VERIFICATION_NOT_VERIFIABLE = "NOT_VERIFIABLE"

DEFAULT_GROUP = "other"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tallercito verification-suite runner.")
    parser.add_argument("--only", action="append", default=[], metavar="GROUP",
                        help="Execute only verifications whose group matches GROUP. Repeatable. Default: all groups.")
    parser.add_argument("--list-groups", action="store_true",
                        help="Print the verification groups present in the manifest and exit.")
    parser.add_argument("--no-install", action="store_true", help="Do not download Node dependencies.")
    return parser.parse_args(argv)


def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _group_of(verification: dict) -> str:
    return str(verification.get("group") or DEFAULT_GROUP).strip().lower() or DEFAULT_GROUP


def _checkout_commit() -> str | None:
    git_dir = REPO_ROOT / ".git"
    if not git_dir.exists():
        return None
    try:
        result = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip().lower() if result.returncode == 0 else None


def _preflight(verifications: list[dict]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for verification in verifications:
        for component in verification.get("target_components", []):
            if not (REPO_ROOT / component).exists():
                missing.setdefault(verification["verification_id"], []).append(component)
    return missing


def _testcase_map(junit_path: Path) -> dict[str, ET.Element]:
    cases: dict[str, ET.Element] = {}
    if not junit_path.is_file():
        return cases
    try:
        root = ET.parse(junit_path).getroot()
    except ET.ParseError:
        return cases
    for case in root.iter("testcase"):
        classname = (case.get("classname") or "").split(".")[-1]
        cases[classname] = case
    return cases


def _classify_case(case: ET.Element | None) -> tuple[str, str]:
    if case is None:
        return VERIFICATION_ERROR, "test was not collected or not executed"
    if case.find("skipped") is not None:
        return VERIFICATION_ERROR, "test was skipped; no oracle was executed"
    failure = case.find("failure")
    error = case.find("error")
    if error is not None:
        message = (error.get("message") or "").strip() or (error.text or "").strip()[:500]
        return VERIFICATION_ERROR, message or "test errored"
    if failure is not None:
        message = (failure.get("message") or "").strip() or (failure.text or "").strip()[:500]
        # An AssertionError indicates the denunciated condition (or the test's oracle) refused
        # to pass; any other exception means the test could not run, i.e. it did NOT prove the violation.
        if "unparseable source" in message:
            return VERIFICATION_ERROR, message or "unparseable source"
        if "AssertionError" in message:
            return VERIFICATION_VIOLATION, message or "test failed"
        return VERIFICATION_ERROR, message or "test failed"
    return VERIFICATION_INCONCLUSIVE, (
        "test passed; its oracle does not distinguish the denounced condition "
        "and must not be read as evidence that the condition is gone"
    )


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


_STATUS_ORDER = [VERIFICATION_ERROR, VERIFICATION_VIOLATION, VERIFICATION_INCONCLUSIVE,
                 VERIFICATION_NOT_VERIFIABLE, VERIFICATION_FIXED]
_STATUS_TITLES = {
    VERIFICATION_ERROR: "Errores de ejecución",
    VERIFICATION_VIOLATION: "Violaciones detectadas",
    VERIFICATION_INCONCLUSIVE: "Sin conclusión",
    VERIFICATION_NOT_VERIFIABLE: "No verificables",
    VERIFICATION_FIXED: "Aprobados (oráculo validado en RED)",
}


def _write_reports(manifest: dict, payload: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = payload["counts"]
    total = len(payload["verifications"])
    violations = counts.get(VERIFICATION_VIOLATION, 0)
    inconclusive = counts.get(VERIFICATION_INCONCLUSIVE, 0)
    approved = counts.get(VERIFICATION_FIXED, 0)
    errors = counts.get(VERIFICATION_ERROR, 0)
    checkout = payload["checkout_commit"]
    if checkout is None:
        checkout_cell = "desconocido (sin metadatos `.git`)"
    elif payload["commit_matches"]:
        checkout_cell = f"`{checkout}` (coincide)"
    else:
        checkout_cell = f"`{checkout}` **(no coincide con el commit auditado)**"
    if total:
        summary = f"{violations}/{total} con violación · {approved}/{total} aprobados · {errors}/{total} con error"
        if inconclusive:
            summary += f" · {inconclusive}/{total} sin conclusión"
    else:
        summary = "sin verificaciones ejecutables"

    lines = [
        f"# Resultado de la ejecución — auditoría {payload['audit_id']}",
        "",
        "| | |",
        "|---|---|",
        f"| **Resultado global** | **{payload['overall_status']}** — {summary} |",
        f"| **Auditoría** | {payload['audit_id']} |",
        f"| **Suite** | `{payload['suite_id']}` · schema {manifest.get('schema_version', '?')} |",
        f"| **Commit auditado** | `{payload['source_commit']}` |",
        f"| **Checkout local** | {checkout_cell} |",
        f"| **Selección** | {', '.join(payload.get('selection') or ['all'])} · grupos: {', '.join(payload.get('groups_present') or []) or '—'} |",
        f"| **Ejecutado** | {payload['executed_at']} · {payload['platform']} · Python {payload['python']} |",
        "",
        "## Resumen por estado",
        "",
        "| Estado | Nº | Verificaciones |",
        "|---|---|---|",
    ]
    for status in _STATUS_ORDER:
        if counts.get(status):
            members = ", ".join(item["verification_id"] for item in payload["verifications"] if item["status"] == status)
            lines.append(f"| `{status}` | {counts[status]} | {members} |")

    grouped = {status: [item for item in payload["verifications"] if item["status"] == status]
               for status in _STATUS_ORDER}
    for status in _STATUS_ORDER:
        items = grouped[status]
        if not items:
            continue
        lines += ["", f"## {_STATUS_TITLES[status]} ({len(items)})", ""]
        for item in items:
            lines += [
                f"### `{item['verification_id']}` — hallazgo `{item['finding_id']}`",
                "",
                f"- **Prueba:** `{item['test_path']}` · estrategia `{item.get('strategy')}` · grupo `{item.get('group') or DEFAULT_GROUP}`",
                f"- **Comprueba que:** {item.get('covered_property')}",
                "- **Detalle:**",
                "",
            ]
            detail = (item.get("detail") or "").rstrip()
            if len(detail) > 1500:
                detail = detail[:1500] + "\n… (detalle truncado; ver report.json)"
            lines += [f"  {line}" for line in detail.splitlines()]
            lines.append("")

    if payload["limitations"]:
        lines += ["## Limitaciones declaradas", "", *[f"- {item}" for item in dict.fromkeys(payload["limitations"])], ""]
    disclaimer = (
        "Un `INCONCLUSIVE` indica que la comprobación no distinguió entre presencia y ausencia de la "
        "condición denunciada; no confirma una corrección. El `verification_status` original de cada "
        "hallazgo no cambia."
    )
    lines += [
        "",
        "## Leyenda y disclaimer",
        "",
        "| Estado | Significado |",
        "|---|---|",
        "| `VIOLATION_PRESENT` | La condición denunciada persiste en el ámbito comprobado. |",
        "| `VERIFIED_FIXED` | El test pasa en este checkout y su oráculo ya fue validado en RED; no implica conformidad global. |",
        "| `INCONCLUSIVE` | La prueba no pudo discriminar entre presencia y ausencia de la condición (un pase aislado no es prueba de corrección). |",
        "| `EXECUTION_ERROR` | El entorno no pudo certificar la comprobación. |",
        "| `NOT_VERIFIABLE` | Sin prueba ejecutable con los datos disponibles. |",
        "",
        disclaimer,
        "",
    ]
    (RESULTS_DIR / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    executed_at = datetime.now(UTC).isoformat()
    base = {"suite_id": "unknown", "audit_id": None, "source_commit": "",
            "checkout_commit": None, "commit_matches": None, "executed_at": executed_at,
            "python": platform.python_version(), "platform": platform.platform(),
            "verifications": [], "counts": {}, "limitations": [], "overall_status": "execution_error"}
    try:
        manifest = _load_manifest()
    except (OSError, json.JSONDecodeError) as error:
        base["limitations"] = [f"manifest.json could not be read: {error}"]
        base["overall_status"] = "execution_error"
        _write_reports({"schema_version": "?"}, base)
        print("[tallercito] ERROR: manifest.json no legible")
        return 2

    args = _parse_args(sys.argv[1:])
    verifications_all = manifest.get("verifications", [])
    groups_present = sorted({_group_of(v) for v in verifications_all})

    if args.list_groups:
        print("\n".join(groups_present))
        return 0

    only = [item.strip().lower() for item in args.only if item.strip()]
    if only:
        unknown = sorted(set(only) - set(groups_present))
        if unknown:
            limitations_note = f"Requested group(s) not present in the manifest: {', '.join(unknown)}."
        else:
            limitations_note = ""
        verifications = [v for v in verifications_all if _group_of(v) in set(only)]
    else:
        limitations_note = ""
        verifications = list(verifications_all)

    selection = only if only else ["all"]

    source_commit = str(manifest.get("source_commit", ""))
    checkout = _checkout_commit()
    limitations = list(manifest.get("limitations", []))
    if limitations_note:
        limitations.append(limitations_note)
    commit_matches = None if checkout is None else checkout == source_commit.lower()
    if commit_matches is False:
        limitations.append(f"The checkout ({checkout}) does not match the audited commit ({source_commit}); results verify corrections, not the original audit state.")
    elif checkout is None:
        limitations.append(".git metadata was not found; the checkout commit could not be verified.")

    missing = _preflight(verifications)
    missing_ids = set(missing)
    if missing_ids:
        paths = sorted({component for items in missing.values() for component in items})
        limitations.append(f"Preflight found missing components ({', '.join(paths)}); affected verifications cannot run.")

    src_dir = REPO_ROOT / "src"
    pythonpath = os.pathsep.join([str(src_dir if src_dir.is_dir() else REPO_ROOT), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)

    runnable = [v for v in verifications if v["verification_id"] not in missing_ids]
    results = []
    counts: dict[str, int] = {}
    env = {**os.environ, "PYTHONPATH": pythonpath, "TALLERCITO_REPO_ROOT": str(REPO_ROOT)}
    junit_path = RESULTS_DIR / "junit.xml"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    node_verifications = [v for v in runnable if v.get("framework", "pytest") != "pytest"]
    runnable_paths = [str(SUITE_ROOT / v["test_path"]) for v in runnable if v.get("framework", "pytest") == "pytest"]
    node_results = {}
    if node_verifications:
        try:
            from node_runtime import run_exported
            node_results, install_receipt = run_exported(REPO_ROOT, SUITE_ROOT, node_verifications,
                                                         install=not args.no_install)
            (RESULTS_DIR / "node-install.json").write_text(json.dumps(install_receipt, indent=2), encoding="utf-8")
            (RESULTS_DIR / "node-results.json").write_text(json.dumps(node_results, indent=2), encoding="utf-8")
            if install_receipt.get("status") == "failed":
                limitations.append("Node project dependency installation failed; only independently executable verifiers could run.")
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            limitations.append(f"Node execution unavailable: {type(error).__name__}")
    pytest_ran = False
    if runnable_paths:
        cmd = [sys.executable, "-m", "pytest", "--continue-on-collection-errors", *runnable_paths, "-q", f"--junitxml={junit_path}"]
        try:
            subprocess.run(cmd, cwd=SUITE_ROOT, env=env, capture_output=True, text=True, timeout=TEST_TIMEOUT_SECONDS, check=False)
            pytest_ran = True
        except subprocess.TimeoutExpired:
            limitations.append(f"pytest exceeded {TEST_TIMEOUT_SECONDS}s; affected verifications are EXECUTION_ERROR.")
        except OSError as error:
            limitations.append(f"pytest could not be launched: {error}")
    cases = _testcase_map(junit_path)

    for verification in verifications:
        vid = verification["verification_id"]
        if vid in missing_ids:
            status, message = VERIFICATION_ERROR, "preflight: missing components: " + ", ".join(missing[vid])
        elif verification.get("framework", "pytest") != "pytest":
            observation = node_results.get(vid, {})
            status = {"pass": VERIFICATION_INCONCLUSIVE, "violation": VERIFICATION_VIOLATION}.get(
                observation.get("classification"), VERIFICATION_ERROR)
            message = observation.get("detail", "Node verifier could not execute")
        elif runnable and not pytest_ran:
            status, message = VERIFICATION_ERROR, "pytest could not run; see results/junit.xml and limitations"
        else:
            classname = Path(verification["test_path"]).stem
            status, message = _classify_case(cases.get(classname))
        execution_passed = status == VERIFICATION_INCONCLUSIVE
        generation_status = verification.get("generation_status", "generated")
        if generation_status == "invalid":
            status, message = VERIFICATION_ERROR, "Oracle validation failed during generation; repair budget exhausted. " + message
        elif execution_passed:
            if generation_status in ("validated_red", "validated_red_green"):
                status, message = VERIFICATION_FIXED, "Validated RED oracle passes at this checkout within its declared scope."
            else:
                status, message = VERIFICATION_ERROR, "Test passed but its RED oracle has not been validated; generator validation required."
        counts[status] = counts.get(status, 0) + 1
        results.append({"verification_id": vid, "finding_id": verification["finding_id"],
                        "test_path": verification["test_path"], "status": status, "group": _group_of(verification),
                         "detail": message, "execution_passed": execution_passed, "strategy": verification.get("strategy"),
                        "covered_property": verification.get("covered_property")})

    if not verifications:
        overall, exit_code = "not_verifiable", 2
    elif any(item["status"] == VERIFICATION_VIOLATION for item in results):
        overall, exit_code = "violations_detected", 1
    elif any(item["status"] == VERIFICATION_ERROR for item in results):
        overall, exit_code = "execution_error", 2
    elif all(item["status"] == VERIFICATION_NOT_VERIFIABLE for item in results):
        overall, exit_code = "not_verifiable", 2
    elif any(item["status"] == VERIFICATION_INCONCLUSIVE for item in results):
        # No positive evidence of a violation was observed. The run succeeds but
        # is explicitly not a proof that the condition is gone.
        overall, exit_code = "inconclusive", 0
    else:
        overall, exit_code = "verified_within_scope", 0

    payload = dict(base, suite_id=manifest.get("suite_id", "unknown"), audit_id=manifest.get("audit_id"),
                   source_commit=source_commit, checkout_commit=checkout, commit_matches=commit_matches,
                   selection=selection, groups_present=groups_present,
                   verifications=results, counts=counts, limitations=limitations, overall_status=overall)
    _write_reports(manifest, payload)

    print(f"[tallercito] audit={payload['audit_id']} selection={','.join(selection)} verifications={len(results)} detected={counts.get(VERIFICATION_VIOLATION, 0)} result={overall}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
