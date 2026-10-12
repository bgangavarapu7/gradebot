"""grade_submission against PostgreSQL: persistence, idempotency and constraints."""

import psycopg
import pytest

from app.grading import GradingOutcome, SubmissionNotFound, grade_submission, save_grade
from app.llm import FakeLLM, LLMTimeout
from tests.conftest import VALID


def grades_for(conn, submission_id):
    return conn.execute(
        "SELECT * FROM grades WHERE submission_id = %s ORDER BY id", (submission_id,)
    ).fetchall()


def test_success_is_persisted_with_audit_fields(conn, settings, make_submission):
    submission_id = make_submission()
    row = grade_submission(submission_id, conn=conn, llm=FakeLLM([VALID]), settings=settings)

    stored = grades_for(conn, submission_id)
    assert len(stored) == 1
    assert stored[0]["id"] == row["id"]
    assert stored[0]["status"] == "success"
    assert stored[0]["score"] == 4
    assert stored[0]["model"] == "fake-llm-v1"
    assert stored[0]["prompt_version"] == "grade_v1"
    assert stored[0]["attempts"] == 1
    assert stored[0]["latency_ms"] >= 0
    assert stored[0]["raw_response"]["attempts"][0]["raw"] == VALID


def test_retry_then_success_persists_three_attempts(conn, settings, make_submission):
    submission_id = make_submission()
    llm = FakeLLM(["garbage", "```json\n{}\n```", VALID])
    row = grade_submission(submission_id, conn=conn, llm=llm, settings=settings)

    assert row["status"] == "success"
    assert row["attempts"] == 3
    assert len(row["raw_response"]["attempts"]) == 3


def test_three_timeouts_persist_failed_with_null_score(conn, settings, make_submission):
    submission_id = make_submission()
    llm = FakeLLM([LLMTimeout("timed out")] * 3)
    row = grade_submission(submission_id, conn=conn, llm=llm, settings=settings)

    assert row["status"] == "failed"
    assert row["score"] is None
    assert row["feedback"] is None
    assert row["attempts"] == 3
    assert [g["status"] for g in grades_for(conn, submission_id)] == ["failed"]


def test_grading_twice_does_not_duplicate_the_success(conn, settings, make_submission):
    submission_id = make_submission()
    llm = FakeLLM([VALID, VALID])
    first = grade_submission(submission_id, conn=conn, llm=llm, settings=settings)
    second = grade_submission(submission_id, conn=conn, llm=llm, settings=settings)

    assert second["id"] == first["id"]
    assert len(grades_for(conn, submission_id)) == 1
    assert llm.calls == 1  # the second request did not pay for another LLM call


def test_concurrent_duplicate_is_rejected_by_the_database(conn, make_submission):
    """Two requests that both passed the 'already graded?' check: the index decides."""
    submission_id = make_submission()
    outcome = GradingOutcome("success", 4.0, "Good.", [], "fake-llm-v1", "grade_v1", 1, 5, None)
    first = save_grade(conn, submission_id, outcome)
    second = save_grade(conn, submission_id, outcome)

    assert second["id"] == first["id"]
    assert len(grades_for(conn, submission_id)) == 1

    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            "INSERT INTO grades (submission_id, score, feedback, status, model,"
            " prompt_version, attempts, latency_ms)"
            " VALUES (%s, 1, 'dup', 'success', 'm', 'grade_v1', 1, 1)",
            (submission_id,),
        )


def test_failed_run_can_be_retried_and_both_rows_are_kept(conn, settings, make_submission):
    submission_id = make_submission()
    llm = FakeLLM([LLMTimeout("t")] * 3 + [VALID])
    grade_submission(submission_id, conn=conn, llm=llm, settings=settings)
    grade_submission(submission_id, conn=conn, llm=llm, settings=settings)

    assert [g["status"] for g in grades_for(conn, submission_id)] == ["failed", "success"]


def test_empty_answer_is_stored_as_zero_without_an_llm_call(conn, settings, make_submission):
    submission_id = make_submission(answer="")
    llm = FakeLLM()
    row = grade_submission(submission_id, conn=conn, llm=llm, settings=settings)

    assert (row["status"], row["score"], row["attempts"]) == ("success", 0, 0)
    assert llm.calls == 0


def test_unknown_submission_raises(conn, settings):
    with pytest.raises(SubmissionNotFound):
        grade_submission(999_999, conn=conn, llm=FakeLLM(), settings=settings)


def test_database_rejects_a_failed_grade_with_a_score(conn, make_submission):
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO grades (submission_id, score, status, model, prompt_version,"
            " attempts, latency_ms) VALUES (%s, 0, 'failed', 'm', 'grade_v1', 3, 1)",
            (make_submission(),),
        )


def test_database_rejects_a_score_above_max_marks(conn, make_submission):
    with pytest.raises(psycopg.errors.CheckViolation, match="exceeds max_marks"):
        conn.execute(
            "INSERT INTO grades (submission_id, score, feedback, status, model,"
            " prompt_version, attempts, latency_ms)"
            " VALUES (%s, 5.5, 'x', 'success', 'm', 'grade_v1', 1, 1)",
            (make_submission(max_marks=5),),
        )
