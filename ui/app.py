import os, json, time, pandas as pd, streamlit as st
from kafka import KafkaConsumer

BOOTSTRAP = os.getenv("BOOTSTRAP_SERVERS", "kafka:9092")
ALERTS_TOPIC = os.getenv("ALERTS_TOPIC", "energy_alerts")
READINGS_TOPIC = os.getenv("READINGS_TOPIC", "energy_readings")
MAX_ROWS = int(os.getenv("MAX_ROWS", "2000"))

st.set_page_config(page_title="Smart Energy – Live", layout="wide")
st.title("⚡ Smart Energy – Live")

@st.cache_resource
def get_alerts_consumer():
    return KafkaConsumer(
        ALERTS_TOPIC,
        bootstrap_servers=BOOTSTRAP,
        auto_offset_reset="latest",
        enable_auto_commit=True,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        consumer_timeout_ms=800,
    )

@st.cache_resource
def get_readings_consumer():
    # readings są w CSV: timestamp,household_id,energy_kwh
    return KafkaConsumer(
        READINGS_TOPIC,
        bootstrap_servers=BOOTSTRAP,
        auto_offset_reset="latest",
        enable_auto_commit=True,
        value_deserializer=lambda v: v.decode("utf-8"),
        consumer_timeout_ms=800,
    )

with st.sidebar:
    st.markdown(f"**Kafka**: `{BOOTSTRAP}`")
    st.markdown(f"**Alerts topic**: `{ALERTS_TOPIC}`")
    st.markdown(f"**Readings topic**: `{READINGS_TOPIC}`")
    st.caption("Auto-refresh ~1s; buforujemy ostatnie rekordy.")

tab_alerts, tab_readings = st.tabs(["🚨 Alerts", "📈 Readings"])

alerts_consumer = get_alerts_consumer()
readings_consumer = get_readings_consumer()

alerts_buf, readings_buf = [], []
alert_ph = tab_alerts.empty()
read_ph = tab_readings.empty()
chart_ph = tab_readings.empty()

def readings_row(line: str):
    # oczekujemy: 2025-09-06T17:54:02+00:00,H001,0.05251
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 3:
        return None
    ts, hh, val = parts
    try:
        return {"timestamp": ts, "household_id": hh, "energy_kwh": float(val)}
    except Exception:
        return None

while True:
    # pull alerts
    for recs in alerts_consumer.poll(timeout_ms=400).values():
        for rec in recs:
            alerts_buf.append(rec.value)
    alerts_buf = alerts_buf[-MAX_ROWS:]

    # pull readings
    for recs in readings_consumer.poll(timeout_ms=400).values():
        for rec in recs:
            row = readings_row(rec.value)
            if row:
                readings_buf.append(row)
    readings_buf = readings_buf[-MAX_ROWS:]

    # render ALERTS
    if alerts_buf:
        df = pd.DataFrame(alerts_buf)
        cols = [c for c in ["household_id","window_start","window_end","kwh","rule","mode"] if c in df.columns]
        if cols:
            alert_ph.dataframe(df[cols].tail(60), use_container_width=True)
        else:
            alert_ph.info("Brak poprawnych kolumn w alertach (czekam na JSON).")
    else:
        alert_ph.info("Czekam na alerty… (upewnij się, że `ALERTS_CONSOLE=0` i Spark pisze do Kafki)")

    # render READINGS + mini-wykres
    if readings_buf:
        rdf = pd.DataFrame(readings_buf)
        read_ph.dataframe(rdf.tail(80), use_container_width=True)

        # prosty wykres: liczba odczytów / minuta
        try:
            r = rdf.copy()
            r["minute"] = r["timestamp"].str.slice(0,16)  # YYYY-MM-DDTHH:MM
            cnt = r.groupby("minute").size().reset_index(name="count").sort_values("minute")
            chart_ph.line_chart(cnt.set_index("minute"))
        except Exception:
            pass
    else:
        read_ph.info("Czekam na odczyty…")

    time.sleep(1)
