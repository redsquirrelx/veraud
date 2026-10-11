"""Independent grader for past architecture descriptions.

The judge checks whether each responsibility line and each quality note is
backed by the source it cites. It grades blind: it never sees the run's
confidence, so the correlation between confidence and support happens
outside, afterwards.

Same model by construction: the judge takes whatever model instance the
caller hands it, and every caller hands it the architect's. There is no
judge entry in dev-agents.yaml to drift out of sync. A shared model can
share blind spots, which is why the report headlines the contradiction
rate: agreement may be self-agreement, but a contradiction is evidence.
"""

from pathlib import Path

from ...config.logs import get_logger
from ...config.prompts import load_prompt, render_prompt
from ...config.tracing import traced_generate
from ..analyzer import parsing as analyzer_parsing
from ..analyzer.evidence import (
    MAX_CHARS_PER_FILE,
    read_excerpts,
    read_ranged_excerpts,
    render_excerpts,
)
from ..base import BaseAgent
from .schemas import GradeVerdict, ItemGrade, JudgeInput, JudgeReport

logger = get_logger("judge-agent")

VERDICTS = frozenset({"supported", "contradicted", "unverifiable"})


class JudgeAgent(BaseAgent[JudgeInput, JudgeReport]):
    agent_type = "judge"
    input_schema = JudgeInput
    output_schema = JudgeReport

    async def run(self, input_data: JudgeInput) -> JudgeReport:
        """Grade every claim against the source it cites."""
        root = Path(input_data.root_path)

        if not root.is_dir():
            raise FileNotFoundError(f"No repository at {input_data.root_path!r}")

        grades: list[ItemGrade] = []

        for component in input_data.description.components:
            grades.append(await self._grade_component(root, component.path, component.responsibility))

        for index, note in enumerate(input_data.description.quality_notes):
            grades.append(await self._grade_note(root, index, note))

        supported = sum(1 for grade in grades if grade.verdict == "supported")
        contradicted = sum(1 for grade in grades if grade.verdict == "contradicted")
        unverifiable = len(grades) - supported - contradicted

        logger.info(
            "run done: grades=%d supported=%d contradicted=%d unverifiable=%d",
            len(grades), supported, contradicted, unverifiable,
        )
        return JudgeReport(
            grades=grades,
            supported=supported,
            contradicted=contradicted,
            unverifiable=unverifiable,
            contradiction_rate=(contradicted / len(grades)) if grades else 0.0,
        )

    async def _grade_component(self, root: Path, path: str, responsibility: str) -> ItemGrade:
        """Grade one responsibility line against its own file."""
        if not responsibility.strip():
            # Nothing was claimed, so there is nothing to spend a call on.
            # Undescribed components surface as unverifiable, which is exactly
            # what drags the architect's confidence down.
            return ItemGrade(kind="component", subject=path, verdict="unverifiable", reason="Undescribed.")

        excerpts = read_excerpts(root, [path], MAX_CHARS_PER_FILE)

        if not excerpts:
            return ItemGrade(
                kind="component", subject=path, verdict="unverifiable",
                reason="The cited file could not be read.",
            )

        verdict, reason, cited = await self._ask_grade(
            subject=path, claim=responsibility, excerpts=render_excerpts(excerpts)
        )
        evidence = _check_evidence(root, cited, {path})
        if verdict in ("supported", "contradicted") and not evidence:
            verdict, reason = "unverifiable", "No checkable evidence cited."
        return ItemGrade(kind="component", subject=path, verdict=verdict, reason=reason, evidence=evidence)

    async def _grade_note(self, root: Path, index: int, note) -> ItemGrade:
        """Grade one quality note against exactly what it cites.

        Evidence carries `path[:lines]`, so only the cited lines plus context
        are read. A range pointing outside its file reads as nothing, which
        lands the note in unverifiable: invented line numbers fail loudly.
        """
        subject = f"note[{index}]: {note.characteristic}"
        evidence = [path for path in note.evidence if isinstance(path, str) and path.strip()]

        if not note.observation.strip() or not evidence:
            return ItemGrade(kind="note", subject=subject, verdict="unverifiable", reason="No evidence cited.")

        excerpts = read_ranged_excerpts(root, evidence)

        if not excerpts:
            return ItemGrade(
                kind="note", subject=subject, verdict="unverifiable",
                reason="The cited evidence could not be read.",
            )

        verdict, reason, cited = await self._ask_grade(
            subject=subject, claim=note.observation, excerpts=render_excerpts(excerpts)
        )
        evidence = _check_evidence(root, cited, {excerpt.path for excerpt in excerpts})
        if verdict in ("supported", "contradicted") and not evidence:
            verdict, reason = "unverifiable", "No checkable evidence cited."
        return ItemGrade(kind="note", subject=subject, verdict=verdict, reason=reason, evidence=evidence)

    async def _ask_grade(self, subject: str, claim: str, excerpts: str) -> tuple[GradeVerdict, str, list[str]]:
        """One model call, fail-safe toward distrust."""
        try:
            response = await traced_generate(self.model, self._prompt(
                "grade", subject=subject, claim=claim, excerpts=excerpts or NO_SOURCE_READ,
            ))
            answer = analyzer_parsing.parse_json(analyzer_parsing.extract_text(response))
        except Exception as error:  # noqa: BLE001 - providers raise varied errors
            logger.warning("grade: model gave no usable answer: %s", error)
            return "unverifiable", "The grader returned nothing usable.", []

        verdict = str(answer.get("verdict", "")).strip().lower()

        if verdict not in VERDICTS:
            return "unverifiable", "The grader returned no usable verdict.", []

        reason = analyzer_parsing.read_text(answer, "reason")
        cited = [
            str(value).strip() for value in answer.get("evidence", [])
            if isinstance(value, str) and str(value).strip()
        ]
        logger.info("grade: %s %s", verdict, subject)
        return verdict, reason, cited  # type: ignore[return-value]

    def _prompt(self, name: str, **values: object) -> str:
        template = load_prompt(self.agent_type, name)
        role = load_prompt(self.agent_type, "system")
        return f"{role}\n\n---\n\n{render_prompt(template, **values)}"


def _check_evidence(root: Path, cited: list[str], read: set[str]) -> list[str]:
    """Cited evidence worth trusting: parseable, on disk, and actually read.

    The grader only saw the excerpts it was shown, so a citation to a file
    that was never read is indistinguishable from an invention. Anything that
    fails a check is dropped; a supported/contradicted verdict left with
    nothing checkable is demoted by the caller.
    """
    valid: list[str] = []

    for entry in cited:
        if entry in valid:
            continue
        split = analyzer_parsing.split_evidence(entry)
        if split is None:
            continue
        path, _ranges = split
        if path not in read:
            continue
        if not (root / path).is_file():
            continue
        valid.append(entry)

    return valid


NO_SOURCE_READ = "(no source code could be read)"
