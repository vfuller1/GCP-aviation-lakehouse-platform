terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.23"
    }

    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.40"
    }
  }

  backend "gcs" {
    bucket = "gcp-lakehouseproject-tfstate"
    prefix = "terraform/state"
  }
}
