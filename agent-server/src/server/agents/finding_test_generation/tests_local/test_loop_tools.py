"""Bounded tool-layer contracts (no LLM, no network)."""

import pytest

from server.runtimes.verification.tools.fs_guard import PathSafetyError
from server.runtimes.verification.tools.repo_reader import RepoReader
from server.runtimes.verification.tools.sandbox import (
    LocalSubprocessExecutor,
    NullSandbox,
    SandboxPlan,
)
from server.runtimes.verification.tools.test_runner import (
    CLASSIFICATION_TECHNICAL,
    CLASSIFICATION_VIOLATION,
    WorkspaceRunner,
)
from server.runtimes.verification.tools.workspace_writer import WorkspaceWriter


def _make_repo(root):
    (root / "src/pkg").mkdir(parents=True)
    (root / "src/pkg/mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=hunter2\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git/config").write_text("[core]\n", encoding="utf-8")


def test_read_file_bounds_and_exclusions(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    big = root / "src/pkg/big.py"
    big.write_text("".join(f"line{i}\n" for i in range(200)), encoding="utf-8")

    reader = RepoReader(root, max_read_bytes_per_file=64, max_files_read=200)
    result = reader.read_file("src/pkg/big.py", start_line=1, end_line=1000)
    assert result["truncated"] is True
    assert len(result["content"].encode("utf-8")) <= 64

    with pytest.raises(PathSafetyError):
        reader.read_file("../outside.py")
    with pytest.raises(PathSafetyError):
        reader.read_file("/etc/passwd")
    with pytest.raises(PathSafetyError):
        reader.read_file(".env")


def test_list_files_skips_secrets_and_vcs(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    reader = RepoReader(root, max_files_read=200)
    paths = [entry["path"] for entry in reader.list_files(".", limit=50)]
    assert "src/pkg/mod.py" in paths
    assert ".env" not in paths
    assert not any(path.startswith(".git") for path in paths)


def test_workspace_writer_confines_writes(tmp_path):
    writer = WorkspaceWriter(tmp_path, max_test_file_bytes=64, max_written_bytes=1024)
    writer.write_test_file(".tallercito/tests/test_ok.py", "def test_x():\n    assert True\n")
    with pytest.raises(PathSafetyError):
        writer.write_test_file(str(tmp_path / "outside.py"), "x = 1\n")
    with pytest.raises(PathSafetyError):
        writer.write_test_file("tests/test_out.py", "x = 1\n")
    with pytest.raises(PathSafetyError):
        writer.write_test_file(".tallercito/tests/test_nope.txt", "x = 1\n")
    with pytest.raises(PathSafetyError):
        writer.write_test_file(".tallercito/tests/test_big.py", "x = '" + "a" * 64 + "'\n")


def test_null_sandbox_refuses_execution(tmp_path):
    from pathlib import Path

    result = NullSandbox().run(SandboxPlan(command=["python", "-m", "pytest"], cwd=Path(tmp_path),
                                           env={}, timeout_seconds=1, max_output_bytes=16))
    assert result.available is False
    assert "sandbox" in (result.reason or "").lower()


def _write_test(root, name, body):
    path = root / ".tallercito" / "tests"
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(body, encoding="utf-8")


def test_runner_classifies_violation_and_technical(tmp_path):
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "mod.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    runner = WorkspaceRunner(tmp_path, executor=LocalSubprocessExecutor(),
                             timeout_seconds=60, max_output_bytes=16_000)

    _write_test(tmp_path, "test_fail.py", "def test_fail():\n    assert 1 + 1 == 3\n")
    assert runner.run_pytest(".tallercito/tests/test_fail.py").classification == CLASSIFICATION_VIOLATION

    _write_test(tmp_path, "test_error.py", "import nonexistent_module_xyz\n\ndef test_broken():\n    assert True\n")
    assert runner.run_pytest(".tallercito/tests/test_error.py").classification == CLASSIFICATION_TECHNICAL


def test_trivial_reason_detects_empty_tautology_and_skip():
    from server.runtimes.verification.tools.test_runner import trivial_reason

    assert trivial_reason("") is not None
    assert trivial_reason("def test_x():\n    pass\n") is not None
    assert trivial_reason("def test_x():\n    assert True\n") is not None
    assert trivial_reason("import pytest\n@pytest.mark.skip(reason='x')\ndef test_x():\n    assert 1 == 1\n") is not None
    assert trivial_reason("def test_x():\n    assert 1 + 1 == 2\n") is None
