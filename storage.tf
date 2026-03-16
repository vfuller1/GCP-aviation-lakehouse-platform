# 1. The Medallion Storage Layers (Data Lake)
resource "google_storage_bucket" "medallion_buckets" {
  for_each      = toset(["bronze", "silver", "gold"])
  name          = "${var.project_id}-${each.key}"
  location      = var.region
  force_destroy = true # Allows easy cleanup during dev

  uniform_bucket_level_access = true
}
