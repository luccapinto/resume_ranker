#!/usr/bin/env bash
# Starts the API detached, for local demos and the e2e suite.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .run
setsid api/.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port "${API_PORT:-8000}" \
  > .run/api.log 2>&1 < /dev/null &
echo $! > .run/api.pid
echo "API iniciando (pid $(cat .run/api.pid)) — log em .run/api.log"
