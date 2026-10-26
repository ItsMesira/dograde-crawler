"""เฝ้าเกรดด้วยบัญชีเดียว แล้ว export ทั้งห้องเมื่อพบว่ามีการเปลี่ยนแปลง

หลักการ:
- ใช้บัญชีกระตุ้น (trigger) 1 คนจาก students.csv เฝ้าเฉพาะภาคที่เลือก
- ตรวจด้วย pixel diff เหมือนบอท แต่เก็บ baseline แยกจาก /watch
  (shots/<sid>/autoexport_Y<ปี>T<ภาค>/) จึงไม่ทับภาพฐานของบอท
- พอพบการเปลี่ยน จะปิด session ของบัญชีกระตุ้นก่อน แล้วเรียก
  export_grades.py เป็น process ย่อยเพื่อดึงทั้งห้องเป็น .xlsx
  (แยก process เพื่อไม่ให้ g.WEBHOOK ของบอทถูกทำให้ว่าง)

CLI:
    python auto_export.py --term 1
    python auto_export.py --term 1 --trigger-sid 12345
    python auto_export.py --term 1 --check       # ตรวจรอบเดียว ไม่ export
    python auto_export.py --term 1 --keep-watching

GUI:
    python auto_export_gui.py

Discord:
    /autoexport term:1
"""
import argparse
import asyncio
import datetime
import json
import re
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import grade_watch_v3 as g
import export_grades as exporter

g.BASE_DIR = ROOT / "shots"     # ให้อยู่ที่ repo root เสมอ ไม่ขึ้นกับ CWD

TERM_BUTTONS = exporter.TERM_BUTTONS
EXPORT_DIR = exporter.EXPORT_DIR
DEFAULT_ROSTER = exporter.DEFAULT_ROSTER

# หัวตาราง ปพ.5: ชั้นมัธยมศึกษาปีที่ X ภาคเรียนที่ Y (ปี 1..3 = ม.4..6)
_HEADING_RX = re.compile(r"ชั้น\s*มัธยมศึกษาปีที่\s*(\d+)\s*ภาคเรียนที่\s*(\d+)")


def default_out(y, t):
    """ชื่อไฟล์ export อัตโนมัติ (ASCII เพื่อความปลอดภัยตอนแนบ Discord)"""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return EXPORT_DIR / f"auto_Y{y}T{t}_{ts}.xlsx"


def _stamp():
    return datetime.datetime.now().strftime("%H:%M:%S")


def pick_trigger(roster, sid=""):
    """เลือกบัญชีกระตุ้น: ระบุ sid หรือใช้คนแรกใน roster"""
    if not roster:
        raise SystemExit("ไม่มีรายชื่อนักเรียน — ต้องมี students.csv หรือใช้ --roster")
    sid = str(sid or "").strip()
    if not sid:
        return roster[0]
    for rec in roster:
        if str(rec["sid"]) == sid:
            return rec
    raise SystemExit(f"ไม่พบรหัสนักเรียน {sid} ในรายชื่อ")


async def check_once(sess, y, t):
    """เปิดภาคที่ต้องการ + แคปภาพ + เทียบ baseline ของ autoexport

    คืน dict: changed, first, diff, updated, rows, name, level, term
    """
    method = await g.go_term(sess.page, y, t)
    if method is None:
        raise RuntimeError(f"ไม่พบปุ่มเลือก ปี{y} ภาค{t} บนหน้าเว็บ")
    if "DooTermX" not in (sess.page.url or ""):
        raise RuntimeError(f"หลุดล็อกอิน (อยู่ที่ {sess.page.url})")

    body, updated, grades, name = await g.read_page(sess.page)
    flat = re.sub(r"\s+", " ", body)
    m = _HEADING_RX.search(flat)
    level = int(m.group(1)) if m else None
    got_term = int(m.group(2)) if m else None
    if level is not None and level != 3 + y:
        raise RuntimeError(f"หน้าเว็บเป็น ม.{level} ไม่ใช่ ปี{y} (คาดว่า ม.{3 + y})")
    if got_term is not None and got_term != t:
        raise RuntimeError(f"หน้าเว็บเป็นภาค {got_term} ไม่ใช่ภาค {t}")
    if level is None and updated is None and not grades:
        raise RuntimeError("ไม่พบหัวตาราง/ข้อมูลเกรด — อาจหลุดล็อกอินหรือเว็บยังโหลดไม่เสร็จ")

    sid = str(sess.S["sid"])
    folder = g.special_folder(sid, f"autoexport_Y{y}T{t}")
    shot = await g.snap(sess.page, folder, f"Y{y}T{t}")

    state_path = folder / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {"image_baseline": {}}
    except Exception:
        state = {"image_baseline": {}}
    state.setdefault("image_baseline", {})
    if not isinstance(state.get("image_baseline"), dict):
        state["image_baseline"] = {}

    # ใช้ state ชั่วคราวของ autoexport โดยเฉพาะ ไม่แตะ state.json ของบอท
    S = {"sid": sid, "pw": sess.S.get("pw", ""), "name": name or sess.S.get("name") or sid,
         "state": state}
    try:
        first, changed, diff = g.image_check(
            S, f"{y}/{t}", folder, shot, f"ปี {y} ภาค {t}")
    finally:
        try:
            shot.unlink()
        except Exception:
            pass

    try:
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except Exception:
        pass

    return {
        "changed": bool(changed),
        "first": bool(first),
        "diff": diff,
        "updated": updated,
        "rows": len(grades),
        "name": name,
        "level": level,
        "term": got_term,
    }


async def export_roster_async(term, out, workers=3, stagger=2.0, limit=0, roster=None):
    """เรียก export_grades.py เป็น process ย่อย แล้วคืน (returncode, output)

    term: เลขปุ่ม 1..6
    out: Path ของไฟล์ .xlsx
    limit: >0 ไว้ทดสอบ (ทำแค่ N คน)
    roster: ไฟล์รายชื่อที่ต้องการ (None = ค่าเริ่มต้นของ export_grades)
    """
    out = Path(out)
    if not out.is_absolute():
        out = (ROOT / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(ROOT / "export_grades.py"),
        "--term", str(term),
        "--out", str(out),
        "--workers", str(workers),
        "--stagger", str(stagger),
    ]
    if roster:
        rp = Path(roster).expanduser()
        if not rp.is_absolute():
            rp = (Path.cwd() / rp).resolve()
        cmd += ["--roster", str(rp)]
    if limit:
        cmd += ["--limit", str(limit)]

    def _run():
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    proc = await asyncio.to_thread(_run)
    text = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0 and not out.exists():
        return 1, text + f"\n[auto_export] ไม่พบไฟล์ผลลัพธ์: {out}"
    return proc.returncode, text


async def _wait(stop, timeout):
    """รอจนครบ timeout หรือมีคนสั่งหยุด (รองรับทั้ง asyncio.Event และ threading.Event)"""
    if timeout is None or timeout <= 0:
        return
    if isinstance(stop, asyncio.Event):
        try:
            await asyncio.wait_for(stop.wait(), timeout)
        except asyncio.TimeoutError:
            pass
    else:
        await asyncio.to_thread(stop.wait, timeout)


async def _watch(browser, rec, y, t, stop, on_change, notify, interval, once, cooldown):
    sid = str(rec["sid"])
    S = {
        "sid": sid,
        "pw": rec["pw"],
        "name": rec.get("name") or sid,
        "state": {},
        "watch_terms": [(y, t)],
        "watch_pp1": False,
    }
    sess = g.StudentSession(browser, S)
    try:
        await sess.open()
        await sess.login()
        notify(f"✅ ล็อกอินบัญชี {sid} แล้ว — เฝ้า ปี{y} ภาค{t} ทุก {int(interval)} วินาที")

        while not stop.is_set():
            try:
                info = await check_once(sess, y, t)
            except Exception as ex:
                notify(f"⚠️ ตรวจรอบนี้ไม่สำเร็จ: {str(ex)[:300]}")
                try:
                    if not await sess.wake():
                        await sess.park()
                        await sess.login()
                except Exception as ex2:
                    notify(f"❌ ล็อกอินใหม่ไม่สำเร็จ: {str(ex2)[:300]}")
                    return False
                await _wait(stop, g.RETRY_FAST)
                continue

            if stop.is_set():
                return False

            if info["first"]:
                notify(f"📌 บันทึกภาพฐาน ปี{y} ภาค{t} แล้ว — รอบถัดไปจะเริ่มเทียบ")
            elif info["changed"]:
                diff = f"{info['diff']}%" if info["diff"] is not None else "?"
                notify(f"🎉 พบการเปลี่ยนแปลง ปี{y} ภาค{t} (ต่าง {diff}) — เริ่ม export ทั้งห้อง")

                # ปิด session กระตุ้นก่อน export เพราะ export จะล็อกอินบัญชีนี้ใหม่
                await sess.close()
                try:
                    ok = bool(await on_change(info))
                except Exception as ex:
                    notify(f"❌ export ไม่สำเร็จ: {str(ex)[:300]}")
                    ok = False

                if once or stop.is_set():
                    return ok

                notify(f"⏳ รอ {int(cooldown)} วินาทีก่อนกลับมาเฝ้าต่อ...")
                await _wait(stop, cooldown)
                if stop.is_set():
                    return ok
                try:
                    sess = g.StudentSession(browser, S)
                    await sess.open()
                    await sess.login()
                except Exception as ex:
                    notify(f"❌ กลับมาเฝ้าต่อไม่ได้: {str(ex)[:300]}")
                    return ok
                notify("🔁 กลับมาเฝ้าต่อแล้ว")
                continue
            else:
                diff = f"{info['diff']}%" if info["diff"] is not None else "?"
                notify(f"… ยังไม่เปลี่ยน (ต่าง {diff}) ปรับปรุง: {info.get('updated') or 'ไม่พบ'}")

            await _wait(stop, interval)

        return False
    finally:
        await sess.close()


async def watch_trigger(browser, rec, term, *, stop=None, on_change=None,
                        notify=None, interval=60, once=True, cooldown=300,
                        headed=False):
    """เฝ้าบัญชีเดียวจนกว่าจะพบการเปลี่ยน

    browser: บราวเซอร์ที่เปิดอยู่แล้ว (บอทส่ง _browser มา) หรือ None = เปิดเอง
    stop: asyncio.Event (บอท) หรือ threading.Event (CLI/GUI)
    on_change: async fn(info) -> path|bool  เรียกเมื่อพบการเปลี่ยน
    once: True = export เสร็จแล้วจบ, False = เฝ้าต่อ
    """
    if g.Image is None:
        raise RuntimeError("ยังไม่ได้ติดตั้ง Pillow — ตรวจภาพไม่ได้ (รัน ./setup.sh)")

    if stop is None:
        stop = threading.Event()
    if notify is None:
        def notify(msg, file_path=None, mention=False):
            print(f"[{_stamp()}] {msg}")
    if on_change is None:
        async def on_change(info):
            notify("พบการเปลี่ยนแปลง (ยังไม่ได้ตั้งค่า export)")
            return True

    y, t = term
    if browser is not None:
        return await _watch(browser, rec, y, t, stop, on_change, notify,
                            interval, once, cooldown)

    async with g.async_playwright() as p:
        b = await p.chromium.launch(headless=not headed)
        try:
            return await _watch(b, rec, y, t, stop, on_change, notify,
                                interval, once, cooldown)
        finally:
            await b.close()


async def check_only(rec, y, t, headed=False):
    """ล็อกอิน + ตรวจรอบเดียว (ใช้ --check / ไว้ทดสอบ)"""
    if g.Image is None:
        raise RuntimeError("ยังไม่ได้ติดตั้ง Pillow — ตรวจภาพไม่ได้ (รัน ./setup.sh)")
    async with g.async_playwright() as p:
        b = await p.chromium.launch(headless=not headed)
        S = {
            "sid": str(rec["sid"]),
            "pw": rec["pw"],
            "name": rec.get("name") or str(rec["sid"]),
            "state": {},
            "watch_terms": [(y, t)],
            "watch_pp1": False,
        }
        sess = g.StudentSession(b, S)
        try:
            await sess.open()
            await sess.login()
            return await check_once(sess, y, t)
        finally:
            await sess.close()
            await b.close()


def choose_term():
    if not sys.stdin.isatty():
        return 1
    print("\nเลือกภาคที่จะเฝ้า:")
    for i, (y, t) in enumerate(TERM_BUTTONS, 1):
        print(f"  {i}) ปี{y} ภาค{t}")
    while True:
        raw = input("เลือก [1-6] (Enter = 1): ").strip()
        if not raw:
            return 1
        try:
            n = int(raw)
        except ValueError:
            print("  พิมพ์เป็นตัวเลข 1-6")
            continue
        if 1 <= n <= 6:
            return n
        print("  พิมพ์เป็นตัวเลข 1-6")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="เฝ้าเกรดบัญชีเดียว แล้ว export ทั้งห้องเมื่อพบการเปลี่ยน")
    ap.add_argument("--term", type=int, choices=range(1, 7), default=None,
                    help="เลขปุ่มภาค 1-6 (ไม่ใส่ = ถาม/ค่าเริ่มต้น 1)")
    ap.add_argument("--trigger-sid", default="",
                    help="รหัสนักเรียนที่จะใช้เฝ้า (ไม่ใส่ = คนแรกใน students.csv)")
    ap.add_argument("--roster", default=str(DEFAULT_ROSTER),
                    help="ไฟล์รายชื่อ CSV/XLSX (ค่าเริ่มต้น students.csv)")
    ap.add_argument("--interval", type=float, default=float(g.INTERVAL),
                    help=f"วินาทีระหว่างการตรวจ (ค่าเริ่มต้น {g.INTERVAL})")
    ap.add_argument("--keep-watching", action="store_true",
                    help="เฝ้าต่อหลัง export (ค่าเริ่มต้นหยุดหลัง export ครั้งแรก)")
    ap.add_argument("--cooldown", type=float, default=300,
                    help="วินาทีรอก่อนเฝ้าต่อเมื่อใช้ --keep-watching (ค่าเริ่มต้น 300)")
    ap.add_argument("--workers", type=int, default=3,
                    help="จำนวนคนที่ export พร้อมกัน (ค่าเริ่มต้น 3)")
    ap.add_argument("--stagger", type=float, default=2,
                    help="หน่วงระหว่างชุดตอน export (ค่าเริ่มต้น 2)")
    ap.add_argument("--limit", type=int, default=0,
                    help="ทำแค่ N คนแรก (ไว้ทดสอบ)")
    ap.add_argument("--out", default="",
                    help="ชื่อไฟล์ .xlsx ที่ต้องการ (ไม่ใส่ = exports/auto_Y...xlsx)")
    ap.add_argument("--headed", action="store_true",
                    help="เปิดหน้าจอเบราว์เซอร์ให้ดู")
    ap.add_argument("--check", action="store_true",
                    help="ตรวจรอบเดียวแล้วจบ ไม่ export (ไว้ทดสอบ baseline)")
    args = ap.parse_args(argv)

    term_choice = args.term or choose_term()
    y, t = TERM_BUTTONS[term_choice - 1]
    if args.interval <= 0:
        print("❌ --interval ต้องมากกว่า 0")
        return 2

    try:
        roster, errors = exporter.load_roster(args.roster)
    except SystemExit as ex:
        print(ex)
        return 2
    except Exception as ex:
        print(f"❌ อ่านรายชื่อไม่สำเร็จ: {ex}")
        return 2
    for err in errors[:10]:
        print(f"⚠️ {err}")
    if len(errors) > 10:
        print(f"⚠️ ... และอีก {len(errors) - 10} รายการ")
    if not roster:
        print("❌ ไม่มีรายชื่อที่ใช้ได้")
        return 2

    rec = pick_trigger(roster, args.trigger_sid)
    print(f"ใช้บัญชีกระตุ้น: {rec['sid']} ({rec.get('name') or 'ไม่มีชื่อ'})")
    print(f"เฝ้า: ปี{y} ภาค{t} | ตรวจทุก {int(args.interval)} วินาที")
    if args.check:
        old_webhook = g.WEBHOOK
        g.WEBHOOK = ""
        try:
            info = asyncio.run(check_only(rec, y, t, args.headed))
        except KeyboardInterrupt:
            print("\nยกเลิก")
            return 130
        except Exception as ex:
            print(f"❌ ตรวจไม่สำเร็จ: {str(ex)[:500]}")
            return 1
        finally:
            g.WEBHOOK = old_webhook
        lv, gt = info.get("level"), info.get("term")
        head = f"ชั้น ม.{lv} ภาค {gt}" if lv is not None else "ไม่พบหัวตาราง"
        diff_txt = f"{info['diff']}%" if info["diff"] is not None else "?"
        print(f"เปลี่ยน: {info['changed']} | ครั้งแรก: {info['first']} | "
              f"ต่าง: {diff_txt} | วิชา: {info['rows']} | "
              f"{head} | ปรับปรุง: {info.get('updated') or 'ไม่พบ'}")
        return 0

    once = not args.keep_watching
    stop = threading.Event()

    def notify(msg, file_path=None, mention=False):
        print(f"[{_stamp()}] {msg}")

    async def on_change(info):
        out = Path(args.out) if args.out else default_out(y, t)
        n = min(args.limit, len(roster)) if args.limit else len(roster)
        print(f"🎉 เริ่ม export {n} คน -> {out}")
        rc, output = await export_roster_async(
            term_choice, out, args.workers, args.stagger, args.limit,
            roster=args.roster)
        if rc != 0:
            print("❌ export ไม่สำเร็จ")
            print(output[-2500:])
            return None
        print(f"✅ export เสร็จ: {out}")
        return out

    old_webhook = g.WEBHOOK
    g.WEBHOOK = ""              # CLI ไม่ต้องยิง log เอนจินเข้า Discord
    try:
        ok = asyncio.run(watch_trigger(
            None, rec, (y, t), stop=stop, on_change=on_change, notify=notify,
            interval=args.interval, once=once, cooldown=args.cooldown,
            headed=args.headed))
    except KeyboardInterrupt:
        stop.set()
        print("\nยกเลิก")
        return 130
    except Exception as ex:
        print(f"❌ ทำงานไม่สำเร็จ: {str(ex)[:500]}")
        return 1
    finally:
        g.WEBHOOK = old_webhook
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
