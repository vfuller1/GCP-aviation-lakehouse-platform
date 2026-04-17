# GCP Aviation Lakehouse Platform

A fully automated, cloud-native data lakehouse built on Google Cloud Platform that ingests synthetic aviation flight data, applies medallion-architecture transformations via Databricks, and surfaces analytics through BigQuery BI views — all triggered from a single `git push`.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Repository Structure](#repository-structure)
- [Infrastructure](#infrastructure)
  - [GCS Medallion Buckets](#gcs-medallion-buckets)
  - [GKE Autopilot Cluster](#gke-autopilot-cluster)
  - [Databricks Workspace](#databricks-workspace)
  - [BigQuery BI Layer](#bigquery-bi-layer)
- [Data Pipeline](#data-pipeline)
  - [Stage 1 — Ingest (Source → Bronze)](#stage-1--ingest-source--bronze)
  - [Stage 2 — Bronze → Silver](#stage-2--bronze--silver)
  - [Stage 3 — Silver → Gold](#stage-3--silver--gold)
  - [Stage 4 — Export to GCS (Parquet)](#stage-4--export-to-gcs-parquet)
- [CI/CD Workflows](#cicd-workflows)
  - [infra.yml — Terraform Apply](#infrayml--terraform-apply)
  - [pipeline.yml — Build, Push & Deploy](#pipelineyml--build-push--deploy)
- [End-to-End Runtime Sequence](#end-to-end-runtime-sequence)
- [Prerequisites & Secrets](#prerequisites--secrets)
- [Configuration Variables](#configuration-variables)
- [BigQuery Views Reference](#bigquery-views-reference)

---

## Architecture Overview

```
GitHub push
    │
    ├─[infra.yml]──► Terraform ──► GCS buckets + BigQuery + GKE + Databricks
    │
    └─[pipeline.yml]─► Docker build/push ──► GKE deploy ──► Ingest job (Bronze)
                                                                     │
                                                        Databricks: Bronze → Silver
                                                                     │
                                                        Databricks: Silver → Gold
                                                                     │
                                                        Databricks: Export to GCS (Parquet)
                                                                     │
                                                        BigQuery views (query-ready)
```

The platform follows the **Medallion Architecture** (Bronze / Silver / Gold):

| Layer  | Storage | Format | Contents |
|--------|---------|--------|----------|
| Bronze | `gcp-lakehouseproject-bronze` | CSV | Raw, unvalidated flight records |
| Silver | `gcp-lakehouseproject-silver` | Parquet (Delta) | Cleaned, validated, deduplicated flights |
| Gold   | `gcp-lakehouseproject-gold`   | Parquet (Delta) | Business-level aggregations |
| BI     | BigQuery `aviation_analytics` | External tables + Views | Ready for dashboards and ad-hoc queries |

---

## Repository Structure

```
.
├── .github/
│   └── workflows/
│       ├── infra.yml            # Terraform provisioning workflow
│       └── pipeline.yml         # Build, deploy & run pipeline workflow
├── databricks_notebooks/
│   ├── bronze_to_silver.py      # Bronze → Silver transformation notebook
│   ├── silver_to_gold.py        # Silver → Gold aggregation notebook
│   └── export_tables_to_gcs.py  # Delta → GCS Parquet export notebook
├── k8s/
│   ├── namespace.yaml           # Kubernetes namespace definition
│   ├── service-account.yaml     # K8s service account (Workload Identity)
│   └── ingest-cronjob.yaml      # Daily ingest CronJob (06:00 UTC)
├── pipeline/
│   └── ingest/
│       ├── Dockerfile           # Python 3.11 container for the ingest job
│       ├── ingest.py            # Synthetic flight data generator
│       └── requirements.txt     # Python dependencies (google-cloud-storage)
├── backend.tf                   # Terraform GCS backend configuration
├── bigquery.tf                  # BigQuery dataset, external tables, BI views
├── databricks.tf                # Databricks workspace + jobs (optional)
├── gke.tf                       # GKE Autopilot cluster + Artifact Registry + IAM
├── imports.tf                   # Terraform import blocks
├── provider.tf                  # GCP & Databricks Terraform providers
├── storage.tf                   # GCS medallion bucket definitions
└── variables.tf                 # Input variable declarations
```

---

## Infrastructure

All infrastructure is managed by **Terraform** and provisioned automatically by the `infra.yml` workflow on every push to `main` that touches a `.tf` file.

### GCS Medallion Buckets

Three GCS buckets are created with uniform bucket-level access:

| Bucket | Purpose |
|--------|---------|
| `gcp-lakehouseproject-bronze` | Raw CSV landing zone — written by the K8s ingest job |
| `gcp-lakehouseproject-silver` | Cleaned Parquet exports — written by Databricks |
| `gcp-lakehouseproject-gold`   | Aggregated Parquet exports — written by Databricks |

### GKE Autopilot Cluster

Enabled when `enable_gke = true` (set via the `TF_VAR_enable_gke` GitHub secret in `infra.yml`).

| Resource | Name | Notes |
|----------|------|-------|
| Cluster | `aviation-pipeline` | GKE Autopilot, `us-central1` |
| Artifact Registry | `aviation-pipeline` | Docker format |
| GCP Service Account | `aviation-pipeline-sa` | `roles/storage.objectCreator` on Bronze bucket only |
| K8s Service Account | `aviation-pipeline-sa` | Annotated for Workload Identity |

**Workload Identity** is used so the K8s pod can authenticate to GCP without embedding credentials.

### Databricks Workspace

Optional — enabled when `enable_databricks = true` and the relevant secrets are configured. The Terraform module provisions:
- A Databricks workspace on GCP
- Notebooks synced from `databricks_notebooks/`
- Three jobs: `aviation-bronze-to-silver`, `aviation-silver-to-gold`, `aviation-export-tables-to-gcs`

### BigQuery BI Layer

A `aviation_analytics` BigQuery dataset is always created. Once Parquet files are exported to GCS, these objects are available immediately:

| Object | Type | Description |
|--------|------|-------------|
| `silver_flights_ext` | External Table | Points to Silver Parquet in GCS |
| `gold_summary_ext` | External Table | Points to Gold Parquet in GCS |
| `bi_airline_performance_v` | View | Airline delay KPIs |
| `bi_route_performance_v` | View | Route delay leaderboard |
| `bi_daily_delays_v` | View | Daily delayed-flight trend |
| `bi_pipeline_refresh_v` | View | Data freshness / pipeline status |

---

## Data Pipeline

### Stage 1 — Ingest (Source → Bronze)

**Component**: `pipeline/ingest/ingest.py`  
**Runtime**: GKE Autopilot pod, scheduled daily at **06:00 UTC** via CronJob  
**Authentication**: Workload Identity (no credentials in the container)

The ingest job generates **1,000 synthetic flight records** per run using the following data model:

| Field | Type | Description |
|-------|------|-------------|
| `flight_id` | UUID | Unique flight identifier |
| `airline` | String | IATA airline code (AA, DL, UA, WN, B6, AS, NK, F9, G4, HA) |
| `origin` | String | Origin airport IATA code |
| `destination` | String | Destination airport IATA code |
| `departure_delay_min` | Int | Departure delay in minutes (−15 to 240) |
| `arrival_delay_min` | Int | Arrival delay in minutes |
| `weather_flag` | Boolean | ~15% of flights are weather-related |
| `status` | String | ON_TIME / DELAYED / CANCELLED / DIVERTED |
| `event_ts` | Timestamp | UTC timestamp of record generation |

Configurable environment variables in the K8s manifest:

| Variable | Default | Description |
|----------|---------|-------------|
| `GCP_PROJECT_ID` | `gcp-lakehouseproject` | GCP project |
| `BRONZE_BUCKET` | `gcp-lakehouseproject-bronze` | Target GCS bucket |
| `NUM_RECORDS` | `1000` | Records per run |
| `BAD_DATA_RATE` | `0.0` | Fraction of intentionally corrupted records (0.0–1.0) |

Output path: `gs://gcp-lakehouseproject-bronze/aviation/raw/date=YYYY-MM-DD/flights.csv`

---

### Stage 2 — Bronze → Silver

**Notebook**: `databricks_notebooks/bronze_to_silver.py`  
**Databricks Job**: `aviation-bronze-to-silver`  
**Output**: Delta table `workspace.aviation.silver_flights` partitioned by `ingest_date`

Transformations applied:

1. **Type casting** — string columns cast to `INT`, `BOOLEAN`, `TIMESTAMP`
2. **Null filtering** — rows missing `flight_id`, `airline`, `origin`, `destination`, or `event_ts` are dropped
3. **Range filtering** — departure delays outside −60 to 600 minutes are removed
4. **Sanity check** — same-origin/destination flights are dropped
5. **Deduplication** — duplicate `flight_id` values are removed

---

### Stage 3 — Silver → Gold

**Notebook**: `databricks_notebooks/silver_to_gold.py`  
**Databricks Job**: `aviation-silver-to-gold`  
**Output**: Delta table `workspace.aviation.gold_flight_summary` (overwrite)

Four business aggregations are computed and unioned into a single summary table:

| `summary_type` | `dimension_key` | Metrics |
|----------------|-----------------|---------|
| `by_airline` | Airline code | Avg departure delay, avg arrival delay, total flights |
| `by_route` | `ORIGIN-DEST` | Same, per route |
| `delayed_by_day` | Date string | Count of delayed flights, count of weather-related delays |
| `on_time_pct` | Airline code | Percentage of on-time flights per airline |

---

### Stage 4 — Export to GCS (Parquet)

**Notebook**: `databricks_notebooks/export_tables_to_gcs.py`  
**Databricks Job**: `aviation-export-tables-to-gcs`

Reads Silver and Gold Delta tables and writes to GCS as Parquet:

| Source Delta Table | GCS Path | Partition |
|--------------------|----------|-----------|
| `workspace.aviation.silver_flights` | `gs://gcp-lakehouseproject-silver/aviation/cleaned/` | `ingest_date` |
| `workspace.aviation.gold_flight_summary` | `gs://gcp-lakehouseproject-gold/aviation/aggregated/` | `summary_type` |

> **Note**: This stage requires a **classic Databricks cluster** configured with GCS credentials. It is not compatible with Serverless compute.

---

## CI/CD Workflows

### infra.yml — Terraform Apply

**Trigger**: Push to `main` touching any `.tf` file, `.terraform.lock.hcl`, or `infra.yml`; also supports `workflow_dispatch`.

**Steps**:
1. Authenticate to GCP using `GCP_SA_KEY`
2. Enable prerequisite APIs (Container, IAM, Artifact Registry, Resource Manager)
3. `terraform init` → `terraform plan` → `terraform apply`

### pipeline.yml — Build, Push & Deploy

**Trigger**: Push to `main` touching `pipeline/**`, `k8s/**`, or `pipeline.yml`; also supports `workflow_dispatch` with an optional `run_ingest_now` boolean input.

**Steps**:
1. Authenticate to GCP
2. Build Docker image from `pipeline/ingest/` tagged with commit SHA + `latest`
3. Push image to Artifact Registry (`us-central1-docker.pkg.dev/<PROJECT>/aviation-pipeline/ingest`)
4. Fetch GKE credentials and apply K8s manifests (`namespace`, `service-account`, `ingest-cronjob`)
5. Update CronJob image to the new commit SHA
6. Trigger a one-off ingest job immediately (on every `push` or when `run_ingest_now=true`)
7. Run Databricks pipeline sequentially: **Bronze → Silver → Gold → Export**
   - Syncs notebooks from `databricks_notebooks/` to the Databricks workspace
   - Falls back to one-off run submission if named jobs don't exist yet
   - Skips Databricks steps gracefully if `DATABRICKS_HOST`/`DATABRICKS_TOKEN` secrets are not set

---

## End-to-End Runtime Sequence

```
1. git push to main
       │
       ├─ infra.yml ──────────────────────────────────────────────────────────┐
       │   └── terraform apply                                                │
       │       ├── GCS buckets (bronze / silver / gold)                       │
       │       ├── BigQuery dataset + external tables + BI views              │
       │       ├── GKE Autopilot cluster (aviation-pipeline)                  │
       │       ├── Artifact Registry (aviation-pipeline, Docker)              │
       │       ├── GCP Service Account (aviation-pipeline-sa)                 │
       │       ├── Workload Identity binding                                  │
       │       └── Databricks workspace + jobs (if enable_databricks=true)   │
       │                                                                      ▼
       └─ pipeline.yml ────────────────────────────────────────────────────────
           ├── Docker build + push (ingest image)
           ├── kubectl apply (namespace / service-account / cronjob)
           ├── CronJob image updated to new SHA
           ├── One-off ingest job runs immediately
           │     └── Writes CSV to Bronze GCS bucket
           ├── Databricks: bronze_to_silver notebook runs
           │     └── Writes Delta table → silver_flights
           ├── Databricks: silver_to_gold notebook runs
           │     └── Writes Delta table → gold_flight_summary
           ├── Databricks: export_tables_to_gcs notebook runs
           │     ├── Writes Silver Parquet to GCS
           │     └── Writes Gold Parquet to GCS
           └── BigQuery external tables & views are now query-ready
```

**Recurring**: The GKE CronJob re-runs ingest daily at **06:00 UTC**. A full Databricks pipeline run should be triggered separately on a schedule (or via `workflow_dispatch`) after each ingest.

---

## Prerequisites & Secrets

Configure the following **GitHub Actions secrets** in your repository settings:

| Secret | Description |
|--------|-------------|
| `GCP_SA_KEY` | Service account JSON key with roles: `artifactregistry.writer`, `container.developer`, `storage.admin`, `bigquery.admin`, `iam.serviceAccountAdmin` |
| `GCP_PROJECT_ID` | GCP project ID (e.g. `gcp-lakehouseproject`) |
| `GKE_CLUSTER_NAME` | GKE cluster name (e.g. `aviation-pipeline`) |
| `GKE_REGION` | GKE cluster region (e.g. `us-central1`) |
| `DATABRICKS_HOST` | Databricks workspace URL (e.g. `https://<workspace>.gcp.databricks.com`) |
| `DATABRICKS_TOKEN` | Databricks personal access token |
| `DATABRICKS_ACCOUNT_ID` | Databricks account ID (for workspace provisioning via Terraform) |

> `DATABRICKS_*` secrets are optional. If not set, the Databricks pipeline steps are skipped gracefully.

---

## Configuration Variables

Defined in `variables.tf`:

| Variable | Default | Description |
|----------|---------|-------------|
| `project_id` | `gcp-lakehouseproject` | GCP Project ID |
| `region` | `us-central1` | Default region for all resources |
| `enable_gke` | `false` | Enable GKE Autopilot cluster, Artifact Registry, and pipeline IAM |
| `enable_databricks` | `false` | Enable Databricks workspace provisioning via Terraform |
| `databricks_host` | `null` | Databricks workspace host URL |
| `databricks_token` | `null` | Databricks personal access token (sensitive) |
| `databricks_account_id` | `null` | Databricks account ID |

In the `infra.yml` workflow, `enable_gke` is set to `"true"` via the `TF_VAR_enable_gke` environment variable.

---

## BigQuery Views Reference

All views live in the `aviation_analytics` dataset and query the `gold_summary_ext` external table.

### `bi_airline_performance_v`
Airline-level delay KPIs — average departure delay, arrival delay, and total flight count per airline.

### `bi_route_performance_v`
Route-level delay leaderboard — same KPIs grouped by `ORIGIN-DEST` route pair.

### `bi_daily_delays_v`
Daily trend of delayed flights — count of delayed flights per calendar date.

### `bi_pipeline_refresh_v`
Pipeline health dashboard — shows the latest `generated_ts`, total Gold summary rows, and a breakdown by `summary_type`. Use this to verify data freshness.

---

## License

This project is provided as a reference implementation and learning resource. See [LICENSE](LICENSE) for details.
