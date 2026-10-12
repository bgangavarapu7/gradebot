"""Versioned prompt templates. A version is a file in prompts/; never edit a released one."""

import re
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

ANSWER_OPEN = "<student_answer>"
ANSWER_CLOSE = "</student_answer>"

# The tags the template uses as structure. A student must not be able to write them.
_STRUCTURAL_TAG = re.compile(r"</?\s*(student_answer|question|rubric)\s*>", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


@lru_cache
def load_template(version: str) -> str:
    if not re.fullmatch(r"[a-z0-9_]+", version):
        raise ValueError(f"invalid prompt version: {version!r}")
    return (PROMPTS_DIR / f"{version}.txt").read_text(encoding="utf-8")


def sanitize_answer(answer: str) -> str:
    """Stop the answer from closing its own delimiter and escaping into the instructions."""
    return _STRUCTURAL_TAG.sub("[tag removed]", answer)


def render_prompt(version: str, *, question: str, rubric: str, max_marks, answer: str) -> str:
    values = {
        "question": question,
        "rubric": rubric,
        "max_marks": f"{float(max_marks):g}",
        "answer": sanitize_answer(answer),
    }
    # One pass over the template: substituted text is never scanned again, so an answer
    # containing "{{rubric}}" stays literal instead of being expanded.
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], load_template(version))
