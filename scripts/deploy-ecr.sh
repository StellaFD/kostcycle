#!/usr/bin/env bash
# Run on the lab EC2 after .env and temporary AWS CLI credentials are configured.
# Usage: bash scripts/deploy-ecr.sh <version>
set -euo pipefail
cd "$(dirname "$0")/.."
version="${1:?Provide an immutable image version, for example v2}"
[[ "$version" =~ ^[a-zA-Z0-9_.-]+$ ]] || { echo 'Invalid image version'; exit 1; }
test -f .env || { echo 'Prepare .env first'; exit 1; }
test -f /etc/kostcycle-project || { echo 'Use a dedicated project EC2. Create /etc/kostcycle-project after verifying this is not the cafe lab server.'; exit 1; }
region="${AWS_DEFAULT_REGION:-us-east-1}"
account_id="$(aws sts get-caller-identity --query Account --output text)"
registry="$account_id.dkr.ecr.$region.amazonaws.com"
aws ecr get-login-password --region "$region" | sudo docker login --username AWS --password-stdin "$registry"
trap 'sudo docker logout "$registry" >/dev/null 2>&1 || true' EXIT
for service in catalog reservation; do
  sudo docker pull "$registry/kostcycle-$service:$version"
done
# Initialize once, before workers start. An optional administrator env file can
# provide DDL permissions while runtime accounts keep fewer privileges.
sudo docker run --rm --env-file "${INIT_ENV_FILE:-.env}" "$registry/kostcycle-catalog:$version" python -m app.bootstrap
sudo docker network inspect kostcycle >/dev/null 2>&1 || sudo docker network create kostcycle
# Keep stopped prior containers for rollback, rather than deleting them.
stamp="$(date +%Y%m%d%H%M%S)"
for service in catalog reservation; do
  if sudo docker inspect "kostcycle-$service" >/dev/null 2>&1; then
    sudo docker stop "kostcycle-$service" >/dev/null
    sudo docker rename "kostcycle-$service" "kostcycle-$service-backup-$stamp"
  fi
done
sudo docker run -d --name kostcycle-reservation --restart unless-stopped --network kostcycle \
  --env-file .env -e SERVICE=reservation "$registry/kostcycle-reservation:$version"
ready=0
for attempt in $(seq 1 30); do
  if sudo docker exec kostcycle-reservation python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)" 2>/dev/null; then ready=1; break; fi
  sleep 2
done
test "$ready" = 1 || { echo 'Reservation startup failed. Inspect docker logs.'; exit 1; }
sudo docker run -d --name kostcycle-catalog --restart unless-stopped --network kostcycle \
  --env-file .env -e SERVICE=catalog -e RESERVATION_URL=http://kostcycle-reservation:8000 \
  -p "${APP_BIND:-127.0.0.1}:${APP_PORT:-8080}:8000" "$registry/kostcycle-catalog:$version"
ready=0
for attempt in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${APP_PORT:-8080}/health"; then ready=1; break; fi
  sleep 2
done
test "$ready" = 1 || { echo 'Catalog startup failed. Inspect docker logs.'; exit 1; }
sudo docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
