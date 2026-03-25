"""
Aviation data ingest job — Kubernetes CronJob
Generates synthetic aviation flight records and writes to the Bronze GCS bucket.

Stage: SOURCE → BRONZE (raw landing zone)
"""

import csv
import io
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

    client = storage.Client(project=PROJECT_ID)
    bucket = client.bucket(BRONZE_BUCKET)
    blob   = bucket.blob(gcs_path)
    blob.upload_from_string(buf.getvalue(), content_type="text/csv")

    print(
        f"[ingest] Uploaded {NUM_RECORDS} records (bad_rows={bad_rows}, bad_data_rate={BAD_DATA_RATE}) "
        f"→ gs://{BRONZE_BUCKET}/{gcs_path}"
    )


if __name__ == "__main__":
    main()
