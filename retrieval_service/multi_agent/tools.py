"""
Shared BigQuery tool for the multi-agent module.

Reuses the same query patterns as agent.py's query_analytics, scoped down
to what the Risk Analyst worker needs: per-airline / per-route delay stats.
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
