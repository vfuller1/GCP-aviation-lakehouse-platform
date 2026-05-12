variable "project_id" {
  description = "The GCP Project ID"
  default     = "gcp-lakehouseproject"
}

variable "region" {
  description = "The default region for resources"
  default     = "us-central1"
}

variable "enable_databricks" {
  description = "Enable Databricks workspace provisioning"
  type        = bool
  default     = false
}

variable "databricks_host" {
  description = "Databricks workspace host URL (for example: https://<workspace>.gcp.databricks.com)"
  type        = string
  default     = null
  nullable    = true
}

variable "databricks_token" {
  description = "Databricks personal access token"
  type        = string
  sensitive   = true
  default     = null
  nullable    = true
}

variable "databricks_account_id" {
  description = "Databricks account ID for workspace provisioning"
  type        = string
  default     = null
  nullable    = true
}

variable "enable_gke" {
  description = "Enable GKE Autopilot cluster, Artifact Registry, and pipeline IAM resources"
  type        = bool
  default     = false
}

variable "enable_vertex_ai" {
  description = "Enable Vertex AI APIs, service account, and AI data foundations"
  type        = bool
  default     = false
}

variable "vertex_embedding_model" {
  description = "Vertex AI text embedding model used by the RAG pipeline"
  type        = string
  default     = "text-embedding-005"
}

variable "vertex_reasoning_model" {
  description = "Vertex AI reasoning model used for natural-language analytics"
  type        = string
  default     = "gemini-2.5-flash"
}

variable "vector_dimension" {
  description = "Embedding vector dimensionality for aviation intelligence retrieval"
  type        = number
  default     = 768
}

variable "enable_vector_search" {
  description = "Enable Vertex AI Vector Search index for semantic retrieval"
  type        = bool
  default     = false
}
