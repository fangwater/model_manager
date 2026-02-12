#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"
mkdir -p logs

if ! command -v pm2 >/dev/null 2>&1; then
  echo "[ERROR] pm2 is not installed. Please install pm2 first." >&2
  echo "Hint: npm i -g pm2" >&2
  exit 2
fi

if pm2 describe model_manager >/dev/null 2>&1; then
  pm2 restart model_manager --update-env
else
  pm2 start ecosystem.config.js --only model_manager
fi

pm2 save
pm2 status model_manager
