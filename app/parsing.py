"""Strict parsing of the model's reply into a validated grade."""

import json
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class InvalidOutput(ValueError):
    """The model's reply is not a usable grade. Retryable."""


class GradeOutput(BaseModel):
    # strict: "4" (string) or true is not accepted as a score.
    model_config = ConfigDict(strict=True)

    score: float = Field(ge=0, allow_inf_nan=False)
    feedback: str = Field(min_length=1)
    rubric_points_met: list[str]


_FENCE = re.compile(r"^```(?:json)?\s*\n(.*?)\n?```$", re.DOTALL | re.IGNORECASE)


def parse_grade_output(raw: str, max_marks) -> GradeOutput:
    text = raw.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidOutput(f"not valid JSON: {exc.msg}") from exc

    try:
        grade = GradeOutput.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise InvalidOutput(f"schema mismatch: {problems}") from exc

    if grade.score > float(max_marks):
        raise InvalidOutput(f"score {grade.score:g} exceeds max_marks {float(max_marks):g}")
    return grade
