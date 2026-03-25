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

# ---------------------------------------------------------------------------
# Notebooks — uploaded from local files into the Databricks workspace
# ---------------------------------------------------------------------------
resource "databricks_notebook" "bronze_to_silver" {
  count    = var.enable_databricks ? 1 : 0
  path     = "/aviation-pipeline/bronze_to_silver"
  language = "PYTHON"
  source   = "${path.module}/databricks_notebooks/bronze_to_silver.py"
}

resource "databricks_notebook" "silver_to_gold" {
  count    = var.enable_databricks ? 1 : 0
  path     = "/aviation-pipeline/silver_to_gold"
  language = "PYTHON"
  source   = "${path.module}/databricks_notebooks/silver_to_gold.py"
}

resource "databricks_notebook" "export_tables_to_gcs" {
  count    = var.enable_databricks ? 1 : 0
  path     = "/aviation-pipeline/export_tables_to_gcs"
  language = "PYTHON"
  source   = "${path.module}/databricks_notebooks/export_tables_to_gcs.py"
}

# ---------------------------------------------------------------------------
# Jobs — one job per transformation stage (Bronze→Silver, Silver→Gold)
# Each job spins up a small ephemeral job cluster to keep costs low.
# The Spark BigQuery connector is pre-installed on Databricks Runtime 13.3+
# when running on GCP (no extra library needed for the silver→gold BQ write).
# ---------------------------------------------------------------------------
resource "databricks_job" "bronze_to_silver" {
  count = var.enable_databricks ? 1 : 0
  name  = "aviation-bronze-to-silver"

  job_cluster {
    job_cluster_key = "aviation-cluster"
    new_cluster {
      num_workers   = 1
      spark_version = "13.3.x-scala2.12"
      node_type_id  = "n1-standard-4"

      gcp_attributes {
        use_preemptible_executors = true
      }

      spark_conf = {
        "spark.gcp.project" = var.project_id
      }
    }
  }

  task {
    task_key        = "bronze_to_silver"
    job_cluster_key = "aviation-cluster"

    notebook_task {
      notebook_path = databricks_notebook.bronze_to_silver[0].path
    }
  }
}

resource "databricks_job" "silver_to_gold" {
  count = var.enable_databricks ? 1 : 0
  name  = "aviation-silver-to-gold"

  job_cluster {
    job_cluster_key = "aviation-cluster"
    new_cluster {
      num_workers   = 1
      spark_version = "13.3.x-scala2.12"
      node_type_id  = "n1-standard-4"

      gcp_attributes {
        use_preemptible_executors = true
      }

      spark_conf = {
        "spark.gcp.project"            = var.project_id
        "spark.datasource.bigquery.project" = var.project_id
      }
    }
  }

  task {
    task_key        = "silver_to_gold"
    job_cluster_key = "aviation-cluster"

    notebook_task {
      notebook_path = databricks_notebook.silver_to_gold[0].path
    }
  }
}

resource "databricks_job" "export_tables_to_gcs" {
  count = var.enable_databricks ? 1 : 0
  name  = "aviation-export-tables-to-gcs"

  job_cluster {
    job_cluster_key = "aviation-cluster"
    new_cluster {
      num_workers   = 1
      spark_version = "13.3.x-scala2.12"
      node_type_id  = "n1-standard-4"

      gcp_attributes {
        use_preemptible_executors = true
      }

      spark_conf = {
        "spark.gcp.project" = var.project_id
      }
    }
  }

  task {
    task_key        = "export_tables_to_gcs"
    job_cluster_key = "aviation-cluster"

    notebook_task {
      notebook_path = databricks_notebook.export_tables_to_gcs[0].path
    }
  }
}
