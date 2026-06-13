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
      algorithm_config {
        tree_ah_config {
          leaf_node_embedding_count    = 100
          leaf_nodes_to_search_percent = 7
        }
      }
    }
    contents_delta_uri = "gs://${var.project_id}-ai/aviation/indices/rag/"
  }

  # contents_delta_uri is managed by the ingest job, not Terraform.
  # Terraform only provisions the index; the ingest pipeline writes vectors
  # to GCS and triggers index updates via the Vertex AI API.
  lifecycle {
    ignore_changes = [metadata]
  }

  depends_on = [
    google_bigquery_table.ai_rag_documents
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

# Deploy the index to the endpoint so the retrieval service can query it.
# Deployment takes ~20-30 min; Terraform waits for the LRO to complete.
# Access control uses the project-level roles/aiplatform.user binding in vertex_ai.tf.
resource "google_vertex_ai_index_endpoint_deployed_index" "aviation_rag" {
  count             = var.enable_vertex_ai && var.enable_vector_search ? 1 : 0
  index_endpoint    = google_vertex_ai_index_endpoint.aviation_rag[0].id
  index             = google_vertex_ai_index.aviation_rag[0].id
  deployed_index_id = "aviation_rag_deployed"
  display_name      = "aviation_rag_deployed"

  automatic_resources {
    min_replica_count = 2
    max_replica_count = 2
  }

  depends_on = [
    google_vertex_ai_index.aviation_rag,
    google_vertex_ai_index_endpoint.aviation_rag,
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
  description = "Stable deployed index ID used when calling the endpoint API"
  value       = "aviation_rag_deployed"
}
