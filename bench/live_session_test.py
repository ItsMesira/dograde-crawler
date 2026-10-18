"""
ทดสอบ storage_state กับเว็บจริง dograde.online/prakan

ทำไมต้องทดสอบ: benchmark ในเครื่องผ่าน แต่เว็บจริงเป็น ASP.NET ที่อาจผูก session
กับ state ฝั่งเซิร์ฟเวอร์ หรือพึ่ง __VIEWSTATE ที่ไม่ serialize ได้
ถ้าใช้ session ซ้ำไม่ได้ สถาปัตยกรรมที่วางไว้ก็พัง

ใช้ login() ตัวจริงจาก grade_watch_v3.py ไม่ใช่โค้ดเขียนใหม่
เพื่อให้ผลที่ได้บอกความจริงกับโค้ดที่จะเอาไปใช้จริง

ไม่บันทึกภาพ ไม่แสดงเนื้อหาเกรด — รายงานแค่โครงสร้าง

รัน:
  DOGRADE_SID=<รหัส> DOGRADE_PW=<วว/ดด/ปปปป> python bench/live_session_test.py
"""
import os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import grade_watch_v3 as g          # ตัวจริงที่จะเอาไป refactor
from playwright.sync_api import sync_playwright

# กันไม่ให้ test ยิง webhook: bot_config.json ตอนนี้ยังเป็นคำอธิบายภาษาไทย
# ซึ่งเป็นค่าที่ "จริง" ตาม bool() -> discord() จะพยายามยิง URL ปลอมวนซ้ำ
g.WEBHOOK = ""

SID = os.environ.get("DOGRADE_SID", "").strip()
PW = os.environ.get("DOGRADE_PW", "").strip()

if not SID or not PW:
    sys.exit("ต้องใส่ DOGRADE_SID และ DOGRADE_PW ใน environment")


def on_grades_page(page):
    """เกณฑ์เดียวกับที่ login() ใช้ตัดสินว่าเข้าหน้าผลการเรียนสำเร็จ"""
    import re
    try:
        flat = re.sub(r"\s+", "", page.inner_text("body"))
    except Exception:
        return False
    return "ปรับปรุง" in flat or "ปี1ภาค1" in flat


def main():
    S = {"sid": SID, "pw": PW, "name": SID, "state": {"terms": {}}}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            # ---- 1. ล็อกอินจริง ----
            ctx = browser.new_context(viewport={"width": 1400, "height": 1000})
            page = ctx.new_page()
            page.set_default_timeout(g.TIMEOUT_MS)

            t0 = time.perf_counter()
            try:
                g.login(page, S, [])
            except Exception as e:
                print(f"ล็อกอินไม่สำเร็จ: {str(e)[:200]}")
                return 1
            login_s = time.perf_counter() - t0
            print(f"1) ล็อกอินสำเร็จ          : {login_s:.2f}s")

            # ---- 2. ดูโครงสร้างคุกกี้ (ไม่แสดงค่า) ----
            state = ctx.storage_state()
            cookies = state.get("cookies", [])
            print(f"2) คุกกี้ที่จับได้        : {len(cookies)} ตัว")
            for c in cookies:
                exp = c.get("expires", -1)
                kind = "คงอยู่จนหมดอายุ" if exp and exp > 0 else "session (หมดเมื่อปิดหน้า)"
                print(f"     - {c['name']:<24} {kind}")
            print(f"     localStorage keys    : {len(state.get('origins', [{}])[0].get('localStorage', []) if state.get('origins') else [])}")

            ctx.close()

            # ---- 3. เปิด context ใหม่ + ใส่ state เดิม ----
            landed_url = page.url
            print(f"   (หน้าที่ล็อกอินแล้วไปจบที่: {landed_url})")

            t0 = time.perf_counter()
            ctx2 = browser.new_context(viewport={"width": 1400, "height": 1000}, storage_state=state)
            page2 = ctx2.new_page()
            page2.set_default_timeout(g.TIMEOUT_MS)
            restore_s = time.perf_counter() - t0

            # ยืนยันว่าคุกกี้ถูก "ใส่" จริงใน context ใหม่ (แยกปัญหาเว็บ ออกจากปัญหาการกู้คืน)
            restored_cookies = [c["name"] for c in ctx2.cookies()]
            print(f"   (คุกกี้ใน context ใหม่: {restored_cookies})")

            # ลองทีละ URL: หน้าแรก แล้วก็หน้าที่ล็อกอินไปจบจริง
            still_in = False
            used_url = None
            for cand in (g.URL, landed_url):
                try:
                    page2.goto(cand, wait_until="domcontentloaded", timeout=30000)
                    g.settle(page2)
                    if on_grades_page(page2):
                        still_in, used_url = True, cand
                        break
                except Exception as e:
                    print(f"   ลอง {cand} ไม่สำเร็จ: {str(e)[:70]}")
            print(f"3) กู้ state แล้วเข้าหน้าเดิม : {restore_s:.2f}s  -> "
                  f"{'ยังล็อกอินอยู่ (ผ่านที่ ' + used_url + ')' if still_in else 'โดนเด้งกลับหน้า login ทุกทาง'}")

            # ---- 4. ข้อสำคัญ: นำทางไปภาคได้ไหม (ทดสอบ ViewState) ----
            nav_ok, nav_note = False, ""
            try:
                method = g.go_term(page2, 1, 1)
                if method:
                    body, updated, grades, name = g.read_page(page2)
                    nav_ok = bool(grades)
                    nav_note = f"วิธี={method}, อ่านข้อมูลได้={len(grades)} แถว"
                else:
                    nav_note = "หาปุ่มภาคไม่เจอ"
            except Exception as e:
                nav_note = f"error: {str(e)[:90]}"

            print(f"4) นำทางไปภาค ปี1ภาค1    : {'ผ่าน' if nav_ok else 'ไม่ผ่าน'} ({nav_note})")

            # ---- 5. จุดสำคัญ: session ยังอยู่ไหมถ้า "พัก" หน้าไว้ที่ about:blank ----
            # ถ้ายังอยู่ เราถือ context ค้างไว้ได้โดยไม่ต้องจ่าย RAM ของหน้าเว็บเต็มๆ
            parked_ok, parked_note = False, ""
            try:
                if not still_in:
                    # กู้คืนไม่ได้ -> ล็อกอินใหม่ใน context นี้เพื่อทดสอบต่อ
                    g.login(page2, S, [])
                page2.goto("about:blank")
                page2.goto(landed_url, wait_until="domcontentloaded", timeout=30000)
                g.settle(page2)
                parked_ok = on_grades_page(page2)
                parked_note = "ยังล็อกอินอยู่" if parked_ok else "โดนเด้งออก"
            except Exception as e:
                parked_note = f"error: {str(e)[:80]}"
            print(f"5) พักที่ about:blank แล้วกลับมา : {'ยังล็อกอินอยู่' if parked_ok else 'หลุด'} ({parked_note})")

            ctx2.close()
            print()
            print("=" * 62)
            if parked_ok:
                print("ผลลัพธ์: session อยู่ได้ตราบใดที่ context ยังเปิดอยู่")
                print("         -> ถือ context ค้างไว้ได้ และ 'พัก' หน้าไว้ที่ about:blank")
                print("            เพื่อประหยัด RAM ของหน้าเว็บ ระหว่างรอบ")
            if still_in and nav_ok:
                print("ผลลัพธ์: ผ่าน — ใช้ session ซ้ำได้จริง")
                print("         สถาปัตยกรรม storage_state ใช้ได้ ไม่ต้องเปิด context ค้าง")
            elif still_in and not nav_ok:
                print("ผลลัพธ์: ผ่านบางส่วน — ยังอยู่ในระบบ แต่นำทางไปภาคไม่ได้")
                print("         แปลว่า session cookie อยู่ แต่ __VIEWSTATE หาย")
            else:
                print("ผลลัพธ์: storage_state ใช้ไม่ได้ — กู้คืน session จากคุกกี้ไม่ได้")
                print("         ต้องล็อกอินใหม่ทุกครั้ง หรือถือ context ค้างไว้")
            print(f"         (ล็อกอิน {login_s:.2f}s vs กู้ state {restore_s:.2f}s)")
            print("=" * 62)
            return 0
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
