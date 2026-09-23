#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ] || ! command -v pnpm >/dev/null 2>&1; then
  echo 'Сначала выполните bash scripts/setup.sh (см. README.md).' >&2
  exit 1
fi
cmp requirements.txt requirements.lock
.venv/bin/python -m pip check

# Never use the auditor's database or a configured external AI service in checks.
check_directory="$(mktemp -d "${TMPDIR:-/tmp}/orgx-check.XXXXXX")"
trap 'rm -rf "$check_directory"' EXIT
export ORGX_DB="$check_directory/check.sqlite"
export ORGX_ENABLE_OPENAI=0
echo 'Проверка backend (без оригиналов организатора source-тесты будут SKIPPED).'
.venv/bin/python -m pytest -q "$@"
echo 'Проверка TypeScript и production-сборки frontend.'
pnpm --dir frontend build
echo 'Все запущенные проверки прошли. SKIPPED означает отсутствие соответствующей проверки.'
