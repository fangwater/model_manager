#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "[ERROR] Missing virtualenv python: ${VENV_PYTHON}" >&2
  echo "Run: ${ROOT_DIR}/setup_venv.sh" >&2
  exit 2
fi

export PYTHONUNBUFFERED=1
export PYTHONPATH="${ROOT_DIR}/..:${PYTHONPATH:-}"

exec "${VENV_PYTHON}" -m model_manager "$@"
