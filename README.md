# GradeBot — LLM Grading Harness

An LLM-powered grading harness that evaluates short subjective student answers against teacher-defined rubrics. It returns scores and feedback, maintains an audit trail of grading attempts, and reports failures honestly instead of inventing scores when the model misbehaves.

Built for the **FDE Offline Exercise**.

**Tech Stack:** Python 3.13 · FastAPI · PostgreSQL 16 · psycopg 3 · Pydantic · pytest

No API key is required. The grading workflow uses a deterministic `FakeLLM` for reproducible testing.

## Features

- **Automated grading:** Grades stored student submissions against teacher-defined rubrics.
- **Versioned prompts:** Uses `prompts/grade_v1.txt` with the rubric and maximum marks.
- **Prompt-injection awareness:** Treats student answers as untrusted data and separates them from grading instructions.
- **Strict output validation:** Validates structured JSON responses and rejects scores outside `0..max_marks`.
- **Resilient execution:** Applies per-call timeouts and retries up to three times with backoff.
- **Honest failure handling:** Records failed grading attempts with a `NULL` score instead of treating failures as zero.
- **Audit trail:** Stores model, prompt version, attempt count, latency and raw response.
- **Idempotency:** Enforces one successful grade per submission and prompt version at the database level.
- **Evaluation harness:** Compares grading results against a golden dataset and enforces a configurable pass-rate threshold.
- **Demo interface:** Provides a simple web page for interacting with the grading workflow.

## Architecture

```text
Teacher / Demo UI
        |
        v
    FastAPI
        |
        v
 Grading Service
        |
        +----> Versioned Prompt
        |
        +----> FakeLLM
        |
        +----> JSON Parsing & Validation
        |
        +----> Retry / Timeout Handling
        |
        v
    PostgreSQL
        |
        +---- Questions
        +---- Submissions
        +---- Grades & Audit History
```

## Getting Started

### Prerequisites

- Python 3.11 or newer
- PostgreSQL 16, or Docker with Docker Compose
- Git

### Option 1: Run with Docker

From the project root:

```bash
make test
make eval
make up
```

These commands run the test suite, execute the golden-set evaluation and start the application, respectively.

Open the following URLs after the application starts:

| Resource | URL |
|---|---|
| Demo page | http://localhost:8000/ |
| Interactive API documentation | http://localhost:8000/docs |
| Health check | http://localhost:8000/health |

**Note:** The Dockerfile, Compose configuration, Makefile and CI workflow have been written but were not executed in the development environment because Docker was unavailable.

### Option 2: Run locally without Docker

Create and activate a virtual environment in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

Create a PostgreSQL database named `gradebot`, then apply the schema and seed data:

```powershell
psql -U USER -d gradebot -f db/schema.sql
psql -U USER -d gradebot -f db/seed.sql
```

Configure the database connection:

```powershell
$env:DATABASE_URL = "postgresql://USER:PASSWORD@localhost:5432/gradebot"
```

Run the automated tests:

```powershell
python -m pytest -q
```

Run the evaluation harness:

```powershell
python -m evals.run_eval
```

Start the application:

```powershell
python -m uvicorn app.main:app --reload
```

Replace `USER` and `PASSWORD` with your local PostgreSQL credentials.

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/submissions/{id}/grade` | Grades a submission |
| `GET` | `/grades?question_id=` | Lists grading runs, optionally filtered by question |
| `GET` | `/submissions?question_id=` | Lists submissions with their question and latest grade |
| `POST` | `/submissions` | Creates a student submission |
| `GET` | `/questions` | Lists questions |
| `POST` | `/questions` | Creates a question |
| `GET` | `/health` | Checks API and database connectivity |
| `GET` | `/` | Serves the demo page |

The first two endpoints satisfy the core API requirements of the exercise. The additional endpoints support the demo interface.

### Grading workflow

1. Submit a grading request for an existing submission.
2. Retrieve the question, rubric, maximum marks and student answer.
3. Render the versioned grading prompt.
4. Call `FakeLLM` and validate the returned JSON.
5. Retry invalid responses or timeouts up to the configured limit.
6. Persist the grading result and audit metadata.
7. Return the result or an explicit failure response.

### Example request

```http
POST /submissions/1/grade
```

A successful response contains the grade, feedback and grading metadata. A nonexistent submission returns `404`. If all grading attempts fail, the API returns `502` with the persisted failure record.

## Database Design

The application uses three primary tables:

- **`questions`** — Question text, teacher rubric and maximum marks.
- **`submissions`** — Student answers and submission timestamps.
- **`grades`** — Scores, feedback, status, model, prompt version, attempts, latency and raw responses.

PostgreSQL constraints enforce valid references, permitted statuses and grading idempotency.

The partial unique index prevents duplicate successful grades for the same `(submission_id, prompt_version)` while preserving failed attempts for auditing.

SQL reporting queries are provided in `db/queries.sql`.

## Testing and Evaluation

### Automated tests

The test suite covers:

- Valid JSON and fenced JSON parsing.
- Missing fields and malformed responses.
- Scores exceeding maximum marks.
- Retry behavior and timeout exhaustion.
- Idempotent grading.
- Prompt-injection input handling.
- API and database behavior.

### Current test results

| Check | Result |
|---|---|
| pytest | 62 passed |
| Golden evaluation | 5/5 cases passed |
| Evaluation threshold | 80% |
| Ruff linting | Clean |

The reported results were obtained in the development environment against PostgreSQL 16.2. Docker-based execution remains unverified.

### Evaluation harness

The evaluation dataset is located at `evals/golden.jsonl`. The runner reports expected score ranges, actual results, pass/fail status and latency.

The evaluation command exits with a non-zero status when the pass rate falls below the configured threshold, allowing CI to block regressions in prompt behavior.

**Important limitation:** The current `FakeLLM` uses keyword matching. Passing these evaluations demonstrates that the grading pipeline and evaluation gate work; it does not establish the accuracy of a real LLM grader.

## Project Structure

```text
gradebot/
├── app/
│   ├── main.py
│   ├── grading.py
│   ├── llm.py
│   ├── prompts.py
│   ├── parsing.py
│   └── static/
│       └── index.html
├── prompts/
│   └── grade_v1.txt
├── db/
│   ├── schema.sql
│   ├── seed.sql
│   └── queries.sql
├── tests/
├── evals/
│   ├── golden.jsonl
│   └── run_eval.py
├── .github/
│   └── workflows/
│       └── ci.yml
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── requirements-dev.txt
├── .env.example
├── .gitignore
├── NOTES.md
└── README.md
```

## Limitations and Future Improvements

- **FakeLLM grading:** Keyword matching is deterministic but cannot reliably assess semantic correctness. A correct Hindi answer, for example, may receive zero.
- **No real provider:** A real LLM provider has not been integrated. The `LLMClient` abstraction in `app/llm.py` provides the extension point.
- **Authentication:** The demo page and endpoints do not currently implement authentication.
- **Container verification:** Docker and Compose configurations have not been executed in the development environment.
- **Production readiness:** A real deployment would need stronger prompt-injection defenses, access controls, cost and latency monitoring, grading-drift evaluation, safe prompt rollouts and human review for uncertain or high-impact grades.

## Documentation


- Setup instructions and design decisions.
- Implementation trade-offs and known limitations.
- Code-review findings and severity ratings.
- Production monitoring and safe prompt-version rollout plans.
- Human-in-the-loop review criteria.
- AI usage log and corrections made during development.
- Git history and submission details.

## License

Created for the FDE Offline Exercise.
