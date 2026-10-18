"""
วัดประสิทธิภาพ: Chromium ตัวเดียว + N context แบบ async ทำ "แฟนเอาต์" ทันเวลาไหม

ใช้ตอบคำถามหลักของสถาปัตยกรรมใหม่:
    เมื่อ MAIN ตรวจพบการเปลี่ยนแปลง ต้องกระจายไปเช็คทุกคนให้เสร็จภายใน 1 นาที
    -> Chromium ตัวเดียวแบก 28 context ไหวหรือไม่

วัด 2 โหมดตามที่ออกแบบไว้:
    fast  = ไม่ล็อกอินใหม่ + แคปเฉพาะภาคหลัก (1 ภาพ)   <- ใช้ตอนแฟนเอาต์
    full  = ล็อกอิน + กวาดทุกภาค (7 ภาพ)                 <- ใช้ตอนเช็คปกติของ MAIN

รัน:
    python bench/fanout_bench.py                     # ค่าเริ่มต้น 1,5,10,28
    python bench/fanout_bench.py --students 28       # ระบุจำนวนเอง
"""
import argparse, asyncio, statistics, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer

from playwright.async_api import async_playwright

# ---------- เว็บจำลอง: หน้าตาคล้ายหน้าผลการเรียนจริง ----------
ROWS = 30  # จำนวนแถววิชา (ยิ่งมาก ภาพยิ่งสูง ยิ่งแคปนาน)

PAGE = f"""<!doctype html><html lang="th"><head><meta charset="utf-8">
<title>ผลการเรียน</title><style>
body{{font-family:sans-serif;margin:24px}}
table{{border-collapse:collapse;width:900px}}
th,td{{border:1px solid #999;padding:6px 10px;text-align:left}}
th{{background:#eee}} .bar{{height:120px;background:linear-gradient(#fff,#ddd)}}
</style></head><body>
<h2>ผลการเรียน ปี 1 ภาค 1</h2>
<p>ปรับปรุง 18/10/2569 14:32</p>
<div class="bar"></div>
<table><tr><th>รหัสวิชา</th><th>ชื่อวิชา</th><th>ระดับคะแนน</th></tr>
{"".join(f"<tr><td>ท{1000+i}</td><td>วิชาทดสอบที่ {i}</td><td>{'4' if i%3 else '0'}</td></tr>" for i in range(ROWS))}
</table></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # ปิด log กันรก
        pass


def start_server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


# ---------- งานของ context เดียว ----------
async def one_check(browser, url, shots_per_check):
    """จำลองการเช็ค 1 คน: สร้าง context -> เปิดหน้า -> แคป N ภาพ -> ปิด"""
    t0 = time.perf_counter()
    ctx = await browser.new_context(viewport={"width": 1400, "height": 1000})
    page = await ctx.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(200)  # เลียนแบบ settle()
        for _ in range(shots_per_check):
            await page.screenshot(full_page=True)
    finally:
        await ctx.close()
    return time.perf_counter() - t0


async def run_batch(browser, url, n, shots):
    t0 = time.perf_counter()
    times = await asyncio.gather(*(one_check(browser, url, shots) for _ in range(n)))
    wall = time.perf_counter() - t0
    return wall, times


async def measure_held(browser, url, n, park=False):
    """เปิด N context ค้างไว้พร้อมกัน (จำลอง persistent session ที่ไม่ต้องล็อกอินใหม่)
    park=True -> พักหน้าไว้ที่ about:blank หลังโหลด (คง session แต่ปล่อย RAM ของหน้า)
    คืน (RAM ที่ค้างอยู่, เวลาที่แคปพร้อมกันจาก context ที่ค้าง)"""
    ctxs = []
    try:
        for _ in range(n):
            ctx = await browser.new_context(viewport={"width": 1400, "height": 1000})
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(100)
            ctxs.append(ctx)
        await asyncio.sleep(0.5)
        if park:
            for ctx in ctxs:
                await ctx.pages[0].goto("about:blank")
            await asyncio.sleep(0.5)
        rss = browser_rss()
        t0 = time.perf_counter()
        await asyncio.gather(*(c.pages[0].screenshot(full_page=True) for c in ctxs))
        return rss, time.perf_counter() - t0
    finally:
        for c in ctxs:
            try:
                await c.close()
            except Exception:
                pass


def browser_rss():
    """รวม RAM ของทุกโปรเซสลูกที่มาจาก Chromium ที่ playwright เปิดไว้"""
    import psutil
    try:
        me = psutil.Process()
        procs = me.children(recursive=True)
        chromium = [p for p in procs if "chrom" in (p.name() or "").lower()]
        return sum(p.memory_info().rss for p in chromium) / 1024 ** 2
    except Exception:
        return float("nan")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--students", type=int, nargs="+", default=[1, 5, 10, 28])
    args = ap.parse_args()

    srv, url = start_server()
    print(f"เว็บจำลอง: {url}  (แถววิชา {ROWS} แถว)\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        base_rss = browser_rss()
        print(f"หน่วยความจำ Chromium เปล่า ๆ: {base_rss:.0f} MB\n")

        for label, shots in (("fast (แคป 1 ภาพ)", 1), ("full (แคป 7 ภาพ)", 7)):
            print(f"===== โหมด {label} =====")
            print(f"{'คน':>5} {'wall(s)':>9} {'เฉลี่ย(s)':>10} {'ช้าสุด(s)':>10} {'RAM(MB)':>9}")
            for n in args.students:
                wall, times = await run_batch(browser, url, n, shots)
                rss = browser_rss()
                print(f"{n:>5} {wall:>9.2f} {statistics.mean(times):>10.2f} "
                      f"{max(times):>10.2f} {rss:>9.0f}")
            print()

        # โหมดที่สถาปัตยกรรมใหม่ต้องใช้จริง: ถือ session ค้างไว้ ไม่ล็อกอินซ้ำ
        print("===== โหมด held (เปิด context ค้างไว้ = persistent session) =====")
        print(f"{'คน':>5} {'แคปพร้อมกัน(s)':>15} {'RAM ค้าง(MB)':>14}")
        for n in args.students:
            rss, wall = await measure_held(browser, url, n)
            print(f"{n:>5} {wall:>15.2f} {rss:>14.0f}")
        print()

        # พักหน้าที่ about:blank: คง session ไว้ แต่ปล่อย RAM ของหน้าที่เรนเดอร์
        print("===== โหมด held+parked (พักหน้า about:blank ระหว่างรอบ) =====")
        print(f"{'คน':>5} {'แคปพร้อมกัน(s)':>15} {'RAM ค้าง(MB)':>14}")
        for n in args.students:
            rss, wall = await measure_held(browser, url, n, park=True)
            print(f"{n:>5} {wall:>15.2f} {rss:>14.0f}")
        print()

        await browser.close()
    srv.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
