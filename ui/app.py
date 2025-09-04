import os, json, time, threading
import pandas as pd
import streamlit as st
from kafka import KafkaConsumer

# --- ENV ---
BOOTSTRAP = os.getenv("BOOTSTRAP_SERVERS", "kafka:9092")
TOPIC = os.getenv("ALERTS_TOPIC", os.getenv("TOPIC", "energy_alerts"))
MAX_ROWS = int(os.getenv("MAX_ROWS", "5000"))

# --- UI ---
st.set_page_config(page_title="Smart Energy – Alerts", layout="wide")
st.title("⚡ Smart Energy – Alerty zużycia")
st.caption(f"Kafka: `{BOOTSTRAP}` • Topic: `{TOPIC}`")

@st.cache_resource(show_spinner=False)
def get_consumer():
    # stała grupa = stabilne offsety
    return KafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP,
        group_id="ui-dashboard",
        enable_auto_commit=True,
        auto_offset_reset="latest",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        key_deserializer=lambda k: k.decode("utf-8") if k else None,
        consumer_timeout_ms=1000,
    )

consumer = get_consumer()

# stan
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(columns=["ts","household_id","kwh","rule","mode"])
lock = threading.Lock()

def poll_loop():
    while True:
        try:
            pack = consumer.poll(timeout_ms=500)
            rows = []
            for _, recs in pack.items():
                for rec in recs:
                    val = rec.value or {}
                    try:
                        ts_raw = val.get("window_end") or val.get("window_start")
                        ts = pd.to_datetime(ts_raw, utc=True)
                        rows.append({
                            "ts": ts,
                            "household_id": val.get("household_id"),
                            "kwh": float(val.get("kwh", 0.0)),
                            "rule": val.get("rule"),
                            "mode": val.get("mode"),
                        })
                    except Exception:
                        continue
            if rows:
                with lock:
                    df = pd.concat([st.session_state.df, pd.DataFrame(rows)], ignore_index=True)
                    if len(df) > MAX_ROWS:
                        df = df.iloc[-MAX_ROWS:]
                    st.session_state.df = df
        except Exception:
            time.sleep(1)

# start czytnika 1x
if "poll_started" not in st.session_state:
    threading.Thread(target=poll_loop, daemon=True).start()
    st.session_state.poll_started = True

with st.sidebar:
    st.subheader("Ustawienia")
    st.write(f"**BOOTSTRAP_SERVERS**: `{BOOTSTRAP}`")
    st.write(f"**ALERTS_TOPIC**: `{TOPIC}`")
    st.write(f"**MAX_ROWS**: `{MAX_ROWS}`")
    st.caption("Dane odświeżają się w tle; UI odświeża się co ~1 s.")

placeholder_kpi = st.empty()
placeholder_chart = st.empty()
placeholder_table = st.empty()

def render():
    with lock:
        df = st.session_state.df.copy()

    now = pd.Timestamp.utcnow()
    df5 = df[df["ts"] >= (now - pd.Timedelta(minutes=5))]
    df15 = df[df["ts"] >= (now - pd.Timedelta(minutes=15))]

    k1,k2,k3,k4 = placeholder_kpi.columns(4)
    k1.metric("Alerts (5 min)", f"{len(df5):,}")
    k2.metric("Unikalne gospodarstwa (5 min)", f"{df5['household_id'].nunique():,}" if len(df5) else "0")
    k3.metric("Średnie kWh (5 min)", f"{df5['kwh'].mean():.3f}" if len(df5) else "—")
    k4.metric("Ostatni event (UTC)", df["ts"].max().strftime("%Y-%m-%d %H:%M:%S") if len(df) else "—")

    placeholder_chart.subheader("Suma kWh / min (ostatnie 15 min)")
    if len(df15):
        series = (df15.set_index("ts").sort_index().resample("1min")["kwh"].sum()
                  .rename("sum_kwh").reset_index().set_index("ts"))
        placeholder_chart.line_chart(series)
    else:
        placeholder_chart.info("Brak danych do wykresu jeszcze…")

    if len(df):
        cols = ["ts","household_id","kwh","rule","mode"]
        placeholder_table.subheader("Ostatnie alerty (200)")
        placeholder_table.dataframe(df.sort_values("ts").tail(200)[cols], use_container_width=True)
    else:
        placeholder_table.empty()

while True:
    render()
    time.sleep(1)
