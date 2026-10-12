import pytest

from app.parsing import InvalidOutput, parse_grade_output

VALID = '{"score": 3.5, "feedback": "Mostly right.", "rubric_points_met": ["definition"]}'


def test_valid_json():
    grade = parse_grade_output(VALID, max_marks=5)
    assert grade.score == 3.5
    assert grade.feedback == "Mostly right."
    assert grade.rubric_points_met == ["definition"]


@pytest.mark.parametrize("fence", ["```json\n{}\n```", "```\n{}\n```", "  ```JSON\n{}\n```  \n"])
def test_fenced_json(fence):
    grade = parse_grade_output(fence.replace("{}", VALID), max_marks=5)
    assert grade.score == 3.5


def test_score_equal_to_max_marks_is_allowed():
    raw = '{"score": 5, "feedback": "Perfect.", "rubric_points_met": []}'
    assert parse_grade_output(raw, max_marks=5).score == 5


@pytest.mark.parametrize(
    "raw, reason",
    [
        ('{"score": 3, "rubric_points_met": []}', "feedback"),  # missing field
        ('{"score": 6, "feedback": "x", "rubric_points_met": []}', "exceeds max_marks"),
        ('{"score": -1, "feedback": "x", "rubric_points_met": []}', "score"),
        ('{"score": "3", "feedback": "x", "rubric_points_met": []}', "score"),  # string score
        ('{"score": true, "feedback": "x", "rubric_points_met": []}', "score"),
        ('{"score": NaN, "feedback": "x", "rubric_points_met": []}', "score"),
        ('{"score": 3, "feedback": "", "rubric_points_met": []}', "feedback"),
        ('{"score": 3, "feedback": "x", "rubric_points_met": "all"}', "rubric_points_met"),
        ("[1, 2, 3]", "schema mismatch"),
        ("Sure! I would give this answer 4 out of 5.", "not valid JSON"),
        ("", "not valid JSON"),
    ],
)
def test_invalid_output_is_rejected(raw, reason):
    with pytest.raises(InvalidOutput, match=reason):
        parse_grade_output(raw, max_marks=5)
