"""Disposable audited-repo copy with hard caps; the copy carries the workspace."""

import shutil
from pathlib import Path

from .fs_guard import EXCLUDED_DIRS, is_excluded
from .repo_reader import PathSafetyError


def copy_repository(source: Path, destination: Path, *, max_files: int, max_bytes: int) -> dict:
    """Copy a repository tree into `destination`, skipping VCS/caches.

    Returns a report. Raises PathSafetyError when the caps are exceeded.
    """

    source = source.resolve()
    files = 0
    total = 0
    for path in source.rglob("*"):
        if path.is_dir():
            continue
        relative = path.relative_to(source)
        if set(relative.parts) & EXCLUDED_DIRS:
            continue
        if is_excluded(relative):
            continue
        try:
            total += path.stat().st_size
        except OSError:
            continue
        files += 1
        if files > max_files:
            shutil.rmtree(destination, ignore_errors=True)
            raise PathSafetyError(f"Repository has more than {max_files} files; refusing to copy for safety.")
        if total > max_bytes:
            shutil.rmtree(destination, ignore_errors=True)
            raise PathSafetyError(f"Repository exceeds {max_bytes} bytes; refusing to copy for safety.")
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if set(relative.parts) & EXCLUDED_DIRS:
            continue
        if is_excluded(relative):
            continue
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    return {"files": files, "bytes": total}
