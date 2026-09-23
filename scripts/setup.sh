#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

for program in python3 node pnpm; do
  if ! command -v "$program" >/dev/null 2>&1; then
    echo "Не найден $program. Установите системные требования из README.md." >&2
    exit 1
  fi
done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else "Требуется Python 3.9 или новее.")'
node -e 'if (Number(process.versions.node.split(".")[0]) < 22) { console.error("Требуется Node.js 22 или новее."); process.exit(1); }'
if [ "$(pnpm --version)" != "9.15.0" ]; then
  echo 'Требуется pnpm 9.15.0: npm install -g pnpm@9.15.0' >&2
  exit 1
fi
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip check
pnpm --dir frontend install --frozen-lockfile
if [ ! -f .env ]; then
  cp .env.example .env
fi
echo 'Установка завершена. Проверка: bash scripts/check.sh. Запуск: bash scripts/start.sh.'
