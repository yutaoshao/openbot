#!/bin/zsh
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
readonly ROOT_DIR="${OPENBOT_ROOT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd -P)}"
readonly PYTHON_BIN="${OPENBOT_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python3}"
readonly WATCHFILES_BIN="${OPENBOT_WATCHFILES_BIN:-$ROOT_DIR/.venv/bin/watchfiles}"
readonly SIGINT_TIMEOUT_SECONDS="${OPENBOT_SIGINT_TIMEOUT_SECONDS:-30}"
readonly SIGKILL_TIMEOUT_SECONDS="${OPENBOT_SIGKILL_TIMEOUT_SECONDS:-5}"
readonly GRACE_PERIOD_SECONDS="${OPENBOT_GRACE_PERIOD_SECONDS:-1}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  print -u2 "Missing Python runtime: $PYTHON_BIN. Run 'uv sync' first."
  exit 1
fi

if [[ ! -x "$WATCHFILES_BIN" ]]; then
  print -u2 "Missing watchfiles runtime: $WATCHFILES_BIN. Run 'uv sync' first."
  exit 1
fi

cd "$ROOT_DIR"

exec "$WATCHFILES_BIN" \
  --target-type command \
  --ignore-paths ".git,.venv,data,frontend/node_modules,frontend/dist" \
  --sigint-timeout "$SIGINT_TIMEOUT_SECONDS" \
  --sigkill-timeout "$SIGKILL_TIMEOUT_SECONDS" \
  --grace-period "$GRACE_PERIOD_SECONDS" \
  "$PYTHON_BIN main.py" \
  main.py src config.yaml .env pyproject.toml uv.lock
