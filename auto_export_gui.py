"""GUI แบบเว็บในเครื่อง (ใช้ stdlib เท่านั้น ไม่ต้องติดตั้ง tkinter)

รัน:
    python auto_export_gui.py

แล้วเบราว์เซอร์จะเปิด http://127.0.0.1:<port>/ ให้อัตโนมัติ
ปิดด้วย Ctrl+C ใน terminal หรือปุ่ม "ปิด GUI" ในหน้าเว็บ

macOS ดับเบิลคลิก run_autoexport_gui.command
Windows ดับเบิลคลิก run_autoexport_gui.bat
Linux: ./run_autoexport_gui.sh
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import auto_export
import export_grades


INDEX_HTML = r"""<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dograde — เฝ้าเกรดแล้ว export</title>
<style>
  :root {
    --bg: #f4f1ea;
    --card: #fffdf8;
    --ink: #1d2a24;
    --muted: #6a746e;
    --line: #d9d4c8;
    --accent: #1f6b4f;
    --accent-2: #2f8a68;
    --danger: #a33a2b;
    --log-bg: #101915;
    --log-ink: #d8f3e5;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background:
      radial-gradient(1200px 500px at 50% -180px, #e4efe5 0%, transparent 70%),
      var(--bg);
    color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans Thai",
                 "Sarabun", "Thonburi", sans-serif;
    line-height: 1.5;
  }
  main { max-width: 900px; margin: 0 auto; padding: 28px 18px 40px; }
  header { margin-bottom: 18px; }
  .eyebrow {
    display: inline-block; font-size: 12px; letter-spacing: .12em;
    text-transform: uppercase; color: var(--accent); font-weight: 700;
    background: #e3efe6; border: 1px solid #c7ddcd; border-radius: 999px;
    padding: 3px 10px; margin-bottom: 10px;
  }
  h1 { margin: 0 0 6px; font-size: clamp(24px, 4vw, 34px); letter-spacing: -.02em; }
  header p { margin: 0; color: var(--muted); max-width: 720px; }
  .card {
    background: var(--card); border: 1px solid var(--line);
    border-radius: 16px; padding: 18px;
    box-shadow: 0 12px 30px rgba(45, 52, 45, .06);
    margin-top: 14px;
  }
  .grid {
    display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
  }
  label.field { display: flex; flex-direction: column; gap: 6px; font-size: 13px;
                color: var(--muted); font-weight: 600; }
  select, input[type="number"] {
    width: 100%; padding: 10px 11px; border: 1px solid var(--line);
    border-radius: 10px; background: #fff; color: var(--ink);
    font: inherit; font-size: 14px; font-weight: 500;
  }
  select:focus, input:focus, button:focus {
    outline: 3px solid rgba(47, 138, 104, .22); outline-offset: 1px;
  }
  .checks { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 14px; }
  .checks label { display: inline-flex; align-items: center; gap: 7px;
                  font-size: 13px; color: var(--ink); cursor: pointer; }
  input[type="checkbox"] { width: 16px; height: 16px; accent-color: var(--accent); }
  .actions { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 16px; }
  button {
    appearance: none; border: 1px solid var(--line); background: #fff;
    color: var(--ink); border-radius: 10px; padding: 10px 15px;
    font: inherit; font-size: 14px; font-weight: 700; cursor: pointer;
    transition: transform .08s ease, background .15s ease, border-color .15s ease;
  }
  button:hover:not(:disabled) { border-color: #b9b2a3; background: #fbf8ef; }
  button:active:not(:disabled) { transform: translateY(1px); }
  button:disabled { opacity: .45; cursor: not-allowed; }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  button.primary:hover:not(:disabled) { background: var(--accent-2); border-color: var(--accent-2); }
  button.danger { color: var(--danger); border-color: #e3c8c1; }
  button.ghost { margin-left: auto; background: transparent; }
  .status {
    margin: 14px 0 0; font-size: 14px; font-weight: 700; color: var(--accent);
    display: flex; align-items: center; gap: 8px;
  }
  .status::before {
    content: ""; width: 9px; height: 9px; border-radius: 50%;
    background: #9aa69f; display: inline-block;
  }
  .status.running::before { background: #25a36f; box-shadow: 0 0 0 4px rgba(37, 163, 111, .14); }
  .status.error { color: var(--danger); }
  .status.error::before { background: var(--danger); }
  .log-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  h2 { font-size: 15px; margin: 0; letter-spacing: .01em; }
  .log-head span { font-size: 12px; color: var(--muted); }
  pre#log {
    margin: 12px 0 0; background: var(--log-bg); color: var(--log-ink);
    border-radius: 12px; padding: 14px; min-height: 220px; max-height: 380px;
    overflow: auto; white-space: pre-wrap; word-break: break-word;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Noto Sans Mono",
                 monospace; font-size: 12.5px; line-height: 1.6;
  }
  .hint { color: var(--muted); font-size: 12.5px; margin: 14px 2px 0; }
  code { background: #ece8de; border-radius: 6px; padding: 1px 5px; font-size: 12px; }
  @media (max-width: 700px) {
    .grid { grid-template-columns: 1fr; }
    .ghost { margin-left: 0; }
  }
</style>
</head>
<body>
<main>
  <header>
    <span class="eyebrow">Local GUI</span>
    <h1>เฝ้าเกรด แล้ว export ทั้งห้อง</h1>
    <p>ใช้บัญชีเดียวตรวจหาการเปลี่ยนแปลงเมื่อภาพหน้าเว็บเปลี่ยน ระบบจะดึงผลการเรียนของทุกคนเป็นไฟล์ Excel</p>
  </header>

  <section class="card">
    <div class="grid">
      <label class="field">ภาคที่จะเฝ้า
        <select id="term"></select>
      </label>
      <label class="field">บัญชีกระตุ้น
        <select id="trigger"></select>
      </label>
      <label class="field">ตรวจทุก (วินาที)
        <input id="interval" type="number" min="10" max="3600" step="5" value="60">
      </label>
    </div>
    <div class="checks">
      <label><input id="once" type="checkbox" checked> หยุดหลัง export ครั้งแรก</label>
      <label><input id="headed" type="checkbox"> แสดงเบราว์เซอร์ (debug)</label>
    </div>
    <div class="actions">
      <button id="start" class="primary" type="button">เริ่มเฝ้า</button>
      <button id="stop" class="danger" type="button" disabled>หยุด</button>
      <button id="open" type="button">เปิดโฟลเดอร์ exports</button>
      <button id="shutdown" class="ghost" type="button">ปิด GUI</button>
    </div>
    <p id="status" class="status">พร้อมทำงาน</p>
  </section>

  <section class="card">
    <div class="log-head">
      <h2>บันทึก</h2>
      <span>อัปเดตทุก 1 วินาที</span>
    </div>
    <pre id="log"></pre>
  </section>

  <p class="hint">ไฟล์ Excel จะถูกบันทึกที่ <code id="exportdir">-</code> — เมื่อรันผ่าน Discord บอทจะแนบไฟล์ในช่อง Webhook</p>
</main>

<script>
const $ = (id) => document.getElementById(id);
let lastId = 0;
let running = false;
let hasRoster = false;

const esc = (value) => String(value).replace(/[&<>"']/g, (ch) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[ch]));

async function api(path, options) {
  const res = await fetch(path, Object.assign({cache: "no-store"}, options || {}));
  let data = {};
  try { data = await res.json(); } catch (e) {}
  if (!res.ok) throw new Error(data.error || data.message || ("HTTP " + res.status));
  return data;
}

function appendLine(ev) {
  const log = $("log");
  const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
  log.textContent += "[" + ev.t + "] " + ev.msg + "\n";
  if (atBottom) log.scrollTop = log.scrollHeight;
}

function setRunning(value) {
  running = !!value;
  $("start").disabled = running || !hasRoster;
  $("stop").disabled = !running;
  $("status").classList.toggle("running", running);
}

function showError(message) {
  $("status").textContent = message;
  $("status").classList.add("error");
  $("status").classList.remove("running");
}

async function loadConfig() {
  const cfg = await api("/api/config");
  hasRoster = cfg.roster.length > 0;
  $("term").innerHTML = cfg.terms
    .map((t) => `<option value="${t.value}">${esc(t.label)}</option>`).join("");
  if (hasRoster) {
    $("trigger").innerHTML = cfg.roster
      .map((r) => `<option value="${esc(r.sid)}">${esc(r.sid)} — ${esc(r.name || "(ไม่มีชื่อ)")}</option>`)
      .join("");
  } else {
    $("trigger").innerHTML = `<option value="">ไม่พบรายชื่อ</option>`;
    $("start").disabled = true;
    showError("ไม่พบ students.csv หรือรายชื่อที่ใช้ได้");
  }
  $("interval").value = cfg.interval || 60;
  $("exportdir").textContent = cfg.export_dir || "-";
  for (const err of (cfg.errors || [])) {
    $("log").textContent += "[config] " + err + "\n";
  }
}

async function poll() {
  try {
    const data = await api("/api/events?since=" + lastId);
    for (const ev of data.events) {
      appendLine(ev);
      lastId = Math.max(lastId, ev.id);
    }
    if (data.status) {
      $("status").textContent = data.status;
      $("status").classList.toggle("error", !!data.status_error);
    }
    setRunning(data.running);
  } catch (e) {
    // เซิร์ฟเวอร์อาจถูกปิดอยู่ — ไม่ต้องรบกวนผู้ใช้
  }
  setTimeout(poll, 1000);
}

$("start").addEventListener("click", async () => {
  $("status").classList.remove("error");
  try {
    setRunning(true);
    await api("/api/start", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        term: Number($("term").value),
        sid: $("trigger").value,
        interval: Number($("interval").value),
        once: $("once").checked,
        headed: $("headed").checked
      })
    });
  } catch (e) {
    setRunning(false);
    showError(e.message);
  }
});

$("stop").addEventListener("click", async () => {
  try { await api("/api/stop", {method: "POST"}); }
  catch (e) { showError(e.message); }
});

$("open").addEventListener("click", async () => {
  try { await api("/api/open-exports", {method: "POST"}); }
  catch (e) { showError(e.message); }
});

$("shutdown").addEventListener("click", async () => {
  if (!confirm("ปิด GUI? (ถ้ากำลังเฝ้าอยู่ ระบบจะหยุดด้วย)")) return;
  try { await api("/api/shutdown", {method: "POST"}); } catch (e) {}
  $("status").textContent = "ปิด GUI แล้ว — ปิดแท็บนี้ได้";
});

loadConfig().catch((e) => showError("โหลดค่าไม่สำเร็จ: " + e.message)).then(poll);
</script>
</body>
</html>
"""


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.events = []
        self.next_id = 1
        self.running = False
        self.status = "พร้อมทำงาน"
        self.status_error = False
        self.thread = None
        self.stop_event = None
        self.roster = []
        self.errors = []
        self.server = None

    # ---------- log/status ----------
    def log(self, msg):
        with self.lock:
            self.events.append({
                "id": self.next_id,
                "t": time.strftime("%H:%M:%S"),
                "msg": str(msg),
            })
            self.next_id += 1
            if len(self.events) > 500:
                self.events = self.events[-500:]

    def set_status(self, text, error=False):
        with self.lock:
            self.status = str(text)
            self.status_error = bool(error)

    def snapshot(self, since=0):
        with self.lock:
            return {
                "events": [e for e in self.events if e["id"] > since],
                "running": self.running,
                "status": self.status,
                "status_error": self.status_error,
            }

    # ---------- roster ----------
    def load_roster(self):
        try:
            self.roster, self.errors = export_grades.load_roster(
                export_grades.DEFAULT_ROSTER)
        except SystemExit as ex:
            self.roster, self.errors = [], [str(ex)]
        except Exception as ex:
            self.roster, self.errors = [], [str(ex)]
        for err in self.errors[:10]:
            self.log(f"⚠️ {err}")
        if not self.roster:
            self.log("❌ ไม่พบ students.csv หรือรายชื่อที่ใช้ได้")
            self.set_status("ไม่พบ students.csv — วางไฟล์ที่ repo root", error=True)

    def config(self):
        return {
            "terms": [
                {"value": i, "label": f"ปี{y} ภาค{t}"}
                for i, (y, t) in enumerate(auto_export.TERM_BUTTONS, 1)
            ],
            "roster": [
                {"sid": str(r["sid"]), "name": r.get("name") or ""}
                for r in self.roster
            ],
            "interval": auto_export.g.INTERVAL,
            "export_dir": str(auto_export.EXPORT_DIR),
            "errors": self.errors[:10],
        }

    # ---------- worker ----------
    def _fail(self, msg):
        self.set_status(msg, error=True)
        self.log(f"❌ {msg}")
        return False, msg

    def start(self, term, sid, interval, once, headed):
        if not self.roster:
            return self._fail("ไม่พบรายชื่อ — ต้องมี students.csv ก่อน")
        try:
            term = int(term)
            if not 1 <= term <= 6:
                raise ValueError
        except (TypeError, ValueError):
            return self._fail("เลขภาคต้องอยู่ระหว่าง 1-6")
        try:
            interval = float(interval)
            if interval < 10:
                raise ValueError
        except (TypeError, ValueError):
            return self._fail("ระยะเวลาตรวจต้องเป็นตัวเลขตั้งแต่ 10 วินาทีขึ้นไป")

        sid = str(sid or "").strip()
        if sid:
            rec = next((r for r in self.roster if str(r["sid"]) == sid), None)
            if rec is None:
                return self._fail(f"ไม่พบรหัส {sid} ใน students.csv")
        else:
            rec = self.roster[0]

        with self.lock:
            already = self.running
            if not already:
                self.running = True
                self.status = "กำลังเริ่ม..."
                self.status_error = False
                self.stop_event = threading.Event()
                stop = self.stop_event
        if already:
            return self._fail("กำลังทำงานอยู่แล้ว")

        y, t = auto_export.TERM_BUTTONS[term - 1]
        self.log(f"เริ่มเฝ้าด้วย {rec['sid']} | ปี{y} ภาค{t} | ทุก {int(interval)} วินาที")
        self.thread = threading.Thread(
            target=self._worker,
            args=(rec, term, y, t, interval, bool(once), bool(headed), stop),
            daemon=True,
            name=f"autoexport-gui-{rec['sid']}",
        )
        self.thread.start()
        return True, f"เริ่มเฝ้า {rec['sid']} ปี{y} ภาค{t} แล้ว"

    def _worker(self, rec, term, y, t, interval, once, headed, stop):
        old_webhook = auto_export.g.WEBHOOK
        old_step = auto_export.g.step
        auto_export.g.WEBHOOK = ""      # GUI ไม่ต้องยิง log เอนจินเข้า Discord
        auto_export.g.step = lambda msg, file_path=None, mention=False: self.log(msg)
        ok = False

        def notify(msg, file_path=None, mention=False):
            self.log(msg)
            if msg.startswith("✅ ล็อกอิน"):
                self.set_status("กำลังเฝ้า...")
            elif msg.startswith("📌"):
                self.set_status("กำลังเฝ้า — บันทึก baseline แล้ว")
            elif msg.startswith("…"):
                self.set_status("กำลังเฝ้า...")
            elif msg.startswith("⚠️"):
                self.set_status("ตรวจรอบล่าสุดไม่สำเร็จ — กำลังลองใหม่", error=True)
            elif msg.startswith("❌"):
                self.set_status(msg[:160], error=True)

        async def on_change(info):
            diff = f"{info['diff']}%" if info["diff"] is not None else "?"
            self.set_status("พบการเปลี่ยนแปลง — กำลัง export ทั้งห้อง...")
            self.log(f"🎉 พบการเปลี่ยนแปลง (ต่าง {diff}) — เริ่ม export")
            out = auto_export.default_out(y, t)
            rc, output = await auto_export.export_roster_async(
                term, out, workers=3, stagger=2)
            if rc != 0:
                self.log("❌ export ไม่สำเร็จ")
                self.log((output or "ไม่มี output")[-2500:])
                self.set_status("export ไม่สำเร็จ", error=True)
                return None
            self.log(f"✅ export เสร็จ: {out}")
            self.set_status(f"export เสร็จ: {out.name}")
            return out

        try:
            ok = asyncio.run(auto_export.watch_trigger(
                None, rec, (y, t), stop=stop, on_change=on_change, notify=notify,
                interval=interval, once=once, headed=headed))
            self.log("✅ จบการทำงาน" if ok else "🛑 หยุดเฝ้าแล้ว")
        except Exception as ex:
            self.log(f"❌ {str(ex)[:500]}")
            self.set_status("เกิดข้อผิดพลาด", error=True)
        finally:
            auto_export.g.WEBHOOK = old_webhook
            auto_export.g.step = old_step
            with self.lock:
                self.running = False
                if ok:
                    self.status = "เสร็จสิ้น — พร้อมเริ่มใหม่"
                    self.status_error = False
                elif self.status_error:
                    pass
                else:
                    self.status = "หยุดแล้ว — พร้อมเริ่มใหม่"
                    self.status_error = False

    def stop(self):
        with self.lock:
            if not self.running or self.stop_event is None:
                return False, "ยังไม่ได้ทำงาน"
            self.stop_event.set()
            self.status = "กำลังหยุด (จะหยุดหลังจบงานปัจจุบัน)..."
            self.status_error = False
        self.log("สั่งหยุดแล้ว")
        return True, "สั่งหยุดแล้ว"

    def open_exports(self):
        path = auto_export.EXPORT_DIR
        path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as ex:
            return False, f"เปิดโฟลเดอร์ไม่ได้: {ex}"
        return True, "เปิดโฟลเดอร์ exports แล้ว"

    def shutdown(self):
        self.stop()
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=5)


class Handler(BaseHTTPRequestHandler):
    state: State = None

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        if n > 65536:
            raise ValueError("payload ใหญ่เกินไป")
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._html(INDEX_HTML)
            elif parsed.path == "/api/config":
                self._json(self.state.config())
            elif parsed.path == "/api/events":
                qs = parse_qs(parsed.query)
                try:
                    since = int((qs.get("since") or ["0"])[0])
                except ValueError:
                    since = 0
                self._json(self.state.snapshot(since))
            elif parsed.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
            else:
                self._json({"error": "not found"}, 404)
        except Exception as ex:
            self._json({"error": str(ex)}, 500)

    def do_POST(self):
        try:
            origin = self.headers.get("Origin")
            if origin and not (origin.startswith("http://127.0.0.1:")
                               or origin.startswith("http://localhost:")):
                self._json({"error": "forbidden"}, 403)
                return
            parsed = urlparse(self.path)
            if parsed.path == "/api/start":
                data = self._read_json()
                ok, msg = self.state.start(
                    data.get("term"), data.get("sid"), data.get("interval"),
                    data.get("once", True), data.get("headed", False))
                self._json({"ok": ok, "message": msg}, 200 if ok else 400)
            elif parsed.path == "/api/stop":
                ok, msg = self.state.stop()
                self._json({"ok": ok, "message": msg}, 200 if ok else 400)
            elif parsed.path == "/api/open-exports":
                ok, msg = self.state.open_exports()
                self._json({"ok": ok, "message": msg}, 200 if ok else 500)
            elif parsed.path == "/api/shutdown":
                self._json({"ok": True, "message": "กำลังปิด GUI"})
                if self.state.server is not None:
                    threading.Thread(target=self.state.server.shutdown, daemon=True).start()
            else:
                self._json({"error": "not found"}, 404)
        except Exception as ex:
            self._json({"error": str(ex)}, 500)


def main():
    ap = argparse.ArgumentParser(description="GUI เว็บในเครื่องสำหรับ auto-export")
    ap.add_argument("--port", type=int, default=0,
                    help="พอร์ตที่ต้องการ (ค่าเริ่มต้น 0 = สุ่มพอร์ตว่าง)")
    ap.add_argument("--no-browser", action="store_true",
                    help="ไม่ต้องเปิดเบราว์เซอร์อัตโนมัติ")
    args = ap.parse_args()

    state = State()
    state.load_roster()
    Handler.state = state

    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as ex:
        print(f"❌ เปิดพอร์ต {args.port} ไม่ได้: {ex}")
        return 1
    server.daemon_threads = True
    state.server = server
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"

    print("Dograde GUI:", url)
    print("ปิดด้วย Ctrl+C หรือปุ่ม 'ปิด GUI' ในหน้าเว็บ")
    if not args.no_browser and not os.environ.get("DOGRADE_GUI_NO_BROWSER"):
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nปิด GUI")
    finally:
        state.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
