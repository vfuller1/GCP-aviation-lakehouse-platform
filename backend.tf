terraform {
  backend "gcs" {
    bucket  = "lakehouse-gcp-state"
    prefix  = "terraform/state"
    credentials = "${path.module}/gcp-key.json"
  }
}
