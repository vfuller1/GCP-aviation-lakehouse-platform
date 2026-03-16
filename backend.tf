terraform {
  backend "gcs" {
    bucket  = "lakehouse-gcp-state"
    prefix  = "terraform/state"
  }
}
