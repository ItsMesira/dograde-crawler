"""
ทดสอบเอนจิ้นหลังแปลงเป็น async กับเว็บจริง

ครอบคลุม: StudentSession -> login -> go_term -> read_page/read_grades
          -> park/wake (session ยังอยู่ไหม) -> check_student โหมดเร็ว

รัน:
  DOGRADE_SID=<รหัส> DOGRADE_PW=<วว/ดด/ปปปป> .venv/bin/python bench/live_engine_test.py
"""
import asyncio, os, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import grade_watch_v3 as g

g.WEBHOOK = ""   # กันยิง webhook ระหว่างทดสอบ

SID = os.environ.get("DOGRADE_SID", "").strip()
PW = os.environ.get("DOGRADE_PW", "").strip()
if not SID or not PW:
    sys.exit("ต้องใส่ DOGRADE_SID และ DOGRADE_PW")


async def main():
    S = {"sid": SID, "pw": PW, "name": SID,
         "state": g.load_or_new_state(SID),
         "watch_terms": [(1, 1)], "watch_pp1": False}

    async with g.async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        sess = g.StudentSession(browser, S)
        try:
            # 1. เปิด + ล็อกอิน
            t0 = time.perf_counter()
            await sess.open()
            await sess.login()
            print(f"1) login ผ่าน async API   : {time.perf_counter() - t0:.2f}s  -> {sess.landed_url}")

            # 2. นำทางไปภาค + อ่านข้อมูล
            t0 = time.perf_counter()
            await g.go_term(sess.page, 1, 1)
            body, updated, grades, name = await g.read_page(sess.page)
            print(f"2) go_term + read_page     : {time.perf_counter() - t0:.2f}s  "
                  f"-> อ่านข้อมูลได้ {len(grades)} แถว, วันที่ปรับปรุง: {updated or 'ไม่พบ'}")
            if name:
                S["name"] = name
                print(f"   ชื่อที่อ่านได้           : {name}")

            # 3. park -> wake : session รอดไหม
            await sess.park()
            await asyncio.sleep(0.5)
            alive = await sess.wake()
            print(f"3) park(about:blank)->wake : {'ยังล็อกอินอยู่ ✔' if alive else 'หลุด ✘'}")

            # 4. check_student โหมดเร็ว (ใช้ตอนแฟนเอาต์)
            t0 = time.perf_counter()
            changed, info = await g.check_student(sess, full=False)
            print(f"4) check_student(fast)     : {time.perf_counter() - t0:.2f}s  "
                  f"-> changed={changed}, info={info}")

            print()
            print("=" * 60)
            ok = bool(grades) and alive
            print("ผลลัพธ์: " + ("ผ่าน — เอนจิ้น async ใช้ได้จริง" if ok
                              else "มีปัญหา ดูรายละเอียดด้านบน"))
            print("=" * 60)
            return 0 if ok else 1
        finally:
            await sess.close()
            await browser.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
