"""Portable Node verification execution. Stdlib only; never imports an LLM.

Call prepare only on a disposable repository copy. Dependencies are installed
with lifecycle scripts disabled and an empty user configuration. This is NOT
a security sandbox: imported project code still needs an OS isolation boundary.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

JS_SUFFIXES = {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}
HARNESS = {"name": "tallercito-node-verification", "version": "1.0.0", "private": True,
           "type": "module", "dependencies": {
               "vitest": "4.0.18", "typescript": "5.9.3", "jsdom": "26.1.0",
               "react": "19.2.0", "react-dom": "19.2.0",
               "@testing-library/react": "16.3.0", "@testing-library/dom": "10.4.1"}}


def language_for(components):
    suffixes = {Path(p).suffix.lower() for p in components}
    if suffixes & JS_SUFFIXES:
        return "typescript" if suffixes & {".ts", ".tsx", ".mts", ".cts"} else "javascript"
    return "python"


def clean_env(root):
    env = {key: os.environ[key] for key in ("PATH", "SystemRoot", "SystemDrive", "TEMP", "TMP")
           if key in os.environ}
    home = root / ".tallercito" / "node-home"
    home.mkdir(parents=True, exist_ok=True)
    config = home / "empty.npmrc"
    config.touch(exist_ok=True)
    env.update({"HOME": str(home), "USERPROFILE": str(home), "CI": "true",
                "NPM_CONFIG_USERCONFIG": str(config), "NPM_CONFIG_GLOBALCONFIG": str(home / "global.npmrc"),
                "NPM_CONFIG_CACHE": str(home / "cache"), "NPM_CONFIG_IGNORE_SCRIPTS": "true",
                "TALLERCITO_REPO_ROOT": str(root)})
    return env


def command(argv, root, timeout=120):
    """Execute a fixed argv, suppressing credentials and killing child trees on timeout."""
    env = clean_env(root)
    executable = shutil.which(argv[0], path=env.get("PATH"))
    if not executable:
        return {"exit_code": None, "stdout": "", "stderr": f"{argv[0]} unavailable", "timeout": False}
    argv = [executable, *argv[1:]]
    if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
        # Fixed package-manager args only; no model-supplied shell command.
        argv = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", subprocess.list2cmdline(argv)]
    with subprocess.Popen(argv, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", errors="replace",
                          start_new_session=os.name != "nt") as proc:
        try:
            out, err = proc.communicate(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, check=False)
            else:
                import signal
                os.killpg(proc.pid, signal.SIGKILL)
            out, err = proc.communicate()
            timed_out = True
    return {"exit_code": proc.returncode, "stdout": out[-64000:], "stderr": err[-64000:], "timeout": timed_out}


def install_project(root, timeout=240, enabled=True):
    """Detect Node and attempt its lock-preserving installation in a COPY only."""
    root = Path(root).resolve()
    if not (root / "package.json").is_file():
        return {"status": "not_node"}
    if not enabled:
        return {"status": "disabled"}
    if (root / "pnpm-lock.yaml").is_file():
        argv = ["pnpm", "install", "--frozen-lockfile", "--ignore-scripts"]
    elif (root / "package-lock.json").is_file():
        argv = ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"]
    elif (root / "yarn.lock").is_file():
        argv = ["yarn", "install", "--frozen-lockfile", "--ignore-scripts"]
    else:
        argv = ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"]
    # Do not use repository .npmrc (may reference credentials or arbitrary registries).
    npmrc = root / ".npmrc"
    if npmrc.is_file():
        npmrc.unlink()  # root is disposable, never the audited checkout
    result = command(argv, root, timeout)
    return {"status": "installed" if result["exit_code"] == 0 else "failed",
            "manager": argv[0], "timeout": result["timeout"], "exit_code": result["exit_code"]}


def prepare(root, timeout=240, enabled=True):
    root = Path(root).resolve()
    receipt = install_project(root, timeout, enabled)
    tooling = root / ".tallercito"
    tooling.mkdir(parents=True, exist_ok=True)
    (tooling / "package.json").write_text(json.dumps(HARNESS, indent=2), encoding="utf-8")
    if enabled and not (tooling / "node_modules" / "vitest" / "vitest.mjs").is_file():
        result = command(["npm", "install", "--prefix", str(tooling), "--ignore-scripts", "--no-audit", "--no-fund"], root, timeout)
        receipt["harness"] = "installed" if result["exit_code"] == 0 else "failed"
    else:
        receipt["harness"] = "available" if (tooling / "node_modules" / "vitest" / "vitest.mjs").is_file() else "disabled"
    # Fixed, agent-owned config; never evaluates the project's vite/vitest config or loads .env.
    config = '''import { defineConfig } from 'vitest/config';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
const root = process.env.TALLERCITO_REPO_ROOT;
const suite = path.dirname(fileURLToPath(import.meta.url));
const modulePath = (name) => fs.existsSync(path.join(root, 'node_modules', name, 'package.json'))
  ? path.join(root, 'node_modules', name) : path.join(suite, 'node_modules', name);
export default defineConfig({
  root, envDir: false,
  resolve: { alias: { '@': root, 'react': modulePath('react'), 'react-dom': modulePath('react-dom') } },
  esbuild: { jsx: 'automatic' },
  test: { include: ['.tallercito/tests/**/*.test.{ts,tsx,js,mjs}'],
    environment: 'node', globals: false, fileParallelism: false,
    testTimeout: 10000, hookTimeout: 10000, maxWorkers: 1 },
});
'''
    (tooling / "vitest.config.mjs").write_text(config, encoding="utf-8")
    (root / ".tallercito" / "node-install.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def classify_cases(cases, exit_code):
    """All cases matter; syntax/import/environment/skips must never become RED/GREEN."""
    if not cases or exit_code not in (0, 1):
        return "technical_failure"
    if any(c["kind"] in ("error", "skipped") for c in cases):
        return "technical_failure"
    if any(c["kind"] == "failed" for c in cases):
        return "violation"
    return "pass" if exit_code == 0 else "technical_failure"


def run(root, test_path, framework="vitest", timeout=120):
    root = Path(root).resolve()
    target = (root / test_path).resolve()
    if not target.is_relative_to(root / ".tallercito" / "tests"):
        raise ValueError("Test outside the verification workspace")
    cases = []
    if framework == "node:test":
        result = command(["node", "--test", "--test-reporter=tap", str(target)], root, timeout)
        blocks = re.split(r"(?m)^(?=(?:not )?ok \d+)", result["stdout"])
        for block in blocks:
            if not re.match(r"(?:not )?ok \d+", block):
                continue
            failed = block.startswith("not ok")
            kind = ("skipped" if "# SKIP" in block or "# TODO" in block else
                    "failed" if failed and "ERR_ASSERTION" in block else "error" if failed else "passed")
            cases.append({"kind": kind, "message": block[:4000]})
    else:
        tooling = root / ".tallercito"
        report = tooling / "vitest-result.json"
        report.unlink(missing_ok=True)
        result = command(["node", str(tooling / "node_modules" / "vitest" / "vitest.mjs"),
                          "run", "--config", str(tooling / "vitest.config.mjs"),
                          "--reporter=json", "--outputFile", str(report), str(target)], root, timeout)
        if report.is_file():
            data = json.loads(report.read_text(encoding="utf-8"))
            result["report"] = data
            for file in data.get("testResults", []):
                for assertion in file.get("assertionResults", []):
                    message = "\n".join(assertion.get("failureMessages", []))
                    status = assertion.get("status")
                    kind = ("passed" if status == "passed" else "skipped" if status in ("pending", "todo", "skipped") else
                            "failed" if "AssertionError" in message else "error")
                    cases.append({"kind": kind, "message": message[:4000], "name": assertion.get("fullName")})
    classification = "timeout" if result["timeout"] else classify_cases(cases, result["exit_code"])
    detail = next((c["message"] for c in cases if c["kind"] != "passed"), "Tests passed within declared scope")
    if not cases:
        detail = json.dumps(result.get("report", {}), ensure_ascii=False)[-6000:] + (result["stdout"] + result["stderr"])[-4000:]
    return {"classification": classification, "detail": detail, "tests": cases, **result}


def trivial_reason(source):
    if not re.search(r"\b(?:test|it)\s*\(", source):
        return "No executable test declaration"
    if not re.search(r"\b(?:expect|assert)\s*[.(]", source):
        return "No assertion"
    if re.search(r"\b(?:test|it)\.(?:skip|todo)|expect\(true\)\.toBe\(true\)", source):
        return "Skipped or tautological test"
    return None


def run_exported(repo, suite, verifications, install=True):
    """Exported suites install/run Node only in a disposable copy, never checkout."""
    repo, suite = Path(repo).resolve(), Path(suite).resolve()
    observed = {}
    with tempfile.TemporaryDirectory(prefix="tallercito-node-") as temporary:
        root = Path(temporary) / "repository"

        def ignore(directory, names):
            return [name for name in names if name in {
                ".git", ".tallercito", "node_modules", ".venv", "__pycache__", ".next", "dist",
                "credentials.json", ".npmrc", ".yarnrc.yml"}
                or name.startswith(".env") or Path(directory, name).is_symlink()
                or name.endswith((".pem", ".key", ".pfx"))]

        shutil.copytree(repo, root, ignore=ignore)
        tests = root / ".tallercito" / "tests"
        tests.mkdir(parents=True)
        for entry in verifications:
            relative = Path(entry["test_path"])
            source = (suite / relative).resolve()
            if not source.is_relative_to(suite / "tests"):
                raise ValueError("Test path escapes suite")
            target = root / ".tallercito" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        receipt = prepare(root, enabled=install)
        for entry in verifications:
            observed[entry["verification_id"]] = run(root, ".tallercito/" + entry["test_path"],
                                                       entry.get("framework", "vitest"))
        return observed, receipt
