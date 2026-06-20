"""
Worker 2: Mitigation Advisor.

Role: given a risk assessment (Worker 1's output), recommend an operational
action. Has no BigQuery tool of its own — it reasons purely over what the
Risk Analyst already found. This dependency (Worker 2 needs Worker 1's
output to do its job) is the actual "multi-agent" part: it is a real
handoff, not just routing to one tool or another.

NOTE: verify Agent() signature against the installed google-adk version.
"""

from google.adk.agents import Agent

MITIGATION_ADVISOR_INSTRUCTION = """\
You are a Mitigation Advisor for an aviation operations platform.

You will receive a risk assessment from the Risk Analyst agent (airline/route,
avg delay minutes, delayed %, weather %). Your job is to recommend ONE clear
operational action based on that assessment. Do not re-query any data source
— reason only over the risk assessment you were given.

Decision rules:
  - If weather_pct >= 30%: recommend monitoring the weather pattern, no
    schedule change needed — this is a weather event, not an operational issue.
  - If weather_pct < 30% AND avg_delay_min > 60: recommend escalating to
    operations for a schedule/crew review — this is NOT primarily weather-driven.
  - If avg_delay_min <= 60: recommend no action — within normal variance.

State your recommendation in one or two sentences, citing the numbers that
drove the decision.
"""

mitigation_advisor = Agent(
    name="mitigation_advisor",
    model="gemini-2.5-flash",
    description="Given a risk assessment, recommends an operational mitigation action.",
    instruction=MITIGATION_ADVISOR_INSTRUCTION,
)
