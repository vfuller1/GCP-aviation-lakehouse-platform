# Cloud Run Retrieval Service for Aviation Intelligence
# Deploys the semantic retrieval + reasoning service
# Gated by enable_vertex_ai

# Service account for the Cloud Run retrieval service
resource "google_service_account" "aviation_retrieval_sa" {
  count           = var.enable_vertex_ai ? 1 : 0
  account_id      = "aviation-retrieval-sa"
  display_name    = "Aviation Intelligence Retrieval Service"
  description     = "Service account for Cloud Run retrieval service (Vector Search + Vertex Reasoning)"
}

# Allow Cloud Run to use Vertex Vector Search
resource "google_project_iam_member" "retrieval_vector_user" {
  count   = var.enable_vertex_ai ? 1 : 0
  project = var.project_id
  role    = "roles/aiplatform.indexEndpointUser"
  member  = "serviceAccount:${google_service_account.aviation_retrieval_sa[0].email}"
}

# Allow Cloud Run to call Vertex Reasoning (GenerativeModel)
resource "google_project_iam_member" "retrieval_vertex_user" {
  count   = var.enable_vertex_ai ? 1 : 0
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.aviation_retrieval_sa[0].email}"
}

# Allow Cloud Run to query BigQuery
resource "google_project_iam_member" "retrieval_bq_user" {
  count   = var.enable_vertex_ai ? 1 : 0
  project = var.project_id
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${google_service_account.aviation_retrieval_sa[0].email}"
}

# Allow Cloud Run to read AI artifacts bucket
resource "google_storage_bucket_iam_member" "retrieval_ai_reader" {
  count  = var.enable_vertex_ai ? 1 : 0
  bucket = google_storage_bucket.ai_artifacts[0].name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.aviation_retrieval_sa[0].email}"
}

# Cloud Run service deployment
resource "google_cloud_run_service" "aviation_retrieval" {
  count    = var.enable_vertex_ai ? 1 : 0
  name     = "aviation-retrieval"
  location = var.region

  template {
    spec {
      service_account_name = google_service_account.aviation_retrieval_sa[0].email
      containers {
        image = "us-central1-docker.pkg.dev/${var.project_id}/aviation-pipeline/retrieval:latest"
        
        # Environment variables
        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "VECTOR_SEARCH_ENDPOINT_ID"
          value = try(google_vertex_ai_index_endpoint.aviation_rag[0].name, "")
        }
        env {
          name  = "VECTOR_SEARCH_REGION"
          value = var.region
        }
        env {
          name  = "VECTOR_SEARCH_INDEX_ID"
          value = try(google_vertex_ai_index.aviation_rag[0].name, "")
        }
        env {
          name  = "BQ_DATASET"
          value = "aviation_analytics"
        }
        env {
          name  = "VERTEX_REGION"
          value = var.region
        }
        env {
          name  = "REASONING_MODEL"
          value = var.vertex_reasoning_model
        }
        env {
          name  = "PORT"
          value = "8080"
        }
        
        # Resource limits
        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
          }
        }
      }

      timeout_seconds = 3600
    }
    
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = "100"
        "autoscaling.knative.dev/minScale" = "0"
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }

  depends_on = [
    google_service_account.aviation_retrieval_sa,
    google_project_iam_member.retrieval_vector_user,
    google_project_iam_member.retrieval_vertex_user,
    google_project_iam_member.retrieval_bq_user,
    google_storage_bucket_iam_member.retrieval_ai_reader,
    google_vertex_ai_index_endpoint.aviation_rag
  ]
}

# Allow public access to the retrieval service
resource "google_cloud_run_service_iam_member" "retrieval_public" {
  count    = var.enable_vertex_ai ? 1 : 0
  service  = google_cloud_run_service.aviation_retrieval[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
  location = var.region
}

# Outputs
output "retrieval_service_url" {
  description = "The public URL of the Aviation Retrieval Service"
  value       = try(google_cloud_run_service.aviation_retrieval[0].status[0].url, null)
}

output "retrieval_service_account" {
  description = "The service account email for the retrieval service"
  value       = try(google_service_account.aviation_retrieval_sa[0].email, null)
}
