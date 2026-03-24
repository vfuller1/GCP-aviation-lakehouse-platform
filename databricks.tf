# Databricks workspace on GCP (Terraform)
# NOTE: You must enable the Databricks API and have the correct permissions in your GCP project.

provider "databricks" {
  host  = var.databricks_host
  token = var.databricks_token
}

resource "databricks_mws_workspaces" "lakehouse" {
  count          = var.enable_databricks ? 1 : 0
  account_id     = var.databricks_account_id
  workspace_name = "lakehouse-demo"
  location       = var.region

  cloud_resource_container {
    gcp {
      project_id = var.project_id
    }
  }
}

# Add more Databricks resources as needed (clusters, jobs, etc.)
