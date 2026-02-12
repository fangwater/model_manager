#!/usr/bin/env bash
set -euo pipefail

if pm2 describe model_manager >/dev/null 2>&1; then
  pm2 stop model_manager
  pm2 delete model_manager
  pm2 save
fi

pm2 status model_manager || true
