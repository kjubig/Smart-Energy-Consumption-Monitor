# aws-start.sh
export PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)
docker compose --env-file .env \
  -f docker-compose.yml -f docker-compose.aws.yml up -d --build
