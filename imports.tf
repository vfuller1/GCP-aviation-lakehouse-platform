# Import existing resources into Terraform state when they already exist.
# This avoids 409 Already Exists failures in CI while keeping declarative management.

import {
  to = google_bigquery_dataset.analytics_layer
  id = "projects/${var.project_id}/datasets/aviation_analytics"
}

import {
  for_each = toset(["bronze", "silver", "gold"])
  to       = google_storage_bucket.medallion_buckets[each.key]
  id       = "${var.project_id}-${each.key}"
}
