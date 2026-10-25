"""ติดตั้งทุกอย่างในคำสั่งเดียว (ใช้ได้ Windows / macOS / Linux)

วิธีใช้:
    ./setup.sh          (macOS/Linux)
    setup.bat           (Windows)
    python bootstrap.py (เรียกตรง ๆ ก็ได้)

สิ่งที่ทำให้:
    1. สร้าง .venv (ถ้ายังไม่มี)
    2. ติดตั้งแพ็กเกจจาก requirements.txt
    3. ติดตั้ง Chromium ของ Playwright
    4. สร้าง bot_config.json / students.csv จากไฟล์ตัวอย่าง (ถ้ายังไม่มี)
    5. ตรวจว่า import แพ็กเกจครบ

รันซ้ำได้ปลอดภัย — ของที่มีอยู่แล้วจะไม่ถูกเขียนทับ
"""
import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIRED = (3, 10)


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def run(cmd):
    print("  $", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def main():
    ap = argparse.ArgumentParser(description="ติดตั้งสภาพแวดล้อมของ Dograde Crawler")
    ap.add_argument("--skip-browser", action="store_true", help="ข้ามการติดตั้ง Chromium")
    ap.add_argument("--force", action="store_true", help="ลบ .venv เดิมแล้วสร้างใหม่")
    args = ap.parse_args()

    if sys.version_info < REQUIRED:
        raise SystemExit(
            f"ต้องใช้ Python {REQUIRED[0]}.{REQUIRED[1]}+ "
            f"(ตอนนี้ {sys.version.split()[0]}) — ดาวน์โหลดที่ https://www.python.org/downloads/")

    if args.force and VENV.exists():
        print("[1/5] ลบ .venv เดิม ...")
        shutil.rmtree(VENV)

    py = venv_python()
    if py.exists():
        print("[1/5] ใช้ .venv เดิม")
    else:
        if VENV.exists():
            print("[1/5] .venv เดิมไม่สมบูรณ์ — สร้างใหม่")
            shutil.rmtree(VENV)
        print("[1/5] สร้าง .venv ...")
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV)
        py = venv_python()
        if not py.exists():
            raise SystemExit("สร้าง .venv ไม่สำเร็จ — ลองรันด้วย --force")

    print("[2/5] ติดตั้งแพ็กเกจ Python ...")
    run([py, "-m", "pip", "install", "--upgrade", "pip", "--quiet"])
    run([py, "-m", "pip", "install", "-r", ROOT / "requirements.txt"])

    if args.skip_browser:
        print("[3/5] ข้าม Chromium (--skip-browser)")
    else:
        print("[3/5] ติดตั้ง Chromium ของ Playwright (อาจใช้เวลา 1-3 นาที) ...")
        run([py, "-m", "playwright", "install", "chromium"])
        if sys.platform.startswith("linux"):
            print("  (Linux: ถ้าเปิด Chromium ไม่ได้ ให้รัน "
                  "'.venv/bin/python -m playwright install-deps chromium')")

    print("[4/5] เตรียมไฟล์ตั้งค่า ...")
    cfg = ROOT / "bot_config.json"
    if not cfg.exists():
        shutil.copyfile(ROOT / "bot_config.example.json", cfg)
        print("  + สร้าง bot_config.json จากตัวอย่าง (ยังต้องใส่ Token/Webhook)")
    else:
        print("  = bot_config.json มีอยู่แล้ว")

    roster = ROOT / "students.csv"
    if not roster.exists():
        shutil.copyfile(ROOT / "students.example.csv", roster)
        print("  + สร้าง students.csv จากตัวอย่าง (ยังต้องใส่รหัส/วันเกิดจริง)")
    else:
        print("  = students.csv มีอยู่แล้ว")

    print("[5/5] ตรวจสอบ ...")
    run([py, "-c",
         "import discord, openpyxl, playwright, PIL, psutil, requests; "
         "print('  แพ็กเกจครบ')"])

    print("""
เสร็จแล้ว! ขั้นต่อไป:

  1) ใส่ Bot Token / Webhook ใน bot_config.json  (ถ้าจะใช้บอท Discord)
  2) ใส่รายชื่อจริงใน students.csv               (ถ้าจะส่งออกเกรด)

  Windows:      run_export.bat    / run_bot.bat
  macOS/Linux:  ./run_export.sh   / ./run_bot.sh

อ่านคู่มือทั้งหมดใน README.md
""")


if __name__ == "__main__":
    main()
