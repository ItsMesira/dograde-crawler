"""
ทดสอบหัวใจของสถาปัตยกรรม: ใช้ session ซ้ำได้ไหมโดยไม่ต้องเปิด context ค้างไว้

!! คำเตือน: test นี้ผ่านกับเว็บจำลอง แต่ "ไม่ผ่าน" กับเว็บจริง
   storage_state ใช้กับ dograde.online ไม่ได้จริง ๆ (session ผูกกับ state ฝั่งเซิร์ฟเวอร์)
   ใช้ตัวนี้เป็น "กรณีเปรียบเทียบ" เท่านั้น — ดูคำตอบจริงที่ bench/live_session_test.py

โจทย์: ต้องการเลี่ยงการล็อกอินซ้ำ 28 ครั้งตอนแฟนเอาต์ (ซึ่งจะถล่มเว็บโรงเรียน)
       แต่ไม่อยากแบก RAM 3.2 GB จากการเปิด context ค้าง 28 อัน

วิธีที่ทดสอบ: ล็อกอินครั้งเดียว -> บันทึก storage_state (คุกกี้) -> ปิด context
             -> เปิด context ใหม่ + ใส่ state ที่บันทึกไว้ -> เข้าหน้าผลการเรียนได้ไหม

ถ้าผ่าน = ใช้ context แบบชั่วคราว (RAM ~240 MB) โดยไม่ต้องล็อกอินซ้ำ
ถ้าไม่ผ่าน = ต้องเลือกระหว่าง RAM 3.2 GB กับ ล็อกอิน 28 ครั้ง/รอบ

รัน: python bench/session_reuse_test.py
"""
import asyncio, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer

from playwright.async_api import async_playwright

LOGIN_PAGE = b"""<!doctype html><html><head><meta charset="utf-8"><title>login</title></head><body>
<form method="POST" action="/do-login">
<input type="text" name="sid"><input type="password" name="pw"><input type="submit" value="login">
</form></body></html>"""

# เลียนแบบหน้าผลการเรียน + ต้องมีคุกกี้ถึงจะเข้าได้
GRADES_PAGE = b"""<!doctype html><html><head><meta charset="utf-8"><title>grades</title></head><body>
<h2>grades</h2><p>adjust 18/10/2569 14:32</p></body></html>"""

VALID = "SESSID=sess-abc123"


class H(BaseHTTPRequestHandler):
    def _send(self, code, body=b"", extra=None):
        self.send_response(code)
        for k, v in (extra or []):
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/login"):
            return self._send(200, LOGIN_PAGE)
        if self.path.startswith("/grades"):
            if VALID in (self.headers.get("Cookie") or ""):
                return self._send(200, GRADES_PAGE)
            return self._send(403, b"denied")
        return self._send(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)  # อ่าน body ทิ้ง (เลียนแบบ postback)
        if self.path.startswith("/do-login"):
            # เหมือนเว็บจริง: ล็อกอินผ่าน -> ตั้งคุกกี้ -> เด้งไปหน้าผลการเรียน
            return self._send(302, b"", [("Set-Cookie", VALID + "; Path=/"), ("Location", "/grades")])
        return self._send(404)

    def log_message(self, *a):
        pass


def start_server():
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


async def do_login(browser, base, sid="99901", pw="01/01/2550"):
    """ล็อกอินเต็มรูปแบบ คืน context ที่ล็อกอินแล้ว"""
    ctx = await browser.new_context(viewport={"width": 1400, "height": 1000})
    page = await ctx.new_page()
    await page.goto(f"{base}/login", wait_until="domcontentloaded")
    await page.fill('input[name="sid"]', sid)
    await page.fill('input[name="pw"]', pw)
    await page.click('input[type="submit"]')
    await page.wait_for_load_state("domcontentloaded")
    return ctx, page


async def main():
    srv, base = start_server()
    print(f"เว็บจำลอง: {base}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # ---- 1. ล็อกอินเต็มรูปแบบ แล้ววัดเวลา ----
        t0 = time.perf_counter()
        ctx1, page1 = await do_login(browser, base)
        login_s = time.perf_counter() - t0
        r = await page1.goto(f"{base}/grades")
        print(f"1) ล็อกอินเต็มรูปแบบ           : {login_s:.3f}s  -> เข้าหน้าผลการเรียน status={r.status}")

        # ---- 2. บันทึก session ลงดิสก์ ----
        state = await ctx1.storage_state()
        cookie_names = [c["name"] for c in state.get("cookies", [])]
        print(f"2) บันทึก storage_state         : คุกกี้ที่จับได้ = {cookie_names}")

        await ctx1.close()  # ปิดทิ้ง -> ไม่กิน RAM ค้าง

        # ---- 3. เปิด context ใหม่ + ใส่ state เดิม (ไม่ล็อกอิน) ----
        t0 = time.perf_counter()
        ctx2 = await browser.new_context(viewport={"width": 1400, "height": 1000}, storage_state=state)
        page2 = await ctx2.new_page()
        restore_s = time.perf_counter() - t0
        r2 = await page2.goto(f"{base}/grades")
        body = await page2.inner_text("body")
        await ctx2.close()

        ok = r2.status == 200 and "adjust" in body
        print(f"3) เปิด context ใหม่ + state เดิม : {restore_s:.3f}s  -> status={r2.status}")
        print(f"\n{'='*58}")
        if ok:
            print("ผลลัพธ์: ผ่าน — ใช้ session ซ้ำได้โดยไม่ต้องเปิด context ค้าง")
            print(f"         ประหยัดเวลา {login_s - restore_s:.3f}s ต่อคน "
                  f"({(login_s - restore_s) * 28:.1f}s สำหรับ 28 คน)")
            print("         -> เลือกใช้ context ชั่วคราว + storage_state ได้ (RAM ~240 MB)")
        else:
            print("ผลลัพธ์: ไม่ผ่าน — ต้องเลือกระหว่างเปิด context ค้างไว้ หรือ ล็อกอินซ้ำ")
        print(f"{'='*58}")

        await browser.close()
    srv.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
