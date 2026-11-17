"""Workspace writer: the only write path available to the coding loop.

Writes are confined to a disposable workspace under the run's working copy.
The audited repository is never written to. Caps apply per file and in
aggregate; only `.py` payloads may be written.
"""

from pathlib import Path

from .fs_guard import PathSafetyError, ensure_relative, resolve_within

TESTS_PREFIX = Path(".tallercito") / "tests"


class WorkspaceWriter:
    def __init__(self, workspace_root: str | Path, *, max_test_file_bytes: int = 64_000, max_written_bytes: int = 256_000):
        self.root = Path(workspace_root).resolve()
        if self.root.exists() and not self.root.is_dir():
            raise PathSafetyError(f"Workspace is not a directory: {self.root}")
        self.max_test_file_bytes = max_test_file_bytes
        self.max_written_bytes = max_written_bytes
        self.written_bytes = 0

    def write_test_file(self, relative_path: str, content: str) -> dict:
        candidate = ensure_relative(relative_path)
        if candidate.suffix not in {".py", ".ts", ".tsx", ".js", ".mjs"}:
            raise PathSafetyError(f"Unsupported test file extension: {relative_path}")
        if not self._under_tests_prefix(candidate):
            raise PathSafetyError(
                f"Writes are confined to {TESTS_PREFIX.as_posix()}/: {relative_path}")
        data = content.encode("utf-8")
        if len(data) > self.max_test_file_bytes:
            raise PathSafetyError(
                f"Test file exceeds the {self.max_test_file_bytes}-byte cap: {relative_path}")
        if self.written_bytes + len(data) > self.max_written_bytes:
            raise PathSafetyError(
                f"Total written-bytes cap ({self.max_written_bytes}) would be exceeded: {relative_path}")
        resolved = resolve_within(self.root, candidate)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(data)
        self.written_bytes += len(data)
        return {"path": candidate.as_posix(), "bytes": len(data), "total_written_bytes": self.written_bytes}

    @staticmethod
    def _under_tests_prefix(candidate: Path) -> bool:
        parts = candidate.parts
        return len(parts) >= 3 and parts[0] == TESTS_PREFIX.parts[0] and parts[1] == TESTS_PREFIX.parts[1]

    def total_written_bytes(self) -> int:
        return self.written_bytes
