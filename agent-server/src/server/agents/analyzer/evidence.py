"""Reading source excerpts off disk for the model to look at.

The representations tell the analyzer where a repository holds together; this
is what lets it actually look. Everything here is bounded: a repository can be
hundreds of thousands of lines and the model gets excerpts, not the source.
"""

from pathlib import Path

from ...config.logs import get_logger

logger = get_logger("analyzer-source")

MAX_LINES_PER_FILE = 220
MAX_CHARS_PER_FILE = 8000

# Ceiling on every excerpt a single run may read, across all rounds. Past this
# the model has as much code as it can usefully weigh, and more only costs.
MAX_CHARS_PER_RUN = 40000


class SourceExcerpt:
    """One file's excerpt, kept as text so it survives the graph state."""

    def __init__(self, path: str, text: str, truncated: bool) -> None:
        self.path = path
        self.text = text
        self.truncated = truncated

    def render(self) -> str:
        header = f"--- {self.path}"
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