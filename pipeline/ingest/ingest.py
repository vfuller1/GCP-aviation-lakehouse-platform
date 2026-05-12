"""
Aviation data ingest job — Kubernetes CronJob
Generates synthetic aviation flight records and writes to the Bronze GCS bucket.

Stage: SOURCE → BRONZE (raw landing zone)
"""

import csv
import io
import json
import os
import random
import uuid
from datetime import datetime, timezone

from google.cloud import storage

# ---------------------------------------------------------------------------
# Config (overridable via environment variables in the K8s manifest)
# ---------------------------------------------------------------------------
PROJECT_ID   = os.environ.get("GCP_PROJECT_ID", "gcp-lakehouseproject")
BRONZE_BUCKET = os.environ.get("BRONZE_BUCKET", f"{PROJECT_ID}-bronze")
NUM_RECORDS  = int(os.environ.get("NUM_RECORDS", "1000"))
BAD_DATA_RATE = float(os.environ.get("BAD_DATA_RATE", "0.0"))
AI_ARTIFACTS_BUCKET = os.environ.get("AI_ARTIFACTS_BUCKET", f"{PROJECT_ID}-ai")
VERTEX_REGION = os.environ.get("VERTEX_REGION", "us-central1")
VERTEX_EMBEDDING_MODEL = os.environ.get("VERTEX_EMBEDDING_MODEL", "text-embedding-005")
BQ_DATASET = os.environ.get("BQ_DATASET", "aviation_analytics")
BQ_RAG_TABLE = os.environ.get("BQ_RAG_TABLE", "ai_rag_documents")


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


ENABLE_RAG_DOC_EXPORT = _as_bool(os.environ.get("ENABLE_RAG_DOC_EXPORT", "false"))
ENABLE_VERTEX_EMBEDDINGS = _as_bool(os.environ.get("ENABLE_VERTEX_EMBEDDINGS", "false"))

AIRLINES = ["AA", "DL", "UA", "WN", "B6", "AS", "NK", "F9", "G4", "HA"]
AIRPORTS = [
    "ATL", "LAX", "ORD", "DFW", "DEN", "JFK", "SFO", "SEA", "LAS", "MCO",
    "EWR", "PHX", "IAH", "BOS", "FLL", "MSP", "LGA", "DTW", "FCO", "CDG",
]
STATUSES = ["ON_TIME", "DELAYED", "CANCELLED", "DIVERTED"]


def generate_record() -> dict:
    origin, destination = random.sample(AIRPORTS, 2)
    dep_delay = random.randint(-15, 240)
    arr_delay = max(dep_delay + random.randint(-10, 30), -30)
    weather_flag = random.random() < 0.15  # ~15 % weather-related

    if dep_delay <= 0:
        status = "ON_TIME"
    elif dep_delay < 45:
        status = "DELAYED"
    elif random.random() < 0.05:
        status = "CANCELLED"
    else:
        status = "DELAYED"

    return {
        "flight_id":            str(uuid.uuid4()),
        "airline":              random.choice(AIRLINES),
        "origin":               origin,
        "destination":          destination,
        "departure_delay_min":  dep_delay,
        "arrival_delay_min":    arr_delay,
        "weather_flag":         "TRUE" if weather_flag else "FALSE",
        "status":               status,
        "event_ts":             datetime.now(timezone.utc).isoformat(),
    }


def inject_bad_data(record: dict) -> dict:
    bad_record = dict(record)
    corruption_type = random.choice([
        "missing_flight_id",
        "missing_airline",
        "missing_origin",
        "missing_destination",
        "missing_event_ts",
    ])

    if corruption_type == "missing_flight_id":
        bad_record["flight_id"] = ""
    elif corruption_type == "missing_airline":
        bad_record["airline"] = ""
    elif corruption_type == "missing_origin":
        bad_record["origin"] = ""
    elif corruption_type == "missing_destination":
        bad_record["destination"] = ""
    else:
        bad_record["event_ts"] = ""

    return bad_record


def build_rag_document(record: dict) -> dict:
    required_fields = [
        "flight_id",
        "airline",
        "origin",
        "destination",
        "event_ts",
        "departure_delay_min",
        "arrival_delay_min",
        "status",
        "weather_flag",
    ]
    for field in required_fields:
        if record.get(field, "") in ("", None):
            raise ValueError(f"missing required field: {field}")

    route = f"{record['origin']}-{record['destination']}"
    dep_delay = int(record["departure_delay_min"])
    arr_delay = int(record["arrival_delay_min"])
    weather_flag = record["weather_flag"] == "TRUE"

    content = (
        f"Flight {record['flight_id']} for airline {record['airline']} on route {route} "
        f"had departure delay {dep_delay} minutes and arrival delay {arr_delay} minutes. "
        f"Status was {record['status']}. Weather impact flag was {weather_flag}. "
        f"Event timestamp was {record['event_ts']}."
    )

    return {
        "doc_id": record["flight_id"],
        "content": content,
        "source_type": "flight_event",
        "airline": record["airline"],
        "route": route,
        "event_date": datetime.fromisoformat(record["event_ts"]).date().isoformat(),
        "metadata": {
            "status": record["status"],
            "weather_flag": weather_flag,
            "departure_delay_min": dep_delay,
            "arrival_delay_min": arr_delay,
        },
    }


def upsert_rag_documents_to_bigquery(bq_client, target_table_id: str, rows: list[dict]) -> None:
    from google.cloud import bigquery

    if not rows:
        return

    temp_table_id = f"{PROJECT_ID}.{BQ_DATASET}._tmp_ai_rag_documents_{uuid.uuid4().hex[:10]}"
    schema = [
        bigquery.SchemaField("doc_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("content", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("source_type", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("airline", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("route", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("event_date", "DATE", mode="NULLABLE"),
        bigquery.SchemaField("embedding", "FLOAT64", mode="REPEATED"),
        bigquery.SchemaField("metadata", "JSON", mode="NULLABLE"),
        bigquery.SchemaField("updated_ts", "TIMESTAMP", mode="REQUIRED"),
    ]

    load_config = bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_TRUNCATE")
    load_job = bq_client.load_table_from_json(rows, temp_table_id, job_config=load_config)
    load_job.result()

    merge_sql = f"""
    MERGE `{target_table_id}` AS target
    USING (
      SELECT * EXCEPT(rn)
      FROM (
        SELECT
          *,
          ROW_NUMBER() OVER (PARTITION BY doc_id ORDER BY updated_ts DESC) AS rn
        FROM `{temp_table_id}`
      )
      WHERE rn = 1
    ) AS source
    ON target.doc_id = source.doc_id
    WHEN MATCHED THEN
      UPDATE SET
        content = source.content,
        source_type = source.source_type,
        airline = source.airline,
        route = source.route,
        event_date = source.event_date,
        embedding = source.embedding,
        metadata = source.metadata,
        updated_ts = source.updated_ts
    WHEN NOT MATCHED THEN
      INSERT (doc_id, content, source_type, airline, route, event_date, embedding, metadata, updated_ts)
      VALUES (source.doc_id, source.content, source.source_type, source.airline, source.route, source.event_date, source.embedding, source.metadata, source.updated_ts)
    """

    try:
        merge_job = bq_client.query(merge_sql)
        merge_job.result()
    finally:
        bq_client.delete_table(temp_table_id, not_found_ok=True)


def export_rag_documents(storage_client: storage.Client, records: list[dict], run_date: str) -> None:
    docs = []
    skipped = 0
    for record in records:
        try:
            docs.append(build_rag_document(record))
        except (ValueError, TypeError) as exc:
            skipped += 1
            print(f"[ingest-ai] Skipping malformed record: {exc}")

    if not docs:
        print("[ingest-ai] No valid RAG documents to export after validation")
        return

    docs_path = f"aviation/rag_docs/date={run_date}/flight_docs.ndjson"

    docs_buf = io.StringIO()
    for doc in docs:
        docs_buf.write(json.dumps(doc))
        docs_buf.write("\n")

    ai_bucket = storage_client.bucket(AI_ARTIFACTS_BUCKET)
    ai_bucket.blob(docs_path).upload_from_string(
        docs_buf.getvalue(),
        content_type="application/x-ndjson",
    )

    print(
        f"[ingest-ai] Exported {len(docs)} RAG docs"
        f" (skipped={skipped}) → gs://{AI_ARTIFACTS_BUCKET}/{docs_path}"
    )

    if not ENABLE_VERTEX_EMBEDDINGS:
        return

    from google.cloud import bigquery
    import vertexai
    from vertexai.language_models import TextEmbeddingModel

    vertexai.init(project=PROJECT_ID, location=VERTEX_REGION)
    model = TextEmbeddingModel.from_pretrained(VERTEX_EMBEDDING_MODEL)

    import time

    embeddings: list[list[float]] = []
    batch_size = 5
    for i in range(0, len(docs), batch_size):
        batch_docs = docs[i : i + batch_size]
        for attempt in range(6):
            try:
                batch_embeddings = model.get_embeddings([doc["content"] for doc in batch_docs])
                embeddings.extend([item.values for item in batch_embeddings])
                break
            except Exception as exc:
                if attempt == 5:
                    raise
                wait = 2 ** attempt * 5
                print(f"[ingest-ai] Embedding batch {i//batch_size} attempt {attempt+1} failed ({exc}); retrying in {wait}s...")
                time.sleep(wait)

    bq_rows = []
    updated_ts = datetime.now(timezone.utc).isoformat()
    for doc, embedding in zip(docs, embeddings):
        bq_rows.append(
            {
                "doc_id": doc["doc_id"],
                "content": doc["content"],
                "source_type": doc["source_type"],
                "airline": doc["airline"],
                "route": doc["route"],
                "event_date": doc["event_date"],
                "embedding": embedding,
                "metadata": doc["metadata"],
                "updated_ts": updated_ts,
            }
        )

    bq = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{BQ_DATASET}.{BQ_RAG_TABLE}"
    upsert_rag_documents_to_bigquery(bq, table_id, bq_rows)

    print(
        f"[ingest-ai] Embedded and upserted {len(bq_rows)} docs into "
        f"{PROJECT_ID}.{BQ_DATASET}.{BQ_RAG_TABLE} using {VERTEX_EMBEDDING_MODEL}"
    )

    # Write Vertex AI batch-update index file (flat — no subdirs allowed)
    # Format: one JSON object per line with 'id' and 'embedding' fields
    index_path = "aviation/indices/rag/batch.json"
    index_buf = io.StringIO()
    for row in bq_rows:
        index_buf.write(json.dumps({"id": row["doc_id"], "embedding": row["embedding"]}))
        index_buf.write("\n")
    ai_bucket.blob(index_path).upload_from_string(
        index_buf.getvalue(),
        content_type="application/x-ndjson",
    )
    print(f"[ingest-ai] Wrote {len(bq_rows)} vectors → gs://{AI_ARTIFACTS_BUCKET}/{index_path}")

    # Trigger Vertex AI index batch update so the new vectors become queryable
    # contentsDeltaUri must be the directory containing batch.json, not the file itself
    index_dir = "aviation/indices/rag/"
    _trigger_index_update(f"gs://{AI_ARTIFACTS_BUCKET}/{index_dir}")


def _trigger_index_update(gcs_dir_uri: str) -> None:
    """Fire a Vertex AI UpdateIndex PATCH (batch update from GCS) — returns immediately after submitting LRO."""
    import json
    import urllib.request
    import google.auth
    import google.auth.transport.requests

    try:
        from google.cloud import aiplatform
        aiplatform.init(project=PROJECT_ID, location=VERTEX_REGION)
        indexes = aiplatform.MatchingEngineIndex.list(
            filter='display_name="aviation-rag-index"',
            project=PROJECT_ID,
            location=VERTEX_REGION,
        )
        if not indexes:
            print("[ingest-ai] No Vector Search index found; skipping index update trigger.")
            return

        index_name = indexes[0].resource_name  # e.g. projects/.../indexes/...
        # Correct endpoint: PATCH the index resource with metadata.contentsDeltaUri
        url = f"https://{VERTEX_REGION}-aiplatform.googleapis.com/v1/{index_name}"
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(google.auth.transport.requests.Request())

        payload = json.dumps({
            "metadata": {
                "contentsDeltaUri": gcs_dir_uri,
                "isCompleteOverwrite": False,
            }
        }).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {credentials.token}",
                "Content-Type": "application/json",
            },
            method="PATCH",
        )
        with urllib.request.urlopen(req) as resp:
            lro = json.loads(resp.read())
            print(f"[ingest-ai] Triggered Vector Search index update LRO: {lro.get('name', 'unknown')}")
    except Exception as exc:
        print(f"[ingest-ai] Warning: could not trigger index update: {exc}")


def main() -> None:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    gcs_path = f"aviation/raw/date={today}/flights.csv"

    records = []
    bad_rows = 0

    for _ in range(NUM_RECORDS):
        record = generate_record()
        if BAD_DATA_RATE > 0 and random.random() < BAD_DATA_RATE:
            record = inject_bad_data(record)
            bad_rows += 1
        records.append(record)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=records[0].keys())
    writer.writeheader()
    writer.writerows(records)

    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(BRONZE_BUCKET)
    blob   = bucket.blob(gcs_path)
    blob.upload_from_string(buf.getvalue(), content_type="text/csv")

    print(
        f"[ingest] Uploaded {NUM_RECORDS} records (bad_rows={bad_rows}, bad_data_rate={BAD_DATA_RATE}) "
        f"→ gs://{BRONZE_BUCKET}/{gcs_path}"
    )

    if ENABLE_RAG_DOC_EXPORT:
        export_rag_documents(storage_client, records, today)
    else:
        print("[ingest-ai] RAG export disabled (set ENABLE_RAG_DOC_EXPORT=true to enable)")


if __name__ == "__main__":
    main()
