"""
Lightweight eval harness for the multi-agent module.

google-adk ships a full evaluation framework (google.adk.evaluation —
AgentEvaluator, trajectory_evaluator, hallucinations_v1, llm_as_judge, etc.)
driven by `.test.json` eval-set files conforming to its EvalCase/Invocation
schema. That framework is the production-grade path, but its schema is
involved enough (Invocation.intermediate_data carries structured tool-call
events) that hand-authoring correct eval-set files without being able to
run them against real GCP credentials risked shipping broken fixtures.

This harness instead checks the three things that actually matter for THIS
agent chain, using plain Python assertions against the live system:

  1. Trajectory  — did risk_analyst run before mitigation_advisor?
                   (proves the sequential handoff actually happened)
  2. Grounding   — does the final answer cite a real number from Worker 1's
                   BigQuery output? (proves Worker 2 used Worker 1's data,
                   not a generic answer)
  3. Correctness — does the final decision match what the documented
                   decision rule (in worker_mitigation.py's instruction)
                   would produce, independently recomputed here from the
                   same BigQuery numbers Worker 1 saw?

Run with:  python -m multi_agent.eval
Requires GCP Application Default Credentials (Cloud Run, Cloud Shell, or
`gcloud auth application-default login` locally).
"""

import json
import re

from .orchestrator import run
from .tools import detect_delay_risk


def _expected_decision(avg_delay_min: float, weather_pct: float) -> str:
    """Reimplementation of the decision rule from worker_mitigation.py's
    instruction — kept independent so this eval can catch the agent
    deviating from its own documented rule."""
    if weather_pct >= 30:
        return "monitor_weather"
    if weather_pct < 30 and avg_delay_min > 60:
        return "escalate_ops"
    return "no_action"


_DECISION_KEYWORDS = {
    "monitor_weather": ["weather", "monitor"],
    "escalate_ops":     ["escalate", "schedule", "crew", "operations"],
    "no_action":        ["no action", "normal", "within"],
}


def eval_disruption_response_chain(question: str, airline: str = "", route: str = "") -> dict:
    """Run one eval case and return a pass/fail report dict."""
    report = {"question": question, "checks": {}}

    # Ground truth: query the same data Worker 1 will see, independently.
    ground_truth = json.loads(detect_delay_risk(airline=airline, route=route))
    rows = ground_truth.get("rows", [])
    if not rows:
        report["checks"]["skipped"] = "No BigQuery rows for this airline/route — cannot eval"
        return report

    top_row = rows[0]
    expected = _expected_decision(top_row["avg_delay_min"], top_row["weather_pct"])

    # Run the actual multi-agent chain.
    result = run(question)
    answer = result["answer"].lower()
    agents_run = result["agents_run"]

    # Check 1 — Trajectory: risk_analyst before mitigation_advisor.
    report["checks"]["trajectory"] = (
        "PASS" if agents_run == ["risk_analyst", "mitigation_advisor"]
        else f"FAIL — got {agents_run}"
    )

    # Check 2 — Grounding: answer cites a real number from Worker 1's data.
    numbers_in_answer = re.findall(r"\d+\.?\d*", result["answer"])
    expected_numbers = [str(top_row["avg_delay_min"]), str(top_row["weather_pct"])]
    grounded = any(n in numbers_in_answer for n in expected_numbers)
    report["checks"]["grounding"] = (
        f"PASS — found {expected_numbers} in answer" if grounded
        else f"FAIL — expected one of {expected_numbers}, answer had {numbers_in_answer}"
    )

    # Check 3 — Correctness: final decision matches the documented rule.
    keywords = _DECISION_KEYWORDS[expected]
    matched = any(kw in answer for kw in keywords)
    report["checks"]["correctness"] = (
        f"PASS — expected '{expected}', found matching keyword" if matched
        else f"FAIL — expected '{expected}' (keywords {keywords}), answer: {answer[:200]}"
    )

    report["ground_truth"] = top_row
    report["answer"] = result["answer"]
    return report


EVAL_CASES = [
    {"question": "Delta is showing high delays on BOS-EWR — what should operations do?",
     "airline": "DL", "route": "BOS-EWR"},
    {"question": "What should we do about delays affecting American Airlines?",
     "airline": "AA", "route": ""},
]


def main():
    print(f"Running {len(EVAL_CASES)} eval case(s) against the live Disruption Response Chain...\n")
    all_passed = True
    for case in EVAL_CASES:
        report = eval_disruption_response_chain(**case)
        print(f"Question: {report['question']}")
        if "skipped" in report["checks"]:
            print(f"  SKIPPED: {report['checks']['skipped']}\n")
            continue
        for check_name, result in report["checks"].items():
            print(f"  {check_name:12s}: {result}")
            if result.startswith("FAIL"):
                all_passed = False
        print()

    print("=" * 50)
    print("ALL CHECKS PASSED" if all_passed else "SOME CHECKS FAILED")
    return 0 if all_passed else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
