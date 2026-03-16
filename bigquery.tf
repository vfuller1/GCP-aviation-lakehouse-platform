# 2. The Intelligence Layer (BigQuery)
resource "google_bigquery_dataset" "analytics_layer" {
  dataset_id    = "aviation_analytics"
  friendly_name = "Aviation Analytics"
  description   = "Gold layer for AI and BI insights"
  location      = var.region
}
