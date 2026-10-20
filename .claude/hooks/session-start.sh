#!/bin/bash
# SessionStart (chỉ phiên cloud): tạo .venv và cài dependency để ./scripts/check.sh chạy được.
# Chạy đồng bộ: phiên chỉ bắt đầu khi cài xong. Chạy lại nhiều lần vẫn an toàn.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements-dev.txt

# Cho agent gọi thẳng python/pytest mà vẫn dùng .venv.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export VIRTUAL_ENV=\"$CLAUDE_PROJECT_DIR/.venv\"" >> "$CLAUDE_ENV_FILE"
  echo "export PATH=\"$CLAUDE_PROJECT_DIR/.venv/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi
