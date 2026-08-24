#!/usr/bin/env bash
set -euo pipefail

# deploy.sh — pull images from GHCR and restart docker-compose services
# Usage: GHCR_TOKEN=<token> ./scripts/deploy.sh [deploy_path]
# If DEPLOY_PATH not provided, uses ./ (current dir).

DEPLOY_PATH=${1:-.}
COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.prod.yml}
GHCR_USER=${GHCR_USER:-${GITHUB_ACTOR:-""}}
GHCR_TOKEN=${GHCR_TOKEN:-""}

if [ -z "$GHCR_TOKEN" ]; then
  echo "GHCR_TOKEN missing. Export GHCR_TOKEN in environment or CI secret." >&2
  exit 2
fi

echo "Deploy path: $DEPLOY_PATH"
cd "$DEPLOY_PATH"

# Login to GHCR
echo "Logging in to ghcr.io as ${GHCR_USER:-'<owner>'}..."
echo "$GHCR_TOKEN" | docker login ghcr.io -u "${GHCR_USER}" --password-stdin

# Pull images (ignore errors for missing images)
docker compose -f "$COMPOSE_FILE" pull || true

# Bring services up
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans

# Basic health checks: wait for API to respond
API_URL=${API_URL:-http://localhost:8000/health}
RETRIES=12
SLEEP=5
for i in $(seq 1 $RETRIES); do
  echo "Checking health ($i/$RETRIES): $API_URL"
  if curl -fsS "$API_URL" >/dev/null 2>&1; then
    echo "API healthy"
    exit 0
  fi
  sleep $SLEEP
done

echo "Warning: API did not become healthy after $((RETRIES*SLEEP))s" >&2
exit 1
