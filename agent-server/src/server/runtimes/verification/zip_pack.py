"""Shared primitives for building and executing portable verification suites.

Deterministic and offline: no LLM, no network access. Both the finding-test
generator and the testability probe build their ``.tallercito/`` packages with
these helpers so the layout, safety checks and ZIP mechanics stay identical.
"""

import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from . import SUITE_ROOT_NAME, TEMPLATES_DIR

__all__ = [
    "SUITE_ROOT_NAME",
    "TEMPLATES_DIR",
    "SuitePackError",
    "copy_templates",
    "safe_extract",
    "stage_suite_root",
    "try_uv_lock",
    "write_suite_zip",
]


class SuitePackError(Exception):
    """The suite package could not be built or extracted safely."""


def stage_suite_root() -> tuple[Path, Path]:
    """Create a temporary staging area with the ``.tallercito/`` skeleton.

    Returns ``(stage, suite_root)``. The caller owns ``shutil.rmtree(stage)``.
    """

    stage = Path(tempfile.mkdtemp(prefix="tallercito-suite-"))
    root = stage / SUITE_ROOT_NAME
    for directory in (root / "tests", root / "docs", root / "results"):
        directory.mkdir(parents=True, exist_ok=True)
    return stage, root


def copy_templates(root: Path, *, readme_replacements: dict[str, str] | None = None) -> None:
    """Copy the maintained launcher/runner templates into ``root``."""

    for source in TEMPLATES_DIR.iterdir():
        if source.is_file():
            shutil.copyfile(source, root / source.name)
    readme = root / "README.md"
    if readme.is_file() and readme_replacements:
        text = readme.read_text(encoding="utf-8")
        for placeholder, value in readme_replacements.items():
            text = text.replace(placeholder, value)
        readme.write_text(text, encoding="utf-8")
    run_sh = root / "run.sh"
    if run_sh.is_file():
        run_sh.chmod(0o755)


def try_uv_lock(root: Path, *, timeout_seconds: float = 300) -> str | None:
    """Resolve a real ``uv.lock`` in ``root``; return a limitation note on failure."""

    uv = shutil.which("uv")
    if uv is None:
        return "uv was not available at packaging time; the suite resolves dependencies at first run and is not fully reproducible."
    try:
        proc = subprocess.run([uv, "lock"], cwd=root, capture_output=True, text=True, timeout=timeout_seconds, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return f"uv.lock could not be resolved at packaging time ({error}); the suite resolves dependencies at first run and is not fully reproducible."
    if proc.returncode == 0 and (root / "uv.lock").is_file():
        return None
    detail = (proc.stderr or "").strip()[:200] or "uv lock failed"
    return f"uv.lock could not be resolved at packaging time ({detail}); the suite resolves dependencies at first run and is not fully reproducible."


def write_suite_zip(stage: Path, root: Path, output_zip: Path) -> Path:
    """Write ``.tallercito/`` (``root``) as the only top-level folder of the ZIP."""

    output_zip = Path(output_zip)
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    if output_zip.exists():
        output_zip.unlink()
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(stage).as_posix())
    return output_zip


def safe_extract(zip_path: Path, destination: Path) -> None:
    """Extract ``zip_path`` refusing entries that escape ``destination``."""

    destination_resolved = Path(destination).resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            candidate = (destination_resolved / member).resolve()
            try:
                candidate.relative_to(destination_resolved)
            except ValueError as error:
                raise SuitePackError(f"Archive entry escapes destination: {member!r}") from error
        archive.extractall(destination)
