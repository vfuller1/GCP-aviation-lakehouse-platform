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

Verified against google-adk==2.3.0 (installed and import-tested locally):
Agent/SequentialAgent field names and Runner/InMemorySessionService/
run_async signatures all match this module's usage.

IMPORTANT: ADK's underlying google-genai Client defaults to Gemini API key
auth, not Vertex AI. This project authenticates via GCP service account
(no API key), so GOOGLE_GENAI_USE_VERTEXAI/GOOGLE_CLOUD_PROJECT/
GOOGLE_CLOUD_LOCATION must be set BEFORE the Agent model strings are
resolved — done below via os.environ.setdefault(), matching how the rest
of this codebase (agent.py, retrieval_service.py) authenticates to Vertex AI.
"""

import asyncio
import logging
import os

# Must be set before any ADK Agent talks to a model — forces Vertex AI
# (service account) auth instead of ADK's default Gemini API key lookup.
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", os.getenv("GCP_PROJECT_ID", "gcp-lakehouseproject"))
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", os.getenv("VERTEX_REGION", "us-central1"))

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
