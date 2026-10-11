"""Reading source excerpts off disk for the model to look at.

The representations tell the analyzer where a repository holds together; this
is what lets it actually look. Everything here is bounded: a repository can be
hundreds of thousands of lines and the model gets excerpts, not the source.
"""

from pathlib import Path

from ...config.logs import get_logger
from .parsing import split_evidence

logger = get_logger("analyzer-source")

MAX_LINES_PER_FILE = 220
MAX_CHARS_PER_FILE = 8000

# Ceiling on every excerpt a single run may read, across all rounds. Past this
# the model has as much code as it can usefully weigh, and more only costs.
MAX_CHARS_PER_RUN = 40000

# Source lines shown around each cited range, so a line interval arrives with
# the neighborhood that makes it intelligible.
RANGE_CONTEXT_LINES = 10


class SourceExcerpt:
    """One file's excerpt, kept as text so it survives the graph state."""

    def __init__(self, path: str, text: str, truncated: bool, label: str | None = None) -> None:
        self.path = path
        self.text = text
        self.truncated = truncated
        self.label = label or path

    def render(self) -> str:
        header = f"--- {self.label}"
        if self.truncated:
            header += " (excerpt, first lines only)"
        return f"{header}\n{self.text}"


def read_excerpts(root: Path, paths: list[str], budget: int) -> list[SourceExcerpt]:
    """Read each path, stopping once the budget is gone.

    `budget` is what is left of MAX_CHARS_PER_RUN, so the caller controls the
    total across rounds rather than this function resetting the count each time.

    A file that cannot be read is skipped rather than failing the run: the
    analyzer would rather describe the project from less evidence than not
    describe it at all.
    """
    excerpts: list[SourceExcerpt] = []
    spent = 0

    for path in paths:
        remaining = budget - spent
        if remaining <= 0:
            logger.info("Source budget spent after %d files", len(excerpts))
            break

        excerpt = _read_one(root, path, min(MAX_CHARS_PER_FILE, remaining))
        if excerpt is None:
            continue

        excerpts.append(excerpt)
        spent += len(excerpt.text)

    return excerpts


def _read_one(root: Path, relative: str, budget: int) -> SourceExcerpt | None:
    target = root / relative

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        logger.warning("Could not read %s: %s", target, error)
        return None

    lines = text.splitlines()
    truncated = False

    if len(lines) > MAX_LINES_PER_FILE:
        lines = lines[:MAX_LINES_PER_FILE]
        truncated = True

    body = "\n".join(lines)
    if len(body) > budget:
        body = body[:budget]
        truncated = True

    # The excerpt keeps the repo-relative path the model was shown in the file
    # listing, so anything it quotes back lines up with what it was given.
    return SourceExcerpt(relative, body, truncated)


def render_excerpts(excerpts: list[SourceExcerpt]) -> str:
    """Excerpts as one block of text, for a prompt to carry."""
    return "\n\n".join(excerpt.render() for excerpt in excerpts)


def read_ranged_excerpts(
    root: Path,
    entries: list[str],
    context: int = RANGE_CONTEXT_LINES,
    budget: int = MAX_CHARS_PER_RUN,
) -> list[SourceExcerpt]:
    """Read only the cited lines plus context, one excerpt per entry.

    Entries are `path` or `path:L1-L2,...` as read_evidence keeps them. A bare
    path reads the whole file capped like read_excerpts; ranges outside the
    file contribute nothing, and an entry with nothing readable is skipped so
    the caller can treat it as unproven rather than failing.
    """
    excerpts: list[SourceExcerpt] = []
    spent = 0

    for entry in entries:
        remaining = budget - spent
        if remaining <= 0:
            logger.info("Source budget spent after %d excerpts", len(excerpts))
            break

        excerpt = _read_ranged(root, entry, context, remaining)
        if excerpt is None:
            continue

        excerpts.append(excerpt)
        spent += len(excerpt.text)

    return excerpts


def _read_ranged(root: Path, entry: str, context: int, budget: int) -> SourceExcerpt | None:
    split = split_evidence(entry.strip())
    if split is None:
        return None

    path, ranges = split
    target = root / path

    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        logger.warning("Could not read %s: %s", target, error)
        return None

    if ranges is None:
        return _read_one(root, path, min(MAX_CHARS_PER_FILE, budget))

    # Expand each range by context, then merge overlaps so shared
    # neighborhoods print once.
    spans: list[tuple[int, int]] = []
    for start, end in ranges:
        first = max(start - context, 1)
        last = min(end + context, len(lines))
        if first > len(lines):
            continue
        if spans and first <= spans[-1][1] + 1:
            spans[-1] = (spans[-1][0], max(spans[-1][1], last))
        else:
            spans.append((first, last))

    if not spans:
        return None

    body = "\n...\n".join("\n".join(lines[first - 1:last]) for first, last in spans)
    if len(body) > budget:
        body = body[:budget]

    return SourceExcerpt(path, body, False, label=entry.strip())