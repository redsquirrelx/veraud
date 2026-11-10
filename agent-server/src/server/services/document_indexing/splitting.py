"""LangChain header splitting with checked, original-line provenance."""

import re

from langchain_text_splitters import MarkdownHeaderTextSplitter

from .schemas import Heading

SPLITTER_VERSION = "markdown-headers-v1"


def split_sections(text: str) -> list[tuple[int, int, tuple[Heading, ...]]]:
    """Map unaggregated LangChain blocks monotonically to original lines.

    Never derive source ranges from the splitter's normalized character offsets.
    Blank lines belong to the preceding block (or the first block for a preamble).
    Fail closed if a library change prevents exact alignment.
    """
    lines = text.splitlines(keepends=True)
    normalized = ["".join(filter(str.isprintable, line.strip())) for line in lines]
    splitter = MarkdownHeaderTextSplitter(
        [("#" * level, str(level)) for level in range(1, 7)],
        strip_headers=False,
        return_each_line=True,
    )
    blocks = splitter.split_text(text)
    starts = []
    cursor = 0
    for block in blocks:
        first = None
        for token in block.page_content.split("\n"):
            if not token:
                continue
            while cursor < len(lines) and not normalized[cursor]:
                cursor += 1
            if cursor >= len(lines) or normalized[cursor] != token:
                raise ValueError("Cannot align Markdown split with original lines")
            if first is None:
                first = cursor
            cursor += 1
        if first is not None:
            headings = tuple(
                Heading(level=int(level), title=title)
                for level, title in sorted(
                    block.metadata.items(), key=lambda item: int(item[0])
                )
            )
            # Rejoin paragraph blocks within a section, but retain repeated
            # identical headings as separate source sections.
            if (
                not starts
                or starts[-1][1] != headings
                or re.match(r"^#{1,6}(?: |$)", normalized[first])
            ):
                starts.append((first, headings))
    if any(normalized[cursor:]):
        raise ValueError("Markdown splitter omitted source content")
    if not starts:
        return [(1, len(lines), ())] if lines else []
    starts[0] = (0, starts[0][1])
    return [
        (start + 1, starts[i + 1][0] if i + 1 < len(starts) else len(lines), headings)
        for i, (start, headings) in enumerate(starts)
    ]
