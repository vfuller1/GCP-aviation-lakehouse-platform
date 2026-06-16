# 2. The Intelligence Layer (BigQuery)
resource "google_bigquery_dataset" "analytics_layer" {
  dataset_id    = "aviation_analytics"
  friendly_name = "Aviation Analytics"
  description   = "Gold layer for AI and BI insights"
  location      = var.region
}

# External table over Silver Parquet export in GCS.
resource "google_bigquery_table" "silver_flights_ext" {
  dataset_id = google_bigquery_dataset.analytics_layer.dataset_id
  table_id   = "silver_flights_ext"
  deletion_protection = false

  # Phase 2: explicit schema to map Parquet INT96 event_ts to TIMESTAMP.
  schema = jsonencode([
    {
      name = "flight_id"
      type = "STRING"
      mode = "NULLABLE"
    },
    {
      name = "airline"
      type = "STRING"
      mode = "NULLABLE"
    },
    {
      name = "origin"
      type = "STRING"
      mode = "NULLABLE"
    },
    {
      name = "destination"
      type = "STRING"
      mode = "NULLABLE"
    },
    {
      name = "departure_delay_min"
      type = "INTEGER"
      mode = "NULLABLE"
    },
    {
      name = "arrival_delay_min"
      type = "INTEGER"
      mode = "NULLABLE"
    },
    {
      name = "weather_flag"
      type = "BOOLEAN"
      mode = "NULLABLE"
    },
    {
      name = "status"
      type = "STRING"
      mode = "NULLABLE"
    },
    {
      name = "event_ts"
      type = "TIMESTAMP"
      mode = "NULLABLE"
    },
    {
      name = "ingest_date"
      type = "DATE"
      mode = "NULLABLE"
    }
  ])

  external_data_configuration {
    source_format = "PARQUET"
    autodetect    = false
    # Flat export (no ingest_date partitioning) so *.parquet is valid (single wildcard).
    # BigQuery does not support multiple * in a single GCS URI.
    source_uris = ["gs://${var.project_id}-silver/aviation/cleaned/*.parquet"]
  }
}

# External table over Gold Parquet export in GCS.
resource "google_bigquery_table" "gold_summary_ext" {
  dataset_id          = google_bigquery_dataset.analytics_layer.dataset_id
  table_id            = "gold_summary_ext"
  deletion_protection = false

  external_data_configuration {
    source_format = "PARQUET"
    autodetect    = true
    # Flat export (no summary_type partitioning) so *.parquet is valid (single wildcard).
    # summary_type remains a regular data column in the Parquet files, so views can
    # filter with WHERE summary_type = '...' without hive partitioning.
    source_uris = ["gs://${var.project_id}-gold/aviation/aggregated/*.parquet"]
  }
}

# BI view: airline performance cards and charts.
resource "google_bigquery_table" "bi_airline_performance_v" {
  dataset_id = google_bigquery_dataset.analytics_layer.dataset_id
  table_id   = "bi_airline_performance_v"

  view {
    use_legacy_sql = false
    query = <<-SQL
      SELECT
        dimension_key AS airline,
        avg_dep_delay_min,
        avg_arr_delay_min,
        total_flights,
        generated_ts
      FROM `${var.project_id}.${google_bigquery_dataset.analytics_layer.dataset_id}.${google_bigquery_table.gold_summary_ext.table_id}`
      WHERE summary_type = 'by_airline'
    SQL
  }
}

# BI view: route-level delay leaderboard.
resource "google_bigquery_table" "bi_route_performance_v" {
  dataset_id = google_bigquery_dataset.analytics_layer.dataset_id
  table_id   = "bi_route_performance_v"

  view {
    use_legacy_sql = false
    query = <<-SQL
      SELECT
        dimension_key AS route,
        avg_dep_delay_min,
        avg_arr_delay_min,
        total_flights,
        generated_ts
      FROM `${var.project_id}.${google_bigquery_dataset.analytics_layer.dataset_id}.${google_bigquery_table.gold_summary_ext.table_id}`
      WHERE summary_type = 'by_route'
    SQL
  }
}

# BI view: daily delayed-flight trend.
resource "google_bigquery_table" "bi_daily_delays_v" {
  dataset_id = google_bigquery_dataset.analytics_layer.dataset_id
  table_id   = "bi_daily_delays_v"

  view {
    use_legacy_sql = false
    query = <<-SQL
      SELECT
        SAFE_CAST(dimension_key AS DATE) AS delay_date,
        total_flights AS delayed_flights,
        generated_ts
      FROM `${var.project_id}.${google_bigquery_dataset.analytics_layer.dataset_id}.${google_bigquery_table.gold_summary_ext.table_id}`
      WHERE summary_type = 'delayed_by_day'
    SQL
  }
}

# BI view: pipeline refresh/status snapshot for dashboard freshness checks.
resource "google_bigquery_table" "bi_pipeline_refresh_v" {
  dataset_id = google_bigquery_dataset.analytics_layer.dataset_id
  table_id   = "bi_pipeline_refresh_v"

  view {
    use_legacy_sql = false
    query = <<-SQL
      SELECT
        MAX(generated_ts) AS last_generated_ts,
        COUNT(*) AS gold_summary_rows,
        COUNTIF(summary_type = 'by_airline') AS airline_rows,
        COUNTIF(summary_type = 'by_route') AS route_rows,
        COUNTIF(summary_type = 'delayed_by_day') AS delayed_day_rows,
        COUNTIF(summary_type = 'on_time_pct') AS on_time_rows,
        SUM(total_flights) AS total_flights_across_summaries
      FROM `${var.project_id}.${google_bigquery_dataset.analytics_layer.dataset_id}.${google_bigquery_table.gold_summary_ext.table_id}`
    SQL
  }
}

# AI view: delay explanation features at the flight record level.
resource "google_bigquery_table" "ai_delay_explanations_v" {
  dataset_id = google_bigquery_dataset.analytics_layer.dataset_id
  table_id   = "ai_delay_explanations_v"

  view {
    use_legacy_sql = false
    query = <<-SQL
      SELECT
        flight_id,
        airline,
        origin,
        destination,
        CONCAT(origin, '-', destination) AS route,
        COALESCE(
          TIMESTAMP_MICROS(SAFE_CAST(CAST(event_ts AS STRING) AS INT64)),
          SAFE_CAST(CAST(event_ts AS STRING) AS TIMESTAMP)
        ) AS event_ts,
        SAFE_CAST(departure_delay_min AS INT64) AS departure_delay_min,
        SAFE_CAST(arrival_delay_min AS INT64) AS arrival_delay_min,
        SAFE_CAST(weather_flag AS BOOL) AS weather_flag,
        status,
        CASE
          WHEN SAFE_CAST(weather_flag AS BOOL) THEN 'WEATHER'
          WHEN SAFE_CAST(departure_delay_min AS INT64) >= 60 THEN 'SEVERE_DEP_DELAY'
          WHEN SAFE_CAST(arrival_delay_min AS INT64) >= 60 THEN 'SEVERE_ARR_DELAY'
          WHEN status = 'CANCELLED' THEN 'CANCELLATION'
          WHEN status = 'DIVERTED' THEN 'DIVERSION'
          ELSE 'OPERATIONAL'
        END AS primary_delay_driver
      FROM `${var.project_id}.${google_bigquery_dataset.analytics_layer.dataset_id}.${google_bigquery_table.silver_flights_ext.table_id}`
    SQL
  }
}

# AI view: route-level risk metrics for retrieval and BI narratives.
resource "google_bigquery_table" "ai_route_risk_v" {
  dataset_id = google_bigquery_dataset.analytics_layer.dataset_id
  table_id   = "ai_route_risk_v"

  view {
    use_legacy_sql = false
    query = <<-SQL
      WITH base AS (
        SELECT
          airline,
          origin,
          destination,
          CONCAT(origin, '-', destination) AS route,
          SAFE_CAST(departure_delay_min AS INT64) AS departure_delay_min,
          SAFE_CAST(arrival_delay_min AS INT64) AS arrival_delay_min,
          SAFE_CAST(weather_flag AS BOOL) AS weather_flag,
          status
        FROM `${var.project_id}.${google_bigquery_dataset.analytics_layer.dataset_id}.${google_bigquery_table.silver_flights_ext.table_id}`
      )
      SELECT
        route,
        ANY_VALUE(airline) AS dominant_airline,
        COUNT(*) AS total_flights,
        COUNTIF(status IN ('DELAYED', 'CANCELLED', 'DIVERTED')) / COUNT(*) AS disruption_rate,
        COUNTIF(departure_delay_min >= 60 OR arrival_delay_min >= 60) / COUNT(*) AS severe_delay_rate,
        COUNTIF(weather_flag) / COUNT(*) AS weather_impact_rate,
        AVG(departure_delay_min) AS avg_departure_delay_min,
        AVG(arrival_delay_min) AS avg_arrival_delay_min,
        ROUND(
          100 * (
            0.45 * (COUNTIF(status IN ('DELAYED', 'CANCELLED', 'DIVERTED')) / COUNT(*)) +
            0.35 * (COUNTIF(departure_delay_min >= 60 OR arrival_delay_min >= 60) / COUNT(*)) +
            0.20 * (COUNTIF(weather_flag) / COUNT(*))
          ),
          2
        ) AS risk_score
      FROM base
      GROUP BY route
    SQL
  }
}

# AI table: canonical RAG document store to be populated by the embedding pipeline.
resource "google_bigquery_table" "ai_rag_documents" {
  dataset_id = google_bigquery_dataset.analytics_layer.dataset_id
  table_id   = "ai_rag_documents"

  schema = jsonencode([
    {
      name = "doc_id"
      type = "STRING"
      mode = "REQUIRED"
    },
    {
      name = "content"
      type = "STRING"
      mode = "REQUIRED"
    },
    {
      name = "source_type"
      type = "STRING"
      mode = "NULLABLE"
    },
    {
      name = "airline"
      type = "STRING"
      mode = "NULLABLE"
    },
    {
      name = "route"
      type = "STRING"
      mode = "NULLABLE"
    },
    {
      name = "event_date"
      type = "DATE"
      mode = "NULLABLE"
    },
    {
      name = "embedding"
      type = "FLOAT64"
      mode = "REPEATED"
    },
    {
      name = "metadata"
      type = "JSON"
      mode = "NULLABLE"
    },
    {
      name = "updated_ts"
      type = "TIMESTAMP"
      mode = "REQUIRED"
    }
  ])
}

# AI view: normalized facts for natural-language analytics and RAG chunk generation.
resource "google_bigquery_table" "ai_nl_analytics_facts_v" {
  dataset_id = google_bigquery_dataset.analytics_layer.dataset_id
  table_id   = "ai_nl_analytics_facts_v"

  view {
    use_legacy_sql = false
    query = <<-SQL
      SELECT
        'route_risk' AS fact_type,
        route AS fact_key,
        TO_JSON_STRING(STRUCT(
          dominant_airline,
          total_flights,
          disruption_rate,
          severe_delay_rate,
          weather_impact_rate,
          avg_departure_delay_min,
          avg_arrival_delay_min,
          risk_score
        )) AS fact_payload,
        CONCAT(
          'Route ', route, ' risk score is ', CAST(risk_score AS STRING),
          ' with disruption rate ', CAST(ROUND(disruption_rate * 100, 2) AS STRING), '%',
          ' and weather impact ', CAST(ROUND(weather_impact_rate * 100, 2) AS STRING), '%.'
        ) AS narrative_text
      FROM `${var.project_id}.${google_bigquery_dataset.analytics_layer.dataset_id}.${google_bigquery_table.ai_route_risk_v.table_id}`

      UNION ALL

      SELECT
        'airline_performance' AS fact_type,
        airline AS fact_key,
        TO_JSON_STRING(STRUCT(
          avg_dep_delay_min,
          avg_arr_delay_min,
          total_flights,
          generated_ts
        )) AS fact_payload,
        CONCAT(
          'Airline ', airline, ' average departure delay is ', CAST(ROUND(avg_dep_delay_min, 2) AS STRING),
          ' minutes across ', CAST(total_flights AS STRING), ' flights.'
        ) AS narrative_text
      FROM `${var.project_id}.${google_bigquery_dataset.analytics_layer.dataset_id}.${google_bigquery_table.bi_airline_performance_v.table_id}`
    SQL
  }
}

# ── Monitoring views ───────────────────────────────────────────────────────────
# These views read from the Cloud Logging sink table created by monitoring.tf.
# The sink auto-creates the table on the first matching log entry. If terraform
# apply runs before any requests have been made, re-run apply once traffic starts.

resource "google_bigquery_table" "monitoring_token_usage_v" {
  dataset_id          = google_bigquery_dataset.analytics_layer.dataset_id
  table_id            = "monitoring_token_usage_v"
  deletion_protection = false

  view {
    use_legacy_sql = false
    query          = <<-SQL
      SELECT
        timestamp,
        TIMESTAMP_TRUNC(timestamp, HOUR)              AS hour,
        jsonPayload.session_id                        AS session_id,
        jsonPayload.endpoint                          AS endpoint,
        CAST(jsonPayload.prompt_tokens   AS INT64)    AS prompt_tokens,
        CAST(jsonPayload.response_tokens AS INT64)    AS response_tokens,
        CAST(jsonPayload.total_tokens    AS INT64)    AS total_tokens
      FROM `${var.project_id}.${google_bigquery_dataset.analytics_layer.dataset_id}.run_googleapis_com_stdout`
      WHERE jsonPayload.event = 'token_usage'
        AND _PARTITIONTIME >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
    SQL
  }
}

resource "google_bigquery_table" "monitoring_guardrails_v" {
  dataset_id          = google_bigquery_dataset.analytics_layer.dataset_id
  table_id            = "monitoring_guardrails_v"
  deletion_protection = false

  view {
    use_legacy_sql = false
    query          = <<-SQL
      SELECT
        timestamp,
        TIMESTAMP_TRUNC(timestamp, HOUR)              AS hour,
        jsonPayload.event                             AS event_type,
        jsonPayload.guardrail_type                    AS guardrail_type,
        jsonPayload.reason                            AS reason,
        jsonPayload.session_id                        AS session_id,
        CAST(jsonPayload.vs_results AS INT64)         AS vs_results,
        severity
      FROM `${var.project_id}.${google_bigquery_dataset.analytics_layer.dataset_id}.run_googleapis_com_stdout`
      WHERE jsonPayload.event IN ('guardrail_triggered', 'bq_fallback')
        AND _PARTITIONTIME >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
    SQL
  }
}
