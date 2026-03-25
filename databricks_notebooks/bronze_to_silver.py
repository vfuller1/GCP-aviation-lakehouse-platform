# Databricks notebook: Bronze → Silver (Integrated Layer)
# Stage: RAW (Bronze) → CLEANED / INTEGRATED (Silver)
#
# Reads raw CSV files dropped by the Kubernetes ingest CronJob,
# applies cleaning and type casting, and writes Parquet to the Silver bucket.

import os

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, BooleanType, TimestampType

spark = SparkSession.builder.getOrCreate()

def get_project_id() -> str:
    """Resolve GCP project from Spark conf with safe fallback for Serverless."""
    for key in ["spark.gcp.project", "spark.hadoop.fs.gs.project.id"]:
        try:
            value = spark.conf.get(key)
            if value:
                return value
        except Exception:
            pass

    return os.environ.get("GCP_PROJECT_ID", "gcp-lakehouseproject")


PROJECT_ID    = get_project_id()
BRONZE_BUCKET = f"gs://{PROJECT_ID}-bronze"
SILVER_BUCKET = f"gs://{PROJECT_ID}-silver"

# ---------------------------------------------------------------------------
# 1. Read all date-partitioned raw files from Bronze
# ---------------------------------------------------------------------------
bronze_path = f"{BRONZE_BUCKET}/aviation/raw/date=*/*.csv"
silver_path = f"{SILVER_BUCKET}/aviation/cleaned/"

df_raw = spark.read.option("header", True).csv(bronze_path)
raw_count = df_raw.count()
print(f"\n[bronze_to_silver] Raw Bronze count: {raw_count}")

# ---------------------------------------------------------------------------
# 2. Cast types, derive columns, drop nulls
# ---------------------------------------------------------------------------
df_typed = (
    df_raw
    .withColumn("departure_delay_min", F.col("departure_delay_min").cast(IntegerType()))
    .withColumn("arrival_delay_min",   F.col("arrival_delay_min").cast(IntegerType()))
    .withColumn("weather_flag",        F.col("weather_flag").cast(BooleanType()))
    .withColumn("event_ts",            F.col("event_ts").cast(TimestampType()))
    .withColumn("ingest_date",         F.to_date("event_ts"))
)

# ---------------------------------------------------------------------------
# 3. Data quality: drop records missing key fields or with implausible delays
# ---------------------------------------------------------------------------
df_clean = (
    df_typed
    .dropna(subset=["flight_id", "airline", "origin", "destination", "event_ts"])
    .filter(F.col("departure_delay_min").between(-60, 600))
    .filter(F.col("arrival_delay_min").between(-60, 600))
    .filter(F.col("origin") != F.col("destination"))
    .dropDuplicates(["flight_id"])
)

# ---------------------------------------------------------------------------
# 4. Write to Silver as Parquet, partitioned by ingest_date
# ---------------------------------------------------------------------------
clean_count = df_clean.count()
rows_dropped = raw_count - clean_count
quality_pct = 100 * rows_dropped / raw_count if raw_count > 0 else 0

print(f"[bronze_to_silver] Clean Silver count: {clean_count}")
print(f"[bronze_to_silver] Quality metrics: {rows_dropped} rows removed ({quality_pct:.1f}%)")

(
    df_clean
    .write
    .mode("overwrite")
    .partitionBy("ingest_date")
    .parquet(silver_path)
)

print(f"[bronze_to_silver] ✓ Wrote {clean_count} records → {silver_path}")
