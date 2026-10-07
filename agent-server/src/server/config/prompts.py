"""Prompt templates, loaded from disk instead of defined in code.

Layout under `prompts/`:

    prompts/
      dummy/
        system.md
        user.md          # optional, {placeholders} filled by the agent
      analyzer/
        system.md
        user.md

An agent names the prompt it wants; the loader resolves it. The agent decides
what to fill in, never how to word the instruction.

Templates use str.format syntax, so literal braces must be doubled.
"""

from functools import lru_cache
from pathlib import Path

from .logs import get_logger

logger = get_logger("prompts")

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


class PromptNotFoundError(FileNotFoundError):
    """Raised when a prompt file is missing or unreadable."""


def prompt_path(agent_type: str, name: str = "system") -> Path:
    """Where a prompt lives, without touching the filesystem."""
    return PROMPTS_DIR / agent_type / f"{name}.md"


@lru_cache(maxsize=64)
def load_prompt(agent_type: str, name: str = "system") -> str:
    """Read a prompt template.

    Cached: templates are read once per process and never change at runtime,
    so re-reading them per request would be pure overhead.
    """
    path = prompt_path(agent_type, name)

    if not path.is_file():
        raise PromptNotFoundError(
            f"Prompt {name!r} not found for agent {agent_type!r}: {path}"
        )

    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise PromptNotFoundError(f"Could not read prompt {path}: {error}") from None


def render_prompt(template: str, **values: object) -> str:
    """Fill a template's placeholders.

    A missing or misspelled placeholder is a bug in the caller, not something
    to paper over, so it raises rather than leaving the literal {name} in the
    prompt sent to a model.
    """
    try:
        return template.format(**values)
    except KeyError as error:
        raise KeyError(
            f"Prompt placeholder {error} not provided. "
            f"Placeholders: {sorted(_placeholders(template))}"
        ) from None
    except IndexError as error:
        raise KeyError(
            f"Prompt uses positional placeholder {error}, but rendering is "
            f"by name only"
        ) from None


def _placeholders(template: str) -> set[str]:
    from string import Formatter

    found: set[str] = set()

    for _, field, _, _ in Formatter().parse(template):
        if field:
            found.add(field.split(".")[0].split("[")[0])

    return found


def clear_cache() -> None:
    """Forget cached templates. For tests that write prompts to a temp dir."""
    load_prompt.cache_clear()