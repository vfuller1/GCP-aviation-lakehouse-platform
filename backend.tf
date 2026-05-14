terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.23"
    }

    databricks = {
      source  = "databricks/databricks"
      # Pinned below v1.112.0 whose GitHub checksum file returns 404.
      # Update the upper bound once the registry issue is resolved.
      version = ">= 1.40.0, < 1.112.0"
    }
  }

  backend "gcs" {
    bucket = "gcp-lakehouseproject-tfstate"
    prefix = "terraform/state"
  }
}
