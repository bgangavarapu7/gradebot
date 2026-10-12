"""LLM provider abstraction and the deterministic FakeLLM used for tests and evals."""

import json
import re
import time
from typing import Protocol


class LLMError(Exception):
    """A provider failure that is worth retrying (network error, 5xx, rate limit)."""


class LLMTimeout(LLMError):
    """The provider did not answer within the per-call timeout."""


class LLMClient(Protocol):
    model: str

    def generate(self, prompt: str, timeout_s: float) -> str:
        """Return the model's raw text. Raise LLMTimeout / LLMError on failure."""
        ...


_STOPWORDS = {"that", "this", "with", "from", "into", "they", "them", "their", "while", "more"}


def _stems(text: str) -> set[str]:
    """Crude content-word stems: lowercase words of 4+ letters, cut to 5 characters."""
    words = re.findall(r"[a-z]+", text.lower())
    return {w[:5] for w in words if len(w) >= 4 and w not in _STOPWORDS}


def _tag(prompt: str, name: str) -> str | None:
    match = re.search(rf"<{name}>\n?(.*?)\n?</{name}>", prompt, re.DOTALL)
    return match.group(1) if match else None


class FakeLLM:
    """Deterministic stand-in for a real model.

    Scripted mode: each call pops the next item of `script`; a string is returned as the raw
    response and an exception is raised. That is how tests force garbage output and timeouts.

    Once the script is empty (or if none was given) it grades with a keyword heuristic: a
    rubric line earns its marks when the answer shares a content word with it. Words from the
    question itself do not count, so repeating the question earns nothing. This exercises the
    pipeline end to end; it says nothing about how well a real model grades.
    """

    def __init__(self, script=None, model: str = "fake-llm-v1", delay_s: float = 0.0):
        self.script = list(script or [])
        self.model = model
        self.delay_s = delay_s
        self.calls = 0
        self.prompts: list[str] = []

    def generate(self, prompt: str, timeout_s: float) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return self._heuristic_grade(prompt)

    def _heuristic_grade(self, prompt: str) -> str:
        question, rubric, answer = (
            _tag(prompt, t) for t in ("question", "rubric", "student_answer")
        )
        if question is None or rubric is None or answer is None:
            return "I could not find the question, rubric and answer in the prompt."

        answer_stems = _stems(answer) - _stems(question)
        score = 0.0
        met = []
        for line in rubric.splitlines():
            match = re.match(r"^\s*-\s*(.+?)\s*\((\d+(?:\.\d+)?) marks?\)\s*$", line)
            if match and _stems(match.group(1)) & answer_stems:
                score += float(match.group(2))
                met.append(match.group(1))

        feedback = f"The answer covers {len(met)} rubric point(s)."
        return json.dumps({"score": score, "feedback": feedback, "rubric_points_met": met})
