#!/usr/bin/env bash
# เฝ้าเกรดบัญชีเดียว แล้ว export ทั้งห้องเมื่อเกรดเปลี่ยน (CLI)
set -euo pipefail
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
else
  echo "ไม่พบ Python 3 — ติดตั้งจาก https://www.python.org/downloads/ แล้วรัน ./setup.sh"
  exit 1
fi

exec "$PY" auto_export.py "$@"
