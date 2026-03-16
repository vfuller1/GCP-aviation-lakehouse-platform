terraform {
  backend "gcs" {
    bucket  = "gcp-lakehouseproject-tfstate"
    prefix  = "terraform/state"
  }
}
