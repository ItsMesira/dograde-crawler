"""
เฝ้าเกรด https://dograde.online/prakan/  (เวอร์ชัน 3)

- ถามแค่ รหัสนักเรียน + วันเกิด
- ทุกขั้นตอนแจ้งใน Discord (เปิดเว็บ/กรอก/กดเข้า/เลือกปีภาค/อ่านค่า/เทียบ/เสร็จรอบ)
- แคปภาพทุกหน้า เก็บเป็นโฟลเดอร์แยก:  shots/<รหัส>/ปี1_ภาค1/ ... ปี3_ภาค2/ , ปพ1/ , error/
- ทุกรอบเช็คตามลำดับ ปี1ภาค1 → ปี1ภาค2 → ปี2ภาค1 → ปี2ภาค2 → ปี3ภาค1 → ปี3ภาค2 → ปพ.1 → Info.
- error ทุกชนิดจะลองใหม่เรื่อยๆ ไม่หยุด (หยุดเองด้วย Ctrl + C)

รัน:
    python grade_watch_v3.py             # วนเช็คเรื่อยๆ
    python grade_watch_v3.py --debug     # เปิดเบราว์เซอร์ให้ดู + เช็ครอบเดียว (กวาดทุกภาค)
    python grade_watch_v3.py --test      # ทดสอบแท็ก Discord
    python grade_watch_v3.py --discover  # ล็อกอินแล้วสรุปปุ่ม/dropdown ของเว็บส่ง Discord (ไว้ปรับการเลือกปี/ภาค)
"""
import asyncio, collections, json, mimetypes, os, random, re, shutil, statistics, sys, time, datetime
from pathlib import Path

try:  # กัน cmd ภาษาไทยพังตอนพิมพ์อีโมจิ
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
from playwright.async_api import async_playwright

try:  # ไม่บังคับ: ถ้าติดตั้ง psutil (pip install psutil) จะแสดง CPU/RAM/เน็ตของเครื่องเราด้วย
    import psutil
except Exception:
    psutil = None

try:  # ต้องมีไว้เทียบภาพ (pip install pillow) ไม่งั้นจะใช้การเทียบข้อความแทนอัตโนมัติ
    from PIL import Image, ImageChops, ImageStat
except Exception:
    Image = None

# ================== ตั้งค่า ==================
URL = "https://dograde.online/prakan/"
GRADE_COLUMN = "ระดับคะแนน"
MONITOR = (1, 1)                                   # (ปี, ภาค) ที่เช็คทุกรอบ
TERMS = [(y, t) for y in (1, 2, 3) for t in (1, 2)]  # ปี1ภาค1 ... ปี3ภาค2

# Webhook/แท็ก: อ่านจาก bot_config.json (ไฟล์นี้ไม่ควร push ขึ้น GitHub — ดู .gitignore)
# ลำดับความสำคัญ: ตัวแปรสภาพแวดล้อม DISCORD_WEBHOOK/MENTION_ID > ค่าใน bot_config.json
_CFG_PATH = Path(__file__).with_name("bot_config.json")
try:
    _cfg = json.loads(_CFG_PATH.read_text(encoding="utf-8")) if _CFG_PATH.exists() else {}
except Exception as _e:
    print(f"[!] อ่าน {_CFG_PATH.name} ไม่สำเร็จ ({_e}); จะใช้ตัวแปรสภาพแวดล้อมแทนถ้ามี")
    _cfg = {}

WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip() or str(_cfg.get("WEBHOOK_URL", "")).strip()
MENTION_ID = os.environ.get("MENTION_ID", "").strip() or str(_cfg.get("ALLOWED_USER_ID", "")).strip()

INTERVAL = 60            # วินาที พักระหว่างรอบ (ตอนปกติ)
RETRY_FAST = 20          # วินาที พักตอนรอบล้มเหลว
SWEEP_EVERY_MIN = 60     # กวาดทุกปี/ภาค + ปพ.1 ทุกกี่นาที (0 = ไม่กวาดตามเวลา กวาดเฉพาะตอนเริ่ม/เกรดเปลี่ยน)
TIMEOUT_MS = 15000       # รอแต่ละขั้นบนหน้าเว็บ (มิลลิวินาที)
SPAM_COUNT = 10          # จำนวนครั้งแท็กรัวตอนเกรดเปลี่ยน
SPAM_DELAY = 2
SLOW_MS = 2500           # ตอบช้ากว่านี้ = 🟡 ช้า
VERY_SLOW_MS = 6000      # ตอบช้ากว่านี้ = 🟠 ช้ามาก (มักเป็นช่วงคนเข้าเยอะ)
PROBE_TIMEOUT = 20       # วินาที รอเว็บตอบตอนตรวจสถานะ
MAX_UPLOAD = 8 * 1024 * 1024   # ไฟล์ใหญ่กว่านี้ไม่อัปโหลด Discord (แต่ยังเก็บในเครื่อง)
IMG_DIFF_THRESHOLD = 0.4        # % ความต่างของภาพ ถ้าเกินนี้ถือว่า "เปลี่ยน" (ต้องมี Pillow)

SEL_SUBMIT = ('input[type="submit"]:visible, button[type="submit"]:visible, '
              'input[type="image"]:visible, button:visible:has-text("เข้าสู่ระบบ")')
NAME_RE = re.compile(r"((?:นางสาว|นาย|นาง|เด็กชาย|เด็กหญิง|ด\.ช\.|ด\.ญ\.)\s*[ก-๙]+(?:\s+[ก-๙]+)?)")

BASE_DIR = Path("shots")
# =============================================


def now_s():
    return datetime.datetime.now().strftime("%H:%M:%S")


# ---------- Discord ----------
_last_send = 0.0


def discord(text, file_path=None, mention=False):
    """ส่งข้อความ (+ไฟล์) เข้า Discord คืน True/False ไม่ throw error"""
    global _last_send
    if not WEBHOOK:
        return False
    text = text[:1900]
    payload = {"content": text,
               "allowed_mentions": {"users": [MENTION_ID] if mention else []}}
    for _ in range(4):
        try:
            gap = 0.5 - (time.time() - _last_send)
            if gap > 0:
                time.sleep(gap)
            fp = Path(file_path) if file_path else None
            if fp and fp.exists() and fp.stat().st_size <= MAX_UPLOAD:
                mime = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
                with open(fp, "rb") as f:
                    r = requests.post(WEBHOOK, data={"payload_json": json.dumps(payload)},
                                      files={"file": (fp.name, f, mime)}, timeout=60)
            else:
                if fp:
                    payload["content"] = (text + "\n(ไฟล์ส่งไม่ได้: ใหญ่เกินหรือไม่พบ เก็บไว้ในเครื่องแล้ว)")[:1900]
                r = requests.post(WEBHOOK, json=payload, timeout=30)
            _last_send = time.time()
            if r.status_code == 429:
                try:
                    wait = float(r.json().get("retry_after", 2))
                except Exception:
                    wait = 2
                time.sleep(wait + 0.5)
                continue
            if r.status_code >= 300:
                print(f"[!] Discord ตอบกลับ {r.status_code}: {r.text[:150]}")
                return False
            return True
        except Exception as e:
            print("ส่ง Discord ไม่สำเร็จ:", str(e)[:150])
            time.sleep(2)
    return False


def step(msg, file_path=None, mention=False):
    """พิมพ์ใน cmd + ส่ง Discord (ทุกการกระทำ)"""
    print(f"[{now_s()}] {msg.splitlines()[0][:160]}")
    discord(f"`{now_s()}` {msg}", file_path, mention)


def alert(text, file_path, name):
    tag = f"<@{MENTION_ID}>"
    print(f"[{now_s()}] 🎉 เกรดมีการเปลี่ยนแปลง!")
    discord(f"{tag} {text}", file_path, mention=True)
    for i in range(2, SPAM_COUNT + 1):
        time.sleep(SPAM_DELAY)
        discord(f"{tag} 🚨 เกรดของ **{name}** ออกแล้ว! เข้าไปดูเลย! ({i}/{SPAM_COUNT})", None, mention=True)


# ---------- โฟลเดอร์/ไฟล์ ----------
def term_folder(sid, y, t):
    p = BASE_DIR / sid / f"ปี{y}_ภาค{t}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def special_folder(sid, name):
    p = BASE_DIR / sid / name
    p.mkdir(parents=True, exist_ok=True)
    return p


async def snap(page, folder, label):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(folder) / f"{label}_{ts}.png"
    await page.screenshot(path=str(path), full_page=True)
    return path


# ---------- ช่วยจัดการหน้าเว็บ ----------
async def settle(page):
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    await page.wait_for_timeout(800)


async def click_by_text(page, pattern):
    """หาและคลิกตามข้อความ ค้นหาในทุก frame (รวม iframe)"""
    rx = re.compile(pattern)
    for fr in page.frames:
        getters = (lambda: fr.get_by_role("link", name=rx),
                   lambda: fr.get_by_role("button", name=rx),
                   lambda: fr.get_by_text(rx))
        for g in getters:
            try:
                loc = g()
                if await loc.count() > 0 and await loc.first.is_visible():
                    await loc.first.click(timeout=5000)
                    return True
            except Exception:
                continue
    return False


_JS_CLICK = """
(needle) => {
  const norm = s => (s || '').replace(/[\\s\\u200b-\\u200d\\ufeff]/g, '').toLowerCase();
  const n = norm(needle);
  let best = null, bestLen = 1e9;
  for (const el of document.querySelectorAll('a,button,input,span,div,li,td,label,[onclick]')) {
    const t = norm(el.tagName === 'INPUT' ? el.value : el.textContent);
    if (!t.includes(n) || t.length > n.length + 6) continue;
    if (!el.getClientRects().length) continue;
    if (t.length < bestLen) { best = el; bestLen = t.length; }
  }
  if (!best) return false;
  (best.closest('a,button,input,[onclick]') || best).click();
  return true;
}
"""


async def js_click(page, needle):
    """สำรอง: คลิกด้วย JavaScript ในทุก frame โดยเทียบข้อความที่ตัดช่องว่าง/อักขระล่องหนออกแล้ว"""
    for fr in page.frames:
        try:
            if await fr.evaluate(_JS_CLICK, needle):
                return True
        except Exception:
            continue
    return False


async def click_label(page, pattern, needle):
    if await click_by_text(page, pattern):
        return True
    return await js_click(page, needle)


_JS_DUMP = """
() => {
  const out = [];
  for (const el of document.querySelectorAll('a,button,input[type=button],input[type=submit],[onclick]')) {
    const t = ((el.tagName === 'INPUT' ? el.value : el.textContent) || '').replace(/\\s+/g, ' ').trim();
    if (t) out.push(el.tagName.toLowerCase() + ':' + t.slice(0, 30));
  }
  return out.slice(0, 40);
}
"""


async def dump_clickables(page):
    parts = []
    for i, fr in enumerate(page.frames):
        try:
            items = await fr.evaluate(_JS_DUMP)
        except Exception:
            items = []
        parts.append(f"frame{i} ({(fr.url or '')[:60]}): " + ", ".join(items))
    return "\n".join(parts)


def term_patterns(y, t):
    return [rf"^\s*ปี\s*{y}\s*ภาค\s*{t}\s*$",
            rf"ปี\D{{0,8}}{y}\D{{0,12}}ภาค\D{{0,8}}{t}",
            rf"ชั้น\D{{0,8}}{y}\D{{0,12}}(ภาค|เทอม)\D{{0,8}}{t}",
            rf"(^|\D){y}\s*/\s*{t}(\D|$)"]


async def pick_select(page, y, t):
    """เลือกปี/ภาคจาก dropdown (<select>) คืนข้อความอธิบายวิธี หรือ None"""
    combo = re.compile(rf"ปี\D{{0,8}}{y}\D{{0,12}}ภาค\D{{0,8}}{t}|(^|\D){y}\s*/\s*{t}(\D|$)")
    yr_rx = re.compile(rf"(ปี|ชั้น|ม\.?)\D{{0,8}}{y}(\D|$)")
    tm_rx = re.compile(rf"(ภาค|เทอม|term)\D{{0,8}}{t}(\D|$)", re.I)
    used = []
    try:
        n = await page.locator("select:visible").count()
    except Exception:
        return None
    for i in range(n):  # query ใหม่ทุกครั้ง เพราะ postback อาจสร้าง DOM ใหม่
        try:
            sel = page.locator("select:visible").nth(i)
            opts = [o.strip() for o in await sel.locator("option").all_inner_texts()]
            meta = (((await sel.get_attribute("id")) or "") + " " + ((await sel.get_attribute("name")) or "")).lower()
            year_hint = re.search(r"year|yr|class|level|grade|ปี|ชั้น", meta)
            term_hint = re.search(r"term|sem|ภาค|เทอม", meta)
            hit = next((o for o in opts if combo.search(o)), None) \
                or next((o for o in opts if yr_rx.search(o)), None) \
                or next((o for o in opts if tm_rx.search(o)), None) \
                or (next((o for o in opts if o == str(y)), None) if year_hint else None) \
                or (next((o for o in opts if o == str(t)), None) if term_hint else None)
            if hit:
                await sel.select_option(label=hit)
                used.append(hit)
                await settle(page)
        except Exception:
            continue
    if used:
        await click_by_text(page, r"^\s*(แสดง|แสดงผล|ค้นหา|ดูผล|ตกลง)\s*$")
        await settle(page)
        return "dropdown: " + " + ".join(used)
    return None


_METHOD_LABEL = ["คลิกปุ่มตรงชื่อพอดี", "คลิกปุ่ม (รูปแบบเต็ม)",
                 "คลิกปุ่ม (รูปแบบชื่อชั้น)", "คลิกปุ่ม (รูปแบบย่อ)"]


async def go_term(page, y, t):
    """ไปหน้าปี y ภาค t คืนข้อความวิธีที่ใช้ (อ่านง่าย ไม่โชว์ regex) หรือ None ถ้าไม่เจอตัวเลือก"""
    m = await pick_select(page, y, t)
    if m:
        return m
    for i, pat in enumerate(term_patterns(y, t)):
        if await click_by_text(page, pat):
            await settle(page)
            return _METHOD_LABEL[i] if i < len(_METHOD_LABEL) else "คลิกปุ่ม"
    if await js_click(page, f"ปี{y}ภาค{t}"):
        await settle(page)
        return "คลิกปุ่ม (วิธีสำรอง)"
    if await click_by_text(page, rf"^\s*(ปี|ชั้น)\D{{0,6}}{y}\s*$"):
        await settle(page)
        if await click_by_text(page, rf"^\s*(ภาค|เทอม)\D{{0,6}}{t}\s*$"):
            await settle(page)
            return "คลิกปี แล้วคลิกภาค"
        return "คลิกปีได้ แต่ไม่พบภาค"
    return None


async def read_grades(page):
    result = []
    for table in await page.locator("table").all():
        try:
            headers = [h.strip() for h in await table.locator("tr").first.locator("th, td").all_inner_texts()]
            idx = next((i for i, h in enumerate(headers) if GRADE_COLUMN in h), None)
            if idx is None:
                continue
            for row in (await table.locator("tr").all())[1:]:
                cells = [c.strip() for c in await row.locator("td").all_inner_texts()]
                if len(cells) > idx:
                    nm = cells[1] if len(cells) > 1 else cells[0]
                    result.append(f"{nm}: {cells[idx]}")
        except Exception:
            continue
    return result


async def read_page(page):
    body = await page.inner_text("body")
    if "Server Error" in body or "Runtime Error" in body:
        raise Exception("เว็บล่ม: ขึ้นหน้า Server Error ระหว่างเปิดหน้าผลการเรียน")
    m = re.search(r"ปรับปรุง[^\d]*(\d{1,2}:\d{2}\s+\d{1,2}/\d{1,2}/\d{4})", body)
    updated = re.sub(r"\s+", " ", m.group(1)).strip() if m else None
    nm = NAME_RE.search(body)
    name = re.sub(r"\s+", " ", nm.group(1)).strip() if nm else None
    return body, updated, await read_grades(page), name


def is_graded(g):
    return g.rsplit(":", 1)[-1].strip() not in ("0", "", "-")


# ---------- ล็อกอิน ----------
async def _on_dialog(d, dialogs):
    """Playwright async: dialog.accept() เป็น coroutine ต้อง await จึงต้องเป็น handler แบบ async"""
    try:
        dialogs.append(d.message)
        await d.accept()
    except Exception:
        pass


async def login(page, S, dialogs):
    sid, pw = S["sid"], S["pw"]
    step("🌐 กำลังเปิดเว็บ")
    resp = await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
    if resp is not None and resp.status >= 400:
        raise Exception(f"เว็บตอบกลับ HTTP {resp.status}")
    await settle(page)

    top = await page.inner_text("body")
    if "Server Error" in top or "Runtime Error" in top:
        raise Exception("เว็บล่ม: ขึ้นหน้า Server Error ตั้งแต่เปิดเว็บ (เซิร์ฟเวอร์ของเว็บพัง ไม่ใช่ปัญหารหัส/สคริปต์)")
    fields = page.locator(
        'input:visible:not([type="hidden"]):not([type="submit"]):not([type="button"])'
        ':not([type="image"]):not([type="checkbox"]):not([type="radio"])')
    n = await fields.count()
    if n < 2:
        raise Exception(f"หาช่องกรอกรหัส/วันเกิดไม่พบ (เจอ {n} ช่อง) เว็บอาจล่มหรือโหลดไม่เต็ม")
    step(f"⌨️ กรอกรหัสนักเรียน {sid} และวันเกิด")
    await fields.nth(0).fill(sid)
    await fields.nth(1).fill(pw)

    step("🔑 กดเข้าสู่ระบบ")
    sub = page.locator(SEL_SUBMIT)
    submitted = False
    if await sub.count() > 0:
        try:
            await sub.first.click(timeout=8000)
            submitted = True
        except Exception as e:
            # เว็บนี้เปลี่ยนหน้าทันทีตอนคลิก (ASP.NET postback) บางครั้ง Playwright
            # รายงาน error ทั้งที่คลิกสำเร็จแล้วจริงๆ เพราะปุ่มเดิม "หายไป" กลางคลิก
            # จึงเช็คสถานะหน้าจริงก่อน ไม่รีบสรุปว่าคลิกไม่สำเร็จ
            step(f"ℹ️ คลิกปุ่มมีข้อความเตือน ({str(e)[:70]}) กำลังตรวจว่าจริงๆ ผ่านไปหรือยัง")
    # ไม่ว่าจะคลิกสำเร็จ/error ให้รอหน้านิ่งแล้วดูว่าออกจากหน้า login ไปหรือยัง
    try:
        await page.wait_for_url(re.compile(r"DooTerm", re.I), timeout=10000)
        submitted = True
    except Exception:
        pass
    await settle(page)
    if not submitted:
        try:
            flat_now = re.sub(r"\s+", "", await page.inner_text("body"))
            if "ปรับปรุง" in flat_now or "ปี1ภาค1" in flat_now or "DooTerm" in page.url:
                submitted = True
        except Exception:
            pass
    if not submitted:
        # คลิกจริงๆ ไม่ติด ลองกด Enter แทน (จำกัดเวลาสั้นลง กันค้าง)
        try:
            await page.locator(
                'input:visible:not([type="hidden"]):not([type="submit"]):not([type="button"])'
                ':not([type="image"]):not([type="checkbox"]):not([type="radio"])'
            ).nth(1).press("Enter", timeout=8000)
        except Exception as e2:
            step(f"⚠️ กด Enter แทนก็ไม่ได้ ({str(e2)[:70]})")
        await settle(page)
    await page.wait_for_timeout(500)

    body = await page.inner_text("body")
    if "Server Error" in body or "Runtime Error" in body:
        raise Exception(f"ขึ้นหน้า Server Error หลังกดเข้าสู่ระบบ (URL ตอนนี้: {page.url})")
    flat = re.sub(r"\s+", "", body)
    if "ปรับปรุง" not in flat and "ปี1ภาค1" not in flat:
        msg = " | ".join(dialogs[-2:]) if dialogs else re.sub(r"\s+", " ", body)[:150]
        raise Exception(f"ล็อกอินไม่ผ่านหรือไม่ได้หน้าผลการเรียน (URL ตอนนี้: {page.url}) เว็บแจ้งว่า: {msg}")
    step(f"✅ ล็อกอินสำเร็จ (อยู่ที่ {page.url})")


# ---------- ตรวจการเปลี่ยนแปลง: เทียบภาพ (หลัก) + เทียบข้อความ (ข้อมูลประกอบ) ----------
def image_diff_percent(path_a, path_b):
    """คืน % ความต่างของภาพ (0-100) หรือ None ถ้าเทียบไม่ได้ (ไม่มี Pillow/ไฟล์เสีย)"""
    if Image is None:
        return None
    try:
        im1 = Image.open(path_a).convert("RGB")
        im2 = Image.open(path_b).convert("RGB")
        if im1.size != im2.size:
            im2 = im2.resize(im1.size)
        diff = ImageChops.difference(im1, im2)
        mean = sum(ImageStat.Stat(diff).mean) / 3
        return round(mean / 255 * 100, 3)
    except Exception as e:
        print("เทียบภาพไม่สำเร็จ:", str(e)[:120])
        return None


def text_changes(S, key, updated, grades):
    """เทียบข้อความ/ตารางเกรดไว้ใช้เป็นข้อมูลประกอบในข้อความแจ้งเตือนเท่านั้น (ไม่ใช่ตัวตัดสินอีกต่อไป)"""
    terms = S["state"].setdefault("terms", {})
    old = terms.get(key)
    terms[key] = {"updated": updated, "grades": grades}
    if old is None:
        return []
    ch = []
    if updated != old.get("updated"):
        ch.append(f"🕒 เวลาปรับปรุงเปลี่ยน: {old.get('updated')} → **{updated}**")
    if grades != old.get("grades"):
        diff = [g for g in grades if g not in (old.get("grades") or [])]
        ch.append(f"📊 **{GRADE_COLUMN}** เปลี่ยน:\n" + "\n".join(diff or grades))
    return ch


def save_state(S):
    try:
        (BASE_DIR / S["sid"]).mkdir(parents=True, exist_ok=True)
        (BASE_DIR / S["sid"] / "state.json").write_text(
            json.dumps(S["state"], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print("บันทึก state ไม่สำเร็จ:", e)


def image_check(S, key, folder, new_shot, tag):
    """เทียบภาพใหม่กับภาพฐาน (baseline) ของภาคนี้
    - ครั้งแรก: เก็บภาพนี้เป็นฐาน
    - ครั้งต่อไป: ถ้าต่างเกิน IMG_DIFF_THRESHOLD % ถือว่า "เปลี่ยน" แล้วเลื่อนฐานมาเป็นภาพนี้
    คืน (is_baseline_first_time:bool, changed:bool, diff_pct:float|None)"""
    baselines = S["state"].setdefault("image_baseline", {})
    base_path = Path(folder) / "baseline.png"
    prev_meta = baselines.get(key)
    if prev_meta is None or not base_path.exists():
        shutil.copyfile(new_shot, base_path)
        baselines[key] = {"saved_at": now_s()}
        return True, False, None
    diff_pct = image_diff_percent(base_path, new_shot)
    if diff_pct is None:
        return False, False, None  # ไม่มี Pillow เทียบภาพไม่ได้ ถือว่ายังไม่เปลี่ยน
    changed = diff_pct > IMG_DIFF_THRESHOLD
    if changed:
        shutil.copyfile(new_shot, base_path)  # เลื่อนฐานมาเป็นภาพล่าสุด กันแจ้งซ้ำทุกรอบ
        baselines[key] = {"saved_at": now_s(), "changed_at": now_s()}
    return False, changed, diff_pct


async def process_term(page, S, y, t, tag):
    """แคปภาพ + เทียบกับภาพฐานของภาคนี้ คืน (changed:bool, grades)"""
    body, updated, grades, name = await read_page(page)
    if name and name != S["name"]:
        S["name"] = name
        step(f"👤 พบชื่อในเว็บ: **{name}**")
    folder = term_folder(S["sid"], y, t)
    shot = await snap(page, folder, f"Y{y}T{t}")
    graded = sum(map(is_graded, grades))
    summary = (f"📸 **{tag}** | ปรับปรุง: {updated or 'ไม่พบ'} | "
               f"แถววิชา {len(grades)} | เกรดออกแล้ว {graded}/{len(grades)}")
    if updated is None and not grades:
        snippet = re.sub(r"\s+", " ", body)[:350]
        step(f"⚠️ {summary}\n(หน้านี้ไม่มีข้อมูลเกรด/วันที่ปรับปรุง)\nข้อความที่เห็นในหน้า: {snippet}", shot)
        return False, grades

    extra = text_changes(S, f"{y}/{t}", updated, grades)
    is_first, img_changed, diff_pct = image_check(S, f"{y}/{t}", folder, shot, tag)
    diff_txt = f" (ต่างจากภาพฐาน {diff_pct}%)" if diff_pct is not None else " (ไม่มี Pillow เทียบภาพไม่ได้ ติดตั้งด้วย pip install pillow)"

    if is_first:
        step(f"📌 บันทึกภาพฐาน (ไว้เทียบรอบถัดไป)\n{summary}", shot)
        return False, grades
    if img_changed:
        detail = ("\n".join(extra) + "\n") if extra else ""
        alert(f"🎉 **เกรดของ {S['name']} มีการอัปเดต!** ({tag})\nภาพหน้าเว็บเปลี่ยนไปจากเดิม{diff_txt}\n"
              f"{detail}{summary}", shot, S["name"])
        return True, grades
    step(f"{summary}\n➡️ ภาพเหมือนเดิม{diff_txt} ไม่ถือว่าเปลี่ยน", shot)
    return False, grades


async def do_pp1(page, ctx, S, downloads):
    step("📄 กำลังเปิดช่อง ปพ.1")
    folder = special_folder(S["sid"], "ปพ1")
    before = len(ctx.pages)
    downloads.clear()
    if not await click_label(page, r"ปพ\s*\.?\s*(1|๑)", "ปพ.1"):
        shot = await snap(page, folder, "PP1_notfound")
        step("⚠️ ไม่พบปุ่ม/ลิงก์ ปพ.1 บนหน้านี้ (ส่งภาพหน้าปัจจุบันให้แทน) ลองรัน --discover เพื่อดูชื่อที่แท้จริง", shot)
        return False
    await page.wait_for_timeout(2500)
    await settle(page)
    for d in list(downloads):
        try:
            ext = Path(d.suggested_filename).suffix or ".bin"
            fp = folder / f"PP1_{datetime.datetime.now():%Y%m%d_%H%M%S}{ext}"
            await d.save_as(str(fp))
            step(f"📥 ดาวน์โหลดไฟล์ ปพ.1 ได้: {fp.name}", fp)
        except Exception as e:
            step(f"⚠️ บันทึกไฟล์ที่โหลดไม่ได้: {str(e)[:100]}")
    target = page
    if len(ctx.pages) > before:
        target = ctx.pages[-1]
        try:
            await target.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
    shot = await snap(target, folder, "PP1")
    is_first, img_changed, diff_pct = image_check(S, "pp1", folder, shot, "ปพ.1")
    diff_txt = f" (ต่างจากภาพฐาน {diff_pct}%)" if diff_pct is not None else ""
    if is_first:
        step(f"📌 **ปพ.1**: บันทึกภาพฐาน (ไว้เทียบรอบถัดไป)", shot)
    elif img_changed:
        alert(f"🎉 **ปพ.1 ของ {S['name']} มีการเปลี่ยนแปลง!**\nภาพเปลี่ยนไปจากเดิม{diff_txt}", shot, S["name"])
    else:
        step(f"📸 **ปพ.1**{diff_txt} ไม่มีการเปลี่ยนแปลง", shot)
    if target is not page:
        try:
            await target.close()
        except Exception:
            pass
    return img_changed


async def sweep(page, ctx, S, downloads):
    terms_list = S.get("watch_terms") or TERMS
    watch_pp1 = S.get("watch_pp1", True)
    names = " → ".join(f"ปี{y}ภาค{t}" for y, t in terms_list) + (" → ปพ.1" if watch_pp1 else "")
    step(f"🧹 เริ่มเช็คตามลำดับ: {names}")
    any_change = False
    prev = None
    for idx, (y, t) in enumerate(terms_list):
        tag = f"ปี {y} ภาค {t}"
        method = await go_term(page, y, t)
        if method is None and idx == 0:
            step(f"ℹ️ ไม่พบปุ่ม {tag} ใช้หน้าที่เว็บแสดงอยู่เป็น {tag}")
            if not S.get("diag_sent"):
                S["diag_sent"] = True
                step("🔎 รายการปุ่ม/ลิงก์ที่สคริปต์มองเห็นในหน้า (ส่งข้อความนี้ให้ผมดู):\n"
                     + (await dump_clickables(page))[:1500])
            changed, grades = await process_term(page, S, y, t, tag)
            if not grades:
                raise Exception(f"{tag} อ่านข้อมูลไม่ได้ (ยังไม่ไปต่อภาคอื่น) จะเริ่มรอบใหม่ตั้งแต่ {tag}")
            any_change = any_change or changed
            prev = grades or prev
            continue
        if method is None:
            shot = await snap(page, term_folder(S["sid"], y, t), f"Y{y}T{t}_notfound")
            step(f"⚠️ ไม่พบตัวเลือกเลือก **{tag}** บนหน้าเว็บ (ส่งภาพหน้าปัจจุบันให้)", shot)
            if not S.get("diag_sent"):
                S["diag_sent"] = True
                step("🔎 รายการปุ่ม/ลิงก์ที่สคริปต์มองเห็นในหน้า (ส่งข้อความนี้ให้ผมดู):\n"
                     + (await dump_clickables(page))[:1500])
            continue
        step(f"🔀 เลือก **{tag}** แล้ว ({method})")
        changed, grades = process_term(page, S, y, t, tag)
        if idx == 0 and not grades:
            raise Exception(f"{tag} อ่านข้อมูลไม่ได้ (ยังไม่ไปต่อภาคอื่น) จะเริ่มรอบใหม่ตั้งแต่ {tag}")
        any_change = any_change or changed
        if prev is not None and grades and grades == prev:
            step(f"⚠️ ข้อมูลของ {tag} เหมือนภาคก่อนหน้าทุกประการ อาจเลือกภาคไม่สำเร็จจริง")
        prev = grades or prev
    if watch_pp1:
        try:
            if await do_pp1(page, ctx, S, downloads):
                any_change = True
        except Exception as e:
            step(f"⚠️ ขั้นตอน ปพ.1 มีปัญหา: {str(e)[:150]}")
    step("🧹 กวาดเสร็จ")
    return any_change


# ---------- 1 รอบการเช็ค ----------
async def run_cycle(browser, S, force_sweep=False):
    ctx = await browser.new_context(viewport={"width": 1400, "height": 1000}, accept_downloads=True)
    page = await ctx.new_page()
    dialogs, downloads = [], []
    page.on("dialog", lambda d: asyncio.ensure_future(_on_dialog(d, dialogs)))
    page.on("download", lambda d: downloads.append(d))
    try:
        page.set_default_timeout(TIMEOUT_MS)
        await login(page, S, dialogs)

        changed = await sweep(page, ctx, S, downloads)   # เช็คครบตามลำดับในทุกรอบ
        S["swept_once"] = True
        save_state(S)
        return changed
    except Exception as e:
        # แคปหน้าตอน error แล้วส่งเข้า Discord ก่อนโยน error ต่อ
        try:
            shot = await snap(page, special_folder(S["sid"], "error"), "error")
            e.shot = shot
        except Exception:
            pass
        raise
    finally:
        try:
            await ctx.close()
        except Exception:
            pass


# ---------- โหมดสำรวจโครงสร้างเว็บ ----------
async def discover(browser, S):
    ctx = await browser.new_context(viewport={"width": 1400, "height": 1000})
    page = await ctx.new_page()
    dialogs = []
    page.on("dialog", lambda d: asyncio.ensure_future(_on_dialog(d, dialogs)))
    try:
        page.set_default_timeout(TIMEOUT_MS)
        await login(page, S, dialogs)
        lines = []
        for i in range(await page.locator("select").count()):
            s = page.locator("select").nth(i)
            opts = [o.strip() for o in await s.locator("option").all_inner_texts()][:40]
            lines.append(f"[select] id={await s.get_attribute('id')} name={await s.get_attribute('name')} options={opts}")
        for sel in ("a", "button", 'input[type="submit"]', 'input[type="button"]'):
            for i in range(min(await page.locator(sel).count(), 80)):
                el = page.locator(sel).nth(i)
                txt = (await el.inner_text() if sel in ("a", "button") else await el.get_attribute("value")) or ""
                lines.append(f"[{sel}] text={txt.strip()[:60]!r} id={await el.get_attribute('id')} "
                             f"href={(await el.get_attribute('href') or '')[:60]}")
        body = re.sub(r"\s+", " ", await page.inner_text("body"))[:1500]
        lines.append("\n[body] " + body)
        out = BASE_DIR / S["sid"] / "discover.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines), encoding="utf-8")
        shot = await snap(page, special_folder(S["sid"], "discover"), "discover")
        step("🔍 สรุปโครงสร้างหน้าเว็บ (select/ปุ่ม/ลิงก์) แนบเป็นไฟล์", out)
        step("📸 หน้าหลังล็อกอิน", shot)
        print("\n".join(lines[:60]))
    finally:
        await ctx.close()



# ---------- ตรวจสถานะเว็บ / traffic / เครื่องเรา ----------
HEALTH = collections.deque(maxlen=20)   # ประวัติการตอบสนองของเว็บ
_last_level = None
_net_base = None


def probe_site():
    """ยิง GET เบาๆ ที่หน้าแรก วัดเวลาตอบ/HTTP status/ขนาด/ข้อมูล server คืน dict"""
    t0 = time.time()
    info = {"ok": False, "status": None, "ms": None, "kb": 0, "server": "", "note": ""}
    try:
        r = requests.get(URL, timeout=PROBE_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        info["ms"] = int((time.time() - t0) * 1000)
        info["status"] = r.status_code
        info["kb"] = round(len(r.content) / 1024, 1)
        info["server"] = " ".join(x for x in (r.headers.get("Server", ""),
                                              r.headers.get("X-Powered-By", ""),
                                              r.headers.get("X-AspNet-Version", "")) if x)[:80]
        text = r.text[:6000]
        if r.status_code >= 500:
            info["note"] = f"HTTP {r.status_code}"
        elif "Server Error" in text or "Runtime Error" in text:
            info["note"] = "ขึ้นหน้า Server Error"
        else:
            info["ok"] = r.status_code < 400
            if not info["ok"]:
                info["note"] = f"HTTP {r.status_code}"
    except requests.exceptions.Timeout:
        info["ms"] = int((time.time() - t0) * 1000)
        info["note"] = f"หมดเวลา (>{PROBE_TIMEOUT}s)"
    except Exception as e:
        info["ms"] = int((time.time() - t0) * 1000)
        info["note"] = f"เชื่อมต่อไม่ได้: {str(e)[:70]}"
    return info


def control_ok():
    """เช็คว่าเน็ตเราเองปกติไหม (ยิงไปเว็บกลางที่เสถียร) ไว้แยกว่าเว็บล่มหรือเน็ตเราหลุด"""
    try:
        t0 = time.time()
        r = requests.get("https://www.gstatic.com/generate_204", timeout=8)
        return r.status_code in (200, 204), int((time.time() - t0) * 1000)
    except Exception:
        return False, None


def level_of(info):
    if not info["ok"]:
        return "down"
    if info["ms"] >= VERY_SLOW_MS:
        return "very_slow"
    if info["ms"] >= SLOW_MS:
        return "slow"
    return "ok"


LEVEL_TXT = {"ok": "🟢 ปกติ", "slow": "🟡 ช้า", "very_slow": "🟠 ช้ามาก (น่าจะคนเข้าเยอะ)", "down": "🔴 ล่ม/ใช้ไม่ได้"}


def local_stats():
    global _net_base
    parts = []
    try:
        free_gb = shutil.disk_usage(".").free / 1024 ** 3
        if psutil:
            cpu = psutil.cpu_percent(interval=0.3)
            ram = psutil.virtual_memory().percent
            parts.append(f"CPU {cpu:.0f}% | RAM {ram:.0f}%")
            nio = psutil.net_io_counters()
            if _net_base:
                dt = max(time.time() - _net_base[0], 1)
                down = (nio.bytes_recv - _net_base[1]) / dt / 1024
                up = (nio.bytes_sent - _net_base[2]) / dt / 1024
                parts.append(f"เน็ต ↓{down:.0f} ↑{up:.0f} KB/s")
            _net_base = (time.time(), nio.bytes_recv, nio.bytes_sent)
        parts.append(f"ดิสก์ว่าง {free_gb:.1f} GB")
    except Exception:
        pass
    return " | ".join(parts)


def health_report():
    """ตรวจเว็บ 1 ครั้ง สรุปเข้า Discord และแจ้งเตือนเมื่อสถานะเปลี่ยน"""
    global _last_level
    info = probe_site()
    level = level_of(info)
    HEALTH.append(info)
    ctl_ok, ctl_ms = control_ok()

    ms_list = [h["ms"] for h in HEALTH if h["ok"] and h["ms"] is not None]
    fails = sum(1 for h in HEALTH if not h["ok"])
    line2 = ""
    if ms_list:
        avg = int(statistics.mean(ms_list))
        trend = ""
        if len(ms_list) >= 6:
            recent = statistics.mean(ms_list[-3:])
            before = statistics.mean(ms_list[:-3])
            if recent > before * 1.5:
                trend = " | แนวโน้ม: ⬆️ ช้าลง (คนน่าจะเข้าเยอะขึ้น)"
            elif recent < before * 0.67:
                trend = " | แนวโน้ม: ⬇️ เร็วขึ้น"
        line2 = (f"\n📈 {len(HEALTH)} ครั้งล่าสุด: เฉลี่ย {avg} ms, ช้าสุด {max(ms_list)} ms, "
                 f"ล้มเหลว {fails}/{len(HEALTH)}{trend}")
    elif HEALTH:
        line2 = f"\n📈 {len(HEALTH)} ครั้งล่าสุด: ล้มเหลว {fails}/{len(HEALTH)}"

    net = f"เน็ตเรา: {'ปกติ' if ctl_ok else '❌ มีปัญหา'}" + (f" ({ctl_ms} ms)" if ctl_ms else "")
    head = f"🌐 **สถานะเว็บ**: {LEVEL_TXT[level]}"
    detail = (f"HTTP {info['status']} | {info['ms']} ms | {info['kb']} KB" if info["status"]
              else f"{info['note']} ({info['ms']} ms)")
    if info["note"] and info["status"] and info["note"] != f"HTTP {info['status']}":
        detail += f" | {info['note']}"
    srv = f"\n🖥️ server: {info['server']}" if info["server"] else ""
    loc = local_stats()
    msg = f"{head} | {detail}{srv}{line2}\n📡 {net}" + (f"\n💻 เครื่องเรา: {loc}" if loc else "")
    if level == "down" and not ctl_ok:
        msg += "\n⚠️ เน็ตฝั่งเราก็มีปัญหา จึงยังสรุปไม่ได้ว่าเว็บล่ม"
    elif level == "down":
        msg += "\nℹ️ เน็ตเราปกติ แปลว่าปัญหาอยู่ที่ฝั่งเว็บ"
    step(msg)

    if _last_level is not None and level != _last_level:
        step(f"🔔 สถานะเว็บเปลี่ยน: {LEVEL_TXT[_last_level]} → **{LEVEL_TXT[level]}**")
    _last_level = level
    return level


# ---------- โมเดลใหม่: MAIN เฝ้าต่อเนื่อง / SUB ตื่นมาตอนแฟนเอาต์ ----------
VIEWPORT = {"width": 1400, "height": 1000}


async def astep(msg, file_path=None, mention=False):
    """step() แบบไม่บล็อก event loop (discord() มี time.sleep เพื่อจำกัดอัตราส่ง)"""
    await asyncio.to_thread(step, msg, file_path, mention)


async def _on_grades(page):
    """เกณฑ์เดียวกับ login(): อยู่ในหน้าผลการเรียนจริงไหม"""
    try:
        flat = re.sub(r"\s+", "", await page.inner_text("body"))
    except Exception:
        return False
    return "ปรับปรุง" in flat or "ปี1ภาค1" in flat


class StudentSession:
    """context + page ของนักเรียน 1 คน

    MAIN : เปิดค้างไว้ตลอดอายุเซสชัน แล้ว park ระหว่างรอบ
           (เว็บจะไม่ตัด session เพราะ context ยังเปิดอยู่)
    SUB  : เปิดตอนแฟนเอาต์ -> ล็อกอิน -> เช็ค -> ปิดทิ้ง ไม่ต้องถือไว้
    """

    def __init__(self, browser, S):
        self.browser = browser
        self.S = S
        self.ctx = None
        self.page = None
        self.landed_url = None
        self.dialogs = []
        self.downloads = []

    async def open(self):
        self.ctx = await self.browser.new_context(viewport=VIEWPORT, accept_downloads=True)
        self.page = await self.ctx.new_page()
        self.page.set_default_timeout(TIMEOUT_MS)
        self.dialogs, self.downloads = [], []
        self.page.on("dialog", lambda d: asyncio.ensure_future(_on_dialog(d, self.dialogs)))
        self.page.on("download", lambda d: self.downloads.append(d))
        return self

    async def login(self):
        """ล็อกอินและจด URL ที่ไปจบ (ใช้ตอนตื่นจากการ park)"""
        await login(self.page, self.S, self.dialogs)
        self.landed_url = self.page.url
        return True

    async def wake(self):
        """พาหน้ากลับมาที่หน้าผลการเรียน โดยยังใช้ session เดิม"""
        try:
            await self.page.goto(self.landed_url or URL, wait_until="domcontentloaded", timeout=30000)
            await settle(self.page)
            return await _on_grades(self.page)
        except Exception:
            return False

    async def ensure_login(self):
        """ตื่นจากการ park แล้วยังล็อกอินอยู่ไหม ถ้าไม่อยู่ให้ล็อกอินใหม่"""
        if await self.wake():
            return True
        await self.park()
        try:
            return await self.login()
        except Exception:
            return False

    async def park(self):
        """พักหน้าไว้ที่ about:blank คง session ไว้ แต่ปล่อย RAM ของหน้าที่เรนเดอร์"""
        try:
            await self.page.goto("about:blank")
        except Exception:
            pass

    async def close(self):
        try:
            if self.ctx is not None:
                await self.ctx.close()
        except Exception:
            pass
        self.ctx = self.page = None


async def check_student(sess, full=True):
    """เช็คนักเรียน 1 คน จาก session ที่ล็อกอินอยู่แล้ว

    full=True  -> กวาดทุกภาคตาม watch_terms (+ปพ.1) แบบเดิม
    full=False -> เช็คแค่ภาคหลัก ใช้ตอนแฟนเอาต์เพื่อความเร็ว

    คืน (changed:bool, info:dict)
    """
    S = sess.S
    terms = list(S.get("watch_terms") or TERMS)
    if not terms:
        terms = [TERMS[0]]

    if full:
        changed = await sweep(sess.page, sess.ctx, S, sess.downloads)
        return changed, {"mode": "full", "terms": len(terms)}

    y, t = terms[0]
    try:
        await go_term(sess.page, y, t)
    except Exception:
        return False, {"mode": "fast", "terms": 1, "error": "go_term"}
    try:
        changed, grades = await process_term(sess.page, S, y, t, "ปี %s ภาค %s" % (y, t))
        return changed, {"mode": "fast", "terms": 1, "rows": len(grades or [])}
    except Exception as e:
        return False, {"mode": "fast", "terms": 1, "error": str(e)[:80]}


async def fan_out(browser, subs, full=False, stagger=1.5, batch=6):
    """MAIN เจอการเปลี่ยนแปลง -> ไล่เช็ค SUB ทุกคน

    จงใจแบ่งเป็นชุดและหน่วงเวลา ไม่ให้ล็อกอินพร้อมกันหมด
    เพราะเว็บโรงเรียนมักล่มพอดีตอนที่นักเรียนทั้งโรงเข้าเว็บพร้อมกัน

    ค่าเริ่มต้นคำนวณจากเวลาจริงที่วัดได้ (login ~6s + เช็ค ~3s = ~9s ต่อชุด):
      27 คน @ batch=6 -> 5 ชุด x 9s + 4 x 1.5s  ~= 51 วินาที  (อยู่ใน 1 นาที)
      ถ้าขึ้น batch=27 จะจบใน ~9 วินาที แต่ล็อกอินพร้อมกัน 27 คนทันที

    คืน list ของผลลัพธ์แต่ละคน
    """
    results = []
    if not subs:
        return results

    async def one(sub):
        sess = StudentSession(browser, sub)
        try:
            await sess.open()
            if not await sess.login():
                return {"sid": sub["sid"], "changed": False, "error": "login"}
            changed, info = await check_student(sess, full=full)
            return {"sid": sub["sid"], "name": sub.get("name") or sub["sid"],
                    "changed": changed, "info": info}
        except Exception as e:
            return {"sid": sub["sid"], "changed": False, "error": str(e)[:120]}
        finally:
            await sess.close()

    for i in range(0, len(subs), batch):
        chunk = subs[i:i + batch]
        if i:
            await asyncio.sleep(stagger)
        results.extend(await asyncio.gather(*(one(s) for s in chunk)))
    return results


def summarize_fanout(results):
    """สรุปผลแฟนเอาต์เป็นบรรทัดเดียวสำหรับแจ้งเข้า Discord"""
    total = len(results)
    changed = [r for r in results if r.get("changed")]
    failed = [r for r in results if r.get("error")]
    bits = ["เช็คแล้ว %d คน" % total]
    if changed:
        bits.append("**มีการเปลี่ยน %d คน**: %s"
                    % (len(changed), ", ".join(r.get("name") or r["sid"] for r in changed)))
    else:
        bits.append("ไม่มีใครเปลี่ยน")
    if failed:
        bits.append("ล้มเหลว %d คน (%s)" % (len(failed), ", ".join(r["sid"] for r in failed[:5])))
    return " | ".join(bits)


def load_or_new_state(sid):
    (BASE_DIR / sid).mkdir(parents=True, exist_ok=True)
    try:
        return json.loads((BASE_DIR / sid / "state.json").read_text(encoding="utf-8"))
    except Exception:
        return {"terms": {}}


# ---------- main ----------
async def main():
    debug = "--debug" in sys.argv

    if "--test" in sys.argv:
        ok = discord("🔌 ทดสอบ webhook")
        print("Webhook ใช้ได้" if ok else "Webhook ใช้ไม่ได้ (ดู error ด้านบน ถ้า 404 = ถูกลบ ให้สร้างใหม่)")
        alert("🧪 **ทดสอบระบบ** (เกรดยังไม่ออกจริง)\n📊 ภาษาไทย 1: 4", None, "ทดสอบ")
        return

    # ---- ถามแค่ 2 อย่าง ----
    while True:
        sid = input("รหัสนักเรียน: ").strip()
        if sid:
            break
    while True:
        pw = input("วันเกิด (วว/ดด/ปปปป พ.ศ. เช่น 18/04/2554): ").strip()
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", pw):
            break
        print("รูปแบบไม่ถูก ต้องเป็นแบบ 18/04/2554")

    (BASE_DIR / sid).mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads((BASE_DIR / sid / "state.json").read_text(encoding="utf-8"))
    except Exception:
        state = {"terms": {}}
    S = {"sid": sid, "pw": pw, "name": sid, "state": state}

    ok = discord(f"✅ เริ่มเฝ้าเกรด รหัส {sid}\n"
                 f"ทุกรอบเช็คตามลำดับ: ปี1ภาค1 → ... → ปี3ภาค2 → ปพ.1 → Info.\n"
                 f"รูปทั้งหมดเก็บที่โฟลเดอร์ shots\\{sid}\\")
    if ok:
        print("Webhook ใช้ได้ ✔")
    else:
        print("\n[!!] ส่ง Discord ไม่สำเร็จ — ตรวจ Webhook (404 = ถูกลบ ให้สร้างใหม่แล้วใส่ที่ WEBHOOK_URL ใน bot_config.json)\n"
              "     สคริปต์ยังทำงานต่อและเก็บรูปในโฟลเดอร์ให้ตามปกติ\n")
    print("\nเริ่มเฝ้าเกรด (กด Ctrl+C เพื่อหยุด)\n")

    fails, down_since, cycle = 0, None, 0

    # วงนอก: เบราว์เซอร์/Playwright พัง → เปิดใหม่แล้วทำต่อ ไม่หยุด
    while True:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=not debug)
                try:
                    if "--discover" in sys.argv:
                        await discover(browser, S)
                        return
                    while True:
                        cycle += 1
                        wait = INTERVAL + random.randint(0, 15)
                        try:
                            await astep(f"▶️ เริ่มรอบที่ {cycle}")
                            try:
                                await asyncio.to_thread(health_report)
                            except Exception as he:
                                print("ตรวจสถานะเว็บไม่สำเร็จ:", str(he)[:120])
                            await run_cycle(browser, S, force_sweep=debug)
                            if fails >= 1:
                                mins = int((time.time() - down_since) / 60)
                                await astep(f"🟢 **{S['name']}**: กลับมาเช็คได้แล้ว (มีปัญหา {fails} ครั้ง ~{mins} นาที)")
                            fails, down_since = 0, None
                            await astep(f"✅ จบรอบที่ {cycle} | รอบถัดไปใน ~{wait} วินาที")
                        except Exception as e:
                            fails += 1
                            if down_since is None:
                                down_since = time.time()
                            wait = RETRY_FAST + random.randint(0, 5)
                            await astep(f"🔴 **{S['name']}**: รอบที่ {cycle} ล้มเหลว (ติดกัน {fails} ครั้ง)\n"
                                        f"สาเหตุ: {str(e)[:300]}\nลองใหม่ใน ~{wait} วินาที",
                                        getattr(e, "shot", None))
                            if any(k in str(e).lower() for k in
                                   ("target closed", "browser has been closed", "browser has been disconnected")):
                                raise  # เบราว์เซอร์ตาย → ออกไปเปิดใหม่
                        if debug:
                            return
                        await asyncio.sleep(wait)
                finally:
                    try:
                        await browser.close()
                    except Exception:
                        pass
        except KeyboardInterrupt:
            print("\nหยุดการทำงาน")
            discord("⏹️ สคริปต์เฝ้าเกรดถูกหยุดโดยผู้ใช้")
            return
        except Exception as e:
            print(f"ระบบเบราว์เซอร์มีปัญหา: {str(e)[:200]} -> เปิดใหม่ใน 15 วินาที")
            discord(f"♻️ เบราว์เซอร์มีปัญหา ({str(e)[:150]}) กำลังเปิดใหม่ใน 15 วินาที")
            try:
                await asyncio.sleep(15)
            except KeyboardInterrupt:
                return


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
