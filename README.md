# GCP Aviation Lakehouse Platform

![GCP Aviation Lakehouse Platform](images/intro%20picture%20for%20the%20readme2.jpg)

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
- [End-to-End Request Flows](#end-to-end-request-flows)
- [Agentic Layer (LangGraph)](#agentic-layer-langgraph)
- [Multi-Agent Layer (Google ADK) — Proof of Concept](#multi-agent-layer-google-adk--proof-of-concept)
- [BigQuery Views Reference](#bigquery-views-reference)
- [CI/CD Workflows](#cicd-workflows)
- [End-to-End Runtime Sequence](#end-to-end-runtime-sequence)
- [Quick Start / Testing](#quick-start--testing)
- [AI Guardrails](#ai-guardrails)
- [OWASP LLM Top 10 — Security Coverage](#owasp-llm-top-10--security-coverage)
- [Monitoring Dashboard](#monitoring-dashboard)
- [Prerequisites & Secrets](#prerequisites--secrets)
- [Configuration Variables](#configuration-variables)

---

## Architecture Overview

![Architecture Overview](images/Architecture%20Overview.png)

The platform follows the **Medallion Architecture** (Bronze / Silver / Gold):

| Layer | Storage | Format | Contents |
|-------|---------|--------|----------|
| Bronze | `gcp-lakehouseproject-bronze` | CSV | Raw, unvalidated flight records — written by GKE ingest job |
| Silver | `gcp-lakehouseproject-silver` | Parquet (flat) | Cleaned, validated, deduplicated — exported to GCS by Databricks `export_tables_to_gcs` |
| Gold | `gcp-lakehouseproject-gold` | Parquet (flat) | Business aggregations — exported to GCS by Databricks `export_tables_to_gcs` |
| AI | `gcp-lakehouseproject-ai` | JSON embeddings | RAG documents + Vertex AI Vector Search index data |
| BI | BigQuery `aviation_analytics` | External tables + Views | Dashboard-ready analytics over Silver/Gold Parquet |

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
├── monitoring.tf                      # Cloud Logging sink → BigQuery (token usage + guardrails)
├── security.tf                        # Cloud Armor WAF (5 OWASP rules) + IAM Audit Logging
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

![Data Pipeline Stages](images/Medallion%20Data%20Pipeline%20Stages.png)

```
pipeline.yml  (Databricks Job Trigger)
      │
      ├──────────────────────────────────────────────────────────┐
      │                                                          │
      ▼                                                          │
 ┌─────────────────┐                                            │
 │     BRONZE       │  GKE Autopilot Ingest Job                 │
 │   (Raw CSV)      │  gs://{project}-bronze/aviation/raw/      │
 └────────┬─────────┘                                            │
          │  Databricks: bronze_to_silver.py                     │
          │  Reads Bronze CSV → cleans, deduplicates             │
          ▼                                                       │
 ┌─────────────────┐                                            │
 │     SILVER       │  Delta table: workspace.aviation.silver_flights
 │  (Cleaned Delta) │                                            │
 └────────┬─────────┘                                            │
          │  Databricks: silver_to_gold.py                       │
          │  Computes 4 business aggregations                    │
          ▼                                                       │
 ┌─────────────────┐                                            │
 │      GOLD        │  Delta table: workspace.aviation.gold_flight_summary
 │ (Business KPIs)  │                                            │
 └────────┬─────────┘                                            │
          │  Databricks: export_tables_to_gcs.py                 │
          │  Reads Silver + Gold Delta → writes flat Parquet     │
          ▼                                                       │
 ┌──────────────────────────────────────────────┐               │
 │  EXPORT  (GCS Parquet — no partitionBy)       │               │
 │  gs://{project}-silver/aviation/cleaned/      │               │
 │  gs://{project}-gold/aviation/aggregated/     │               │
 └──────────────────────────────────────────────┘               │
          │                                                       │
          ▼                                                       │
 BigQuery External Tables                                        │
 silver_flights_ext  ·  gold_summary_ext                         │
 BI Views + AI fallback views  ◄──────────────────────────────── ┘
```

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

A Flask application deployed on **Cloud Run** (`aviation-retrieval`) exposes three AI endpoints backed by two distinct reasoning paths.

**Base URL**: `https://aviation-retrieval-ohvijuloea-uc.a.run.app`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Liveness check |
| `/health/ready` | GET | Readiness check (verifies BQ + Vector Search connectivity) |
| `/ask` | POST | **Unified router** — auto-routes to `/retrieve` or `/agent`; response includes `routed_to` and `tools_used` |
| `/retrieve` | POST | **Simple path** — fixed pipeline: embed → Vector Search → Gemini (1 Gemini call) |
| `/agent` | POST | **Complex path** — LangGraph loop: autonomous tool selection, multi-step reasoning |
| `/session/clear` | POST | Clear Firestore session history |

---

### Router (`/ask`) — Simple vs Complex

The `/ask` endpoint is the recommended entry point. It classifies the question using a zero-latency heuristic and forwards to the right AI layer automatically.

```
User question
      │
      ▼
  _classify_question()   ← heuristic, no LLM call, no cost
      │
      ├── simple / scoped  ──►  /retrieve   fast, 1 Gemini call, ~500–800 tokens
      └── complex / comparative ──►  /agent  LangGraph loop, 3–5 steps, ~2000–3000 tokens
```

**Signals that route to `/agent`** (matched by regex, zero latency):

| Signal | Example words |
|--------|--------------|
| Ranking / superlatives | `best`, `worst`, `highest`, `lowest`, `most`, `least` |
| Comparison | `compare`, `versus`, `vs`, `rank` |
| Decision language | `should I`, `avoid`, `recommend`, `better alternative` |
| Trend / time-series | `trend`, `over time`, `week over week` |
| Multiple questions | Two or more `?` in one request |

Everything else routes to `/retrieve`.

**Every `/ask` response includes:**
```json
{
  "routed_to":    "retrieve" or "agent",
  "tools_used":   ["bigquery_fallback", "gemini_2.5_flash"],
  "tools_called": ["query_analytics"],
  "steps":        5
}
```

---

### Simple Path — `/retrieve`

**Purpose**: Fast, deterministic answers to well-scoped questions about a single airline, route, or fact. One Gemini call, predictable latency and cost.

```
1. Embed question        text-embedding-005 → 768-dim vector
2. Vector Search         top-K nearest flight records
3. BigQuery fallback     only if VS returns < 3 results
4. Gemini 2.5 Flash      single call with retrieved context
5. Return answer         + context_count, facts_count, tools_used
```

**Example question**: *"What delays is Delta experiencing?"*
```bash
curl -s -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What delays is Delta experiencing?", "airline": "DL", "session_id": "demo-s"}' \
  | python3 -c "
import sys, json; d = json.load(sys.stdin)
print('ROUTED TO  :', d.get('routed_to'))
print('TOOLS USED :', d.get('tools_used'))
print('TOKENS     :', d.get('token_usage',{}).get('total_tokens'))
print('ANSWER     :', d.get('answer','')[:300])"
```

Expected output:
```
ROUTED TO  : retrieve
TOOLS USED : ['bigquery_fallback', 'gemini_2.5_flash']
TOKENS     : 777
ANSWER     : Delta (DL) is experiencing significant delays — BOS-EWR 100% delayed,
             avg 174.5 min; PHX-ATL 100% delayed, avg 156.8 min ...
```

### BigQuery Fallback

The fallback ensures the system **always returns an answer** — even when the Vector Search index is stale or rebuilding after an ingest.

**Decision logic** (`retrieval_service.py`):
```python
if len(context_docs) < 3:
    # Vector Search didn't return enough — BigQuery steps in
    facts = query_bigquery_fallback(...)
else:
    # Vector Search healthy — BigQuery skipped entirely
    facts = []
```

The threshold is **3 results** (not 0) — because 1 or 2 results signals a partially stale index, not a healthy one.

**Why Vector Search returns < 3:**

| Reason | Detail |
|--------|--------|
| Index rebuilding | BATCH_UPDATE takes 1–2 hours after each ingest job |
| First deployment | Index is empty until the first ingest run completes |
| Embedding mismatch | Query model differs from the model used to build the index |

**What BigQuery returns** — query type is determined by keywords in the question:

| `query_type` | Triggered by | Returns |
|---|---|---|
| `airline` | `"delay"` in question | Avg delays, weather %, on-time % per carrier |
| `route_risk` | `"route"` + `"delay"` or `"risk"` | Delay stats and risk scores per route |
| `generic` | Everything else | Summary rows from `ai_rag_documents` |

**How to tell which path ran** — read `context_count` vs `facts_count` in the response:

```
Fallback ran (VS stale):        Healthy VS (no fallback):
  "context_count": 0              "context_count": 5
  "facts_count":   10             "facts_count":   0
  "tools_used": [                 "tools_used": [
    "bigquery_fallback",            "vector_search",
    "gemini_2.5_flash"              "gemini_2.5_flash"
  ]                               ]
```

> The system never returns an empty answer. BigQuery `ai_rag_documents` is always populated by the ingest job regardless of Vector Search status, so the fallback always has data to work with.

---

### Complex Path — `/agent`

**Purpose**: Autonomous reasoning for comparative, ranking, or multi-source questions. LangGraph runs a decision loop — the agent decides which tools to call and in what order, retrying with different parameters if needed, stopping only when it has enough evidence.

```
1. LangGraph loop starts
   ├── Agent node   Gemini decides: "which tool do I need?"
   ├── Tool node    Runs the chosen tool, appends result to state
   └── Agent node   Gemini decides: "do I need another tool, or is this enough?"
       ├── YES → loop back to tool node
       └── NO  → synthesise final answer → END
2. Return answer    + tools_called, tools_used, steps, token_usage
```

`recursion_limit = 10` caps the loop at 4 tool calls max, preventing runaway loops.

**Example question**: *"Which airline has the worst on-time performance this week?"*
```bash
curl -s -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Which airline has the worst on-time performance this week?", "session_id": "demo-c"}' \
  | python3 -c "
import sys, json; d = json.load(sys.stdin)
print('ROUTED TO  :', d.get('routed_to'))
print('TOOLS USED :', d.get('tools_used'))
print('TOOLS CALLED:', d.get('tools_called'))
print('STEPS      :', d.get('steps'))
print('TOKENS     :', d.get('token_usage',{}).get('total_tokens'))
print('ANSWER     :', d.get('answer','')[:300])"
```

Expected output:
```
ROUTED TO   : agent
TOOLS USED  : ['query_analytics', 'gemini_2.5_flash']
TOOLS CALLED: ['query_analytics']
STEPS       : 5
TOKENS      : 2738
ANSWER      : Delta (DL) had the worst on-time performance — 100% delayed on
              BOS-EWR, avg 174.5 min delay over the last 7 days.
```

### Session Memory

Conversation history is stored in **Firestore** (`rag-sessions` database). Both `/retrieve` and `/agent` append each Q&A turn to `sessions/{session_id}`, enabling follow-up questions that reference prior answers. Sessions expire automatically after 1 hour (TTL on `expireAt`). Pass the same `session_id` across calls to maintain context.

Each session document also accumulates a running `token_usage` sub-document across all turns:
```json
{
  "turns": [...],
  "token_usage": {
    "prompt_tokens":   9340,
    "response_tokens": 1821,
    "total_tokens":    11161,
    "request_count":   5
  },
  "expireAt": "2026-06-13T13:00:00Z"
}
```

---

## End-to-End Request Flows

![AI Layer Request Flows — /retrieve vs /agent](images/AI%20Layer%20Request%20Flows%20-%20RAG%20vs.%20Agent.jpg)

The `/ask` router classifies every question with a zero-latency heuristic and forwards to the right path. Simple, scoped questions go to `/retrieve` (fixed pipeline, 1 Gemini call). Comparative, ranking, or multi-step questions go to `/agent` (LangGraph loop, autonomous tool selection). The `routed_to` and `tools_used` fields in every response show exactly which path ran and which data sources were queried.

---

## Agentic Layer (LangGraph)

**LangGraph** is an open-source framework from LangChain for building stateful, multi-step AI agents. Instead of a hard-coded function call sequence, you define a graph of nodes (the LLM, tool executors) and edges (conditional routing logic). LangGraph manages the message state between steps, handles the tool-call loop automatically, and gives you a compiled graph object you invoke like a function. This makes it straightforward to build agents that can reason across multiple data sources, retry with different parameters when a first call returns nothing, and stop only when the model decides it has enough evidence — without writing the loop logic yourself.

The `/agent` endpoint wraps the same GCP tools in a **LangGraph `StateGraph`** — instead of a fixed embed → search → generate sequence, the agent decides autonomously which tools to call and in what order until it has enough evidence to answer.

### Architecture

![Agentic Layer — LangGraph StateGraph](images/Agentic%20Layer%20-LangGraph.png)

### Tools

| Tool | When the agent uses it |
|------|----------------------|
| `search_flight_records` | Specific routes, airlines, or events — semantic similarity over individual records |
| `query_analytics` | Aggregate stats (worst airline, weather trends, route risk rankings) |
| `get_pipeline_status` | Data freshness check — called automatically if prior tools return 0 rows |

> **Resilience note**: `query_analytics` tries the richer BigQuery external tables (`silver_flights_ext`, `ai_route_risk_v`) first. If those are unavailable (Parquet export not yet run, or GCS IAM restriction), it automatically falls back to the native `ai_rag_documents` table, which is always populated by the ingest job. The agent always gets an answer.

**Tools are Python functions — not stored in BigQuery.** They are defined with the `@tool` decorator in `agent.py` and registered at Cloud Run startup. BigQuery and Vector Search are what the tools *query*, not where the tools live.

| | Where it lives | What it does |
|---|---|---|
| **Tool definition** | Python `@tool` functions in `agent.py` | Defines what each tool does |
| **Tool registration** | `_TOOLS` list at container startup | Makes tools available to LangGraph |
| **Tool schema** | Sent to Gemini via `bind_tools()` | Tells Gemini when and how to call each tool |
| **Tool execution** | Python function runs inside Cloud Run | Actually queries BigQuery or Vector Search |
| **Data** | BigQuery + Vertex AI Vector Search | Where the actual aviation data lives |

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
  "token_usage":  {"prompt_tokens": 2841, "response_tokens": 418, "total_tokens": 3259},
  "timestamp":    "2026-06-13T12:00:00Z"
}
```

> **Agent token note**: `token_usage` sums across every Gemini call in the loop — each tool-call decision and the final synthesis step. A 5-step agent run with 2 tool calls will show the combined token spend for all 3 Gemini invocations.

### /retrieve vs /agent vs /ask

| | `/retrieve` (simple path) | `/agent` (complex path) | `/ask` (router) |
|---|---|---|---|
| **Purpose** | Fast, scoped factual lookup | Autonomous cross-source reasoning | Single entry point — auto-selects the right path |
| **Flow** | Fixed: embed → VS → Gemini | LangGraph loop: agent decides tools + order | Heuristic classify → forward to `/retrieve` or `/agent` |
| **Gemini calls** | 1 | 1 per step (typically 2–3) | Depends on routed path |
| **Tool calls** | Vector Search + conditional BQ | 1–4 autonomous tool calls | Depends on routed path |
| **Steps** | N/A (no loop) | 3–5 typical (capped at 10) | N/A |
| **Tokens** | ~500–800 | ~2000–3000 | Depends on routed path |
| **Latency** | ~2–4 s | ~4–10 s | Adds ~0 ms (no LLM call) |
| **Response extras** | `context_count`, `facts_count`, `tools_used` | `tools_called`, `tools_used`, `steps` | `routed_to` + all fields from routed endpoint |
| **Best for** | "What are Delta's delays?" | "Which airline has the worst performance?" | All questions — recommended default |

---

## Multi-Agent Layer (Google ADK) — Proof of Concept

> **Status**: Proof-of-concept module, isolated from the production endpoints above. Built to demonstrate genuine multi-agent orchestration (distinct agent roles + handoff) alongside the existing single-agent LangGraph implementation.

### Multi-step vs. multi-agent — the distinction this module demonstrates

`/agent` (LangGraph) is **single-agent, multi-step**: one decision-maker loops through up to 3 tools, choosing which to call and when to stop. `/multi-agent` (ADK) is genuinely **multi-agent**: two distinct agents with different roles, where the second agent's input is the first agent's output — a real dependency chain, not just tool selection.

```
                    /agent (LangGraph)              /multi-agent (ADK)
                    ───────────────────              ──────────────────
                    1 decision-maker                 2 agents, distinct roles
                    loops over 3 tools                Worker 1 → Worker 2 (sequential handoff)
                    "which tool do I need?"           "detect risk" → "recommend action"
```

### Architecture — Disruption Response Chain

```
User question
      │
      ▼
┌─────────────────────────────┐
│  SUPER-AGENT (Orchestrator)  │   SequentialAgent — runs sub-agents in order
│  disruption_response_        │
│  orchestrator                │
└──────────────┬───────────────┘
               │
               ▼
┌─────────────────────────────┐
│  WORKER 1: Risk Analyst      │   Role: detect & quantify the problem
│  Tool: detect_delay_risk()   │   Queries BigQuery ai_rag_documents
│  → "Delta BOS-EWR: 100%      │
│     delayed, 174.5 min avg,  │
│     14% weather"             │
└──────────────┬───────────────┘
               │  (A2A handoff — Worker 1's output
               │   becomes Worker 2's input)
               ▼
┌─────────────────────────────┐
│  WORKER 2: Mitigation        │   Role: given a risk, recommend action
│  Advisor                     │   No tools — reasons only over Worker 1's
│  → "Not weather-driven (14%) │   output (decision rules in its prompt)
│     — escalate to ops for    │
│     schedule review"         │
└──────────────┬───────────────┘
               │
               ▼
        Final answer returned
```

### How the Super-Agent Is Used in This Project

The super-agent (`disruption_response_orchestrator`) is a **coordinator, not a domain expert** — it has no BigQuery tool, no decision rules, and no knowledge of aviation delays. Its only three jobs are: run workers in the right order, hand each worker's output to the next, and return the final worker's response.

```
                    ┌──────────────────────────────────────┐
                    │      SUPER-AGENT (SequentialAgent)     │
                    │      disruption_response_orchestrator  │
                    │                                        │
                    │  Job 1: SEQUENCE                       │
                    │    run sub_agents in declared order     │
                    │    [risk_analyst, mitigation_advisor]   │
                    │                                        │
                    │  Job 2: HANDOFF                         │
                    │    pass each agent's output forward     │
                    │    as the next agent's input            │
                    │                                        │
                    │  Job 3: RETURN                          │
                    │    final sub-agent's response           │
                    │    becomes the orchestrator's response  │
                    └────────────────┬───────────────────────┘
                                     │  delegates to, in order:
                    ┌────────────────┼────────────────┐
                    ▼                                 ▼
          ┌──────────────────┐              ┌──────────────────────┐
          │  Worker 1         │   output →   │  Worker 2             │
          │  risk_analyst     │ ───────────► │  mitigation_advisor   │
          │  HAS a BQ tool    │              │  HAS no tools —       │
          │  detects risk     │              │  reasons over Worker  │
          │                   │              │  1's output only     │
          └──────────────────┘              └──────────────────────┘
```

**Why this matters architecturally**: the super-agent pattern scales by adding workers, not by making the orchestrator smarter. Today it sequences 2 workers. Extending to a 3-worker "Daily Ops Briefing" (Risk Analyst + Weather Analyst + Pipeline Health, run in parallel via `ParallelAgent` instead of `SequentialAgent`) requires zero changes to either worker — only the orchestrator's composition changes:

```python
# Today: SequentialAgent — workers depend on each other
disruption_response_orchestrator = SequentialAgent(
    sub_agents=[risk_analyst, mitigation_advisor],
)

# Extension: ParallelAgent — workers are independent, fan-out/fan-in
daily_briefing_orchestrator = ParallelAgent(
    sub_agents=[risk_analyst, weather_analyst, pipeline_health],
)
```

This is the core idea behind a "super-agent + specialized worker agents" topology: the super-agent's composition type (`Sequential` vs `Parallel`) encodes the *dependency structure* of the problem, while each worker stays a small, focused, independently-testable unit.

### Code structure

```
retrieval_service/
└── multi_agent/
    ├── __init__.py
    ├── tools.py              # detect_delay_risk() — BigQuery query, scoped for risk detection
    ├── worker_risk.py        # Risk Analyst ADK Agent — detects & quantifies
    ├── worker_mitigation.py  # Mitigation Advisor ADK Agent — recommends action
    └── orchestrator.py       # SequentialAgent wiring + run() entrypoint
```

This module is fully isolated — it does not modify `agent.py`, `retrieval_service.py`'s existing endpoints, or any Terraform-provisioned infrastructure. It reuses the same `aviation_analytics` BigQuery dataset the rest of the platform already provisions.

### Endpoint

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/multi-agent` | POST | Runs the Disruption Response Chain — Risk Analyst → Mitigation Advisor |

**Example**:
```bash
curl -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/multi-agent \
  -H "Content-Type: application/json" \
  -d '{"question": "Delta is showing high delays on BOS-EWR — what should operations do?", "session_id": "demo-multi-agent"}'
```

**Response shape**:
```json
{
  "question":   "Delta is showing high delays on BOS-EWR — what should operations do?",
  "answer":     "Delta's BOS-EWR delays are not primarily weather-driven (14%) — recommend escalating to operations for a schedule/crew review rather than treating this as a weather event.",
  "agents_run": ["risk_analyst", "mitigation_advisor"],
  "session_id": "demo-multi-agent",
  "timestamp":  "2026-06-20T12:00:00Z"
}
```

### Why SequentialAgent, not ParallelAgent

Worker 2 has a hard dependency on Worker 1's output — it cannot recommend mitigation before risk has been quantified. This is the right pattern when workers depend on each other. A **fan-out/fan-in** design (`ParallelAgent`) would instead be used for independent workers — e.g. a "Daily Ops Briefing" combining a Risk Analyst, a Weather Analyst, and a Pipeline Health check that don't depend on each other's output, where running them in parallel and synthesizing at the end is faster than running them one after another.

> **Verified**: Tested locally against `google-adk==2.3.0` — `Agent`, `SequentialAgent`, `Runner`, and `InMemorySessionService` field names and signatures all match this module's usage. Authentication forces Vertex AI (service account) mode via `GOOGLE_GENAI_USE_VERTEXAI` rather than ADK's default Gemini API key lookup, matching how `agent.py` and `retrieval_service.py` already authenticate. Full execution requires GCP Application Default Credentials (present on Cloud Run, not on a bare local machine).

> **Verified live on Cloud Run**: `risk_analyst` queried real BigQuery data (168.0 min avg delay, 11.1% weather-related) and `mitigation_advisor` correctly cited those exact numbers when recommending "escalate to operations for a schedule/crew review" — confirming the handoff actually passes data, not just control flow.

### Monitoring — Cloud Trace, Monitoring, Logging (ADK-native)

Unlike the LangGraph layer, which needed a hand-built pipeline (structured logs → Cloud Logging sink → BigQuery views → Looker Studio, see [Monitoring Dashboard](#monitoring-dashboard)), ADK ships OpenTelemetry instrumentation natively. Enabling GCP export is one function call in `multi_agent/telemetry.py`:

```python
from google.adk.telemetry.google_cloud import get_gcp_exporters
from google.adk.telemetry.setup import maybe_set_otel_providers

hooks = get_gcp_exporters(
    enable_cloud_tracing=True,
    enable_cloud_metrics=True,
    enable_cloud_logging=True,
)
maybe_set_otel_providers([hooks])
```

| What you get | Where to see it |
|---|---|
| Full span per agent run — `risk_analyst`'s tool call latency, `mitigation_advisor`'s turn, total chain duration | Cloud Trace |
| Token usage and request count metrics, auto-exported | Cloud Monitoring |
| Structured log entries per agent turn | Cloud Logging |

Fails silently (logs a warning, doesn't crash the agent) if GCP Application Default Credentials aren't available — verified locally, where it correctly falls back without breaking agent construction.

### Eval

`google.adk.evaluation` ships a full evaluation framework (`AgentEvaluator`, trajectory evaluators, hallucination detection, LLM-as-judge) driven by `.test.json` eval-set files. Its `Invocation`/`IntermediateData` schema is involved enough that hand-authoring correct eval-set files without running them against real GCP credentials risked shipping broken fixtures — so this module ships a **lightweight custom eval harness** (`multi_agent/eval.py`) instead, checking the three things that matter most for this specific chain:

| Check | What it proves |
|---|---|
| **Trajectory** | `agents_run == ["risk_analyst", "mitigation_advisor"]` — the sequential handoff actually happened |
| **Grounding** | The final answer cites a real number from Worker 1's BigQuery output — proves Worker 2 used Worker 1's data, not a generic answer |
| **Correctness** | The final decision matches an independently-recomputed version of the documented decision rule — catches the agent silently deviating from its own instructions |

```bash
python -m multi_agent.eval
```

> **Next step**: migrate these checks into ADK's native `AgentEvaluator` + `.test.json` eval sets once there's time to validate the full `Invocation` schema against real agent runs — the custom harness above is the pragmatic stand-in, not the long-term answer.

---

## CI/CD Workflows

### infra.yml — Terraform Apply

**Trigger**: push to `main` touching `**.tf`  |  `workflow_dispatch`

```
Git Push (**.tf changed)  ──or──  workflow_dispatch
                   │
                   ▼
     Checkout  +  Setup Terraform v1.6.6
                   │
                   ▼
     Authenticate to GCP  (GCP_SA_KEY)
                   │
                   ▼
     Enable 7 GCP APIs
     cloudresourcemanager · iam · container
     artifactregistry · aiplatform · firestore · run
                   │
                   ▼
     Terraform Init  (-upgrade, 3-attempt retry, 15s backoff)
                   │
                   ▼
     Terraform Plan  (-lock-timeout=15m)
                   │
                   ▼
     Wait for retrieval:latest in Artifact Registry
     (polls every 10s · max 30 attempts · fails if not found)
                   │
                   ▼
     Drop BQ External Tables  (pre-apply safety step)
     silver_flights_ext  +  gold_summary_ext
     ── external only, no GCS data deleted ──
                   │
                   ▼
     ┌─────────────────────────────────────────────┐
     │         Terraform Apply  (-auto-approve)     │
     │                                             │
     │  GCS buckets          bronze/silver/gold/AI │
     │  BigQuery             dataset + views       │
     │  GKE Autopilot        aviation-pipeline     │
     │  Artifact Registry    aviation-pipeline     │
     │  Cloud Run            aviation-retrieval    │
     │  Firestore            rag-sessions          │
     │  Vertex AI            Vector Search index   │
     │  Cloud Armor WAF      5 OWASP rules         │
     │  IAM + Workload Identity                    │
     │  IAM Audit Logging    BQ + GCS              │
     └─────────────────────────────────────────────┘
                   │
                   ▼
     Force Cloud Run revision → retrieval:latest
     migrate 100% traffic to new revision
                   │
                   ▼
     Verify AI BigQuery objects
     ai_delay_explanations_v · ai_route_risk_v
     ai_nl_analytics_facts_v · ai_rag_documents
                   │
                   ▼
     Verify Cloud Run URL  +  Report Vector Search status
     (index vector count · endpoint public URL)
                   │
                   ▼
     E2E Smoke Tests  (tests/test_retrieval_e2e.py · --timeout 45s)
                   │
                   ▼
            Pipeline PASSED ✓
```

### pipeline.yml — Build, Push & Deploy

**Trigger**: push to `main` touching `pipeline/**` `retrieval_service/**` `k8s/**`  |  `workflow_dispatch`

```
Git Push (pipeline / retrieval_service / k8s)  ──or──  workflow_dispatch
                        │
                        ▼
          Checkout  +  Authenticate to GCP
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
   Build ingest image      Build retrieval image
   pipeline/ingest/        retrieval_service/
              │                   │
              ▼                   ▼
   Push ingest:sha        Push retrieval:sha
   Push ingest:latest     Push retrieval:latest
   → Artifact Registry    → Artifact Registry
              │                   │
              └─────────┬─────────┘
                        │
                        ▼
          Deploy retrieval → Cloud Run
          aviation-retrieval · migrate traffic to latest
                        │
                        ▼
          Get GKE credentials
                        │
                        ▼
          Apply K8s manifests
          namespace · service-account · ingest-cronjob
                        │
                        ▼
          Update CronJob image → new commit SHA
                        │
                        ▼
          Run one-time ingest job  (every push)
          waits for completion · max 10 min
          → 5,000 records → Bronze GCS (CSV)
          → Embeddings → BigQuery ai_rag_documents
          → GCS batch.json → Vector Search index trigger
                        │
                        ▼
          Verify AI RAG data freshness + embeddings
          (total_docs · docs_with_embeddings · fresh_docs_24h)
                        │
                        ▼
          Databricks pipeline  (skips if secrets not set)
          │
          ├── bronze_to_silver   Raw CSV → cleaned Delta silver_flights
          ├── silver_to_gold     Aggregations → Delta gold_flight_summary
          └── export_to_gcs      Flat Parquet → GCS Silver + Gold buckets
                                 BigQuery external tables now query-ready
                        │
                        ▼
               Pipeline PASSED ✓
```

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

## AI Guardrails

Five guardrail layers are active on every request.

| Layer | Where | What it does |
|-------|-------|-------------|
| **Input validation** | `/retrieve` and `/agent` handlers | Rejects malformed input before any GCP call is made |
| **Gemini safety settings** | `reason_with_vertex()` | Blocks harmful content at `BLOCK_MEDIUM_AND_ABOVE` for dangerous content, hate speech, harassment, and sexually explicit categories |
| **Parameterized BigQuery** | All BQ queries in `retrieval_service.py` and `agent.py` | `@days_back`, `@airline`, `@route` — prevents SQL injection via LLM-supplied or user-supplied values |
| **Prompt injection defence** | `build_reasoning_prompt()`, agent system prompt, `search_flight_records` | XML-delimited prompt sections + `_sanitise_context()` regex strips instruction-override patterns from all retrieved content |
| **Token usage monitoring** | `reason_with_vertex()`, `/agent` handler, `append_session_turn()` | Logs, returns in response, and accumulates per-session in Firestore |

### Token Usage Monitoring

Token counts are captured from `response.usage_metadata` on every Gemini call and surfaced at three levels:

**Level 1 — Cloud Logging** (every request):
```
Token usage — prompt: 1842, response: 312, total: 2154
```
Visible in GCP Console → Cloud Run → `aviation-retrieval` → Logs. Queryable with Log Explorer for cost trend analysis.

**Level 2 — API response** (every `/retrieve` and `/agent` call):
```bash
curl -s -X POST .../retrieve \
  -H "Content-Type: application/json" \
  -d '{"question": "Which routes have the highest weather delays?", "session_id": "demo-1"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['answer']); print('Tokens:', d['token_usage'])"
# Tokens: {'prompt_tokens': 1842, 'response_tokens': 312, 'total_tokens': 2154}
```
The `/agent` response sums token spend across all Gemini invocations in the reasoning loop.

**Level 3 — Firestore session accumulation** (per `session_id`):

GCP Console → Firestore → `rag-sessions` → `sessions` → click any session document:
```json
{
  "token_usage": {
    "prompt_tokens":   9340,
    "response_tokens": 1821,
    "total_tokens":    11161,
    "request_count":   5
  }
}
```
Provides per-user / per-session cost attribution across the full conversation lifetime without any external tracking infrastructure.

![Firestore token_usage — live session document](images/Monitor%20Tokens.jpg)

### Input validation rules

| Parameter | Rule | Error |
|-----------|------|-------|
| `question` | Required; max 500 characters | `400` |
| `session_id` | Letters, digits, hyphens, underscores only; max 64 chars | `400` |
| `airline` | 2–3 uppercase IATA code, e.g. `AA` | `400` |
| `route` | `ORIGIN-DEST` with 3-letter codes, e.g. `ATL-LAX` | `400` |
| `days_back` | Integer 1–30 | `400` |
| `top_k` | Integer 1–20 | `400` |

### Testing guardrails

**Happy path — valid `/retrieve` with all filters:**
```bash
curl -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/retrieve \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the weather delay trends for Delta?", "session_id": "demo-1", "airline": "DL", "days_back": 7, "top_k": 5}'
# → {"answer": "...", "context_count": 5, ...}
```

**Question too long (> 500 chars):**
```bash
curl -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/retrieve \
  -H "Content-Type: application/json" \
  -d '{"question": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "session_id": "demo-1"}'
# → {"error": "'question' must be 500 characters or fewer"} HTTP 400
```

**Invalid session_id (contains a space):**
```bash
curl -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/retrieve \
  -H "Content-Type: application/json" \
  -d '{"question": "Show me delay trends", "session_id": "my session"}'
# → {"error": "'session_id' must contain only letters, digits, hyphens, or underscores (max 64 chars)"} HTTP 400
```

**Invalid airline code (lowercase / too long):**
```bash
curl -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/retrieve \
  -H "Content-Type: application/json" \
  -d '{"question": "Show me delay trends", "airline": "delta"}'
# → {"error": "'airline' must be a 2–3 character IATA code (e.g. '\''AA'\'')"} HTTP 400
```

**Invalid route format:**
```bash
curl -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/retrieve \
  -H "Content-Type: application/json" \
  -d '{"question": "Route risk", "route": "Atlanta to LA"}'
# → {"error": "'route' must be ORIGIN-DEST with 3-letter codes (e.g. 'ATL-LAX')"} HTTP 400
```

**`days_back` out of range:**
```bash
curl -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/retrieve \
  -H "Content-Type: application/json" \
  -d '{"question": "Show me delay trends", "days_back": 90}'
# → {"error": "'days_back' must be between 1 and 30"} HTTP 400
```

**Valid `/agent` query:**
```bash
curl -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/agent \
  -H "Content-Type: application/json" \
  -d '{"question": "Which airline has the worst on-time performance this week?", "session_id": "demo-guardrails"}'
# → {"answer": "...", "tools_called": ["query_analytics"], "steps": 3, ...}
```

**Invalid session_id on `/agent`:**
```bash
curl -X POST https://aviation-retrieval-ohvijuloea-uc.a.run.app/agent \
  -H "Content-Type: application/json" \
  -d '{"question": "Show me delay trends", "session_id": "bad session!"}'
# → {"error": "'session_id' must contain only letters, digits, hyphens, or underscores (max 64 chars)"} HTTP 400
```

---

## OWASP LLM Top 10 — Security Coverage

Assessment of the platform against the [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/).

| # | Vulnerability | Status | How it's covered |
|---|---|---|---|
| LLM01 | Prompt Injection | ✅ Strong | `_INJECTION_RE` regex strips override patterns from all retrieved content; XML-delimited prompt sections separate instructions from untrusted data; both `/retrieve` and `/agent` prompts explicitly instruct Gemini to ignore instructions inside retrieved sections |
| LLM02 | Insecure Output Handling | ⚠️ Partial | Responses returned as JSON (not rendered as HTML by this service); no HTML escaping of answer text — downstream clients must escape before rendering |
| LLM03 | Training Data Poisoning | ✅ Good | No fine-tuning or training — uses Google's hosted Gemini 2.5 Flash; RAG documents come from a deterministic synthetic ingest job; Databricks `bronze_to_silver` filters null, out-of-range, and duplicate records before anything enters the AI layer |
| LLM04 | Model Denial of Service | ⚠️ Partial | Input size limits (question ≤ 500 chars, `days_back` 1–30, `top_k` 1–20); Cloud Armor WAF at the network edge; no per-IP rate limiting or per-session token budget |
| LLM05 | Supply Chain Vulnerabilities | ⚠️ Partial | All LLM calls go to Google's managed Gemini API (vetted vendor); open-source dependencies (LangChain, VertexAI SDK, Flask) are well-known packages; no automated dependency vulnerability scanning in CI/CD |
| LLM06 | Sensitive Information Disclosure | ✅ Strong | Fully synthetic dataset — no real PII; all BigQuery queries parameterized (`@airline`, `@route`, `@days_back`); Firestore sessions isolated by `session_id`; Gemini safety settings block harmful content; IAM Audit Logging on BigQuery + GCS |
| LLM07 | Insecure Plugin Design | ✅ Strong | Agent exposes exactly 3 read-only tools (`search_flight_records`, `query_analytics`, `get_pipeline_status`); LLM-supplied values go through parameterized queries only; tool outputs sanitized by `_sanitise()` before re-entering the agent loop; no shell execution, file access, or arbitrary HTTP calls |
| LLM08 | Excessive Agency | ✅ Strong | All agent tools are SELECT-only — no writes to any storage; Cloud Run SA has `roles/bigquery.dataViewer` + `roles/bigquery.jobUser` only; GKE SA has `roles/storage.objectCreator` on Bronze bucket only; LangGraph `ToolNode` limits the agent to the registered tool set |
| LLM09 | Overreliance | ⚠️ Partial | Agent system prompt instructs Gemini to acknowledge synthetic data and narrow time windows; `get_pipeline_status` tool surfaces data freshness; every response includes `context_count` and `facts_count`; no explicit `data_synthetic` disclaimer field in every response |
| LLM10 | Model Theft | ✅ Strong | No model weights in this project — uses Google's hosted Gemini API; Vector Search index stored in Vertex AI managed internal storage (not browsable); Cloud Armor WAF blocks enumeration and scraping patterns |

**6 of 10 fully covered. The 4 partial gaps are low-risk for a demo platform and are documented trade-offs.**

---

## Monitoring Dashboard

Token spend and guardrail activity are exported from Cloud Run logs to BigQuery via a structured log sink, then surfaced in Looker Studio alongside the flight analytics dashboard.

### How it works

Every request emits structured JSON to stdout. Cloud Run forwards these to Cloud Logging, and the `aviation-cloudrun-monitoring` log sink writes them to BigQuery automatically.

| Event | When emitted | Key fields |
|-------|-------------|------------|
| `token_usage` | Every `/retrieve` and `/agent` response | `endpoint`, `session_id`, `prompt_tokens`, `response_tokens`, `total_tokens` |
| `guardrail_triggered` | Every rejected request (400) | `guardrail_type`, `reason`, `session_id` |
| `bq_fallback` | When Vector Search returns < 3 results | `vs_results`, `session_id` |

### BigQuery views

| View | Description |
|------|-------------|
| `monitoring_token_usage_v` | Token spend per request — by hour, endpoint, and session |
| `monitoring_guardrails_v` | Guardrail triggers and BigQuery fallback events — by hour and type |

### Looker Studio dashboard pages

**Page 1 — Token Usage**
- Total tokens today / this week
- Prompt vs response token split by endpoint (`/retrieve` vs `/agent`)
- Top sessions by token spend

**Page 2 — Guardrails & Reliability**
- Rejection count by type (input validation, prompt injection)
- BigQuery fallback rate (% of requests where Vector Search returned < 3 results)
- Rejection trend over time

> **Note**: The BigQuery sink table (`run_googleapis_com_stdout`) is created automatically on the first request after deployment. If `terraform apply` runs before any traffic, re-run it once the service receives its first request.

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

![BigQuery Views and Analytics Schema](images/BigQuery%20Views%20and%20Analytics%20Schema.jpg)

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

### BI Dashboard (Looker Studio)

![Looker Studio — Flight Risk Dashboard](images/Looker%20studio.png)

---

## License

This project is provided as a reference implementation and learning resource. See [LICENSE](LICENSE) for details.
