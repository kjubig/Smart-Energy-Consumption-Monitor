import os, json, time, threading
from datetime import timedelta
import pandas as pd
import streamlit as st
from kafka import KafkaConsumer

# --- ENV ---
BOOTSTRAP = os.getenv("BOOTSTRAP_SERVERS", "kafka:9092")
TOPIC = os.getenv("ALERTS_TOPIC", os.getenv("TOPIC", "energy_alerts"))
MAX_ROWS = int(os.getenv("MAX_ROWS", "5000"))

# --- UI setup ---
st.set_page_config(page_title="Energy Alerts Dashboard", layout="wide")
st.title("⚡ Smart Energy – Alerty zużycia")
st.caption(f"Kafka: `{BOOTSTRAP}` • Topic: `{TOPIC}`")

# --- Kafka consumer (cache = 1 instancja na proces) ---
@st.cache_resource(show_spinner=False)
def get_consumer():
    return KafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP,
        group_id="dashboard",                # spójna grupa = stabilne offsety
        enable_auto_commit=True,
        auto_offset_reset="latest",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        key_deserializer=lambda k: k.decode("utf-8") if k else None,
        consumer_timeout_ms=1000,            # nie blokuj niekończąco
    )

consumer = get_consumer()

# --- Stan aplikacji ---
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(columns=["ts","household_id","kwh","rule","mode"])

lock = threading.Lock()

def poll_loop():
    """Czytaj w pętli z Kafki i aktualizuj bufor DataFrame."""
    while True:
        try:
            msgs = consumer.poll(timeout_ms=500)
            if not msgs:
                time.sleep(0.2)
                continue

            rows = []
            for _, batch in msgs.items():
                for msg in batch:
                    val = msg.value or {}
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
                        # pomiń wadliwe rekordy
                        continue

            if rows:
                with lock:
                    df = pd.concat([st.session_state.df, pd.DataFrame(rows)], ignore_index=True)
                    # ogranicz rozmiar bufora
                    if len(df) > MAX_ROWS:
                        df = df.iloc[-MAX_ROWS:]
                    st.session_state.df = df
        except Exception:
            # w razie chwilowych błędów połączenia – krótki backoff
            time.sleep(1)

# uruchom czytnik 1x
if "poll_thread" not in st.session_state:
    t = threading.Thread(target=poll_loop, daemon=True)
    t.start()
    st.session_state.poll_thread = True

# --- Sidebar/Info ---
with st.sidebar:
    st.subheader("Ustawienia")
    st.write(f"**BOOTSTRAP_SERVERS**: `{BOOTSTRAP}`")
    st.write(f"**ALERTS_TOPIC**: `{TOPIC}`")
    st.write(f"**MAX_ROWS**: `{MAX_ROWS}`")
    st.caption("Dane odświeżają się w tle, UI rerenderuje się co ~1s.")

# --- Widok główny ---
placeholder_kpi = st.empty()
placeholder_chart = st.empty()
placeholder_table = st.empty()

def render():
    with lock:
        df = st.session_state.df.copy()

    now_utc = pd.Timestamp.utcnow()
    last_5m = now_utc - pd.Timedelta(minutes=5)
    last_15m = now_utc - pd.Timedelta(minutes=15)

    df_5m = df[df["ts"] >= last_5m]
    df_15m = df[df["ts"] >= last_15m]

    # KPI
    k1,k2,k3,k4 = placeholder_kpi.columns(4)
    k1.metric("Alerts (5 min)", f"{len(df_5m):,}")
    k2.metric("Unikalne gospodarstwa (5 min)", f"{df_5m['household_id'].nunique():,}" if len(df_5m) else "0")
    k3.metric("Średnie kWh (5 min)", f"{df_5m['kwh'].mean():.3f}" if len(df_5m) else "—")
    k4.metric("Ostatni event (UTC)", df["ts"].max().strftime("%Y-%m-%d %H:%M:%S") if len(df) else "—")

    # Wykres: suma kWh / minuta (ostatnie 15 min)
    if len(df_15m):
        s = (df_15m
             .set_index("ts")
             .sort_index()
             .resample("1min")["kwh"].sum()
             .reset_index())
        s.rename(columns={"ts": "minute", "kwh": "sum_kwh"}, inplace=True)
        placeholder_chart.subheader("Suma kWh / min (ostatnie 15 min)")
        placeholder_chart.line_chart(s.set_index("minute"))
    else:
        placeholder_chart.subheader("Suma kWh / min (ostatnie 15 min)")
        placeholder_chart.info("Brak danych do wykresu jeszcze…")

    # Tabela: ostatnie 200
    if len(df):
        cols = ["ts","household_id","kwh","rule","mode"]
        placeholder_table.subheader("Ostatnie alerty (200)")
        placeholder_table.dataframe(df.sort_values("ts").tail(200)[cols], use_container_width=True)
    else:
        placeholder_table.empty()

# proste auto-odświeżanie UI
while True:
    render()
    time.sleep(1)
