"""
Shared BigQuery tools for the multi-agent module.

detect_delay_risk        -> risk_analyst (per-airline / per-route delay stats)
detect_weather_impact    -> weather_analyst (weather-specific delay breakdown)
check_pipeline_health    -> pipeline_health (data freshness, reuses agent.py's
                             get_pipeline_status query pattern)
"""

import json
import logging
import os

from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "gcp-lakehouseproject")
BQ_DATASET = os.getenv("BQ_DATASET", "aviation_analytics")


def detect_delay_risk(airline: str = "", route: str = "", days_back: int = 7) -> str:
    """Detect and quantify delay risk for an airline or route from BigQuery.

    Args:
        airline:   IATA carrier code filter, e.g. 'DL'. Leave blank for all airlines.
        route:     Route filter, e.g. 'BOS-EWR'. Leave blank for all routes.
        days_back: Look-back window in days (1-30).

    Returns:
        JSON string with rows of: airline, route, flight_count, avg_delay_min,
        delayed_pct, weather_pct.
    """
    try:
        client     = bigquery.Client(project=PROJECT_ID)
        days_back  = max(1, min(int(days_back), 30))
        airline    = airline.upper() if airline else ""
        route      = route.upper()   if route   else ""

        al_clause = "AND airline = @airline" if airline else ""
        rt_clause = "AND route = @route"     if route   else ""

        params = [bigquery.ScalarQueryParameter("days_back", "INT64", days_back)]
        if airline:
            params.append(bigquery.ScalarQueryParameter("airline", "STRING", airline))
        if route:
            params.append(bigquery.ScalarQueryParameter("route", "STRING", route))
        job_config = bigquery.QueryJobConfig(query_parameters=params)

        sql = f"""
        SELECT airline, route,
               COUNT(*) AS flight_count,
               ROUND(AVG(CAST(JSON_VALUE(metadata, '$.departure_delay_min') AS FLOAT64)), 1) AS avg_delay_min,
               ROUND(COUNTIF(JSON_VALUE(metadata, '$.status') = 'DELAYED') / COUNT(*) * 100, 1) AS delayed_pct,
               ROUND(COUNTIF(LOWER(JSON_VALUE(metadata, '$.weather_flag')) = 'true') / COUNT(*) * 100, 1) AS weather_pct
        FROM `{PROJECT_ID}.{BQ_DATASET}.ai_rag_documents`
        WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days_back DAY)
          {al_clause} {rt_clause}
        GROUP BY airline, route
        ORDER BY avg_delay_min DESC
        LIMIT 5
        """
        rows = [dict(r) for r in client.query(sql, job_config=job_config).result()]
        return json.dumps({"row_count": len(rows), "rows": rows})

    except Exception as exc:
        logger.warning("detect_delay_risk failed: %s", exc)
        return json.dumps({"error": str(exc), "rows": []})


def detect_weather_impact(airline: str = "", days_back: int = 7) -> str:
    """Isolate weather-specific delay impact, separate from scheduling/operational delays.

    Args:
        airline:   IATA carrier code filter, e.g. 'DL'. Leave blank for all airlines.
        days_back: Look-back window in days (1-30).

    Returns:
        JSON string with: total_flights, weather_affected, weather_pct,
        avg_delay_if_weather (minutes), avg_delay_if_not_weather (minutes).
    """
    try:
        client    = bigquery.Client(project=PROJECT_ID)
        days_back = max(1, min(int(days_back), 30))
        airline   = airline.upper() if airline else ""
        al_clause = "AND airline = @airline" if airline else ""

        params = [bigquery.ScalarQueryParameter("days_back", "INT64", days_back)]
        if airline:
            params.append(bigquery.ScalarQueryParameter("airline", "STRING", airline))
        job_config = bigquery.QueryJobConfig(query_parameters=params)

        sql = f"""
        SELECT
            COUNT(*) AS total_flights,
            COUNTIF(LOWER(JSON_VALUE(metadata, '$.weather_flag')) = 'true') AS weather_affected,
            ROUND(COUNTIF(LOWER(JSON_VALUE(metadata, '$.weather_flag')) = 'true') / COUNT(*) * 100, 1) AS weather_pct,
            ROUND(AVG(IF(LOWER(JSON_VALUE(metadata, '$.weather_flag')) = 'true',
                CAST(JSON_VALUE(metadata, '$.departure_delay_min') AS FLOAT64), NULL)), 1) AS avg_delay_if_weather,
            ROUND(AVG(IF(LOWER(JSON_VALUE(metadata, '$.weather_flag')) != 'true',
                CAST(JSON_VALUE(metadata, '$.departure_delay_min') AS FLOAT64), NULL)), 1) AS avg_delay_if_not_weather
        FROM `{PROJECT_ID}.{BQ_DATASET}.ai_rag_documents`
        WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days_back DAY)
          {al_clause}
        """
        rows = [dict(r) for r in client.query(sql, job_config=job_config).result()]
        return json.dumps({"row_count": len(rows), "rows": rows})

    except Exception as exc:
        logger.warning("detect_weather_impact failed: %s", exc)
        return json.dumps({"error": str(exc), "rows": []})


def check_pipeline_health() -> str:
    """Check data pipeline health and freshness — same query pattern as
    agent.py's get_pipeline_status, duplicated here to keep this module
    fully isolated from the LangGraph layer.

    Returns:
        JSON string with last ingestion timestamp and row counts, source
        indicates whether Gold layer or the always-populated ai_rag_documents
        table answered the query.
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)

        gold_sql = f"""
        SELECT last_generated_ts, gold_summary_rows, airline_rows,
               route_rows, total_flights_across_summaries
        FROM `{PROJECT_ID}.{BQ_DATASET}.bi_pipeline_refresh_v`
        """
        try:
            rows = [dict(r) for r in client.query(gold_sql).result()]
            if rows and rows[0].get("gold_summary_rows"):
                return json.dumps({"status": "ok", "source": "gold_layer", "pipeline_data": rows})
        except Exception as gold_exc:
            logger.warning("bi_pipeline_refresh_v failed (%s); falling back", gold_exc)

        rag_sql = f"""
        SELECT MAX(event_date) AS last_ingest_date, COUNT(*) AS rag_document_count,
               COUNT(DISTINCT airline) AS airline_count
        FROM `{PROJECT_ID}.{BQ_DATASET}.ai_rag_documents`
        """
        rows = [dict(r) for r in client.query(rag_sql).result()]
        return json.dumps({"status": "ok", "source": "ai_rag_documents", "pipeline_data": rows})

    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})
