"""Mini eval harness: grade the golden answers and gate on the pass rate.

    python -m evals.run_eval [--threshold 0.8]

Exits 1 when the pass rate is below the threshold, so CI can block a prompt change.
"""

import argparse
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.grading import run_grading
from app.llm import FakeLLM, LLMClient

GOLDEN_PATH = Path(__file__).resolve().parent / "golden.jsonl"


def load_cases(path: Path = GOLDEN_PATH) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def run_eval(llm: LLMClient, cases: list[dict], prompt_version: str) -> list[dict]:
    results = []
    for case in cases:
        outcome = run_grading(
            llm,
            question=case["question"],
            rubric=case["rubric"],
            max_marks=case["max_marks"],
            answer=case["answer"],
            prompt_version=prompt_version,
            backoff_base_s=0,
        )
        # A failed grading run has no score and can never pass.
        passed = (
            outcome.status == "success" and case["min_score"] <= outcome.score <= case["max_score"]
        )
        results.append(
            {
                "case": case["case"],
                "expected": f"{case['min_score']:g}-{case['max_score']:g}",
                "actual": f"{outcome.score:g}" if outcome.score is not None else "FAILED",
                "passed": passed,
                "latency_ms": outcome.latency_ms,
            }
        )
    return results


def pass_rate(results: list[dict]) -> float:
    return sum(r["passed"] for r in results) / len(results) if results else 0.0


def print_table(results: list[dict]) -> None:
    print(f"{'case':<12} {'expected':<9} {'actual':<7} {'result':<6} {'latency_ms':>10}")
    print("-" * 48)
    for r in results:
        verdict = "PASS" if r["passed"] else "FAIL"
        print(
            f"{r['case']:<12} {r['expected']:<9} {r['actual']:<7} {verdict:<6}"
            f" {r['latency_ms']:>10}"
        )


def main(argv=None, llm: LLMClient | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--threshold", type=float, default=0.8, help="minimum pass rate (0-1)")
    args = parser.parse_args(argv)

    llm = llm or FakeLLM()
    prompt_version = get_settings().prompt_version
    results = run_eval(llm, load_cases(), prompt_version)
    rate = pass_rate(results)

    print(f"model={llm.model} prompt_version={prompt_version}\n")
    print_table(results)
    print(f"\npass rate: {rate:.0%} (threshold {args.threshold:.0%})")
    return 0 if rate >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
