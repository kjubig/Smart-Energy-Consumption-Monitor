import os, json, time
import pandas as pd
import streamlit as st
from kafka import KafkaConsumer

BOOTSTRAP = os.getenv("BOOTSTRAP_SERVERS", "kafka:9092")
TOPIC = os.getenv("ALERTS_TOPIC", "energy_alerts")

st.set_page_config(page_title="Smart Energy Alerts", layout="wide")
st.title("⚡ Smart Energy – Alerty zużycia")

@st.cache_resource
def get_consumer():
    return KafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP,
        auto_offset_reset="latest",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        consumer_timeout_ms=1000,
    )

consumer = get_consumer()
placeholder = st.empty()
buf = []

info = st.sidebar.container()
info.markdown(f"""
**Kafka**: `{BOOTSTRAP}`  
**Topic**: `{TOPIC}`  
""")

st.caption("Strumień odświeża się co ~1s. Pokazujemy ostatnie 200 rekordów.")
while True:
    # pobierz paczkę rekordów (bez blokowania na zawsze)
    msg_pack = consumer.poll(timeout_ms=500)
    for recs in msg_pack.values():
        for rec in recs:
            buf.append(rec.value)
    buf = buf[-200:]

    if buf:
        df = pd.DataFrame(buf)
        # kolumny w przyjaznej kolejności
        cols = ["household_id","window_start","window_end","kwh","rule","mode"]
        df = df[[c for c in cols if c in df.columns]]
        placeholder.dataframe(df.tail(50), use_container_width=True)
    time.sleep(1)
