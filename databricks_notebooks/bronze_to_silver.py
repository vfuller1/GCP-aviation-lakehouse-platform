# Databricks notebook: Bronze to Silver transformation
# Reads raw data from bronze bucket, cleans/transforms, writes to silver bucket

from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()

bronze_path = "gs://gcp-lakehouseproject-bronze/aviation_sample.csv"
silver_path = "gs://gcp-lakehouseproject-silver/aviation_sample_cleaned.parquet"

df = spark.read.option("header", True).csv(bronze_path)
# Example transformation: filter out flights with < 130 passengers
df_clean = df.filter(df.passenger_count >= 130)
df_clean.write.mode("overwrite").parquet(silver_path)
