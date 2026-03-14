terraform {
  backend "gcs" {
    bucket  = "lakehouse-gcp-state"
    prefix  = "terraform/state"
    credentials = "c:/Users/vfull/gcp-keys/kubernetes-365701-7477240054cf.json"
  }
}
