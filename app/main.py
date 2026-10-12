from datetime import datetime
from pathlib import Path
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints

from app.db import connect
from app.grading import SubmissionNotFound, grade_submission
from app.llm import FakeLLM, LLMClient
from app.logging_config import configure_logging

configure_logging()
app = FastAPI(title="GradeBot")

INDEX_HTML = Path(__file__).resolve().parent / "static" / "index.html"


class GradeRecord(BaseModel):
    id: int
    submission_id: int
    status: str
    score: float | None
    feedback: str | None
    model: str
    prompt_version: str
    attempts: int
    latency_ms: int
    created_at: datetime


# Surrounding whitespace is dropped and a blank value is rejected, matching the table CHECKs.
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class QuestionCreate(BaseModel):
    text: NonBlank
    rubric: NonBlank
    max_marks: float = Field(gt=0, le=999.99)  # the column is NUMERIC(5,2)


class QuestionRecord(BaseModel):
    id: int
    text: str
    rubric: str
    max_marks: float


class SubmissionCreate(BaseModel):
    question_id: int
    student_id: NonBlank
    answer: str = Field(max_length=20_000)  # may be empty: a blank hand-in is still a submission


class SubmissionCreated(BaseModel):
    id: int
    question_id: int
    student_id: str
    answer: str
    submitted_at: datetime


class SubmissionRecord(BaseModel):
    id: int
    question_id: int
    question: str
    rubric: str
    max_marks: float
    student_id: str
    answer: str
    submitted_at: datetime
    grade: GradeRecord | None  # the most recent grading run, if any


def get_conn():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def get_llm() -> LLMClient:
    # Only the fake exists today; a real provider would be selected here from an env var.
    return FakeLLM()


@app.get("/", include_in_schema=False)
def index():
    """The demo page: a thin client over the JSON endpoints below."""
    return FileResponse(INDEX_HTML)


@app.get("/health")
def health(conn=Depends(get_conn)):
    conn.execute("SELECT 1")
    return {"status": "ok"}


@app.post(
    "/submissions/{submission_id}/grade",
    response_model=GradeRecord,
    responses={
        404: {"description": "Submission not found"},
        502: {"model": GradeRecord, "description": "Grading failed after all attempts"},
    },
)
def grade(
    submission_id: int,
    response: Response,
    conn=Depends(get_conn),
    llm: LLMClient = Depends(get_llm),
):
    try:
        row = grade_submission(submission_id, conn=conn, llm=llm)
    except SubmissionNotFound:
        raise HTTPException(status_code=404, detail="Submission not found") from None
    if row["status"] == "failed":
        # The failed run is stored and returned, but a caller that only looks at the
        # status code must not mistake it for a grade.
        response.status_code = 502
    return row


@app.get("/grades", response_model=list[GradeRecord])
def list_grades(question_id: int | None = None, conn=Depends(get_conn)):
    return conn.execute(
        """
        SELECT g.*
        FROM grades g
        JOIN submissions s ON s.id = g.submission_id
        WHERE %(question_id)s::bigint IS NULL OR s.question_id = %(question_id)s
        ORDER BY g.id
        """,
        {"question_id": question_id},
    ).fetchall()


@app.get("/submissions", response_model=list[SubmissionRecord])
def list_submissions(question_id: int | None = None, conn=Depends(get_conn)):
    """Submissions with their question and latest grading run. Read-only; backs the demo page."""
    return conn.execute(
        """
        SELECT s.id, s.question_id, q.text AS question, q.rubric, q.max_marks,
               s.student_id, s.answer, s.submitted_at, to_jsonb(g) AS grade
        FROM submissions s
        JOIN questions q ON q.id = s.question_id
        LEFT JOIN LATERAL (
            SELECT *
            FROM grades
            WHERE submission_id = s.id
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        ) g ON true
        WHERE %(question_id)s::bigint IS NULL OR s.question_id = %(question_id)s
        ORDER BY s.question_id, s.id
        """,
        {"question_id": question_id},
    ).fetchall()


@app.get("/questions", response_model=list[QuestionRecord])
def list_questions(conn=Depends(get_conn)):
    return conn.execute("SELECT id, text, rubric, max_marks FROM questions ORDER BY id").fetchall()


@app.post("/questions", response_model=QuestionRecord, status_code=201)
def create_question(question: QuestionCreate, conn=Depends(get_conn)):
    return conn.execute(
        "INSERT INTO questions (text, rubric, max_marks) VALUES (%s, %s, %s)"
        " RETURNING id, text, rubric, max_marks",
        (question.text, question.rubric, question.max_marks),
    ).fetchone()


@app.post(
    "/submissions",
    response_model=SubmissionCreated,
    status_code=201,
    responses={404: {"description": "Question not found"}},
)
def create_submission(submission: SubmissionCreate, conn=Depends(get_conn)):
    try:
        return conn.execute(
            "INSERT INTO submissions (question_id, student_id, answer) VALUES (%s, %s, %s)"
            " RETURNING id, question_id, student_id, answer, submitted_at",
            (submission.question_id, submission.student_id, submission.answer),
        ).fetchone()
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(status_code=404, detail="Question not found") from None
