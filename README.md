# GradeBot

An LLM harness that grades short subjective student answers against a teacher's rubric.
It returns a score and feedback, stores every grading run for audit, and reports a failure
honestly instead of inventing a score when the model misbehaves.

Built for the FDE offline exercise. Design decisions, trade-offs, the code review, the
production plan and the AI usage log are in [NOTES.md](NOTES.md).

**Stack:** Python 3.13 · FastAPI · PostgreSQL 16 · psycopg 3 · Pydantic · pytest.
No API key is needed: grading runs on a deterministic `FakeLLM`.

## What it does

- Grades a stored submission through `POST /submissions/{id}/grade`.
- Builds the prompt from a versioned template (`prompts/grade_v1.txt`) that includes the rubric
  and maximum marks, and treats the student's answer as untrusted data.
- Validates the model's JSON reply strictly and rejects any score outside `0..max_marks`.
- Applies a timeout to each call and retries up to 3 times with backoff.
- Stores `status='failed'` with no score when all attempts fail. A failure is never recorded as 0.
- Keeps one successful grade per submission and prompt version, enforced by the database.
- Records model, prompt version, attempts, latency and the raw response of every attempt.

## Run it

### With Docker

```
make test     # build, start Postgres, run the test suite
make eval     # run the golden-set evaluation
make up       # start the app with a seeded database
```

Then open http://localhost:8000/ for the demo page or http://localhost:8000/docs for the API.

Without `make`: copy `.env.example` to `.env`, then run
`docker compose run --rm --build test pytest -q`.

### Without Docker

You need Python 3.11+ and a PostgreSQL database. Apply `db/schema.sql` and then `db/seed.sql`
to it, then (PowerShell):

```
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
$env:DATABASE_URL = "postgresql://USER:PASSWORD@localhost:5432/gradebot"

.\.venv\Scripts\python -m pytest -q                    # tests
.\.venv\Scripts\python -m evals.run_eval               # evaluation
.\.venv\Scripts\python -m uvicorn app.main:app         # app on http://localhost:8000/
```

The tests create and drop their own `gradebot_test` schema, so they do not touch seeded data.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/submissions/{id}/grade` | Grade a submission. `200` with the grade, `404` if the submission does not exist, `502` with the stored failed record if all attempts failed. |
| GET | `/grades?question_id=` | List grading runs, optionally for one question. |
| GET | `/submissions?question_id=` | List submissions with their question and latest grade. |
| POST | `/submissions` | Add a student answer. |
| GET, POST | `/questions` | List or add questions. |
| GET | `/health` | Checks the API can reach the database. |
| GET | `/` | Demo page. |

The exercise asks for the first two. The rest support the demo page.

## Project layout

```
app/
  main.py            FastAPI endpoints
  grading.py         grade_submission: retries, timeout, persistence
  llm.py             LLMClient interface and FakeLLM
  prompts.py         prompt rendering and answer sanitising
  parsing.py         strict validation of the model's reply
  static/index.html  demo page
prompts/grade_v1.txt versioned prompt template
db/                  schema.sql, seed.sql, queries.sql
tests/               62 tests
evals/               golden.jsonl and run_eval.py
```

## Test status

- `pytest -q`: 62 passed, against PostgreSQL 16.2.
- `python -m evals.run_eval`: 5 of 5 golden cases pass (threshold 80%). The command exits
  non-zero below the threshold so CI can block a prompt change.
- `ruff check .`: clean.

- CI: the GitHub Actions workflow runs lint, the tests against a `postgres:16` service
  container and the eval gate on every push and pull request. See the Actions tab.

The Dockerfile, `docker-compose.yml` and Makefile were written but not executed, because the
development machine had no Docker. See NOTES.md, section 1.

## Limitations

- `FakeLLM` grades by keyword matching. It proves the pipeline and the CI gate work; it says
  nothing about how well a real model grades. For example, it scores a correct Hindi answer 0.
- No real LLM provider is wired in. `LLMClient` in `app/llm.py` is the place to add one.
- The demo page and its endpoints have no authentication.
