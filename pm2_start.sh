#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"
mkdir -p logs

if pm2 describe model_manager >/dev/null 2>&1; then
  pm2 restart model_manager --update-env
else
  pm2 start ecosystem.config.js --only model_manager
fi

pm2 save
pm2 status model_manager
