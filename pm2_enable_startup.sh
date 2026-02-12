#!/usr/bin/env bash
set -euo pipefail

echo "[STEP] Running 'pm2 startup' to print the required sudo command"
pm2 startup

echo
echo "[NEXT] Run the sudo command printed above, then execute:"
echo "       pm2 save"
