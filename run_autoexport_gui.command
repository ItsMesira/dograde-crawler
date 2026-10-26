#!/usr/bin/env bash
# macOS: ดับเบิลคลิกไฟล์นี้เพื่อเปิด GUI
cd "$(dirname "$0")"
exec ./run_autoexport_gui.sh "$@"
