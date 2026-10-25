#!/usr/bin/env bash
# ติดตั้งทุกอย่างในคำสั่งเดียว (macOS/Linux)
set -euo pipefail
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
else
  echo "ไม่พบ Python 3 — ติดตั้งจาก https://www.python.org/downloads/ แล้วลองใหม่"
  exit 1
fi

exec "$PY" bootstrap.py "$@"
