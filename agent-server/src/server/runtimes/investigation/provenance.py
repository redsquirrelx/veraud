"""Shared read-only verification that retained bytes belong to the named commit."""

import hashlib
import re
import subprocess


def matches_commit(repository, source, timeout):
    if not repository.commit or not re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", repository.commit):
        return False
    if timeout <= 0 or source.content is None:
        return False
    raw = source.content.encode("utf-8")
    # The existing inventory decodes utf-8-sig, but retains the original byte hash.
    if hashlib.sha256(raw).hexdigest() != source.content_hash:
        raw = b"\xef\xbb\xbf" + raw
    if hashlib.sha256(raw).hexdigest() != source.content_hash:
        return False
    try:
        result = subprocess.run(
            ["git", "-C", repository.root_path, "rev-parse", "--verify",
             f"{repository.commit}:{source.path}"],
            capture_output=True, timeout=min(5, timeout), check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    object_id = result.stdout.strip().decode("ascii", errors="replace")
    if result.returncode or len(object_id) not in (40, 64):
        return False
    blob = b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    digest = hashlib.sha1(blob).hexdigest() if len(object_id) == 40 else hashlib.sha256(blob).hexdigest()
    return digest == object_id
