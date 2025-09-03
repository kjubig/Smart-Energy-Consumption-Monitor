import os
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, from_csv, to_timestamp, window, sum as _sum, lit, trim, to_json, struct
)

# --- Konfiguracja przez ENV ---
RUN_MODE         = os.getenv("RUN_MODE", "demo").lower()          # "demo" | "prod"
KAFKA_BOOTSTRAP  = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
SOURCE_TOPIC     = os.getenv("SOURCE_TOPIC", "energy_readings")
ALERTS_TOPIC     = os.getenv("ALERTS_TOPIC", "energy_alerts")
DEBUG_PARSED     = os.getenv("DEBUG_PARSED", "0") == "1"

# Gdzie trzymać checkpointy (domyślnie /tmp/chk, bo zawsze zapisywalne)
CHECKPOINT_ROOT  = os.getenv("CHECKPOINT_ROOT", "/tmp/chk")

if RUN_MODE == "prod":
    STARTING_OFFSETS = "latest"
    WINDOW_DURATION  = "15 minutes"
    SLIDE_DURATION   = "15 seconds"
    THRESHOLD_KWH    = 2.0
    CKP_NS           = "energy_stream_prod_v1"
else:
    STARTING_OFFSETS = "earliest"
    WINDOW_DURATION  = "1 minute"
    SLIDE_DURATION   = "15 seconds"
    THRESHOLD_KWH    = 0.05
    CKP_NS           = "energy_stream_demo_v2"

def ckp(subdir: str) -> str:
    # /tmp/chk/<namespace>/<subdir>
    return os.path.join(CHECKPOINT_ROOT, CKP_NS, subdir)

# --- Spark ---
spark = (
    SparkSession.builder.appName("smart-energy-stream")
    .config("spark.sql.session.timeZone", "UTC")
    .getOrCreate()
)
spark.sparkContext.setLogLevel("INFO")

# --- Źródło: Kafka -> STRING ---
raw = (
    spark.readStream.format("kafka")
    .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP)
    .option("subscribe", SOURCE_TOPIC)
    .option("startingOffsets", STARTING_OFFSETS)
    .option("failOnDataLoss", "false")
    .load()
    .selectExpr("CAST(value AS STRING) AS value")
)

# --- Parsowanie CSV (tolerancja spacji, timestamp z XXX) ---
parsed = (
    raw.select(
        from_csv(
            col("value"),
            "timestamp string,household_id string,energy_kwh double",
            {"ignoreLeadingWhiteSpace": "true", "ignoreTrailingWhiteSpace": "true"}
        ).alias("r")
    )
    .select(
        to_timestamp(col("r.timestamp"), "yyyy-MM-dd'T'HH:mm:ssXXX").alias("event_time"),
        trim(col("r.household_id")).alias("household_id"),
        col("r.energy_kwh").alias("energy_kwh"),
    )
    .where(col("event_time").isNotNull())
    .withWatermark("event_time", "10 minutes")
)

if DEBUG_PARSED:
    (parsed.writeStream.format("console").outputMode("append")
        .option("truncate", "false").option("numRows", "20")
        .option("checkpointLocation", ckp("dbg_parsed"))
        .start())

# --- Agregacja okienna ---
agg = (
    parsed
    .groupBy(window(col("event_time"), WINDOW_DURATION, SLIDE_DURATION), col("household_id"))
    .agg(_sum("energy_kwh").alias("kwh_window"))
)

# --- Alerty ---
alerts = (
    agg.where(col("kwh_window") > lit(THRESHOLD_KWH))
       .select(
           col("household_id").cast("string").alias("key"),
           to_json(struct(
               col("household_id").alias("household_id"),
               col("window").getField("start").cast("string").alias("window_start"),
               col("window").getField("end").cast("string").alias("window_end"),
               col("kwh_window").alias("kwh"),
               lit(f"kwh>{THRESHOLD_KWH} over {WINDOW_DURATION}").alias("rule"),
               lit(RUN_MODE).alias("mode")
           )).alias("value")
       )
)

# --- Sinki ---
# 1) Konsola z agregatami (diagnostyka)
(agg.select(
    col("household_id"),
    col("window").getField("start").cast("string").alias("window_start"),
    col("window").getField("end").cast("string").alias("window_end"),
    col("kwh_window")
).writeStream.format("console").outputMode("update")
 .option("truncate", "false").option("numRows", "50")
 .option("checkpointLocation", ckp("console"))
 .start())

# 2) Kafka z alertami
(alerts.writeStream.format("kafka")
 .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP)
 .option("topic", ALERTS_TOPIC)
 .option("checkpointLocation", ckp("alerts"))
 .outputMode("append")
 .start())

# (opcjonalnie) echo alertów do konsoli (ustaw ALERTS_CONSOLE=1)
if os.getenv("ALERTS_CONSOLE", "0") == "1":
    (alerts.selectExpr("CAST(value AS STRING) AS json")
     .writeStream.format("console").outputMode("append")
     .option("truncate", "false").option("numRows", "50")
     .option("checkpointLocation", ckp("alerts_console"))
     .start())

spark.streams.awaitAnyTermination()
