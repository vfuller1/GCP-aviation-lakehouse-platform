"""
Worker: Pipeline Health.

Role: check data freshness and pipeline status. Only relevant when a
question asks about data recency — most operational questions (delays,
weather, mitigation) don't need this, so the coordinator should skip it
unless explicitly asked.
"""

from google.adk.agents import Agent

from .tools import check_pipeline_health

PIPELINE_HEALTH_INSTRUCTION = """\
You are a Pipeline Health monitor for an aviation operations platform.

Your ONLY job is to check data freshness and pipeline status using the
check_pipeline_health tool. Do not discuss delays, weather, or
recommendations — that is out of scope for your role.

Report:
  - When the data was last refreshed
  - Whether the Gold layer (Databricks export) or the native RAG table
    answered the query (source field) — note if Gold layer data is stale
    or unavailable
"""

pipeline_health = Agent(
    name="pipeline_health",
    model="gemini-2.5-flash",
    description="Checks data pipeline freshness and health from BigQuery.",
    instruction=PIPELINE_HEALTH_INSTRUCTION,
    tools=[check_pipeline_health],
)
