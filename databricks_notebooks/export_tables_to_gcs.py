# Databricks notebook: Export Silver/Gold Delta tables to GCS
#
# Purpose:
#   Keep Serverless-friendly transforms in Unity Catalog tables, then optionally
#   export those tables to GCS buckets for external visibility and downstream use.
#
# Recommended runtime:
#   Classic Databricks compute with GCS credentials configured.

import os

from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "gcp-lakehouseproject")

SILVER_TABLE = os.environ.get("SILVER_TABLE", "workspace.aviation.silver_flights")
GOLD_TABLE = os.environ.get("GOLD_TABLE", "workspace.aviation.gold_flight_summary")

SILVER_EXPORT_PATH = os.environ.get(
    "SILVER_EXPORT_PATH",
    f"gs://{PROJECT_ID}-silver/aviation/cleaned/",
)
GOLD_EXPORT_PATH = os.environ.get(
    "GOLD_EXPORT_PATH",
    f"gs://{PROJECT_ID}-gold/aviation/aggregated/",
)

# ---------------------------------------------------------------------------
# 1. Read Delta tables from Unity Catalog
# ---------------------------------------------------------------------------
df_silver = spark.table(SILVER_TABLE)
df_gold = spark.table(GOLD_TABLE)

silver_count = df_silver.count()
gold_count = df_gold.count()

print(f"[export_to_gcs] Silver table: {SILVER_TABLE} ({silver_count} rows)")
print(f"[export_to_gcs] Gold table: {GOLD_TABLE} ({gold_count} rows)")

# ---------------------------------------------------------------------------
# 2. Export Silver and Gold to GCS as Parquet
# ---------------------------------------------------------------------------
(
    df_silver
    .write
    .mode("overwrite")
    # No partitionBy — flat Parquet so BigQuery can use *.parquet glob (single wildcard).
    # ingest_date remains a data column; BigQuery views filter by it as needed.
    .parquet(SILVER_EXPORT_PATH)
)

(
    df_gold
    .write
    .mode("overwrite")
    # No partitionBy — flat Parquet so BigQuery can use *.parquet glob (single wildcard)
    # and so summary_type remains a regular data column (partitionBy strips it from
    # Parquet files into directory names, making it invisible to BigQuery views).
    .parquet(GOLD_EXPORT_PATH)
)

print(f"[export_to_gcs] Exported Silver Parquet -> {SILVER_EXPORT_PATH}")
print(f"[export_to_gcs] Exported Gold Parquet -> {GOLD_EXPORT_PATH}")
