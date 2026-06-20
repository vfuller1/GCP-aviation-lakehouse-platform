"""
Worker 1: Risk Analyst.

Role: detect and quantify delay risk for an airline/route. Does NOT recommend
action — that is Worker 2's job. This separation of concerns (detect vs.
recommend) is what makes this a genuine multi-agent design rather than a
single agent with two tools.

NOTE: google-adk is a newer framework (2025). Verify this Agent() constructor
signature against the installed package version before relying on it —
ADK's API may have changed since this was written.
"""

from google.adk.agents import Agent

from .tools import detect_delay_risk

RISK_ANALYST_INSTRUCTION = """\
You are a Risk Analyst for an aviation operations platform.

Your ONLY job is to detect and quantify delay risk using the
detect_delay_risk tool. Do not recommend any operational action — that is
handled by a different agent downstream.

Always report:
  - Which airline/route is affected
  - The average delay in minutes
  - The delayed flight percentage
  - The weather-related percentage

Be precise and cite the exact numbers returned by the tool.
"""

risk_analyst = Agent(
    name="risk_analyst",
    model="gemini-2.5-flash",
    description="Detects and quantifies airline/route delay risk from BigQuery.",
    instruction=RISK_ANALYST_INSTRUCTION,
    tools=[detect_delay_risk],
)
