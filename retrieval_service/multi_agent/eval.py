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
  4. Token budget — did the run stay under a sane token ceiling? (catches
                   a runaway agent loop or unexpectedly verbose prompt
                   inflating cost — not an exact-match check, just a bound)

A second eval suite, eval_coordination_routing(), covers /coordinate
(coordinator.py). Unlike the fixed chain above, the correct workers_called
genuinely VARIES per question — there's no single hardcoded expectation.
So these checks assert routing CONSTRAINTS instead of an exact list:
  - "is the data fresh" must call pipeline_health and NOTHING else
    (calling risk_analyst/weather_analyst here would be wasted work)
  - a mitigation question must call mitigation_advisor AFTER risk_analyst
    (the data dependency the coordinator must respect)
  - a pure weather question must NOT call mitigation_advisor
    (no action was requested, so recommending one is overreach)
Each coordination case also gets the same token-budget check, scaled to
the number of workers actually called (more workers called legitimately
costs more tokens, so the ceiling scales with workers_called rather than
being a single fixed number).

These thresholds were calibrated against verified live Cloud Run runs
(see README "Coordination Agent" section) — not invented in the abstract.

A third function, eval_architecture_comparison(), runs the SAME question
through /agent (LangGraph), /multi-agent, and /coordinate and reports what
each one called plus its token cost, side by side. It is NOT a pass/fail
check — the three architectures don't do equivalent work by design, so
there's nothing to assert correctness against. It exists to make the
cost/architecture tradeoff concrete instead of describing it in the abstract.

Run with:  python -m multi_agent.eval
Requires GCP Application Default Credentials (Cloud Run, Cloud Shell, or
`gcloud auth application-default login` locally).
"""

import json
import re

from .orchestrator import run
from .coordinator import run as run_coordinator
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

# Generous per-model-call ceiling — wide enough to not flag normal prompt/
# response variance, tight enough to catch a genuinely runaway agent (e.g.
# the recursion_limit bug previously found in agent.py's LangGraph loop).
_TOKENS_PER_CALL_CEILING = 4000


def _check_token_budget(total_tokens: int, num_calls: int) -> str:
    ceiling = _TOKENS_PER_CALL_CEILING * num_calls
    if total_tokens <= 0:
        return f"FAIL — got {total_tokens} tokens, expected > 0"
    if total_tokens > ceiling:
        return f"FAIL — {total_tokens} tokens exceeds ceiling {ceiling} ({num_calls} calls)"
    return f"PASS — {total_tokens} tokens (ceiling {ceiling} for {num_calls} calls)"


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

    # Check 4 — Token budget: this chain is always exactly 2 model calls
    # (risk_analyst, mitigation_advisor), so the ceiling is fixed here.
    report["checks"]["token_budget"] = _check_token_budget(result["total_tokens"], num_calls=2)
    report["total_tokens"] = result["total_tokens"]

    report["ground_truth"] = top_row
    report["answer"] = result["answer"]
    return report


EVAL_CASES = [
    {"question": "Delta is showing high delays on BOS-EWR — what should operations do?",
     "airline": "DL", "route": "BOS-EWR"},
    {"question": "What should we do about delays affecting American Airlines?",
     "airline": "AA", "route": ""},
]


def eval_coordination_routing(question: str, constraint: str, **kwargs) -> dict:
    """Run one /coordinate eval case and check a routing CONSTRAINT
    (not an exact list, since the correct set of workers varies)."""
    report = {"question": question, "checks": {}}
    result = run_coordinator(question)
    called = result["workers_called"]
    report["workers_called"] = called
    report["answer"] = result["answer"]

    if constraint == "exactly_pipeline_health":
        report["checks"]["routing"] = (
            "PASS" if called == ["pipeline_health"]
            else f"FAIL — expected exactly ['pipeline_health'], got {called}"
        )

    elif constraint == "mitigation_after_risk":
        has_both = "risk_analyst" in called and "mitigation_advisor" in called
        ordered = has_both and called.index("risk_analyst") < called.index("mitigation_advisor")
        report["checks"]["routing"] = (
            "PASS" if ordered
            else f"FAIL — expected risk_analyst before mitigation_advisor, got {called}"
        )

    elif constraint == "no_mitigation_for_pure_weather":
        report["checks"]["routing"] = (
            "PASS" if "mitigation_advisor" not in called and "weather_analyst" in called
            else f"FAIL — expected weather_analyst without mitigation_advisor, got {called}"
        )

    # Token budget scales with workers actually called (+1 for the
    # coordinator's own routing/synthesis calls), since that legitimately
    # varies per question by design.
    report["checks"]["token_budget"] = _check_token_budget(
        result["total_tokens"], num_calls=len(called) + 1
    )
    report["total_tokens"] = result["total_tokens"]

    return report


COORDINATION_EVAL_CASES = [
    {"question": "Is the data fresh?",
     "constraint": "exactly_pipeline_health"},
    {"question": "Delta is delayed on BOS-EWR — what should ops do?",
     "constraint": "mitigation_after_risk"},
    {"question": "Is Delta's BOS-EWR delay weather or scheduling related?",
     "constraint": "no_mitigation_for_pure_weather"},
]


def eval_architecture_comparison(question: str) -> dict:
    """Run the same question through /agent (LangGraph), /multi-agent
    (ADK fixed chain), and /coordinate (ADK dynamic routing) and report
    what each one called + how many tokens it cost.

    This is NOT a pass/fail correctness check — the three architectures
    don't do equivalent work by design (one tool-calling agent vs. a fixed
    2-agent handoff vs. 1-4 dynamically chosen workers), so there's no
    single "correct" answer to assert against. It's a cost/architecture
    comparison, useful for showing the tradeoff directly rather than
    describing it in the abstract.
    """
    import agent as aviation_agent
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    report = {"question": question}

    # /agent — LangGraph single agent looping over N tools.
    messages = [SystemMessage(content=aviation_agent.SYSTEM_PROMPT), HumanMessage(content=question)]
    agent_result = aviation_agent.run(messages)
    agent_tools_called = [m.name for m in agent_result["messages"] if hasattr(m, "name") and m.name]
    agent_tokens = 0
    for msg in agent_result["messages"]:
        if isinstance(msg, AIMessage):
            um = (getattr(msg, "response_metadata", None) or {}).get("usage_metadata", {})
            agent_tokens += um.get("total_token_count", 0)
    report["agent"] = {"tools_called": agent_tools_called, "total_tokens": agent_tokens}

    # /multi-agent — ADK fixed SequentialAgent (always risk -> mitigation).
    multi_result = run(question)
    report["multi_agent"] = {
        "agents_run": multi_result["agents_run"],
        "total_tokens": multi_result["total_tokens"],
    }

    # /coordinate — ADK dynamic coordinator (1-4 workers depending on question).
    coord_result = run_coordinator(question)
    report["coordinate"] = {
        "workers_called": coord_result["workers_called"],
        "total_tokens": coord_result["total_tokens"],
    }

    return report


COMPARISON_CASES = [
    "Delta is delayed on BOS-EWR — what should ops do?",
]


def main():
    all_passed = True

    print(f"Running {len(EVAL_CASES)} eval case(s) against the live Disruption Response Chain...\n")
    for case in EVAL_CASES:
        report = eval_disruption_response_chain(**case)
        print(f"Question: {report['question']}")
        if "skipped" in report["checks"]:
            print(f"  SKIPPED: {report['checks']['skipped']}\n")
            continue
        print(f"  total_tokens: {report.get('total_tokens')}")
        for check_name, result in report["checks"].items():
            print(f"  {check_name:12s}: {result}")
            if result.startswith("FAIL"):
                all_passed = False
        print()

    print(f"Running {len(COORDINATION_EVAL_CASES)} eval case(s) against the live coordination agent...\n")
    for case in COORDINATION_EVAL_CASES:
        report = eval_coordination_routing(**case)
        print(f"Question: {report['question']}")
        print(f"  workers_called: {report['workers_called']}")
        print(f"  total_tokens  : {report['total_tokens']}")
        for check_name, result in report["checks"].items():
            print(f"  {check_name:12s}: {result}")
            if result.startswith("FAIL"):
                all_passed = False
        print()

    print(f"Running {len(COMPARISON_CASES)} architecture comparison case(s) "
          "(/agent vs /multi-agent vs /coordinate — no pass/fail, cost comparison only)...\n")
    for question in COMPARISON_CASES:
        report = eval_architecture_comparison(question)
        print(f"Question: {report['question']}")
        print(f"  /agent       (LangGraph)   tools_called={report['agent']['tools_called']}  "
              f"total_tokens={report['agent']['total_tokens']}")
        print(f"  /multi-agent (ADK fixed)   agents_run={report['multi_agent']['agents_run']}  "
              f"total_tokens={report['multi_agent']['total_tokens']}")
        print(f"  /coordinate  (ADK dynamic) workers_called={report['coordinate']['workers_called']}  "
              f"total_tokens={report['coordinate']['total_tokens']}")
        print()

    print("=" * 50)
    print("ALL CHECKS PASSED" if all_passed else "SOME CHECKS FAILED")
    return 0 if all_passed else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
