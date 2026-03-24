# Import existing resources into Terraform state when they already exist.
# This avoids 409 Already Exists failures in CI while keeping declarative management.

import {
  to = google_bigquery_dataset.analytics_layer
  id = "projects/${var.project_id}/datasets/aviation_analytics"
}

import {
  to = google_storage_bucket.medallion_buckets["bronze"]
  id = "${var.project_id}-bronze"
}

import {
  to = google_storage_bucket.medallion_buckets["silver"]
  id = "${var.project_id}-silver"
}

import {
  to = google_storage_bucket.medallion_buckets["gold"]
  id = "${var.project_id}-gold"
}
