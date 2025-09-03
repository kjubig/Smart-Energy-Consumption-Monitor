#!/usr/bin/env bash
set -euo pipefail
BOOT=${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}
TOPIC_IN=${TOPIC_INPUT:-energy_readings}
TOPIC_OUT=${TOPIC_ALERTS:-energy_alerts}

docker exec -it $(docker ps -qf name=kafka) \
  /opt/bitnami/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 \
  --create --if-not-exists --topic "$TOPIC_IN" --partitions 1 --replication-factor 1

docker exec -it $(docker ps -qf name=kafka) \
  /opt/bitnami/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 \
  --create --if-not-exists --topic "$TOPIC_OUT" --partitions 1 --replication-factor 1
