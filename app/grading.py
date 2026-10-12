"""The grading harness: prompt -> LLM -> validate -> retry -> persist."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from app.config import Settings, get_settings
from app.llm import LLMClient, LLMError, LLMTimeout
from app.parsing import InvalidOutput, parse_grade_output
from app.prompts import render_prompt

logger = logging.getLogger("gradebot.grading")

MAX_ATTEMPTS = 3
EMPTY_ANSWER_MODEL = "rule:empty-answer"

_llm_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="llm")


class SubmissionNotFound(LookupError):
    pass


@dataclass
class GradingOutcome:
    status: str  # 'success' | 'failed'
    score: float | None
    feedback: str | None
    rubric_points_met: list[str]
    model: str
    prompt_version: str
    attempts: int
    latency_ms: int
    raw_response: dict | None


def _call_with_deadline(llm: LLMClient, prompt: str, timeout_s: float) -> str:
    """Enforce the per-call timeout here, even if the client ignores the one it is given.

    The worker thread cannot be killed, so a hung call keeps its pool slot until the client
    returns; a real client must therefore also honour timeout_s on its HTTP request.
    """
    future = _llm_pool.submit(llm.generate, prompt, timeout_s)
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeout:
        future.cancel()
        raise LLMTimeout(f"no response within {timeout_s:g}s") from None


def run_grading(
    llm: LLMClient,
    *,
    question: str,
    rubric: str,
    max_marks,
    answer: str,
    prompt_version: str,
    timeout_s: float = 10.0,
    backoff_base_s: float = 0.2,
    sleep=time.sleep,
) -> GradingOutcome:
    """Grade one answer. No database access, so tests and the eval harness can call it directly."""
    if not answer.strip():
        # Nothing to grade: do not spend an LLM call on it.
        return GradingOutcome(
            status="success",
            score=0.0,
            feedback="No answer was submitted, so no marks were awarded.",
            rubric_points_met=[],
            model=EMPTY_ANSWER_MODEL,
            prompt_version=prompt_version,
            attempts=0,
            latency_ms=0,
            raw_response=None,
        )

    prompt = render_prompt(
        prompt_version, question=question, rubric=rubric, max_marks=max_marks, answer=answer
    )
    attempt_log = []
    total_latency_ms = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        raw = None
        started = time.perf_counter()
        try:
            raw = _call_with_deadline(llm, prompt, timeout_s)
            grade = parse_grade_output(raw, max_marks)
            error = None
        except (LLMError, InvalidOutput) as exc:
            grade = None
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = int((time.perf_counter() - started) * 1000)
        total_latency_ms += latency_ms
        # NUL cannot be stored in JSONB.
        attempt_log.append(
            {
                "attempt": attempt,
                "latency_ms": latency_ms,
                "raw": raw.replace("\x00", "") if raw is not None else None,
                "error": error,
            }
        )

        if grade is not None:
            return GradingOutcome(
                status="success",
                score=round(grade.score, 2),
                feedback=grade.feedback,
                rubric_points_met=grade.rubric_points_met,
                model=llm.model,
                prompt_version=prompt_version,
                attempts=attempt,
                latency_ms=total_latency_ms,
                raw_response={"attempts": attempt_log},
            )

        logger.warning(
            "grading_attempt_failed",
            extra={"attempt": attempt, "error": error, "latency_ms": latency_ms},
        )
        if attempt < MAX_ATTEMPTS:
            sleep(backoff_base_s * 2 ** (attempt - 1))

    # Out of attempts: report the failure honestly. A score of 0 here would be a lie.
    return GradingOutcome(
        status="failed",
        score=None,
        feedback=None,
        rubric_points_met=[],
        model=llm.model,
        prompt_version=prompt_version,
        attempts=MAX_ATTEMPTS,
        latency_ms=total_latency_ms,
        raw_response={"attempts": attempt_log},
    )


def _existing_success(conn: psycopg.Connection, submission_id: int, prompt_version: str):
    return conn.execute(
        "SELECT * FROM grades"
        " WHERE submission_id = %s AND prompt_version = %s AND status = 'success'",
        (submission_id, prompt_version),
    ).fetchone()


def save_grade(conn: psycopg.Connection, submission_id: int, outcome: GradingOutcome) -> dict:
    """Insert the grade row. If another request already stored a success for this
    (submission, prompt version), the unique index rejects ours and we return theirs."""
    row = conn.execute(
        """
        INSERT INTO grades (submission_id, score, feedback, status, model, prompt_version,
                            attempts, latency_ms, raw_response)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (submission_id, prompt_version) WHERE status = 'success' DO NOTHING
        RETURNING *
        """,
        (
            submission_id,
            outcome.score,
            outcome.feedback,
            outcome.status,
            outcome.model,
            outcome.prompt_version,
            outcome.attempts,
            outcome.latency_ms,
            Jsonb(outcome.raw_response) if outcome.raw_response is not None else None,
        ),
    ).fetchone()
    return row or _existing_success(conn, submission_id, outcome.prompt_version)


def grade_submission(
    submission_id: int,
    *,
    conn: psycopg.Connection,
    llm: LLMClient,
    settings: Settings | None = None,
    sleep=time.sleep,
) -> dict:
    """Grade a stored submission and return the persisted grades row.

    Idempotent per (submission, prompt version): once a success exists it is returned as is.
    A failed run is stored too (for audit) and does not block a later retry.
    """
    settings = settings or get_settings()

    submission = conn.execute(
        """
        SELECT s.answer, q.text AS question, q.rubric, q.max_marks
        FROM submissions s
        JOIN questions q ON q.id = s.question_id
        WHERE s.id = %s
        """,
        (submission_id,),
    ).fetchone()
    if submission is None:
        raise SubmissionNotFound(submission_id)

    existing = _existing_success(conn, submission_id, settings.prompt_version)
    if existing is not None:
        logger.info("grade_already_exists", extra={"submission_id": submission_id})
        return existing

    outcome = run_grading(
        llm,
        question=submission["question"],
        rubric=submission["rubric"],
        max_marks=submission["max_marks"],
        answer=submission["answer"],
        prompt_version=settings.prompt_version,
        timeout_s=settings.llm_timeout_s,
        backoff_base_s=settings.backoff_base_s,
        sleep=sleep,
    )
    row = save_grade(conn, submission_id, outcome)
    logger.info(
        "submission_graded",
        extra={
            "submission_id": submission_id,
            "grade_id": row["id"],
            "status": row["status"],
            "model": row["model"],
            "prompt_version": row["prompt_version"],
            "attempts": row["attempts"],
            "latency_ms": row["latency_ms"],
        },
    )
    return row
