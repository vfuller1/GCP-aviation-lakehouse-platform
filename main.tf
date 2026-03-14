provider "google" {
  project = var.project_id
  region  = var.region
}

# 1. The Medallion Storage Layers (Data Lake)
resource "google_storage_bucket" "medallion_buckets" {
  for_each      = toset(["bronze", "silver", "gold"])
  name          = "${var.project_id}-${each.key}"
  location      = var.region
  force_destroy = true # Allows easy cleanup during dev

  uniform_bucket_level_access = true
}

# 2. The Intelligence Layer (BigQuery)
resource "google_bigquery_dataset" "analytics_layer" {
  dataset_id                  = "aviation_analytics"
  friendly_name               = "Aviation Analytics"
  description                 = "Gold layer for AI and BI insights"
  location                    = var.region
}