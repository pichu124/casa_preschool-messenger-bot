#!/usr/bin/env bash
# Check thật của bot cho đội agent (./scripts/check.sh gọi file này).
#   1. Cú pháp toàn bộ app/
#   2. pytest trong tests/ (gồm smoke test import app.main, không cần mạng hay API key)
#   PYTHON=...  chỉ định interpreter (mặc định: .venv của repo, rồi python3)
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

py="${PYTHON:-}"
if [ -z "$py" ]; then
  for c in .venv/bin/python .venv/Scripts/python.exe python3 python; do
    if "$c" -c 'import fastapi, pytest' >/dev/null 2>&1; then
      py="$c"
      break
    fi
  done
fi
if [ -z "$py" ]; then
  echo "Không tìm thấy Python có fastapi + pytest. Chạy: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt" >&2
  exit 1
fi

export PYTHONIOENCODING=utf-8
"$py" -m compileall -q app || exit 1
exec "$py" -m pytest -q -p no:cacheprovider
