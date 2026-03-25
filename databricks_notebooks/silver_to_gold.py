# Databricks notebook: Silver → Gold (Curated Layer)
# Stage: INTEGRATED (Silver) → CURATED / AGGREGATED (Gold) → BigQuery
#
# Reads cleaned Parquet from Silver, computes business-level aggregations,
# writes Gold Parquet, and loads the summary table into BigQuery via the
# Spark BigQuery connector (bundled with Databricks Runtime 13.3+ on GCP).

import os

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

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


PROJECT_ID     = get_project_id()
SILVER_BUCKET  = f"gs://{PROJECT_ID}-silver"
GOLD_BUCKET    = f"gs://{PROJECT_ID}-gold"
BQ_DATASET     = "aviation_analytics"
BQ_TABLE       = f"{PROJECT_ID}.{BQ_DATASET}.flight_summary"
TEMP_GCS_BUCKET = f"{PROJECT_ID}-gold"  # BigQuery connector uses GCS as a staging area

silver_path = f"{SILVER_BUCKET}/aviation/cleaned/"
gold_path   = f"{GOLD_BUCKET}/aviation/aggregated/"

# ---------------------------------------------------------------------------
# 1. Read Silver
# ---------------------------------------------------------------------------
df_silver = spark.read.parquet(silver_path)

# ---------------------------------------------------------------------------
# 2. Aggregations — four Gold views
# ---------------------------------------------------------------------------

# a) Average delay by airline
avg_delay_airline = (
    df_silver
    .groupBy("airline")
    .agg(
        F.round(F.avg("departure_delay_min"), 2).alias("avg_dep_delay_min"),
        F.round(F.avg("arrival_delay_min"),   2).alias("avg_arr_delay_min"),
        F.count("*").alias("total_flights"),
    )
    .withColumn("summary_type", F.lit("by_airline"))
    .withColumn("dimension_key", F.col("airline"))
)

# b) Average delay by route (origin → destination)
avg_delay_route = (
    df_silver
    .withColumn("route", F.concat_ws("-", F.col("origin"), F.col("destination")))
    .groupBy("route")
    .agg(
        F.round(F.avg("departure_delay_min"), 2).alias("avg_dep_delay_min"),
        F.round(F.avg("arrival_delay_min"),   2).alias("avg_arr_delay_min"),
        F.count("*").alias("total_flights"),
    )
    .withColumn("summary_type", F.lit("by_route"))
    .withColumn("dimension_key", F.col("route"))
)

# c) Delayed flights by day
delayed_by_day = (
    df_silver
    .filter(F.col("status") == "DELAYED")
    .groupBy("ingest_date")
    .agg(
        F.count("*").alias("total_flights"),
        F.count(F.when(F.col("weather_flag") == True, 1)).alias("weather_related"),
    )
    .withColumn("avg_dep_delay_min", F.lit(None).cast("double"))
    .withColumn("avg_arr_delay_min", F.lit(None).cast("double"))
    .withColumn("summary_type", F.lit("delayed_by_day"))
    .withColumn("dimension_key", F.col("ingest_date").cast("string"))
)

# d) On-time performance by airline
ontime_pct = (
    df_silver
    .groupBy("airline")
    .agg(
        F.count("*").alias("total_flights"),
        F.round(
            F.sum(F.when(F.col("status") == "ON_TIME", 1).otherwise(0)) * 100.0 / F.count("*"),
            2,
        ).alias("on_time_pct"),
    )
    .withColumn("avg_dep_delay_min", F.lit(None).cast("double"))
    .withColumn("avg_arr_delay_min", F.lit(None).cast("double"))
    .withColumn("summary_type", F.lit("on_time_pct"))
    .withColumn("dimension_key", F.col("airline"))
)

# ---------------------------------------------------------------------------
# 3. Union all Gold aggregations into a single summary table
# ---------------------------------------------------------------------------
cols = ["summary_type", "dimension_key", "avg_dep_delay_min",
        "avg_arr_delay_min", "total_flights"]

df_gold = (
    avg_delay_airline.select(cols)
    .union(avg_delay_route.select(cols))
    .union(delayed_by_day.select(cols))
    .union(ontime_pct.select(cols))
    .withColumn("generated_ts", F.current_timestamp())
)

# ---------------------------------------------------------------------------
# 4. Write Gold Parquet
# ---------------------------------------------------------------------------
(
    df_gold
    .write
    .mode("overwrite")
    .partitionBy("summary_type")
    .parquet(gold_path)
)
print(f"[silver_to_gold] Wrote Gold Parquet → {gold_path}")

# ---------------------------------------------------------------------------
# 5. Load Gold into BigQuery (Spark BigQuery connector)
# ---------------------------------------------------------------------------
(
    df_gold
    .write
    .format("bigquery")
    .option("table",               BQ_TABLE)
    .option("temporaryGcsBucket",  TEMP_GCS_BUCKET)
    .mode("overwrite")
    .save()
)
print(f"[silver_to_gold] Loaded Gold summary → BigQuery table {BQ_TABLE}")
