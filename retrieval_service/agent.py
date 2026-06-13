"""
Aviation Intelligence Agent

LangGraph-based autonomous reasoning loop that sits above the single-shot RAG
retrieval service. Instead of a fixed embed→search→generate sequence, the agent
decides which tools to call and in what order, loops until it has enough evidence,
then constructs a grounded answer with citations.

Tool roster:
  - search_flight_records  : semantic vector search over individual flight events
  - query_analytics        : aggregated BigQuery statistics (delays, routes, weather)
  - get_pipeline_status    : data freshness / pipeline health check
"""

import json
import logging
import os
from typing import Annotated, List, TypedDict

from langchain_core.messages import BaseMessage
from langchain_core.tools import tool
from langchain_google_vertexai import ChatVertexAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

logger = logging.getLogger(__name__)

PROJECT_ID     = os.getenv("GCP_PROJECT_ID",            "gcp-lakehouseproject")
VECTOR_ENDPOINT_ID = os.getenv("VECTOR_SEARCH_ENDPOINT_ID", "")
VECTOR_REGION  = os.getenv("VECTOR_SEARCH_REGION",      "us-central1")
BQ_DATASET     = os.getenv("BQ_DATASET",                "aviation_analytics")
VERTEX_REGION  = os.getenv("VERTEX_REGION",             "us-central1")
REASONING_MODEL = os.getenv("REASONING_MODEL",          "gemini-2.5-flash")
EMBEDDING_MODEL = os.getenv("VERTEX_EMBEDDING_MODEL",   "text-embedding-005")

SYSTEM_PROMPT = """\
You are an aviation intelligence agent with access to real-time flight data.
Your goal is to answer questions about airline performance, route delays, and weather impacts
using grounded data — always cite specific numbers and data sources.

You have three tools:
  search_flight_records : semantic search over individual flight events (best for specific
                          routes, airlines, or event descriptions)
  query_analytics       : aggregated statistics from the data warehouse (best for trends,
                          rankings, comparisons across airlines or time windows)
  get_pipeline_status   : check data freshness and pipeline health

Strategy:
1. For specific questions (one route, one airline, one event), call search_flight_records first.
2. For aggregate questions (worst airline, busiest route, overall weather impact), call
   query_analytics first.
3. If the first call returns insufficient data, call a second tool with different parameters
   — e.g., widen the time window or switch query_type.
4. Always include specific numbers and the data source in your final answer.
5. Acknowledge when the underlying dataset is synthetic or the time window is narrow.
"""


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool
def search_flight_records(question: str, top_k: int = 5) -> str:
    """Semantic search over individual flight event records.

    Use for questions about specific routes, airlines, or flight events.
    Returns the most relevant flight records with delay minutes, weather flag, and status.

    Args:
        question: Natural-language description of what to find.
        top_k: Number of records to return (1-10).
    """
    try:
        import vertexai
        from google.cloud import aiplatform_v1
        from vertexai.language_models import TextEmbeddingModel

        vertexai.init(project=PROJECT_ID, location=VERTEX_REGION)
        embedding = TextEmbeddingModel.from_pretrained(EMBEDDING_MODEL).get_embeddings([question])[0].values

        if not VECTOR_ENDPOINT_ID:
            return json.dumps({"error": "Vector Search endpoint not configured", "records": []})

        endpoint_id = VECTOR_ENDPOINT_ID.split("/")[-1]
        client = aiplatform_v1.MatchServiceClient(
            client_options={"api_endpoint": f"{VECTOR_REGION}-aiplatform.googleapis.com"}
        )
        response = client.match({
            "index_endpoint": f"projects/{PROJECT_ID}/locations/{VECTOR_REGION}/indexEndpoints/{endpoint_id}",
            "deployed_index_id": "aviation-rag-deployed",
            "queries": [{"datapoint": {"vector": embedding}}],
            "return_full_datapoint": True,
        })

        results = []
        for match in response.responses[0].matches[:top_k]:
            try:
                md = dict(getattr(match.datapoint, "custom_metadata", {}).items())
            except Exception:
                md = {}
            results.append({
                "doc_id":     match.id,
                "similarity": round(float(match.distance), 4),
                "content":    md.get("content", ""),
                "airline":    md.get("airline", ""),
                "route":      md.get("route", ""),
                "event_date": md.get("event_date", ""),
            })

        return json.dumps({"record_count": len(results), "records": results})

    except Exception as exc:
        logger.warning("search_flight_records failed: %s", exc)
        return json.dumps({"error": str(exc), "records": []})


@tool
def query_analytics(
    query_type: str,
    airline: str = "",
    route: str = "",
    days_back: int = 7,
) -> str:
    """Aggregated aviation statistics from BigQuery.

    Args:
        query_type: One of 'airline' (delay stats per carrier), 'route_risk' (risk scores
                    per route), 'weather' (weather impact summary), or 'generic' (overall
                    summary from the RAG documents table — works even when Parquet export
                    is not ready).
        airline:   IATA carrier code filter, e.g. 'AA'. Leave blank for all airlines.
        route:     Route filter, e.g. 'ATL-LAX'. Leave blank for all routes.
        days_back: Look-back window in days (1-30).
    """
    try:
        from google.cloud import bigquery

        client    = bigquery.Client(project=PROJECT_ID)
        days_back = max(1, min(int(days_back), 30))
        al_filter = f"AND airline = '{airline.upper()}'" if airline else ""
        rt_filter = f"AND route = '{route.upper()}'"     if route   else ""
        date_expr = f"DATE_SUB(CURRENT_DATE(), INTERVAL {days_back} DAY)"

        if query_type in ("route_risk", "risk"):
            sql = f"""
            SELECT route,
                   total_flights                             AS flight_count,
                   ROUND(risk_score, 2)                      AS avg_risk_score,
                   ROUND(disruption_rate * 100, 1)           AS disruption_pct,
                   ROUND(weather_impact_rate * 100, 1)       AS weather_impact_pct
            FROM `{PROJECT_ID}.{BQ_DATASET}.ai_route_risk_v`
            WHERE 1=1 {rt_filter}
            ORDER BY avg_risk_score DESC
            LIMIT 10
            """
        elif query_type in ("airline", "performance", "delays"):
            sql = f"""
            SELECT airline,
                   COUNT(*) AS flight_count,
                   ROUND(AVG(CAST(departure_delay_min AS FLOAT64)), 1)                   AS avg_delay_min,
                   ROUND(COUNTIF(departure_delay_min > 15) / COUNT(*) * 100, 1)          AS delayed_pct,
                   ROUND(COUNTIF(weather_flag) / COUNT(*) * 100, 1)                      AS weather_pct
            FROM `{PROJECT_ID}.{BQ_DATASET}.silver_flights_ext`
            WHERE DATE(event_ts) >= {date_expr} {al_filter}
            GROUP BY airline
            ORDER BY avg_delay_min DESC
            LIMIT 10
            """
        elif query_type == "weather":
            sql = f"""
            SELECT COUNT(*) AS total_flights,
                   COUNTIF(weather_flag) AS weather_affected,
                   ROUND(COUNTIF(weather_flag) / COUNT(*) * 100, 1)                                     AS weather_pct,
                   ROUND(AVG(IF(weather_flag, CAST(departure_delay_min AS FLOAT64), NULL)), 1)           AS avg_delay_if_weather
            FROM `{PROJECT_ID}.{BQ_DATASET}.silver_flights_ext`
            WHERE DATE(event_ts) >= {date_expr}
            """
        else:
            # generic — always works; queries the native ai_rag_documents table
            sql = f"""
            SELECT airline, route,
                   COUNT(*) AS flight_count,
                   ROUND(AVG(CAST(JSON_VALUE(metadata, '$.departure_delay_min') AS FLOAT64)), 1) AS avg_delay_min,
                   ROUND(COUNTIF(CAST(JSON_VALUE(metadata, '$.weather_flag') AS BOOL)) / COUNT(*) * 100, 1) AS weather_pct,
                   ROUND(COUNTIF(JSON_VALUE(metadata, '$.status') = 'DELAYED') / COUNT(*) * 100, 1) AS delayed_pct
            FROM `{PROJECT_ID}.{BQ_DATASET}.ai_rag_documents`
            WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days_back} DAY)
              {al_filter} {rt_filter}
            GROUP BY airline, route
            ORDER BY avg_delay_min DESC
            LIMIT 10
            """

        rows = [dict(r) for r in client.query(sql).result()]
        return json.dumps({"row_count": len(rows), "rows": rows})

    except Exception as exc:
        logger.warning("query_analytics failed: %s", exc)
        return json.dumps({"error": str(exc), "rows": []})


@tool
def get_pipeline_status() -> str:
    """Check data pipeline health and data freshness.

    Use when the user asks about data recency or when prior tool calls returned 0 rows
    (may indicate the pipeline hasn't run yet or Parquet export is pending).
    Returns the latest ingestion timestamp and row counts per summary type.
    """
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=PROJECT_ID)
        sql = f"""
        SELECT summary_type, row_count, latest_generated_ts
        FROM `{PROJECT_ID}.{BQ_DATASET}.bi_pipeline_refresh_v`
        ORDER BY latest_generated_ts DESC
        """
        rows = [dict(r) for r in client.query(sql).result()]
        return json.dumps({"status": "ok", "pipeline_data": rows})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


# ---------------------------------------------------------------------------
# Agent graph
# ---------------------------------------------------------------------------

class _AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]


_TOOLS = [search_flight_records, query_analytics, get_pipeline_status]
_tool_node = ToolNode(_TOOLS)

# Compiled graph — built once at import time, reused across requests.
_agent_graph = None


def _get_agent():
    global _agent_graph
    if _agent_graph is not None:
        return _agent_graph

    llm_with_tools = ChatVertexAI(
        model=REASONING_MODEL,
        project=PROJECT_ID,
        location=VERTEX_REGION,
    ).bind_tools(_TOOLS)

    def _agent_node(state: _AgentState) -> dict:
        return {"messages": [llm_with_tools.invoke(state["messages"])]}

    def _should_continue(state: _AgentState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(_AgentState)
    graph.add_node("agent", _agent_node)
    graph.add_node("tools", _tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    _agent_graph = graph.compile()
    return _agent_graph


def run(messages: List[BaseMessage]) -> dict:
    """Invoke the agent and return the final state dict.

    The caller is responsible for prepending a SystemMessage and any history.
    The final answer is in result['messages'][-1].content.
    """
    return _get_agent().invoke({"messages": messages})
