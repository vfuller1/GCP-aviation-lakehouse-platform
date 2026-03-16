terraform {
  backend "gcs" {
    bucket  = "lakehouse-gcp-state"
    prefix  = "terraform/state"
    credentials = "gcp-key.json"
  }
}
