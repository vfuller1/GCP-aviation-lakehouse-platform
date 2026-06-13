# GCP Aviation Lakehouse Platform

A fully automated, cloud-native data lakehouse built on Google Cloud Platform that ingests synthetic aviation flight data, applies medallion-architecture transformations, and surfaces analytics through two AI layers — a **Gemini-powered RAG retrieval service** (`/retrieve`) and a **LangGraph agentic reasoning loop** (`/agent`) — all triggered from a single `git push`.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Repository Structure](#repository-structure)
- [Infrastructure](#infrastructure)
- [Data Pipeline](#data-pipeline)
  - [Stage 1 — Ingest (Source → Bronze)](#stage-1--ingest-source--bronze)
  - [Stage 2 — Bronze → Silver](#stage-2--bronze--silver)
  - [Stage 3 — Silver → Gold](#stage-3--silver--gold)
  - [Stage 4 — Export to GCS (Parquet)](#stage-4--export-to-gcs-parquet)
- [AI / RAG Layer](#ai--rag-layer)
  - [Embeddings Pipeline](#embeddings-pipeline)
  - [Vector Search](#vector-search)
  - [Retrieval Service](#retrieval-service)
  - [Session Memory](#session-memory)
- [Agentic Layer (LangGraph)](#agentic-layer-langgraph)
- [BigQuery Views Reference](#bigquery-views-reference)
- [CI/CD Workflows](#cicd-workflows)
- [End-to-End Runtime Sequence](#end-to-end-runtime-sequence)
- [Quick Start / Testing](#quick-start--testing)
- [Prerequisites & Secrets](#prerequisites--secrets)
- [Configuration Variables](#configuration-variables)

---

## Architecture Overview

```
GitHub push
    │
    ├─[infra.yml]──► Terraform ──► GCS · BigQuery · GKE · Vertex AI · Vector Search
    │                               Cloud Run · Firestore · Artifact Registry
    │
    └─[pipeline.yml]─► Docker build/push ──► GKE CronJob (Bronze ingest)
                                                    │
                                          Vertex AI text-embedding-005
                                          ai_rag_documents (BigQuery)
                                                    │
                                          Databricks: Bronze → Silver → Gold
                                                    │
                                          GCS Parquet (Silver / Gold)
                                                    │
                                          BigQuery external tables + BI views
                                                    │
                                    Cloud Run Retrieval Service (Flask + Gemini)
                                          │                    │
                                  /retrieve (RAG)      /agent (LangGraph)
                                                    │
                                           Firestore session memory
```

The platform follows the **Medallion Architecture** (Bronze / Silver / Gold):

| Layer | Storage | Format | Contents |
|-------|---------|--------|----------|
| Bronze | `gcp-lakehouseproject-bronze` | CSV | Raw, unvalidated flight records |
| Silver | `gcp-lakehouseproject-silver` | Parquet (flat) | Cleaned, validated, deduplicated flights |
| Gold | `gcp-lakehouseproject-gold` | Parquet (flat) | Business-level aggregations |
| AI | `gcp-lakehouseproject-ai` | JSON embeddings | RAG documents + Vertex AI index data |
| BI | BigQuery `aviation_analytics` | External tables + Views | Dashboard-ready analytics |

---

## Repository Structure

```
.
├── .github/
│   └── workflows/
│       ├── infra.yml                  # Terraform provisioning workflow
│       └── pipeline.yml               # Build, deploy & run pipeline workflow
├── databricks_notebooks/
│   ├── bronze_to_silver.py            # Bronze → Silver transformation
│   ├── silver_to_gold.py              # Silver → Gold aggregation
│   └── export_tables_to_gcs.py        # Delta → GCS Parquet export (flat, no partitionBy)
├── k8s/
│   ├── namespace.yaml                 # Kubernetes namespace
│   ├── service-account.yaml           # K8s service account (Workload Identity)
│   └── ingest-cronjob.yaml            # Daily ingest CronJob (06:00 UTC)
├── pipeline/
│   └── ingest/
│       ├── Dockerfile                 # Python 3.11 ingest container
│       ├── ingest.py                  # Synthetic flight data generator + embeddings
│       └── requirements.txt
├── retrieval_service/
│   ├── Dockerfile                     # Python 3.11 retrieval service container
│   ├── retrieval_service.py           # Flask RAG service (Gemini 2.5 Flash)
│   ├── agent.py                       # LangGraph agentic layer (3 tools, autonomous loop)
│   └── requirements.txt
├── tests/
│   ├── test_retrieval_e2e.py          # E2E smoke tests for retrieval service
│   ├── demo_rag_queries.ps1           # Interactive /retrieve demo (4 questions + session memory)
│   └── demo_agent_queries.ps1         # Interactive /agent demo (multi-tool autonomous queries)
├── backend.tf                         # Terraform GCS backend + provider versions
├── bigquery.tf                        # BigQuery dataset, external tables, BI/AI views
├── databricks.tf                      # Databricks workspace + jobs (optional)
├── firestore.tf                       # Firestore session memory database
├── gke.tf                             # GKE Autopilot cluster + Artifact Registry + IAM
├── imports.tf                         # Terraform import blocks for existing resources
├── provider.tf                        # GCP Terraform provider
├── retrieval_service.tf               # Cloud Run retrieval service + IAM
├── storage.tf                         # GCS medallion bucket definitions
├── variables.tf                       # Input variable declarations
├── vector_search.tf                   # Vertex AI Vector Search index + endpoint
└── vertex_ai.tf                       # Vertex AI APIs + service accounts + IAM
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
**Runtime**: GKE Autopilot CronJob — daily at **06:00 UTC**  
**Authentication**: Workload Identity (no embedded credentials)

Generates **5,000 synthetic flight records** per run and writes to the Bronze bucket. Also generates Vertex AI embeddings and writes RAG documents to BigQuery.

| Field | Type | Description |
|-------|------|-------------|
| `flight_id` | UUID | Unique flight identifier |
| `airline` | String | IATA code (AA, DL, UA, WN, B6, AS, NK, F9, G4, HA) |
| `origin` | String | Origin airport IATA code |
| `destination` | String | Destination airport IATA code |
| `departure_delay_min` | Int | Departure delay (−15 to 240 min) |
| `arrival_delay_min` | Int | Arrival delay |
| `weather_flag` | Boolean | ~15% of flights weather-related |
| `status` | String | ON_TIME / DELAYED / CANCELLED / DIVERTED |
| `event_ts` | Timestamp | UTC generation timestamp |

**Key environment variables (set in `k8s/ingest-cronjob.yaml`):**

| Variable | Value | Description |
|----------|-------|-------------|
| `NUM_RECORDS` | `5000` | Records per run |
| `BAD_DATA_RATE` | `0.02` | Fraction of intentionally corrupted records |
| `ENABLE_RAG_DOC_EXPORT` | `true` | Write RAG docs to `ai_rag_documents` |
| `ENABLE_VERTEX_EMBEDDINGS` | `true` | Generate Vertex AI embeddings |
| `VERTEX_EMBEDDING_MODEL` | `text-embedding-005` | Embedding model |

**Output**: `gs://gcp-lakehouseproject-bronze/aviation/raw/date=YYYY-MM-DD/flights.csv`

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

Reads Silver and Gold Delta tables and writes **flat Parquet** (no `partitionBy`) to GCS. This ensures all columns — including partition columns like `summary_type` — are present as data columns in the Parquet bytes, which BigQuery external tables require for direct queries and views.

| Source Delta Table | GCS Path |
|--------------------|----------|
| `workspace.aviation.silver_flights` | `gs://gcp-lakehouseproject-silver/aviation/cleaned/*.parquet` |
| `workspace.aviation.gold_flight_summary` | `gs://gcp-lakehouseproject-gold/aviation/aggregated/*.parquet` |

> **Note**: This stage requires a **classic Databricks cluster** with GCS credentials. It is not compatible with Serverless compute.

---

## AI / RAG Layer

### Embeddings Pipeline

During ingest, each flight record is summarized into a natural-language sentence and embedded using **Vertex AI `text-embedding-005`** (768-dimensional). These embeddings are written to the `ai_rag_documents` BigQuery native table with metadata fields for retrieval.

### Vector Search

A Vertex AI Vector Search **index** (`aviation-rag-index`) is built from the `ai_rag_documents` embeddings and deployed to an endpoint (`aviation-rag-endpoint`). The retrieval service queries this endpoint using cosine similarity (DOT_PRODUCT on normalized vectors) to find the most relevant flight records for a given question.

> **Note**: The Vector Search index runs in BATCH_UPDATE mode. After a large ingest, allow 1–2 hours for the index to rebuild.

### Retrieval Service

A Flask application deployed on **Cloud Run** (`aviation-retrieval`) implements a Retrieval-Augmented Generation (RAG) pattern:

1. Embed the user question using `text-embedding-005`
2. Query Vector Search for the top-K nearest neighbours
3. Fetch the matching RAG documents from BigQuery
4. Send the retrieved context + question to **Gemini 2.5 Flash**
5. Return the structured answer

**Base URL**: `https://aviation-retrieval-ohvijuloea-uc.a.run.app`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Liveness check |
| `/health/ready` | GET | Readiness check (verifies BQ + Vector Search connectivity) |
| `/retrieve` | POST | RAG query: fixed embed → search → generate sequence |
| `/agent` | POST | Agentic query: LangGraph loop, autonomous tool selection |
| `/session/clear` | POST | Clear Firestore session history |

**Example** — ask a delay question:
```bash
curl -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/retrieve \
  -H "Content-Type: application/json" \
  -d '{"question": "Which routes have the highest weather-related delays?", "session_id": "demo-1"}'
```

### Session Memory

Conversation history is stored in **Firestore** (`rag-sessions` database). Both `/retrieve` and `/agent` append each Q&A turn to `sessions/{session_id}`, enabling follow-up questions that reference prior answers. Sessions expire automatically after 1 hour (TTL on `expireAt`). Pass the same `session_id` across calls to maintain context.

---

## Agentic Layer (LangGraph)

The `/agent` endpoint wraps the same GCP tools in a **LangGraph reasoning loop** — instead of a fixed embed → search → generate sequence, the agent decides autonomously which tools to call and in what order until it has enough evidence to answer.

### Architecture

```
POST /agent
    │
    ▼
SystemMessage + session history + question
    │
    ▼
┌──────────────────────────────────────────────────────┐
│  LangGraph StateGraph                                │
│                                                      │
│  ┌─────────┐    tool_calls?     ┌──────────────┐   │
│  │  agent  │ ─── yes ────────► │  tool_node   │   │
│  │(Gemini) │ ◄── results ────  │              │   │
│  └─────────┘                   │  • search_flight_records  │
│       │                        │  • query_analytics        │
│       │ no tool_calls          │  • get_pipeline_status    │
│       ▼                        └──────────────┘   │
│     END                                            │
└──────────────────────────────────────────────────────┘
    │
    ▼
Grounded answer + tools_called list + step count
```

### Tools

| Tool | When the agent uses it |
|------|----------------------|
| `search_flight_records` | Specific routes, airlines, or events — semantic similarity over individual records |
| `query_analytics` | Aggregate stats (worst airline, weather trends, route risk rankings) |
| `get_pipeline_status` | Data freshness check — called automatically if prior tools return 0 rows |

> **Resilience note**: `query_analytics` tries the richer BigQuery external tables (`silver_flights_ext`, `ai_route_risk_v`) first. If those are unavailable (Parquet export not yet run, or GCS IAM restriction), it automatically falls back to the native `ai_rag_documents` table, which is always populated by the ingest job. The agent always gets an answer.

### Example

```bash
# Single-turn agentic query
curl -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/agent \
  -H "Content-Type: application/json" \
  -d '{"question": "Which airline should I avoid if flying into ATL this week due to weather delays?", "session_id": "demo-agent-1"}'

# Multi-turn: follow-up uses Firestore session history
curl -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/agent \
  -H "Content-Type: application/json" \
  -d '{"question": "What about routes out of LAX for the same airline?", "session_id": "demo-agent-1"}'
```

**Response shape:**
```json
{
  "question":     "Which airline should I avoid ...",
  "answer":       "Based on 7-day analytics data, Spirit Airlines (NK) shows the highest average departure delay of 47.2 minutes and a 34% delayed flight rate...",
  "session_id":   "demo-agent-1",
  "tools_called": ["query_analytics", "search_flight_records"],
  "steps":        5,
  "timestamp":    "2026-06-13T12:00:00Z"
}
```

### /retrieve vs /agent

| | `/retrieve` | `/agent` |
|---|---|---|
| Flow | Fixed: embed → vector search → BQ → Gemini | Autonomous: agent decides tools + order |
| Tool calls | Always 1 vector search + 1 BQ query | 1–N calls based on question complexity |
| Multi-step reasoning | No | Yes — can refine query if first call is empty |
| Latency | Lower (~2–4 s) | Higher (~4–10 s depending on steps) |
| Best for | High-volume, well-scoped questions | Complex, multi-faceted or exploratory questions |

---

## CI/CD Workflows

### infra.yml — Terraform Apply

**Trigger**: Push to `main` touching any `.tf` file or `infra.yml`; also `workflow_dispatch`.

**Steps**:
1. Authenticate to GCP (`GCP_SA_KEY`)
2. Enable prerequisite APIs
3. Drop BigQuery external tables (pre-apply, to allow schema changes)
4. `terraform init -upgrade` (3-attempt retry loop)
5. `terraform plan` → `terraform apply`

> The `--upgrade` flag ensures provider versions are re-resolved without relying on a committed lock file.

### pipeline.yml — Build, Push & Deploy

**Trigger**: Push to `main` touching `pipeline/**`, `retrieval_service/**`, `k8s/**`, or `pipeline.yml`; also `workflow_dispatch` with optional `run_ingest_now` boolean.

**Steps**:
1. Authenticate to GCP
2. Build + push ingest Docker image to Artifact Registry
3. Build + push retrieval service Docker image and deploy to Cloud Run
4. Apply K8s manifests and update CronJob image to new commit SHA
5. Trigger one-off ingest job (on every push or when `run_ingest_now=true`)
6. Run Databricks pipeline: Bronze → Silver → Gold → Export
   - Gracefully skips if `DATABRICKS_HOST`/`DATABRICKS_TOKEN` are not set

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

## Quick Start / Testing

**Base URL**: `https://aviation-retrieval-ohvijuloea-uc.a.run.app`

### 1. Health check
```bash
curl https://aviation-retrieval-ohvijuloea-uc.a.run.app/health/ready
# → {"ready": true}
```

### 2. RAG layer — interactive demo (PowerShell)
```powershell
.\tests\demo_rag_queries.ps1
```
Runs 4 questions against `/retrieve`, with the last question testing Firestore session memory.

### 3. Agent layer — interactive demo (PowerShell)
```powershell
.\tests\demo_agent_queries.ps1
```
Runs 4 questions against `/agent`. Watch the `[Tools called: ...]` line on each response — it shows which tools the agent invoked autonomously and in what order.

### 4. Single curl query (agent)
```bash
curl -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/agent \
  -H "Content-Type: application/json" \
  -d '{"question": "Which airline has the worst delays this week?", "session_id": "my-session"}'
```

### 5. Multi-turn session (agent)
```bash
# First question
curl -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/agent \
  -H "Content-Type: application/json" \
  -d '{"question": "Which routes have the highest weather delay risk?", "session_id": "my-session"}'

# Follow-up — references context from the first answer
curl -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/agent \
  -H "Content-Type: application/json" \
  -d '{"question": "For those routes, which airline handles it best?", "session_id": "my-session"}'
```

---

## Prerequisites & Secrets

Configure the following **GitHub Actions secrets**:

| Secret | Description |
|--------|-------------|
| `GCP_SA_KEY` | Service account JSON key with `storage.admin`, `bigquery.admin`, `artifactregistry.writer`, `container.developer`, `iam.serviceAccountAdmin`, `run.admin`, `datastore.user` |
| `GCP_PROJECT_ID` | GCP project ID (e.g. `gcp-lakehouseproject`) |
| `GKE_CLUSTER_NAME` | GKE cluster name (e.g. `aviation-pipeline`) |
| `GKE_REGION` | GKE region (e.g. `us-central1`) |
| `DATABRICKS_HOST` | Databricks workspace URL |
| `DATABRICKS_TOKEN` | Databricks personal access token |
| `DATABRICKS_ACCOUNT_ID` | Databricks account ID (for Terraform provisioning) |

> `DATABRICKS_*` secrets are optional. If not set, all Databricks steps are skipped.

---

## Configuration Variables

Defined in `variables.tf`:

| Variable | Default | Description |
|----------|---------|-------------|
| `project_id` | `gcp-lakehouseproject` | GCP Project ID |
| `region` | `us-central1` | Default region |
| `enable_gke` | `false` | Enable GKE Autopilot cluster + pipeline IAM |
| `enable_vertex_ai` | `false` | Enable Vertex AI + Vector Search + Cloud Run retrieval |
| `enable_databricks` | `false` | Enable Databricks workspace provisioning |
| `databricks_host` | `null` | Databricks workspace host URL |
| `databricks_token` | `null` | Databricks PAT (sensitive) |
| `databricks_account_id` | `null` | Databricks account ID |

In `infra.yml`, `enable_gke` and `enable_vertex_ai` are both set to `"true"` via `TF_VAR_*` environment variables.

---

## BigQuery Views Reference

All views live in the `aviation_analytics` dataset.

### BI Views (query `gold_summary_ext`)

| View | Description |
|------|-------------|
| `bi_airline_performance_v` | Average departure/arrival delay and total flights per airline |
| `bi_route_performance_v` | Same KPIs grouped by `ORIGIN→DEST` route |
| `bi_daily_delays_v` | Count of delayed flights per calendar date |
| `bi_pipeline_refresh_v` | Data freshness: latest `generated_ts`, row counts by `summary_type` |

### AI Views (query `ai_rag_documents`)

| View | Description |
|------|-------------|
| `ai_delay_explanations_v` | Gemini-generated delay explanations for each flight event |
| `ai_route_risk_v` | Route-level risk scores and reasoning |
| `ai_nl_analytics_facts_v` | Natural-language analytics facts extracted during ingest |

---

## License

This project is provided as a reference implementation and learning resource. See [LICENSE](LICENSE) for details.
