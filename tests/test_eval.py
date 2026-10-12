from app.llm import FakeLLM
from evals.run_eval import load_cases, main, pass_rate, run_eval


class AlwaysFullMarks(FakeLLM):
    """A grader that has been talked into giving everyone 5/5."""

    def generate(self, prompt: str, timeout_s: float) -> str:
        return '{"score": 5, "feedback": "Full marks!", "rubric_points_met": []}'


def test_golden_set_covers_the_required_cases():
    cases = {c["case"] for c in load_cases()}
    assert {"strong", "partial", "wrong", "off_topic", "injection"} <= cases


def test_eval_passes_with_the_default_fake(capsys):
    assert main([]) == 0
    assert "pass rate: 100%" in capsys.readouterr().out


def test_eval_gate_fails_when_the_grader_regresses(capsys):
    assert main(["--threshold", "0.8"], llm=AlwaysFullMarks()) == 1
    # Only the 'strong' case legitimately deserves 5/5.
    assert "pass rate: 20%" in capsys.readouterr().out


def test_failed_grading_counts_as_a_failed_case():
    results = run_eval(FakeLLM(["garbage"] * 3), load_cases()[:1], "grade_v1")
    assert results[0]["actual"] == "FAILED"
    assert pass_rate(results) == 0
