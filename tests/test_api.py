import pytest
from fastapi.testclient import TestClient

from app.llm import FakeLLM, LLMTimeout
from app.main import app, get_conn, get_llm
from tests.conftest import VALID


@pytest.fixture
def client(conn, monkeypatch):
    monkeypatch.setenv("LLM_BACKOFF_BASE_S", "0")
    llm = FakeLLM()
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[get_llm] = lambda: llm
    test_client = TestClient(app)
    test_client.llm = llm
    yield test_client
    app.dependency_overrides.clear()


def test_grade_happy_path(client, make_submission):
    submission_id = make_submission()
    client.llm.script = [VALID]

    response = client.post(f"/submissions/{submission_id}/grade")

    assert response.status_code == 200
    body = response.json()
    assert body["submission_id"] == submission_id
    assert body["status"] == "success"
    assert body["score"] == 4
    assert body["feedback"] == "Good answer."
    assert body["prompt_version"] == "grade_v1"


def test_grade_unknown_submission_returns_404(client):
    response = client.post("/submissions/999999/grade")
    assert response.status_code == 404


def test_exhausted_retries_return_502_with_a_null_score(client, make_submission):
    submission_id = make_submission()
    client.llm.script = [LLMTimeout("timed out")] * 3

    response = client.post(f"/submissions/{submission_id}/grade")

    assert response.status_code == 502
    assert response.json()["status"] == "failed"
    assert response.json()["score"] is None


def test_list_grades_filters_by_question(client, conn, make_submission):
    first, second = make_submission(), make_submission()  # two different questions
    client.llm.script = [VALID, VALID]
    client.post(f"/submissions/{first}/grade")
    client.post(f"/submissions/{second}/grade")
    assert len(client.get("/grades").json()) == 2  # unfiltered: both

    question_id = conn.execute(
        "SELECT question_id FROM submissions WHERE id = %s", (first,)
    ).fetchone()["question_id"]
    filtered = client.get("/grades", params={"question_id": question_id}).json()
    assert [g["submission_id"] for g in filtered] == [first]
    assert client.get("/grades", params={"question_id": 12345}).json() == []


def test_list_submissions_includes_the_latest_grade(client, make_submission):
    graded, ungraded = make_submission(), make_submission(answer="")
    client.llm.script = [VALID]
    client.post(f"/submissions/{graded}/grade")

    by_id = {s["id"]: s for s in client.get("/submissions").json()}

    assert by_id[graded]["grade"]["score"] == 4
    assert by_id[graded]["question"] == "Explain photosynthesis."
    assert by_id[graded]["max_marks"] == 5
    assert by_id[ungraded]["grade"] is None
    assert "raw_response" not in by_id[graded]["grade"]  # audit detail stays in the database


def test_demo_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "GradeBot" in response.text


QUESTION = {"text": "Why is the sky blue?", "rubric": "- Scattering (2 marks)", "max_marks": 2}


def test_create_question_then_list_it(client):
    created = client.post("/questions", json={**QUESTION, "text": "  Why is the sky blue?  "})

    assert created.status_code == 201
    assert created.json()["text"] == "Why is the sky blue?"  # surrounding whitespace dropped
    assert created.json()["max_marks"] == 2
    assert client.get("/questions").json() == [created.json()]


@pytest.mark.parametrize(
    "change",
    [{"text": "   "}, {"rubric": ""}, {"max_marks": 0}, {"max_marks": -1}, {"max_marks": 1000}],
)
def test_create_question_rejects_invalid_input(client, change):
    assert client.post("/questions", json={**QUESTION, **change}).status_code == 422
    assert client.get("/questions").json() == []


def test_create_submission_then_grade_it(client):
    question_id = client.post("/questions", json=QUESTION).json()["id"]
    created = client.post(
        "/submissions",
        json={"question_id": question_id, "student_id": "stu-9", "answer": "Light scattering."},
    )
    assert created.status_code == 201

    graded = client.post(f"/submissions/{created.json()['id']}/grade")  # heuristic fake

    assert graded.status_code == 200
    assert graded.json()["score"] == 2


def test_create_submission_allows_an_empty_answer(client):
    question_id = client.post("/questions", json=QUESTION).json()["id"]
    body = {"question_id": question_id, "student_id": "stu-9", "answer": ""}
    assert client.post("/submissions", json=body).status_code == 201


def test_create_submission_for_unknown_question_returns_404(client):
    body = {"question_id": 999999, "student_id": "stu-9", "answer": "x"}
    assert client.post("/submissions", json=body).status_code == 404


def test_create_submission_rejects_a_blank_student_id(client):
    question_id = client.post("/questions", json=QUESTION).json()["id"]
    body = {"question_id": question_id, "student_id": "  ", "answer": "x"}
    assert client.post("/submissions", json=body).status_code == 422
