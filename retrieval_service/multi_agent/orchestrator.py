"""
Super-agent orchestrator — sequential handoff between Risk Analyst and
Mitigation Advisor.

Disruption Response Chain:
  1. risk_analyst runs first   -> detects & quantifies the problem
  2. mitigation_advisor runs second, receiving risk_analyst's output
     as its input -> recommends an action
  3. SequentialAgent returns the final agent's response as the answer

This is a SequentialAgent specifically (not ParallelAgent) because Worker 2
has a hard dependency on Worker 1's output — it cannot reason about
mitigation before risk has been quantified. Contrast with a fan-out/fan-in
design (parallel workers + synthesis) which would be used for independent
workers, e.g. a "daily ops briefing" combining risk + weather + pipeline
health checks that don't depend on each other.

NOTE: SequentialAgent composition and Runner/session API are based on
google-adk's documented patterns as of its 2025 release. Verify against
the installed package version — this is a newer framework and the exact
Runner/session calls may have changed.
"""

import asyncio
import logging
import os

from google.adk.agents import SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .worker_risk import risk_analyst
from .worker_mitigation import mitigation_advisor

logger = logging.getLogger(__name__)

APP_NAME = "aviation-disruption-response"

disruption_response_orchestrator = SequentialAgent(
    name="disruption_response_orchestrator",
    sub_agents=[risk_analyst, mitigation_advisor],
)

_session_service = InMemorySessionService()


async def _run_async(question: str, user_id: str = "demo-user") -> dict:
    session = await _session_service.create_session(app_name=APP_NAME, user_id=user_id)
    runner = Runner(
        agent=disruption_response_orchestrator,
        app_name=APP_NAME,
        session_service=_session_service,
    )

    content = types.Content(role="user", parts=[types.Part(text=question)])
    final_answer = ""
    agents_run = []

    async for event in runner.run_async(
        user_id=user_id, session_id=session.id, new_message=content
    ):
        if getattr(event, "author", None):
            agents_run.append(event.author)
        if event.is_final_response() and event.content and event.content.parts:
            final_answer = event.content.parts[0].text

    return {"answer": final_answer, "agents_run": agents_run}


def run(question: str) -> dict:
    """Synchronous entrypoint matching agent.py's run() signature.

    Returns: {"answer": str, "agents_run": ["risk_analyst", "mitigation_advisor"]}
    """
    return asyncio.run(_run_async(question))
