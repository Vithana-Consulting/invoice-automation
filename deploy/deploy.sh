#!/bin/bash
# Run from the project root on the production VM.
# Pulls latest code, runs migrations, rebuilds, and restarts.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Pulling latest"
git fetch --prune
git checkout main
git pull --ff-only

echo "==> Building images"
docker compose -f docker-compose.prod.yml build

echo "==> Running Alembic migrations (against live DB)"
docker compose -f docker-compose.prod.yml run --rm backend \
  alembic upgrade head

echo "==> Restarting services"
docker compose -f docker-compose.prod.yml up -d

echo "==> Health check"
sleep 5
curl -fsS "https://${API_DOMAIN}/health" && echo "  OK" || {
  echo "FAIL — check 'docker compose -f docker-compose.prod.yml logs backend'"
  exit 1
}

echo "==> Done."
