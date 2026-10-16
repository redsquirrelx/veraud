"""Bounded report loading and atomic CLI checkpoints for repository analysis."""

import os
import tempfile
from pathlib import Path

from .agents.project_analysis.project_architecture.schemas import ArchitectureResult
from .runtimes.repository.responses import parse_json_value

MAX_REPORT_BYTES = 2_000_000


def load_architecture_report(path):
    """Accept bounded UTF-8/UTF-16 exports, including PowerShell redirection."""
    with path.open("rb") as stream:
        raw = stream.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("Architectural report exceeds the 2 MB input limit.")
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    try:
        exported = parse_json_value(raw.decode(encoding), MAX_REPORT_BYTES)
    except UnicodeError as error:
        raise ValueError(
            "Architectural report must be UTF-8 or BOM-marked UTF-16 JSON."
        ) from error
    if not isinstance(exported, dict):
        raise ValueError("Expected an exported architectural result object.")  # noqa: TRY004 - invalid external JSON is a CLI value error
    # Pre-runtime-extraction architecture exports carried an unused analyst counter.
    if (
        isinstance(exported.get("usage"), dict)
        and exported["usage"].get("investigations_started") == 0
    ):
        exported["usage"].pop("investigations_started")
    return ArchitectureResult.model_validate(
        {
            key: value
            for key, value in exported.items()
            if key in ArchitectureResult.model_fields
        }
    )


class ArchitectureCheckpoint:
    """Persist accepted reports before fallible presentation calls, atomically."""

    def __init__(self, path: Path):
        self.path = path

    async def on_stage_start(self, stage):
        pass

    async def on_architecture_revision(self, result):
        await self.on_stage_result("architecture_revision", result)

    async def on_stage_result(self, stage, result):
        if (
            stage not in {"architecture", "architecture_revision"}
            or result.architecture is None
        ):
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A unique temporary file avoids collisions between simultaneous runs.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(result.model_dump_json(indent=2))
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
