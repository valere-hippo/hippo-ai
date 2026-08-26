#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env.gpu"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.gpu.yml"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE"
  echo "Create it from .env.gpu.example and set a strong VLLM_API_KEY/WHISPER_API_KEY."
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

mkdir -p \
  "${HIPPO_GPU_DATA_DIR}/huggingface" \
  "${HIPPO_GPU_DATA_DIR}/vllm-cache"

cd "$ROOT_DIR"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" pull
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d

echo
sleep 5
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
