# ---------------------------------------------------------------------------
# GKE Autopilot cluster + Artifact Registry + Pipeline IAM
# Toggle: set enable_gke = true in tfvars (or GitHub secret TF_VAR_enable_gke)
# ---------------------------------------------------------------------------

# Enable required APIs
resource "google_project_service" "container_api" {
  count   = var.enable_gke ? 1 : 0
  project = var.project_id
  service = "container.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "artifactregistry_api" {
  count   = var.enable_gke ? 1 : 0
  project = var.project_id
  service = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Artifact Registry — Docker repo for pipeline container images
# ---------------------------------------------------------------------------
resource "google_artifact_registry_repository" "pipeline" {
  count         = var.enable_gke ? 1 : 0
  project       = var.project_id
  location      = var.region
  repository_id = "aviation-pipeline"
  format        = "DOCKER"
  description   = "Docker images for aviation pipeline Kubernetes jobs"

  depends_on = [google_project_service.artifactregistry_api]
}

# ---------------------------------------------------------------------------
# GKE Autopilot cluster
# ---------------------------------------------------------------------------
resource "google_container_cluster" "aviation_pipeline" {
  count    = var.enable_gke ? 1 : 0
  name     = "aviation-pipeline"
  location = var.region
  project  = var.project_id

  enable_autopilot = true

  # Workload Identity is mandatory in Autopilot
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  deletion_protection = false

  depends_on = [google_project_service.container_api]
}

# ---------------------------------------------------------------------------
# GCP Service Account for the Kubernetes pipeline jobs
# ---------------------------------------------------------------------------
resource "google_service_account" "pipeline_sa" {
  count        = var.enable_gke ? 1 : 0
  project      = var.project_id
  account_id   = "aviation-pipeline-sa"
  display_name = "Aviation Pipeline Kubernetes Job SA"
}

# Grant write access to the Bronze bucket only (least-privilege)
resource "google_storage_bucket_iam_member" "pipeline_bronze_writer" {
  count  = var.enable_gke ? 1 : 0
  bucket = google_storage_bucket.medallion_buckets["bronze"].name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.pipeline_sa[0].email}"
}

# Workload Identity binding: K8s SA → GCP SA
resource "google_service_account_iam_member" "pipeline_workload_identity" {
  count              = var.enable_gke ? 1 : 0
  service_account_id = google_service_account.pipeline_sa[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[aviation-pipeline/aviation-pipeline-sa]"

  depends_on = [google_container_cluster.aviation_pipeline]
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
output "gke_cluster_name" {
  value       = var.enable_gke ? google_container_cluster.aviation_pipeline[0].name : null
  description = "GKE Autopilot cluster name"
}

output "artifact_registry_url" {
  value       = var.enable_gke ? "${var.region}-docker.pkg.dev/${var.project_id}/aviation-pipeline" : null
  description = "Artifact Registry Docker host prefix for pipeline images"
}
