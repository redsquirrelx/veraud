"""Commit diagnostics distinguish changed bytes from unavailable verification."""

import hashlib
import subprocess
from types import SimpleNamespace

import pytest

from server.runtimes.investigation.provenance import verify_commit


@pytest.mark.parametrize("raw", [b"print('ok')\n", b"\xef\xbb\xbfprint('ok')\r\n"])
def test_verification_preserves_retained_bytes_including_bom_and_line_endings(monkeypatch, raw):
    source = SimpleNamespace(content=raw.decode("utf-8-sig"), content_hash=hashlib.sha256(raw).hexdigest(), path="source.py")
    repository = SimpleNamespace(commit="a" * 40, root_path="checkout")
    blob = b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=hashlib.sha1(blob).hexdigest().encode("ascii")))
    assert verify_commit(repository, source, 10).matched
    source.content += "# changed\n"
    source.content_hash = hashlib.sha256(source.content.encode("utf-8")).hexdigest()
    result = verify_commit(repository, source, 10)
    assert not result.matched and result.reason == "commit_blob_mismatch"


@pytest.mark.parametrize(("failure", "reason"), [
    (OSError("PRIVATE_GIT_DETAILS"), "git_unavailable"),
    (subprocess.TimeoutExpired("PRIVATE_COMMAND", 5), "git_verification_timeout"),
])
def test_operational_failure_is_not_reported_as_different_commit_bytes(monkeypatch, failure, reason):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(subprocess, "run", fail)
    source = SimpleNamespace(content="x", content_hash=hashlib.sha256(b"x").hexdigest(), path="source.py")
    result = verify_commit(SimpleNamespace(commit="a" * 40, root_path="checkout"), source, 10)
    assert not result.matched and result.reason == reason
    assert "PRIVATE" not in repr(result)


@pytest.mark.parametrize(("committed", "retained", "expected"), [
    (b"a\nb\n", b"a\r\nb\r\n", True),
    (b"a\r\nb\r\n", b"a\nb\n", True),
    (b"a\r\nb\n", b"a\nb\r\n", True),
    (b"a\nb\n", b"a \r\nb\r\n", False),
    (b"a\nb\n", b"a\r\nc\r\n", False),
    (b"a\nb\n", b"\xef\xbb\xbfa\r\nb\r\n", False),
    (b"a\nb\n", b"a\rb\n", False),
])
def test_only_line_ending_differences_are_equivalent(monkeypatch, committed, retained, expected):
    blob = b"blob " + str(len(committed)).encode("ascii") + b"\0" + committed
    object_id = hashlib.sha1(blob).hexdigest()
    def git(args, **kwargs):
        output = object_id.encode("ascii") if "rev-parse" in args else committed
        return SimpleNamespace(returncode=0, stdout=output)

    monkeypatch.setattr(subprocess, "run", git)
    source = SimpleNamespace(content=retained.decode("utf-8-sig"),
        content_hash=hashlib.sha256(retained).hexdigest(), path="source.py")
    result = verify_commit(SimpleNamespace(commit="a" * 40, root_path="checkout"), source, 10)
    assert result.matched is expected
    assert result.reason == ("line_endings_equivalent" if expected else "commit_blob_mismatch")
    assert result.blob_id == object_id
