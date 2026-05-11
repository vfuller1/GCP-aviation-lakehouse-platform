# ---------------------------------------------------------------------------
# Vertex AI foundation for aviation intelligence (MVP)
# Toggle: set enable_vertex_ai = true in tfvars (or TF_VAR_enable_vertex_ai)
# ---------------------------------------------------------------------------

# Enable Vertex AI API.
resource "google_project_service" "vertex_ai_api" {
  count              = var.enable_vertex_ai ? 1 : 0
  project            = var.project_id
  service            = "aiplatform.googleapis.com"
  disable_on_destroy = false
}

# Service account used by AI pipelines to build embeddings and query analytics.
resource "google_service_account" "aviation_ai_sa" {
  count        = var.enable_vertex_ai ? 1 : 0
  project      = var.project_id
  account_id   = "aviation-ai-sa"
  display_name = "Aviation Intelligence AI Service Account"
}

# Allow AI pipeline service account to invoke Vertex AI models and endpoints.
resource "google_project_iam_member" "aviation_ai_vertex_user" {
  count   = var.enable_vertex_ai ? 1 : 0
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.aviation_ai_sa[0].email}"
}

# Allow AI pipeline service account to query BigQuery semantic views.
resource "google_project_iam_member" "aviation_ai_bigquery_user" {
  count   = var.enable_vertex_ai ? 1 : 0
  project = var.project_id
  role    = "roles/bigquery.user"
  member  = "serviceAccount:${google_service_account.aviation_ai_sa[0].email}"
}

resource "google_project_iam_member" "aviation_ai_bigquery_data_viewer" {
  count   = var.enable_vertex_ai ? 1 : 0
  project = var.project_id
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${google_service_account.aviation_ai_sa[0].email}"
}

# Allow AI pipeline service account to write embedding artifacts and retrieval manifests.
resource "google_storage_bucket_iam_member" "aviation_ai_bucket_writer" {
  count  = var.enable_vertex_ai ? 1 : 0
  bucket = google_storage_bucket.ai_artifacts[0].name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.aviation_ai_sa[0].email}"
}

# Allow AI pipeline service account to read medallion outputs used to build RAG documents.
resource "google_storage_bucket_iam_member" "aviation_ai_silver_reader" {
  count  = var.enable_vertex_ai ? 1 : 0
  bucket = google_storage_bucket.medallion_buckets["silver"].name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.aviation_ai_sa[0].email}"
}

resource "google_storage_bucket_iam_member" "aviation_ai_gold_reader" {
  count  = var.enable_vertex_ai ? 1 : 0
  bucket = google_storage_bucket.medallion_buckets["gold"].name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.aviation_ai_sa[0].email}"
}

# Optional: allow the existing GKE ingest service account to run AI enrichment in-cluster.
resource "google_project_iam_member" "pipeline_sa_vertex_user" {
  count   = var.enable_vertex_ai && var.enable_gke ? 1 : 0
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.pipeline_sa[0].email}"
}

resource "google_project_iam_member" "pipeline_sa_bigquery_user" {
  count   = var.enable_vertex_ai && var.enable_gke ? 1 : 0
  project = var.project_id
  role    = "roles/bigquery.user"
  member  = "serviceAccount:${google_service_account.pipeline_sa[0].email}"
}

resource "google_project_iam_member" "pipeline_sa_bigquery_data_editor" {
  count   = var.enable_vertex_ai && var.enable_gke ? 1 : 0
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.pipeline_sa[0].email}"
}

resource "google_storage_bucket_iam_member" "pipeline_sa_ai_bucket_writer" {
  count  = var.enable_vertex_ai && var.enable_gke ? 1 : 0
  bucket = google_storage_bucket.ai_artifacts[0].name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.pipeline_sa[0].email}"
}

output "aviation_ai_service_account_email" {
  value       = var.enable_vertex_ai ? google_service_account.aviation_ai_sa[0].email : null
  description = "Service account for Vertex AI embedding and analytics pipeline"
}

output "aviation_ai_artifacts_bucket" {
  value       = var.enable_vertex_ai ? google_storage_bucket.ai_artifacts[0].name : null
  description = "Bucket used for AI retrieval and embedding artifacts"
}
