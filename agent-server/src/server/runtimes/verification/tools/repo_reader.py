"""Bounded, read-only repository access for the coding loop."""

import fnmatch
from pathlib import Path

from .fs_guard import (
    EXCLUDED_DIRS,
    EXCLUDED_NAMES,
    PathSafetyError,
    is_excluded,
    resolve_within,
)


class RepoReader:
    """Reads from a repository without mutating it."""

    def __init__(self, repo_root: str | Path, *, max_read_bytes_per_file: int = 64_000, max_files_read: int = 200):
        self.root = Path(repo_root).resolve()
        if not self.root.is_dir():
            raise PathSafetyError(f"Repository root is not a directory: {self.root}")
        self.max_read_bytes = max_read_bytes_per_file
        self.max_files_read = max_files_read
        self.files_read = 0

    # -- list_files ----------------------------------------------------------
    def list_files(self, path: str = "", limit: int = 100, pattern: str | None = None) -> list[dict]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        base = resolve_within(self.root, path or ".")
        if not base.exists():
            raise PathSafetyError(f"Not found: {path or '.'}")
        entries: list[dict] = []
        if base.is_file():
            rel = base.relative_to(self.root)
            if not is_excluded(rel):
                entries.append(self._entry(rel))
            return entries
        for candidate in sorted(base.rglob("*")):
            if len(entries) >= limit:
                break
            if candidate.is_dir():
                continue
            rel = candidate.relative_to(self.root)
            if is_excluded(rel):
                continue
            if pattern and not fnmatch.fnmatch(candidate.name, pattern):
                continue
            entries.append(self._entry(rel))
        return entries

    def _entry(self, relative: Path) -> dict:
        full = self.root / relative
        try:
            size = full.stat().st_size
        except OSError:
            size = -1
        return {"path": relative.as_posix(), "bytes": size}

    # -- read_file -------------------------------------------------------------
    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> dict:
        if self.files_read >= self.max_files_read:
            raise PathSafetyError(f"File read budget exhausted ({self.max_files_read} files).")
        resolved = resolve_within(self.root, path)
        if not resolved.is_file():
            raise PathSafetyError(f"Not a file: {path}")
        relative = resolved.relative_to(self.root)
        if is_excluded(relative):
            raise PathSafetyError(f"Refusing to read excluded file: {path}")
        data = resolved.read_bytes()
        if len(data) > self.max_read_bytes:
            note = f"File exceeds the {self.max_read_bytes}-byte read budget; content truncated."
            data = data[: self.max_read_bytes]
        else:
            note = None
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            raise PathSafetyError(f"Refusing to read non-UTF-8 file: {path}") from None
        lines = content.splitlines()
        start = max(1, start_line)
        end = end_line if end_line is not None else len(lines)
        if end < start:
            raise ValueError("end_line must be >= start_line")
        selected = lines[start - 1 : end]
        self.files_read += 1
        return {"path": relative.as_posix(), "start_line": start, "end_line": min(end, len(lines)),
                "line_count": len(lines), "truncated": note is not None or end < len(lines),
                "note": note, "content": "\n".join(selected)}

    def relative(self, path: str) -> str:
        return resolve_within(self.root, path).relative_to(self.root).as_posix()


__all__ = ["EXCLUDED_DIRS", "EXCLUDED_NAMES", "PathSafetyError", "RepoReader"]
