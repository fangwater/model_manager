#!/usr/bin/env bash
set -euo pipefail

pm2 logs model_manager --lines "${1:-200}"
