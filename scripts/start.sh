#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ] || ! command -v pnpm >/dev/null 2>&1; then
  echo 'Сначала выполните bash scripts/setup.sh (см. README.md).' >&2
  exit 1
fi
if [ ! -d frontend/node_modules ]; then
  echo 'Не установлены зависимости frontend. Выполните bash scripts/setup.sh.' >&2
  exit 1
fi
# Rebuild on every launch: a dist directory may belong to an older checkout.
pnpm --dir frontend build
echo "ORG-X: http://127.0.0.1:${PORT:-8000} (Ctrl+C для остановки)"
exec .venv/bin/python -m uvicorn orgx.main:app --app-dir backend --host 127.0.0.1 --port "${PORT:-8000}"
