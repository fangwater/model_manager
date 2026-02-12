#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"
mkdir -p logs

WEB_HOST="${MODEL_MANAGER_HTTP_HOST:-}"
WEB_PORT="${MODEL_MANAGER_HTTP_PORT:-}"
GRPC_PORT="${MODEL_MANAGER_GRPC_PORT:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --web-host)
      WEB_HOST="${2:-}"
      shift 2
      ;;
    --web-port)
      WEB_PORT="${2:-}"
      shift 2
      ;;
    *)
      echo "[ERROR] Unknown argument: $1" >&2
      echo "Usage: ./start.sh [--web-host HOST] [--web-port PORT]" >&2
      exit 2
      ;;
  esac
done

WEB_HOST="${WEB_HOST:-0.0.0.0}"
WEB_PORT="${WEB_PORT:-6300}"
GRPC_PORT="${GRPC_PORT:-13001}"

export MODEL_MANAGER_HTTP_HOST="${WEB_HOST}"
export MODEL_MANAGER_HTTP_PORT="${WEB_PORT}"
export MODEL_MANAGER_GRPC_PORT="${GRPC_PORT}"

if ! command -v pm2 >/dev/null 2>&1; then
  echo "[ERROR] pm2 is not installed. Please install pm2 first." >&2
  echo "Hint: npm i -g pm2" >&2
  exit 2
fi

if pm2 describe model_manager >/dev/null 2>&1; then
  pm2 restart model_manager --update-env
else
  pm2 start ecosystem.config.js --only model_manager --update-env
fi

pm2 save
pm2 status model_manager

echo "[OK] Web server endpoint: http://${MODEL_MANAGER_HTTP_HOST}:${MODEL_MANAGER_HTTP_PORT}"
echo "[OK] gRPC endpoint      : 0.0.0.0:${MODEL_MANAGER_GRPC_PORT}"
