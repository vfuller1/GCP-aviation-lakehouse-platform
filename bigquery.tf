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

  external_data_configuration {
    source_format = "PARQUET"
    autodetect    = true
    source_uris = [
      "gs://${var.project_id}-silver/aviation/cleaned/silver_flights.parquet",
    ]
  }
}

# External table over Gold Parquet export in GCS.
resource "google_bigquery_table" "gold_summary_ext" {
  dataset_id = google_bigquery_dataset.analytics_layer.dataset_id
  table_id   = "gold_summary_ext"

  external_data_configuration {
    source_format = "PARQUET"
    autodetect    = true
    source_uris = [
      "gs://${var.project_id}-gold/aviation/aggregated/gold_summary.parquet",
    ]
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
