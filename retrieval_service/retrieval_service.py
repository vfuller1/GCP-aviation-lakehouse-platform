"""
Aviation Intelligence Retrieval Service

Semantic retrieval + grounded reasoning for aviation delays, route risk, and NL analytics.
Accepts natural-language questions and returns grounded answers with source citations.

Environment variables:
  GCP_PROJECT_ID: Google Cloud project ID
  VECTOR_SEARCH_ENDPOINT_ID: Index endpoint ID for retrieval
  VECTOR_SEARCH_REGION: Region (us-central1)
  VECTOR_SEARCH_INDEX_ID: Vector Search index ID
  BQ_DATASET: BigQuery dataset (aviation_analytics)
  VERTEX_REGION: Region for Vertex Reasoning (us-central1)
  REASONING_MODEL: Vertex model (gemini-2.5-flash)
  PORT: HTTP port (8080 default)
"""

import json
import os
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
import functools

from flask import Flask, request, jsonify
from google.cloud import aiplatform
from google.cloud import bigquery
from google.api_core.gapic_v1 import client_info as grpc_client_info

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Load environment
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "gcp-lakehouseproject")
VECTOR_ENDPOINT_ID = os.getenv("VECTOR_SEARCH_ENDPOINT_ID", "")
VECTOR_REGION = os.getenv("VECTOR_SEARCH_REGION", "us-central1")
VECTOR_INDEX_ID = os.getenv("VECTOR_SEARCH_INDEX_ID", "")
BQ_DATASET = os.getenv("BQ_DATASET", "aviation_analytics")
VERTEX_REGION = os.getenv("VERTEX_REGION", "us-central1")
REASONING_MODEL = os.getenv("REASONING_MODEL", "gemini-2.5-flash")
PORT = int(os.getenv("PORT", 8080))

# Initialize clients (lazy)
_bq_client = None
_embedding_client = None
_reasoning_client = None


@functools.lru_cache(maxsize=1)
def get_bq_client():
    """Lazy initialize BigQuery client."""
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


@functools.lru_cache(maxsize=1)
def get_embedding_client():
    """Lazy initialize Vertex Embeddings client."""
    global _embedding_client
    if _embedding_client is None:
        aiplatform.init(project=PROJECT_ID, location=VERTEX_REGION)
        _embedding_client = aiplatform.TextEmbeddingModel.from_pretrained("text-embedding-005")
    return _embedding_client


@functools.lru_cache(maxsize=1)
def get_reasoning_client():
    """Lazy initialize Vertex Reasoning (GenerativeModel) client."""
    global _reasoning_client
    if _reasoning_client is None:
        aiplatform.init(project=PROJECT_ID, location=VERTEX_REGION)
        _reasoning_client = aiplatform.GenerativeModel(REASONING_MODEL)
    return _reasoning_client


def embed_query(query_text: str) -> List[float]:
    """Embed a natural-language query into a vector."""
    try:
        client = get_embedding_client()
        embeddings = client.get_embeddings([query_text])
        return embeddings[0].values
    except Exception as e:
        logger.error(f"Failed to embed query: {e}")
        raise


def search_vector_index(query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
    """Query Vertex Vector Search for top-K similar documents."""
    if not VECTOR_ENDPOINT_ID or not VECTOR_INDEX_ID:
        logger.warning("Vector Search not configured; falling back to BigQuery")
        return []

    try:
        from google.cloud import aiplatform_v1
        
        client = aiplatform_v1.MatchServiceClient(
            client_options={"api_endpoint": f"{VECTOR_REGION}-aiplatform.googleapis.com"}
        )
        
        request_body = {
            "index_endpoint": f"projects/{PROJECT_ID}/locations/{VECTOR_REGION}/indexEndpoints/{VECTOR_ENDPOINT_ID}",
            "deployed_index_id": "aviation-rag-deployed",
            "queries": [
                {
                    "datapoint": {
                        "vector": query_vector
                    }
                }
            ],
            "return_full_datapoint": True,
        }
        
        response = client.match(request_body)
        results = []
        
        for match in response.responses[0].matches[:top_k]:
            results.append({
                "doc_id": match.id,
                "distance": float(match.distance),
                "content": match.datapoint.custom_metadata.get("content", ""),
                "source_type": match.datapoint.custom_metadata.get("source_type", ""),
                "airline": match.datapoint.custom_metadata.get("airline", ""),
                "route": match.datapoint.custom_metadata.get("route", ""),
                "event_date": match.datapoint.custom_metadata.get("event_date", ""),
            })
        
        logger.info(f"Vector Search returned {len(results)} results")
        return results
        
    except Exception as e:
        logger.error(f"Vector Search failed: {e}; falling back to BigQuery")
        return []


def query_bigquery_fallback(
    query_type: str,
    airline: Optional[str] = None,
    route: Optional[str] = None,
    days_back: int = 7
) -> List[Dict[str, Any]]:
    """Fallback: deterministic BigQuery queries for common questions."""
    client = get_bq_client()
    
    if days_back < 1:
        days_back = 7
    
    date_filter = f"DATE_SUB(CURRENT_DATE(), INTERVAL {days_back} DAY)"
    airline_filter = f"AND airline = '{airline}'" if airline else ""
    route_filter = f"AND route = '{route}'" if route else ""
    
    # Route Risk Analysis
    if query_type.lower() in ["route_risk", "risk", "disruption"]:
        sql = f"""
        SELECT 
            route,
            COUNT(*) as flight_count,
            ROUND(AVG(risk_score), 2) as avg_risk_score,
            ROUND(SUM(CASE WHEN disruption_flag THEN 1 ELSE 0 END) / COUNT(*) * 100, 1) as disruption_pct,
            ROUND(SUM(CASE WHEN severe_delay_flag THEN 1 ELSE 0 END) / COUNT(*) * 100, 1) as severe_delay_pct
        FROM `{PROJECT_ID}.{BQ_DATASET}.ai_route_risk_v`
        WHERE event_date >= {date_filter} {route_filter}
        GROUP BY route
        ORDER BY avg_risk_score DESC
        LIMIT 10
        """
    
    # Airline Performance
    elif query_type.lower() in ["airline", "performance", "delays"]:
        sql = f"""
        SELECT 
            airline,
            COUNT(*) as flight_count,
            ROUND(AVG(CAST(delay_minutes AS FLOAT64)), 1) as avg_delay_minutes,
            ROUND(SUM(CASE WHEN delay_minutes > 15 THEN 1 ELSE 0 END) / COUNT(*) * 100, 1) as delayed_pct,
            ROUND(SUM(CASE WHEN weather_flag THEN 1 ELSE 0 END) / COUNT(*) * 100, 1) as weather_impact_pct
        FROM `{PROJECT_ID}.{BQ_DATASET}.silver_flights_ext`
        WHERE event_date >= {date_filter} {airline_filter}
        GROUP BY airline
        ORDER BY avg_delay_minutes DESC
        LIMIT 10
        """
    
    # Weather Impact
    elif query_type.lower() in ["weather", "impact"]:
        sql = f"""
        SELECT 
            COUNT(*) as total_flights,
            SUM(CASE WHEN weather_flag THEN 1 ELSE 0 END) as weather_affected,
            ROUND(SUM(CASE WHEN weather_flag THEN 1 ELSE 0 END) / COUNT(*) * 100, 1) as weather_pct,
            ROUND(AVG(CASE WHEN weather_flag THEN CAST(delay_minutes AS FLOAT64) ELSE NULL END), 1) as avg_delay_if_weather
        FROM `{PROJECT_ID}.{BQ_DATASET}.silver_flights_ext`
        WHERE event_date >= {date_filter}
        """
    
    else:
        # Generic NL facts
        sql = f"""
        SELECT 
            COUNT(*) as total_flights,
            COUNT(DISTINCT airline) as airline_count,
            COUNT(DISTINCT route) as route_count,
            ROUND(AVG(CAST(delay_minutes AS FLOAT64)), 1) as avg_delay_minutes
        FROM `{PROJECT_ID}.{BQ_DATASET}.silver_flights_ext`
        WHERE event_date >= {date_filter}
        """
    
    try:
        query_job = client.query(sql)
        rows = list(query_job)
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"BigQuery fallback failed: {e}")
        return []


def build_reasoning_prompt(
    question: str,
    context_docs: List[Dict[str, Any]],
    deterministic_facts: List[Dict[str, Any]]
) -> str:
    """Build a prompt for Vertex Reasoning with retrieved context and facts."""
    context_str = ""
    if context_docs:
        context_str = "**Retrieved Aviation Documents:**\n"
        for i, doc in enumerate(context_docs[:3], 1):
            context_str += f"\n[Ref {i}] {doc.get('source_type', 'Unknown')} - {doc.get('airline', 'N/A')} {doc.get('route', 'N/A')} ({doc.get('event_date', 'N/A')})\n"
            context_str += f"Content: {doc.get('content', '')[:500]}...\n"
    
    facts_str = ""
    if deterministic_facts:
        facts_str = "\n**Deterministic Facts from Data Warehouse:**\n"
        for row in deterministic_facts[:3]:
            facts_str += f"{json.dumps(row, indent=2)}\n"
    
    prompt = f"""You are an aviation intelligence assistant. Answer the following question based on the provided context and facts.
Provide a clear, grounded answer with specific data citations (e.g., "Route ATL-LAX has a 67% disruption rate based on 450 flights").
If uncertain, acknowledge the limitation.

Question: {question}

{context_str}
{facts_str}

Please provide a concise, data-driven answer with specific metrics and citations."""
    
    return prompt


def reason_with_vertex(prompt: str) -> str:
    """Call Vertex Reasoning API to generate a grounded answer."""
    try:
        client = get_reasoning_client()
        response = client.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.error(f"Vertex Reasoning failed: {e}")
        return f"Error generating answer: {str(e)}"


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy"}), 200


@app.route("/retrieve", methods=["POST"])
def retrieve():
    """
    Main retrieval endpoint.
    
    Request JSON:
    {
        "question": "Why are flights on route ATL-LAX experiencing delays?",
        "airline": "optional airline code",
        "route": "optional route (e.g., ATL-LAX)",
        "days_back": 7,
        "top_k": 5
    }
    
    Response JSON:
    {
        "answer": "Grounded answer with citations",
        "context_docs": [...retrieved docs...],
        "facts": [...deterministic BigQuery facts...],
        "sources": [...source citations...]
    }
    """
    try:
        payload = request.get_json()
        question = payload.get("question", "").strip()
        airline = payload.get("airline", "").upper() or None
        route = payload.get("route", "").upper() or None
        days_back = payload.get("days_back", 7)
        top_k = payload.get("top_k", 5)
        
        if not question:
            return jsonify({"error": "Missing 'question' field"}), 400
        
        logger.info(f"Query: {question} (airline={airline}, route={route}, days_back={days_back})")
        
        # 1. Embed the query
        query_vector = embed_query(question)
        logger.info(f"Embedded query to {len(query_vector)}-dim vector")
        
        # 2. Retrieve from Vector Search
        context_docs = search_vector_index(query_vector, top_k=top_k)
        logger.info(f"Retrieved {len(context_docs)} documents from Vector Search")
        
        # 3. Query BigQuery for deterministic facts
        # Infer query type from question keywords
        query_type = "generic"
        if any(word in question.lower() for word in ["risk", "disruption", "delay"]):
            query_type = "route_risk" if "route" in question.lower() else "airline"
        
        facts = query_bigquery_fallback(query_type, airline=airline, route=route, days_back=days_back)
        logger.info(f"Retrieved {len(facts)} fact rows from BigQuery")
        
        # 4. Build reasoning prompt
        prompt = build_reasoning_prompt(question, context_docs, facts)
        
        # 5. Call Vertex Reasoning
        answer = reason_with_vertex(prompt)
        logger.info(f"Generated answer: {answer[:100]}...")
        
        # 6. Format response with citations
        sources = [
            {
                "doc_id": doc.get("doc_id"),
                "source_type": doc.get("source_type"),
                "airline": doc.get("airline"),
                "route": doc.get("route"),
                "event_date": doc.get("event_date"),
                "similarity": doc.get("distance"),
            }
            for doc in context_docs
        ]
        
        return jsonify({
            "question": question,
            "answer": answer,
            "context_count": len(context_docs),
            "facts_count": len(facts),
            "sources": sources,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }), 200
    
    except Exception as e:
        logger.error(f"Retrieval failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/health/ready", methods=["GET"])
def readiness():
    """Readiness check: verify Vector Search and BigQuery connectivity."""
    try:
        # Check BigQuery
        client = get_bq_client()
        client.query(f"SELECT 1").result()
        
        # Check embedding model (lazy load)
        _ = get_embedding_client()
        
        return jsonify({"ready": True}), 200
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return jsonify({"ready": False, "error": str(e)}), 503


if __name__ == "__main__":
    logger.info(f"Starting Aviation Retrieval Service on port {PORT}")
    logger.info(f"Project: {PROJECT_ID}, Region: {VERTEX_REGION}, Model: {REASONING_MODEL}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
