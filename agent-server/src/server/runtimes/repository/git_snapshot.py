"""Read an immutable Git commit into an empty disposable directory, without checkout.

Only regular tracked blobs are supported. No hooks, filters, fetches, symlinks,
submodules or working-tree files are used.
"""

import os
import re
import subprocess
from pathlib import Path


def materialize_commit(repository: Path, destination: Path, commit: str, *, max_files: int, max_bytes: int) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise ValueError("Target commit must be a full 40-character Git hash")

    def git(*args, data=None):
        result = subprocess.run(
            ["git", "--no-replace-objects", "-C", str(repository), *args], input=data,
            capture_output=True, timeout=60, check=False,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_OPTIONAL_LOCKS": "0"})
        if result.returncode:
            raise ValueError("Requested commit is unavailable in the recorded repository; no checkout was executed")
        return result.stdout

    top = Path(git("rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
    if top != repository.resolve():
        raise ValueError("Recorded repository must be the Git checkout root; parent repository fallback is forbidden")
    resolved = git("rev-parse", "--verify", f"{commit}^{{commit}}").decode("ascii").strip()
    if resolved.lower() != commit.lower():
        raise ValueError("Requested commit did not resolve to the exact commit")
    rows = [row for row in git("ls-tree", "-r", "-z", resolved).split(b"\0") if row]
    if len(rows) > max_files:
        raise ValueError("Commit snapshot exceeds the configured file limit")
    entries = []
    seen = set()
    root = destination.resolve()
    for row in rows:
        metadata, raw_path = row.split(b"\t", 1)
        mode, kind, oid = metadata.split()
        path = raw_path.decode("utf-8")
        parts = path.split("/")
        if mode not in (b"100644", b"100755") or kind != b"blob":
            raise ValueError("Commit snapshot contains unsupported symlinks or submodules")
        if any(part in ("", ".", "..") or part.lower() in (".git", ".tallercito") for part in parts) or "\\" in path or ":" in path:
            raise ValueError("Commit snapshot contains an unsafe or reserved path")
        target = root.joinpath(*parts).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Commit snapshot path escapes its destination")
        key = os.path.normcase(str(target))
        if key in seen:
            raise ValueError("Commit contains colliding paths on this platform")
        seen.add(key)
        entries.append((target, oid, mode))
    if not entries:
        raise ValueError("Requested commit has no regular tracked files")
    objects = b"".join(oid + b"\n" for _, oid, _ in entries)
    sizes = git("cat-file", "--batch-check=%(objecttype) %(objectsize)", data=objects).splitlines()
    if len(sizes) != len(entries) or any(not size.startswith(b"blob ") for size in sizes):
        raise ValueError("Commit snapshot contains unavailable Git objects")
    if sum(int(size.split()[1]) for size in sizes) > max_bytes:
        raise ValueError("Commit snapshot exceeds the configured byte limit")
    blobs = git("cat-file", "--batch", data=objects)
    offset = 0
    for target, oid, mode in entries:
        end = blobs.index(b"\n", offset)
        actual_oid, kind, size = blobs[offset:end].split()
        length = int(size)
        if actual_oid != oid or kind != b"blob":
            raise ValueError("Git blob identity mismatch")
        start = end + 1
        content = blobs[start:start + length]
        if len(content) != length or blobs[start + length:start + length + 1] != b"\n":
            raise ValueError("Truncated Git blob")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        if mode == b"100755":
            target.chmod(0o755)
        offset = start + length + 1
    return resolved.lower()
