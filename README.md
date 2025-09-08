# Smart Energy Consumption Monitor

**Autorzy:** Łukasz Kubik 193178 & Nikodem Kozak 193388 (ACiR KSD)

> System do strumieniowego monitoringu zużycia energii: **Producer → Kafka → Spark (Structured Streaming) → Kafka (alerty) → Streamlit UI**. Uruchamiane jednym `docker compose` na **AWS EC2** (lub lokalnie).

---

## Spis treści

* [1) Cel i zakres](#1-cel-i-zakres)
* [2) Strategia i architektura](#2-strategia-i-architektura)
* [3) Technologie i deployment](#3-technologie-i-deployment)
* [4) Struktura repo i odpowiedzialności](#4-struktura-repo-i-odpowiedzialności)
* [5) Kluczowe mechanizmy i funkcje](#5-kluczowe-mechanizmy-i-funkcje)
* [6) Uruchomienie na AWS EC2 (krok po kroku)](#6-uruchomienie-na-aws-ec2-krok-po-kroku)
* [7) Przełączanie trybu demo/prod](#7-przełączanie-trybu-demoprod)
* [8) Co pokazać na prezentacji + miejsce na wykresy](#8-co-pokazać-na-prezentacji--miejsce-na-wykresy)
* [9) Rozwiązywanie problemów (FAQ/Troubleshooting)](#9-rozwiązywanie-problemów-faqtroubleshooting)
* [10) Sugestie rozwoju](#10-sugestie-rozwoju)
* [11) Ściągawka komend](#11-ściągawka-komend)

---

## 1) Cel i zakres

**Cel:** zbudować działający system *streamingowy*, który:

* generuje syntetyczne **odczyty zużycia energii** dla wielu gospodarstw,
* transportuje je przez **Apache Kafka**,
* wykrywa **alerty** w **Apache Spark Structured Streaming** (przekroczenia progu w oknach czasowych),
* publikuje alerty do Kafki i **prezentuje je w UI (Streamlit)**.

**Wymagania funkcjonalne:**

* Strumień wejściowy: `timestamp,household_id,energy_kwh`.
* Agregacja okienna i próg (sumaryczne kWh > próg).
* Dwa tryby:

  * **demo** – okno 1 min, próg `0.05 kWh` (dużo alertów),
  * **prod** – okno 15 min, próg `2.0 kWh` (realistycznie, alerty głównie w szczytach).
* Wizualizacja odczytów i alertów w czasie rzeczywistym.
* Uruchamianie na **AWS EC2** z **Docker Compose**.

---

## 2) Strategia i architektura

**Architektura:**

1. **Producer (Python)** – symuluje odczyty w CSV (bez spacji):
   `YYYY-MM-DDTHH:MM:SSZ,HXYZ,0.01234`
   Zmienność dobową (szczyty, południe, noc) + **jitter**.

2. **Kafka** – 2 tematy:

   * `energy_readings` (wejściowy),
   * `energy_alerts` (wyjściowy, JSON z opisem alertu).

3. **Spark Structured Streaming** – parsuje CSV, nakłada **watermark (10 min)**, liczy sumę kWh w **oknach czasowych** i filtruje przekroczenia progu → zapis do Kafki (alerty JSON).

4. **UI (Streamlit)** – 2 konsumenty Kafki: odczyty i alerty; podgląd „na żywo”.

**Dlaczego okna/progi?**
Okna wygładzają szum, agregują sygnał w sensownym horyzoncie (minuty). Dwa tryby umożliwiają zarówno szybki pokaz (demo), jak i realistyczną pracę (prod).

---

## 3) Technologie i deployment

* **Docker Compose** uruchamia:

  * `kafka` (bitnami/kafka:3.7),
  * `spark-master`, `spark-worker`, `spark-submit` (Apache Spark 3.5.1),
  * `producer` (Python 3.11, kafka-python),
  * `ui` (Streamlit + kafka-python + pandas).
* **AWS EC2** (Ubuntu 24.04): dostęp do UI poprzez **tunel SSH** (forwarding portów), bez wystawiania UI publicznie.

---

## 4) Struktura repo i odpowiedzialności

```
Smart-Energy-Consumption-Monitor/
├─ docker-compose.yml
├─ .env.example            # skopiuj do .env i ustaw RUN_MODE=demo|prod itd.
│
├─ producer/
│  ├─ Dockerfile
│  └─ simulator.py         # generator odczytów CSV → Kafka: energy_readings
│
├─ spark/
│  └─ stream.py            # Spark job: CSV→parse→window→sum→alerty→Kafka
│
└─ ui/
   ├─ Dockerfile
   └─ app.py               # Streamlit: podgląd odczytów i alertów (Kafka)
```

### Producer — `producer/simulator.py`

* Generuje **H001..H{N}** co `TICK_SECONDS` w czasie **event time**.
* Model dobowy (`base_kwh_at`) + **jitter** (losowy rozrzut).
* ENV:

  * `BOOTSTRAP_SERVERS` (domyślnie `kafka:9092`)
  * `TOPIC=energy_readings`
  * `HOUSEHOLDS=50`, `TICK_SECONDS=15`, `SPEEDUP=30`, `JITTER_PCT=10`

### Spark — `spark/stream.py`

* **Parse CSV** → `event_time`, `household_id`, `energy_kwh` + **watermark 10 min**.
* **Okna**: `window(event_time, WINDOW_DURATION, SLIDE_DURATION)`

  * demo: `1 minute` / `15 seconds` / próg `0.05`
  * prod: `15 minutes` / `15 seconds` / próg `2.0`
* **Alerty**: `kwh_window > THRESHOLD_KWH` → JSON → topic `energy_alerts`.
* **Checkpointy**: `CHECKPOINT_ROOT=/tmp/chk/<namespace>`.

  > Zmiana trybu/próg → **wyczyść checkpointy** (patrz sekcja 7).

### UI — `ui/app.py`

* Konsument `READINGS_TOPIC` (CSV) i `ALERTS_TOPIC` (JSON).
* Odświeżanie \~1 s, paginacja do `MAX_ROWS`.
* ENV: `BOOTSTRAP_SERVERS`, `READINGS_TOPIC`, `ALERTS_TOPIC`, `MAX_ROWS`.

---

## 5) Kluczowe mechanizmy i funkcje

* **Watermark (10 min)** – tolerancja opóźnień, kontrola rozmiaru stanu.
* **Okna czasowe + slide** – sumaryczne kWh w horyzoncie, mniejsza podatność na szum.
* **Dwa tryby** – *demo* do prezentacji i *prod* do realistycznych alertów.
* **Checkpointing** – wznawialność strumienia, spójność offsetów.
* **Separacja odpowiedzialności** – generator / transport / analiza / prezentacja.

---

## 6) Uruchomienie na AWS EC2 (krok po kroku)

> **Założenia:** Ubuntu 24.04, Docker + Compose zainstalowane, Security Group ma otwarty **port 22** (SSH).

1. **Klon i konfiguracja**

```bash
git clone https://github.com/kjubig/Smart-Energy-Consumption-Monitor.git
cd Smart-Energy-Consumption-Monitor
cp .env.example .env
# Ustaw tryb:
# RUN_MODE=demo  # gęste alerty do prezentacji
# RUN_MODE=prod  # realistycznie (alerty głównie w szczytach)
```

2. **Start usług**

```bash
docker compose up -d --build kafka spark-master spark-worker producer spark-submit ui
```

3. **Weryfikacja**

```bash
docker compose ps
docker compose logs -f ui     # powinno wypisać: URL: http://0.0.0.0:8501
```

4. **Tunel SSH z własnego komputera (Windows PowerShell)**

```powershell
ssh -o IdentitiesOnly=yes -i "C:\ścieżka\do\klucza.pem" `
    -L 8501:localhost:8501 `
    -L 8080:localhost:8080 `
    -L 4040:localhost:4040 `
    ubuntu@PUBLICZNE_IP_EC2
```

5. **Otwórz w przeglądarce**

* UI: `http://localhost:8501`
* Spark Master UI: `http://localhost:8080`
* Spark Job UI (gdy aktywny): `http://localhost:4040`

6. **Sanity check (na EC2)**

```bash
# Czy lecą odczyty?
docker compose exec kafka bash -lc \
  "/opt/bitnami/kafka/bin/kafka-console-consumer.sh \
   --bootstrap-server kafka:9092 --topic energy_readings \
   --group sanity-rd --timeout-ms 6000" | head

# Czy pojawiają się alerty?
docker compose exec kafka bash -lc \
  "/opt/bitnami/kafka/bin/kafka-console-consumer.sh \
   --bootstrap-server kafka:9092 --topic energy_alerts \
   --group sanity-alerts --timeout-ms 6000" | head
```

> **Uwaga:** W **prod** alerty naturalnie pojawią się głównie w godzinach szczytu (rana/wieczór) — w *demo* są praktycznie od razu.

---

## 7) Przełączanie trybu demo/prod

Zmiany `RUN_MODE`, okna/progu **wymagają wyczyszczenia checkpointów**, aby Spark nie kontynuował starego stanu.

```bash
# zatrzymaj i usuń job
docker compose stop spark-submit
docker compose rm -f spark-submit

# wyczyść checkpointy
docker run --rm -v /tmp:/tmp alpine sh -c 'rm -rf /tmp/chk/* || true'

# uruchom ponownie job (z buildem jeśli zmieniałeś kod)
docker compose up -d --build spark-submit

# opcjonalnie: upewnij się w logach, że reguła/tryb się zmieniły:
docker compose logs --tail=200 spark-submit | egrep -m1 '"rule"|\"mode\"'
# oczekuj np.: "rule":"kwh>2.0 over 15 minutes", "mode":"prod"
```

**UI pokazuje „stare” alerty?** Zresetuj offset grupy konsumenckiej UI i zrestartuj UI:

```bash
docker compose exec kafka bash -lc '
/opt/bitnami/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server kafka:9092 \
  --group ui-streamlit \
  --topic energy_alerts \
  --reset-offsets --to-latest --execute'
docker compose restart ui
```

---

## 8) Co pokazać na prezentacji + miejsce na wykresy

**Minimum demonstracyjne:**

* UI (Streamlit) – **odczyty** na żywo.
* UI – **alerty** (w *demo* od razu; w *prod* w szczytach).

**Dodatkowe pomysły (opcjonalnie):**

* Wykres liniowy sumy kWh w oknie dla wybranego `household_id`.
* „Top N” gospodarstw z największą liczbą alertów (agregacja z logów/eksportu).
* Heatmapa `godzina × gospodarstwo` (liczba alertów/suma kWh).

**Miejsce na grafiki (wklej screeny):**

### 📊 Wykres 1: Strumień odczytów (sample)

*(tu wklej screen lub wykres)*

### 🚨 Wykres 2: Alerty w czasie (demo)

*(tu wklej screen lub wykres)*

### 📈 Wykres 3: Alerty w prod (szczyty)

*(tu wklej screen lub wykres)*

---

## 9) Rozwiązywanie problemów (FAQ/Troubleshooting)

**Kafka „unhealthy” / restart środowiska**

```bash
docker compose down -v --remove-orphans
docker network prune -f
docker compose up -d --build kafka
# po kilku sekundach: reszta usług
```

**Brak alertów w prod**
To **normalne poza szczytem**. Na pokaz:

* przełącz `RUN_MODE=demo` **(i wyczyść checkpointy)**, **albo**
* tymczasowo obniż próg (np. `THRESHOLD_KWH=1.0`) w kodzie i przebuduj job.

**UI pokazuje stare dane**
Zresetuj offset grupy UI (sekcja 7) i zrestartuj `ui`.

**Zmieniłem tryb, ale w logach dalej „demo”**
Nie zostały wyczyszczone checkpointy lub job wstał ze starym stanem. Wykonaj kroki z sekcji 7.

**Dostęp do UI z zewnątrz**
Zalecany **tunel SSH**. Nie wystawiaj portu 8501 publicznie.

---

## 10) Sugestie rozwoju

* **Walidacja schematu** (pydantic / schema registry) dla twardszej kontroli jakości danych.
* **Trwała persystencja alertów** (np. S3/Parquet) i dashboard (Superset/Grafana).
* **Metryki Prometheus/Grafana** – lag konsumentów, throughput, metryki joba.
* **Bardziej zaawansowana detekcja** – odchylenie od profilu per gospodarstwo, progi dynamiczne.
* **Obsługa błędnych rekordów** – DLQ (dead-letter topic) dla nieparsowalnych wpisów.

---

## 11) Ściągawka komend

```bash
# start całości
docker compose up -d --build kafka spark-master spark-worker producer spark-submit ui

# status i logi
docker compose ps
docker compose logs -f spark-submit
docker compose logs -f ui

# sanity: tematy i szybkie sprawdzenie strumieni
docker compose exec kafka bash -lc "/opt/bitnami/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list"

docker compose exec kafka bash -lc "/opt/bitnami/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:9092 --topic energy_readings --group sanity-rd --timeout-ms 6000" | head

docker compose exec kafka bash -lc "/opt/bitnami/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:9092 --topic energy_alerts --group sanity-alerts --timeout-ms 6000" | head

# przełączenie trybu/progu (wyczyść checkpointy!)
docker compose stop spark-submit && docker compose rm -f spark-submit
docker run --rm -v /tmp:/tmp alpine sh -c 'rm -rf /tmp/chk/* || true'
docker compose up -d --build spark-submit

# reset offsetu grupy UI i restart
docker compose exec kafka bash -lc '
/opt/bitnami/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server kafka:9092 \
  --group ui-streamlit \
  --topic energy_alerts \
  --reset-offsets --to-latest --execute'
docker compose restart ui
```

---

**Podsumowanie:**
System *end-to-end* działa: **Producer → Kafka → Spark → Kafka (alerty) → UI**. Tryb **demo** ułatwia prezentację (dużo zdarzeń), a **prod** odwzorowuje realistyczne zachowanie (alerty głównie w szczytach). Instrukcje powyżej obejmują uruchamianie, przełączanie trybu, diagnostykę i typowe naprawy.
