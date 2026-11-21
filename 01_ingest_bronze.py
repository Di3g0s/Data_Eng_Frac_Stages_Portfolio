# Databricks notebook source
# TEMPLATE: edit these four identifiers and create/choose a volume first.
# This notebook has NOT been executed in your Databricks workspace.
CATALOG = "main"
SCHEMA = "frac_demo"
VOLUME = "landing"
INPUT_SUBDIR = "wits"

# COMMAND ----------
from pyspark.sql import functions as F
from pyspark.sql.types import MapType, StringType, StructField, StructType

spark.conf.set("spark.sql.session.timeZone", "UTC")
ROOT = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
INPUT = f"{ROOT}/{INPUT_SUBDIR}"
# Keep the same checkpoint across reruns of THIS source/table pipeline.
CHECKPOINT = f"{ROOT}/_checkpoints/bronze_wits_raw"
TABLE = f"{CATALOG}.{SCHEMA}.bronze_wits_raw"

schema = StructType([
    StructField(name, StringType(), True) for name in [
        "envelope_version", "receipt_id", "received_at_utc", "replay_run_id",
        "connection_id", "raw_frame_b64", "raw_text", "raw_sha256", "parse_error"
    ]
] + [StructField("fields", MapType(StringType(), StringType()), True)])

incoming = (spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "json")
    .option("pathGlobFilter", "*.jsonl")
    .option("rescuedDataColumn", "_rescued_data")
    .schema(schema)
    .load(INPUT)
    .withColumn("landing_file", F.col("_metadata.file_path"))
    .withColumn("ingested_at_utc", F.current_timestamp()))

query = (incoming.writeStream.format("delta")
    .option("checkpointLocation", CHECKPOINT)
    .trigger(availableNow=True)
    .toTable(TABLE))
query.awaitTermination()

# COMMAND ----------
# Observe receipt counts and parsing quality. These are NOT deduplicated samples.
display(spark.table(TABLE).groupBy("replay_run_id", "parse_error").count())
