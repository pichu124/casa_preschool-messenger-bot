#!/usr/bin/env bash
# Check thật của bot cho đội agent (./scripts/check.sh gọi file này).
#   1. Cú pháp toàn bộ app/
#   2. ruff chỉ các lỗi chắc chắn là bug (cú pháp, tên chưa định nghĩa như F821), bỏ qua config
#   3. pytest trong tests/ (gồm smoke test import app.main, không cần mạng hay API key)
#   PYTHON=...  chỉ định interpreter (mặc định: .venv của repo, rồi python3)
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

py="${PYTHON:-}"
if [ -z "$py" ]; then
  candidates=(.venv/bin/python .venv/Scripts/python.exe)
  # Worktree của agent không có .venv riêng: dùng .venv của checkout chính.
  if common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"; then
    candidates+=("$(dirname "$common")/.venv/bin/python")
  fi
  candidates+=(python3 python)
  for c in "${candidates[@]}"; do
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
"$py" -m ruff check --isolated --select E9,F63,F7,F82 app tests scripts || exit 1
exec "$py" -m pytest -q -p no:cacheprovider
