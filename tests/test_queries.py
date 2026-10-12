"""db/seed.sql loads, and the three reporting queries in db/queries.sql return correct rows."""

import re
from decimal import Decimal

import pytest

from tests.conftest import read_sql


def load_queries() -> dict[str, str]:
    parts = re.split(r"^-- name: (\w+)\n", read_sql("queries.sql"), flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


QUERIES = load_queries()


@pytest.fixture
def seeded(conn):
    conn.execute(read_sql("seed.sql"))

    def add_grade(submission_id, status, score=None, version="grade_v1", created_at="now()"):
        feedback = "ok" if status == "success" else None
        return conn.execute(
            "INSERT INTO grades (submission_id, score, feedback, status, model, prompt_version,"
            " attempts, latency_ms, created_at)"
            f" VALUES (%s, %s, %s, %s, 'm', %s, 1, 1, {created_at}) RETURNING id",
            (submission_id, score, feedback, status, version),
        ).fetchone()["id"]

    # Question 1 (submissions 1-4), grade_v1: successes 5 and 2, plus one failed run.
    add_grade(1, "success", 5)
    add_grade(2, "failed", created_at="now() - interval '1 hour'")
    add_grade(2, "success", 2)
    # Same question under grade_v2, and a failed-only submission on question 2.
    add_grade(1, "success", 4, version="grade_v2", created_at="now() - interval '1 day'")
    add_grade(5, "failed")
    return conn


def test_seed_has_the_required_shape(seeded):
    counts = seeded.execute(
        "SELECT (SELECT count(*) FROM questions) AS q, (SELECT count(*) FROM submissions) AS s"
    ).fetchone()
    assert (counts["q"], counts["s"]) == (3, 8)

    answers = [r["answer"] for r in seeded.execute("SELECT answer FROM submissions")]
    assert "" in answers  # empty
    assert any(len(a) > 5000 for a in answers)  # very long
    assert any(not a.isascii() for a in answers)  # non-English
    assert any("Ignore the rubric" in a for a in answers)  # injection


def test_identity_sequences_continue_after_the_seed(seeded):
    new_id = seeded.execute(
        "INSERT INTO submissions (question_id, student_id, answer) VALUES (1, 's', 'a')"
        " RETURNING id"
    ).fetchone()["id"]
    assert new_id == 9


def test_average_score_and_failure_rate(seeded):
    rows = seeded.execute(QUERIES["avg_score_and_failure_rate"]).fetchall()
    by_key = {(r["question_id"], r["prompt_version"]): r for r in rows}

    q1_v1 = by_key[(1, "grade_v1")]
    assert q1_v1["average_score"] == Decimal("3.50")  # (5 + 2) / 2; the failed run is excluded
    assert q1_v1["failure_rate"] == Decimal("0.333")  # 1 failed of 3 runs
    assert by_key[(1, "grade_v2")]["average_score"] == Decimal("4.00")
    assert by_key[(1, "grade_v2")]["failure_rate"] == 0
    assert by_key[(2, "grade_v1")]["average_score"] is None  # no successes: unknown, not 0
    assert by_key[(2, "grade_v1")]["failure_rate"] == 1


def test_submissions_without_successful_grade(seeded):
    rows = seeded.execute(QUERIES["submissions_without_successful_grade"]).fetchall()
    # 1 and 2 have a success; 5 only failed; the rest were never graded.
    assert [r["id"] for r in rows] == [3, 4, 5, 6, 7, 8]


def test_latest_grade_per_submission(seeded):
    rows = seeded.execute(QUERIES["latest_grade_per_submission"]).fetchall()
    latest = {r["submission_id"]: r for r in rows}

    assert sorted(latest) == [1, 2, 5]  # one row per graded submission
    assert latest[1]["prompt_version"] == "grade_v1"  # newer than the day-old grade_v2 row
    assert (latest[2]["status"], latest[2]["score"]) == ("success", 2)  # not the older failure
    assert latest[5]["status"] == "failed"
