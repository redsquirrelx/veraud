"""Diagnostic heuristics for generated tests.

These flags are advisory only: they never invalidate a verification by
themselves and never block a gate decision. They exist so a reviewer (or the
report) can spot suspicious test shapes; final validity always depends on the
execution result and the oracle, exactly as with any other verification.
"""

import re

_PATCH_RE = re.compile(r"\b(mock\.)?patch(\.object|\.dict)?\s*\(")
_MOCK_TOKEN_RE = re.compile(r"\b(mock|Mock|MagicMock|AsyncMock)\b")
_ASSERT_MOCK_RE = re.compile(r"\b(mock|called|call_count|call_args)\b", re.IGNORECASE)


def subject_tokens(components: list[str], dotted_names: list[str]) -> list[str]:
    tokens = list(components)
    tokens.extend(dotted_names)
    for component in components:
        parts = [part for part in component.split("/") if part]
        stem = parts[-1].rsplit(".", 1)[0]
        if stem not in tokens:
            tokens.append(stem)
        for index in range(len(parts) - 1):
            tokens.append("/".join(parts[: index + 1]))
    return list(dict.fromkeys(token for token in tokens if token))


def suspicion_flags(source: str | None, subject: list[str] | None = None) -> list[str]:
    """Return a list of diagnostic flags; empty when nothing looks suspicious."""
    flags: list[str] = []
    if not source:
        return flags
    subject = subject or []
    touches_subject = any(token and token in source for token in subject)
    if _PATCH_RE.search(source):
        flags.append(
            "uses mock.patch/patch.object: review whether it isolates a collaborator "
            "or substitutes the subject under verification (patches the target)",
        )
    observes_subject = bool(re.search(r"\b(fn|offenders|assess|build|scan_scope)\s*\(", source))
    assert_lines = [line.strip() for line in source.splitlines() if line.strip().startswith(("assert ", "assert("))]
    if assert_lines and observes_subject is False and all(_ASSERT_MOCK_RE.search(line) for line in assert_lines):
        flags.append("asserts only mock behaviour; the code under test is never observed")
    if _MOCK_TOKEN_RE.search(source) and not touches_subject:
        flags.append("references mocks but never the subject module/component")
    if not touches_subject and assert_lines:
        flags.append("never references the subject of verification; assertion target unclear")
    return flags
