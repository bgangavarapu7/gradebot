import os
from pathlib import Path

import psycopg
import pytest

from app.config import Settings, get_settings
from app.db import connect

ROOT = Path(__file__).resolve().parent.parent
# Tests build their own schema so they never touch the seeded tables in the default schema.
TEST_SCHEMA = "gradebot_test"

RUBRIC = "- Mentions sunlight (2 marks)\n- Mentions oxygen (3 marks)"
VALID = '{"score": 4, "feedback": "Good answer.", "rubric_points_met": ["Mentions sunlight"]}'


def read_sql(name: str) -> str:
    return (ROOT / "db" / name).read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def database_url() -> str:
    url = get_settings().database_url
    try:
        psycopg.connect(url, connect_timeout=3).close()
    except psycopg.OperationalError as exc:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"PostgreSQL is not reachable (set DATABASE_URL or run `make up`): {exc}")
    return url


@pytest.fixture
def conn(database_url):
    """A connection to a freshly created copy of db/schema.sql."""
    with connect(database_url, options=f"-c search_path={TEST_SCHEMA}") as connection:
        connection.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
        connection.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
        connection.execute(read_sql("schema.sql"))
        yield connection
        connection.execute(f"DROP SCHEMA {TEST_SCHEMA} CASCADE")


@pytest.fixture
def settings(database_url) -> Settings:
    return Settings(
        database_url=database_url, prompt_version="grade_v1", llm_timeout_s=2, backoff_base_s=0
    )


@pytest.fixture
def make_submission(conn):
    """Insert a question (max 5 marks) with one submission; return the submission id."""

    def _make(answer: str = "Plants use sunlight.", max_marks=5) -> int:
        question_id = conn.execute(
            "INSERT INTO questions (text, rubric, max_marks) VALUES (%s, %s, %s) RETURNING id",
            ("Explain photosynthesis.", RUBRIC, max_marks),
        ).fetchone()["id"]
        return conn.execute(
            "INSERT INTO submissions (question_id, student_id, answer)"
            " VALUES (%s, 'stu-1', %s) RETURNING id",
            (question_id, answer),
        ).fetchone()["id"]

    return _make
