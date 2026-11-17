"""Path safety shared by the bounded tools.

Read paths must stay inside the repository root; write paths must stay inside
the disposable workspace. Absolute paths, `..` traversal and symlinks that
escape the allowed root are rejected before any I/O happens.
"""

import os
from pathlib import Path

EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "node_modules", ".venv", "venv", ".tallercito", ".next", "out", "coverage",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", "__pycache__", "dist", "build",
}
EXCLUDED_NAMES = {".env", ".env.local", ".env.production", ".env.development", "credentials.json", "id_rsa"}
EXCLUDED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".sqlite3", ".db", ".zip", ".tar", ".gz", ".png", ".jpg", ".jpeg", ".pdf", ".xlsx"}


class PathSafetyError(ValueError):
    pass


def _real(path: Path) -> Path:
    return Path(os.path.realpath(path))


def ensure_relative(relative: str | os.PathLike) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise PathSafetyError(f"Absolute paths are not allowed: {relative}")
    if any(part == ".." for part in candidate.parts):
        raise PathSafetyError(f"Path traversal is not allowed: {relative}")
    return candidate


def resolve_within(root: Path, relative: str | os.PathLike) -> Path:
    candidate = ensure_relative(relative)
    root = _real(root)
    resolved = _real(root / candidate)
    if resolved != root and root not in resolved.parents:
        raise PathSafetyError(f"Path escapes the allowed root: {relative}")
    return resolved


def is_excluded(relative: Path) -> bool:
    parts = set(relative.parts)
    if parts & EXCLUDED_DIRS:
        return True
    name = relative.name.lower()
    if name in EXCLUDED_NAMES or name.startswith(".env"):
        return True
    return relative.suffix.lower() in EXCLUDED_SUFFIXES
