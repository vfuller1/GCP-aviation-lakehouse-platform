# Monitoring: export Cloud Run structured logs to BigQuery for token usage
# and guardrail dashboards in Looker Studio.

resource "google_logging_project_sink" "cloud_run_monitoring" {
  name        = "aviation-cloudrun-monitoring"
  destination = "bigquery.googleapis.com/projects/${var.project_id}/datasets/${google_bigquery_dataset.analytics_layer.dataset_id}"

  # Capture only our three structured event types — keeps the BQ table small.
  filter = <<-EOT
    resource.type="cloud_run_revision"
    AND resource.labels.service_name="aviation-retrieval"
    AND (
      jsonPayload.event="token_usage"
      OR jsonPayload.event="guardrail_triggered"
      OR jsonPayload.event="bq_fallback"
    )
  EOT

  bigquery_options {
    use_partitioned_tables = true
  }

  unique_writer_identity = true
}

# Grant the sink's service account write access to the BigQuery dataset.
resource "google_bigquery_dataset_iam_member" "logging_sink_writer" {
  dataset_id = google_bigquery_dataset.analytics_layer.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_logging_project_sink.cloud_run_monitoring.writer_identity
}
