#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${ROOT_DIR}/scripts/cleanup_history.py"

if [[ ! -f "${SCRIPT}" ]]; then
  echo "[ERROR] Missing script: ${SCRIPT}" >&2
  exit 2
fi

usage() {
  echo "Usage: ./cleanup_history.sh [--background]" >&2
}

if [[ "${1:-}" == "--background" ]]; then
  shift
  if [[ $# -gt 0 ]]; then
    usage
    exit 2
  fi
  mkdir -p "${ROOT_DIR}/logs"
  nohup "${ROOT_DIR}/cleanup_history.sh" >"${ROOT_DIR}/logs/cleanup_history.out.log" 2>&1 &
  echo "[OK] cleanup started in background. pid=$!"
  exit 0
fi

if [[ $# -gt 0 ]]; then
  usage
  exit 2
fi

PYTHON_BIN=""
if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "[ERROR] python3 not found and .venv/bin/python missing." >&2
  exit 2
fi

exec "${PYTHON_BIN}" "${SCRIPT}"
