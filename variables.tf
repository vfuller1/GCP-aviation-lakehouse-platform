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