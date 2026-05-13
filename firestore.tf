# ---------------------------------------------------------------------------
# Firestore — RAG session memory store
# ---------------------------------------------------------------------------

resource "google_firestore_database" "rag_sessions" {
  project     = var.project_id
  name        = "rag-sessions"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  # Delete all documents when the database is destroyed (safe for session data)
  delete_protection_state = "DELETE_PROTECTION_DISABLED"
}

# TTL policy: automatically delete session documents after 'expireAt' timestamp
resource "google_firestore_field" "session_ttl" {
  project    = var.project_id
  database   = google_firestore_database.rag_sessions.name
  collection = "sessions"
  field      = "expireAt"

  ttl_config {}
}

# Grant the Cloud Run retrieval service account read/write access to Firestore
resource "google_project_iam_member" "retrieval_firestore_user" {
  count   = var.enable_vertex_ai ? 1 : 0
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.aviation_retrieval_sa[0].email}"

  depends_on = [google_firestore_database.rag_sessions]
}
