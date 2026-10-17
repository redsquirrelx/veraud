"""Shared read-only verification that retained bytes belong to the named commit."""

import hashlib
import re
import subprocess
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True)
class CommitVerification:
    matched: bool
    reason: str
    blob_id: str | None = None


def verify_commit(repository, source, timeout):
    started = monotonic()
    if not repository.commit or not re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", repository.commit):
        return CommitVerification(False, "invalid_commit")
    if timeout <= 0:
        return CommitVerification(False, "verification_time_exhausted")
    if source.content is None:
        return CommitVerification(False, "source_content_unavailable")
    raw = source.content.encode("utf-8")
    # The existing inventory decodes utf-8-sig, but retains the original byte hash.
    if hashlib.sha256(raw).hexdigest() != source.content_hash:
        raw = b"\xef\xbb\xbf" + raw
    if hashlib.sha256(raw).hexdigest() != source.content_hash:
        return CommitVerification(False, "snapshot_content_hash_mismatch")
    try:
        result = subprocess.run(
            ["git", "-C", repository.root_path, "rev-parse", "--verify",
             f"{repository.commit}:{source.path}"],
            capture_output=True, timeout=min(5, timeout), check=False,
        )
    except subprocess.TimeoutExpired:
        return CommitVerification(False, "git_verification_timeout")
    except OSError:
        return CommitVerification(False, "git_unavailable")
    object_id = result.stdout.strip().decode("ascii", errors="replace")
    if result.returncode or len(object_id) not in (40, 64):
        return CommitVerification(False, "git_object_unavailable")
    blob = b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    digest = hashlib.sha1(blob).hexdigest() if len(object_id) == 40 else hashlib.sha256(blob).hexdigest()
    if digest == object_id:
        return CommitVerification(True, "verified", object_id)
    remaining = min(5, timeout) - (monotonic() - started)
    if remaining <= 0:
        return CommitVerification(False, "verification_time_exhausted", object_id)
    try:
        committed = subprocess.run(
            ["git", "-C", repository.root_path, "cat-file", "blob", object_id],
            capture_output=True, timeout=remaining, check=False,
        )
    except subprocess.TimeoutExpired:
        return CommitVerification(False, "git_verification_timeout", object_id)
    except OSError:
        return CommitVerification(False, "git_unavailable", object_id)
    if committed.returncode:
        return CommitVerification(False, "git_object_unavailable", object_id)
    # Only CRLF/LF equivalence is allowed. BOMs, whitespace, lone CR and all
    # other bytes remain significant; the snapshot's original hash is retained.
    if raw.replace(b"\r\n", b"\n") == committed.stdout.replace(b"\r\n", b"\n"):
        return CommitVerification(True, "line_endings_equivalent", object_id)
    return CommitVerification(False, "commit_blob_mismatch", object_id)


def matches_commit(repository, source, timeout):
    """Compatibility predicate; detailed verification distinguishes unavailable from different bytes."""
    return verify_commit(repository, source, timeout).matched
