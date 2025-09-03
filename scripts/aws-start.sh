#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# publiczny IP EC2 (metadata)
export PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)

# z override'em tylko jeśli chcesz łączyć się do Kafki z zewnątrz
if [[ -f docker-compose.aws.yml ]]; then
  docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build
else
  docker compose up -d --build
fi

docker compose ps
echo "Spark UI:  http://$PUBLIC_IP:4040"
echo "App UI:    http://$PUBLIC_IP:8501"
