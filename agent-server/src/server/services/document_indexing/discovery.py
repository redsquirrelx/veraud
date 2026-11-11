"""Discover committed Markdown strictly inside the selected Git directory."""

import subprocess
from pathlib import Path

from ..repository_analysis.inventory import EXCLUDED_DIRECTORIES

EXCLUSIONS = EXCLUDED_DIRECTORIES | frozenset(
    {
        ".cache",
        ".nuxt",
        ".output",
        ".svelte-kit",
        ".yarn",
        ".pnpm-store",
        ".nox",
        ".turbo",
        ".vercel",
        ".angular",
        ".docusaurus",
        ".vite",
        ".parcel-cache",
        "coverage",
        "htmlcov",
        "site",
        "_site",
        "_build",
        "generated",
        "__generated__",
    }
)


def git(root: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise ValueError(
            "Cannot read repository commit: "
            + result.stderr.decode("utf-8", errors="replace").strip()
        )
    return result.stdout


def discover(root: Path, commit: str) -> list[tuple[str, str]]:
    files = []
    # ls-tree is scoped to -C's directory and emits paths relative to it.
    # Do not use --full-tree or replace root with --show-toplevel.
    for entry in git(root, "ls-tree", "-rz", commit).split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if (
            mode in {"100644", "100755"}
            and kind == "blob"
            and Path(path).suffix.casefold() == ".md"
            and not any(part.casefold() in EXCLUSIONS for part in path.split("/")[:-1])
        ):
            files.append((path, oid))
    return sorted(files)
