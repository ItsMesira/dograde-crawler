#!/usr/bin/env bash
# ส่งออกเกรดเป็น Excel — ใช้ได้ทั้ง macOS และ Linux
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

exec "$PY" export_grades.py "$@"
