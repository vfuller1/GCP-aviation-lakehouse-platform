# Vertex AI Vector Search for semantic retrieval of aviation intelligence
# Gated by enable_vertex_ai && enable_vector_search

# Create the Vector Search index pointing to ai_rag_documents
resource "google_vertex_ai_index" "aviation_rag" {
  count          = var.enable_vertex_ai && var.enable_vector_search ? 1 : 0
  region         = var.region
  display_name   = "aviation-rag-index"
  description    = "Vector Search index for aviation RAG documents (delay explanations, route risk, NL facts)"
  index_update_method = "BATCH_UPDATE"

  metadata {
    config {
      dimensions                  = var.vector_dimension
      approximate_neighbors_count = 100
      shard_size                  = "SHARD_SIZE_SMALL"
      distance_measure_type       = "DOT_PRODUCT_DISTANCE"
    }
    contents_delta_uri = "gs://${var.project_id}-ai/aviation/indices/rag/"
  }

  index_config {
    algorithm_config {
      tree_ah_config {
        leaf_node_embedding_count = 100
        leaf_nodes_to_search_percent = 7
      }
    }
  }

  depends_on = [
    google_bigquery_table.ai_rag_documents,
    google_project_service.aiplatform
  ]
}

# Create the Vector Search index endpoint for serving queries
resource "google_vertex_ai_index_endpoint" "aviation_rag" {
  count            = var.enable_vertex_ai && var.enable_vector_search ? 1 : 0
  region           = var.region
  display_name     = "aviation-rag-endpoint"
  description      = "Index endpoint for aviation RAG semantic retrieval"
  public_endpoint_enabled = true

  depends_on = [
    google_vertex_ai_index.aviation_rag
  ]
}

# Deploy the index to the endpoint
resource "google_vertex_ai_index_endpoint_deploy_indexed_model" "aviation_rag" {
  count             = var.enable_vertex_ai && var.enable_vector_search ? 1 : 0
  index_endpoint    = google_vertex_ai_index_endpoint.aviation_rag[0].id
  deployed_index_id = "aviation-rag-deployed"
  index_id          = google_vertex_ai_index.aviation_rag[0].id

  depends_on = [
    google_vertex_ai_index.aviation_rag,
    google_vertex_ai_index_endpoint.aviation_rag
  ]
}

# Allow the aviation AI service account to use the index
resource "google_vertex_ai_index_iam_member" "aviation_ai_retriever" {
  count   = var.enable_vertex_ai && var.enable_vector_search ? 1 : 0
  index   = google_vertex_ai_index.aviation_rag[0].id
  role    = "roles/aiplatform.indexReader"
  member  = "serviceAccount:${google_service_account.aviation_ai_sa[0].email}"

  depends_on = [
    google_service_account.aviation_ai_sa,
    google_vertex_ai_index.aviation_rag
  ]
}

# Allow the aviation AI service account to use the endpoint
resource "google_vertex_ai_index_endpoint_iam_member" "aviation_ai_retriever" {
  count        = var.enable_vertex_ai && var.enable_vector_search ? 1 : 0
  index_endpoint = google_vertex_ai_index_endpoint.aviation_rag[0].id
  role         = "roles/aiplatform.indexEndpointUser"
  member       = "serviceAccount:${google_service_account.aviation_ai_sa[0].email}"

  depends_on = [
    google_service_account.aviation_ai_sa,
    google_vertex_ai_index_endpoint.aviation_rag
  ]
}

# Outputs
output "vector_search_index_id" {
  description = "The ID of the Vertex AI Vector Search index for aviation RAG documents"
  value       = try(google_vertex_ai_index.aviation_rag[0].id, null)
}

output "vector_search_index_endpoint_id" {
  description = "The ID of the Vertex AI Index endpoint for serving retrieval queries"
  value       = try(google_vertex_ai_index_endpoint.aviation_rag[0].id, null)
}

output "vector_search_index_endpoint_domain_name" {
  description = "The domain name of the index endpoint for API calls"
  value       = try(google_vertex_ai_index_endpoint.aviation_rag[0].public_endpoint_domain_name, null)
}

output "deployed_index_id" {
  description = "The deployed index ID for direct API access"
  value       = "aviation-rag-deployed"
}
