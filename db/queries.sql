-- Reporting queries. The "-- name:" markers let tests/test_queries.py run each one.

-- name: avg_score_and_failure_rate
-- (a) Average score and failure rate per question per prompt_version.
-- average_score is over successful runs only; failure_rate is failed runs / all runs.
SELECT
    s.question_id,
    g.prompt_version,
    ROUND(AVG(g.score) FILTER (WHERE g.status = 'success'), 2) AS average_score,
    ROUND(AVG(CASE WHEN g.status = 'failed' THEN 1.0 ELSE 0.0 END), 3) AS failure_rate,
    COUNT(*) AS grading_runs
FROM grades g
JOIN submissions s ON s.id = g.submission_id
GROUP BY s.question_id, g.prompt_version
ORDER BY s.question_id, g.prompt_version;

-- name: submissions_without_successful_grade
-- (b) Submissions that have no successful grade yet (never graded, or only failed runs).
SELECT s.id, s.question_id, s.student_id, s.submitted_at
FROM submissions s
WHERE NOT EXISTS (
    SELECT 1
    FROM grades g
    WHERE g.submission_id = s.id
      AND g.status = 'success'
)
ORDER BY s.id;

-- name: latest_grade_per_submission
-- (c) Latest grade per submission. id breaks ties when created_at is identical.
SELECT DISTINCT ON (g.submission_id)
    g.submission_id, g.id AS grade_id, g.status, g.score, g.prompt_version, g.created_at
FROM grades g
ORDER BY g.submission_id, g.created_at DESC, g.id DESC;
