import os, time, random
from datetime import datetime, timezone, timedelta
from kafka import KafkaProducer

BOOTSTRAP = os.environ.get("BOOTSTRAP_SERVERS", "kafka:9092")
TOPIC = os.environ.get("TOPIC", "energy_readings")
HOUSEHOLDS = int(os.environ.get("HOUSEHOLDS", "50"))
TICK_SECONDS = int(os.environ.get("TICK_SECONDS", "15"))
SPEEDUP = float(os.environ.get("SPEEDUP", "30"))
JITTER_PCT = float(os.environ.get("JITTER_PCT", "10"))

households = [f"H{str(i).zfill(3)}" for i in range(1, HOUSEHOLDS + 1)]

def base_kwh_at(ts: datetime) -> float:
    hour = ts.hour + ts.minute / 60
    if 6 <= hour < 9:
        return 0.03
    elif 17 <= hour < 22:
        return 0.05
    elif 12 <= hour < 14:
        return 0.035
    else:
        return 0.015

def jitter(x: float) -> float:
    span = x * (JITTER_PCT / 100.0)
    v = random.uniform(x - span, x + span)
    return max(0.0, v)

producer = KafkaProducer(
    bootstrap_servers=BOOTSTRAP,
    acks="all",
    linger_ms=10,
    value_serializer=lambda v: v.encode("utf-8"),
)

print(f"[producer] sending to {BOOTSTRAP} topic={TOPIC} households={HOUSEHOLDS}", flush=True)

event_time = datetime.now(timezone.utc).replace(microsecond=0)

while True:
    for hid in households:
        kwh = jitter(base_kwh_at(event_time))
        line = f"{event_time.isoformat()},{hid},{kwh:.5f}"  # CSV bez spacji
        producer.send(TOPIC, value=line)
    producer.flush()
    event_time += timedelta(seconds=TICK_SECONDS)
    time.sleep(max(0.01, TICK_SECONDS / SPEEDUP))
