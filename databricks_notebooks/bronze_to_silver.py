# Databricks notebook: Bronze → Silver (Integrated Layer)
# Stage: RAW (Bronze) → CLEANED / INTEGRATED (Silver)
#
# Reads raw CSV files from the Bronze Unity Catalog Volume,
# applies cleaning and type casting, and writes a Delta table to Silver.
#
# Prerequisites:
#   - Upload CSVs into /Volumes/workspace/aviation/bronze/raw/
#     (e.g. via Kubernetes ingest CronJob, REST API, or dbutils.fs.cp)

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, BooleanType, TimestampType

spark = SparkSession.builder.getOrCreate()

# ---------------------------------------------------------------------------
# Unity Catalog paths (Serverless-compatible)
# ---------------------------------------------------------------------------
BRONZE_VOLUME = "/Volumes/workspace/aviation/bronze"
SILVER_TABLE  = "workspace.aviation.silver_flights"

# ---------------------------------------------------------------------------
# 1. Read all date-partitioned raw files from Bronze volume
# ---------------------------------------------------------------------------
bronze_path = f"{BRONZE_VOLUME}/raw/date=*/*.csv"

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
# 4. Write to Silver as a Delta table, partitioned by ingest_date
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
    .option("overwriteSchema", "true")
    .partitionBy("ingest_date")
    .saveAsTable(SILVER_TABLE)
)

print(f"[bronze_to_silver] ✓ Wrote {clean_count} records → {SILVER_TABLE}")
