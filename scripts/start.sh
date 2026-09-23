#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -d frontend/dist ]; then
  pnpm --dir frontend build
fi
exec .venv/bin/python -m uvicorn orgx.main:app --app-dir backend --host 127.0.0.1 --port "${PORT:-8000}"
