# Databricks notebook: Silver → Gold (Curated Layer)
# Stage: INTEGRATED (Silver) → CURATED / AGGREGATED (Gold)
#
# Reads the cleaned Silver Delta table, computes business-level aggregations,
# and writes a Gold summary Delta table (Serverless-compatible).

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

spark = SparkSession.builder.getOrCreate()

# ---------------------------------------------------------------------------
# Unity Catalog tables (Serverless-compatible)
# ---------------------------------------------------------------------------
SILVER_TABLE = "workspace.aviation.silver_flights"
GOLD_TABLE   = "workspace.aviation.gold_flight_summary"

# ---------------------------------------------------------------------------
# 1. Read Silver
# ---------------------------------------------------------------------------
df_silver = spark.table(SILVER_TABLE)

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
# 4. Write Gold Delta table
# ---------------------------------------------------------------------------
(
    df_gold
    .write
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(GOLD_TABLE)
)
print(f"[silver_to_gold] ✓ Wrote Gold summary → {GOLD_TABLE}")

# ---------------------------------------------------------------------------
# NOTE: BigQuery export removed — the Spark BigQuery connector requires GCS
# staging (temporaryGcsBucket) which is not accessible from Serverless.
# To export to BigQuery, use a Databricks Lakehouse Federation connection
# or a scheduled job on a classic cluster with GCS credentials.
# ---------------------------------------------------------------------------