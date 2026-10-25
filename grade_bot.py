"""
บอทควบคุมระบบเฝ้าเกรดผ่าน Discord ล้วนๆ

วิธีใช้งาน (หลังตั้งค่าครั้งแรกตามคู่มือ):
    ดับเบิลคลิก run_bot.bat / รัน ./run_bot.sh (หรือ python grade_bot.py) ครั้งเดียว
    ที่เหลือสั่งผ่าน Discord:
        /watch   เปิดฟอร์มกรอกรหัสนักเรียน + วันเกิด (ไม่โชว์ในแชท) แล้วเริ่มเฝ้า
        /stop    หยุดเฝ้ารหัสที่ระบุ
        /check   สั่งเช็คทันที ไม่ต้องรอรอบถัดไป
        /status  ดูว่ากำลังเฝ้ารหัสไหนอยู่บ้าง
        /help_grade  สรุปคำสั่งทั้งหมด

ติดตั้งก่อนใช้ (ครั้งเดียว):
    ./setup.sh        (macOS/Linux)
    setup.bat         (Windows)

ต้องมีไฟล์ bot_config.json อยู่โฟลเดอร์เดียวกัน (คัดลอกจาก bot_config.example.json แล้วใส่ค่าจริง)
ไฟล์เดียวกันนี้ยังเก็บ WEBHOOK_URL ที่ grade_watch_v3.py ใช้ส่งผลลัพธ์ด้วย
"""
import asyncio
import json
import re
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

import grade_watch_v3 as g   # ใช้เอนจิ้นเดิมทั้งหมด (login, sweep, step, alert, ฯลฯ)

# ---------------- ตั้งค่า ----------------
CONFIG_PATH = Path(__file__).with_name("bot_config.json")
if not CONFIG_PATH.exists():
    raise SystemExit(f"ไม่พบไฟล์ตั้งค่า {CONFIG_PATH}\nสร้างไฟล์นี้ก่อนตามตัวอย่างในคู่มือ")

cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
BOT_TOKEN = str(cfg.get("BOT_TOKEN", "")).strip()
try:
    ALLOWED_USER_ID = int(cfg.get("ALLOWED_USER_ID") or g.MENTION_ID)
except (TypeError, ValueError):
    raise SystemExit("ALLOWED_USER_ID ใน bot_config.json ต้องเป็นตัวเลข (Discord User ID)")
GUILD_ID = str(cfg.get("GUILD_ID") or "").strip()
if GUILD_ID and not GUILD_ID.isdigit():
    raise SystemExit("GUILD_ID ใน bot_config.json ต้องเป็นตัวเลข (Server ID) หรือเว้นว่าง")

if not BOT_TOKEN:
    raise SystemExit("ยังไม่ได้ใส่ BOT_TOKEN ใน bot_config.json")

# ให้ shots/ อยู่ที่ repo root เสมอ ไม่ขึ้นกับ CWD ที่เปิดบอท
g.BASE_DIR = Path(__file__).resolve().parent / "shots"

# sid -> {"S": state dict, "stop": asyncio.Event, "force": asyncio.Event, "task": Task}
workers: dict[str, dict] = {}
_browser = None
_pw = None
_announced = False

# ---------------- คิวส่ง Discord ----------------
# เอนจินเรียก step()/alert() แบบ sync และ discord() มี time.sleep สำหรับ throttle
# จึงเปลี่ยนให้แค่เข้าคิว แล้วมี task เดียวค่อยส่งใน thread แยก
# (ถ้าปล่อยให้ step() บล็อก event loop บอทจะ heartbeat กระตุกตอนแจ้งเตือน)
_orig_step = g.step
_orig_alert = g.alert
_outbox: asyncio.Queue = asyncio.Queue()


def _queue_step(msg, file_path=None, mention=False):
    _outbox.put_nowait(("step", msg, file_path, mention))


def _queue_alert(text, file_path, name):
    _outbox.put_nowait(("alert", text, file_path, name))


# patch ทั้ง module เพื่อให้ sweep()/process_term() ที่เรียก step/alert ใช้คิวนี้
g.step = _queue_step
g.alert = _queue_alert


async def _send_pump():
    while True:
        kind, *args = await _outbox.get()
        try:
            if kind == "step":
                await asyncio.to_thread(_orig_step, *args)
            else:
                await asyncio.to_thread(_orig_alert, *args)
        except Exception as e:
            print("ส่ง Discord ไม่สำเร็จ:", str(e)[:150])
        finally:
            _outbox.task_done()


# ---------------- ผู้ช่วย ----------------
def allowed(inter: discord.Interaction) -> bool:
    return inter.user.id == ALLOWED_USER_ID


async def deny(inter: discord.Interaction):
    await inter.response.send_message("คุณไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)


async def _wait_any(*events):
    """รอจนกว่า event ใดตัวหนึ่งจะถูก set (ใช้แทน sleep ที่ interrupt ได้)"""
    tasks = [asyncio.create_task(e.wait()) for e in events]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _student_loop(sid, S, stop_e, force_e):
    """วนเช็คของนักเรียน 1 คนบน event loop เดียวกับบอท (1 context ต่อคน)"""
    sess = g.StudentSession(_browser, S)
    logged_in = False
    auth_fails = 0
    try:
        await sess.open()
        while not stop_e.is_set():
            force_e.clear()
            try:
                if not logged_in:
                    await sess.login()
                    logged_in = True
                elif not await sess.wake():
                    # session หลุด -> ล็อกอินใหม่ (ให้ error จริงหลุดออกมา ไม่กลืนเหมือน ensure_login)
                    await sess.park()
                    await sess.login()

                await g.sweep(sess.page, sess.ctx, S, sess.downloads)
                S["swept_once"] = True
                g.save_state(S)
                auth_fails = 0
                delay = g.INTERVAL
            except Exception as e:
                msg = str(e)[:300]
                _queue_step(f"⚠️ **{sid}** ผิดพลาด: {msg}\nจะลองใหม่ใน {g.RETRY_FAST} วินาที")
                if "ล็อกอินไม่ผ่าน" in msg:
                    auth_fails += 1
                    logged_in = False
                    if auth_fails >= 3:
                        _queue_step(f"🛑 **{sid}** ล็อกอินไม่ผ่านติดกัน 3 ครั้ง — หยุดเฝ้า "
                                    f"ตรวจรหัส/วันเกิด แล้วใช้ /watch ใหม่")
                        break
                delay = g.RETRY_FAST

            if stop_e.is_set():
                break
            try:
                await asyncio.wait_for(_wait_any(stop_e, force_e), timeout=delay)
            except asyncio.TimeoutError:
                pass
    except Exception as e:
        _queue_step(f"⚠️ **{sid}** เปิดเซสชันไม่ได้: {str(e)[:300]}")
    finally:
        await sess.close()
        workers.pop(sid, None)
        _queue_step(f"🛑 หยุดเฝ้า **{sid}** แล้ว")


async def start_worker(sid: str, pw: str, watch_terms: list, watch_pp1: bool) -> str:
    w = workers.get(sid)
    if w and w.get("task") and not w["task"].done():
        return f"กำลังเฝ้ารหัส {sid} อยู่แล้ว"

    S = {"sid": sid, "pw": pw, "name": sid, "state": g.load_or_new_state(sid),
         "watch_terms": watch_terms, "watch_pp1": watch_pp1}
    stop_e, force_e = asyncio.Event(), asyncio.Event()
    entry = {"S": S, "stop": stop_e, "force": force_e, "task": None}
    workers[sid] = entry
    entry["task"] = asyncio.create_task(
        _student_loop(sid, S, stop_e, force_e), name=f"watch-{sid}")

    picked = ", ".join(f"ปี{y}ภาค{t}" for y, t in watch_terms) + (" + ปพ.1" if watch_pp1 else "")
    return (f"เริ่มเฝ้ารหัส {sid} แล้ว ✅ (เลือก: {picked})\n"
            f"(ข้อความทั้งหมดจะแจ้งในช่อง Discord ที่ตั้งเว็บฮุคไว้)")


# ---------------- ฟอร์มกรอกรหัส/วันเกิด (ไม่โชว์ในแชท) ----------------
class WatchModal(discord.ui.Modal, title="เริ่มเฝ้าเกรด"):
    sid_in = discord.ui.TextInput(label="รหัสนักเรียน", max_length=20, placeholder="99901")
    pw_in = discord.ui.TextInput(label="วันเกิด (วว/ดด/ปปปป พ.ศ.)", max_length=12,
                                 placeholder="01/01/2550")

    def __init__(self, watch_terms: list, watch_pp1: bool):
        super().__init__()
        self.watch_terms = watch_terms
        self.watch_pp1 = watch_pp1

    async def on_submit(self, inter: discord.Interaction):
        sid = str(self.sid_in.value).strip()
        pw = str(self.pw_in.value).strip()
        if not sid:
            await inter.response.send_message("ต้องกรอกรหัสนักเรียน", ephemeral=True)
            return
        if not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", pw):
            await inter.response.send_message(
                "รูปแบบวันเกิดไม่ถูกต้อง ต้องเป็นแบบ 01/01/2550", ephemeral=True)
            return
        msg = await start_worker(sid, pw, self.watch_terms, self.watch_pp1)
        await inter.response.send_message(msg, ephemeral=True)


# ---------------- ขั้นที่ 1: เลือกภาคที่จะเฝ้า (ติ๊กได้หลายอัน) ----------------
TERM_OPTIONS = [(y, t) for y in (1, 2, 3) for t in (1, 2)]  # ปี1ภาค1 ... ปี3ภาค2


class TermSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=f"ปี {y} ภาค {t}", value=f"{y}-{t}")
                   for (y, t) in TERM_OPTIONS]
        options.append(discord.SelectOption(label="ปพ.1", value="pp1", emoji="📄"))
        super().__init__(placeholder="เลือกภาค/ปพ.1 ที่จะเฝ้า (เลือกได้หลายอัน)",
                         min_values=1, max_values=len(options), options=options)

    async def callback(self, inter: discord.Interaction):
        if not allowed(inter):
            return await deny(inter)
        values = self.values
        terms = sorted({tuple(map(int, v.split("-"))) for v in values if v != "pp1"})
        pp1 = "pp1" in values
        if not terms and not pp1:
            await inter.response.send_message("ต้องเลือกอย่างน้อย 1 รายการ", ephemeral=True)
            return
        if not terms:
            terms = [TERM_OPTIONS[0]]  # ถ้าเลือกแต่ ปพ.1 ยังต้องมีภาคหลักไว้ล็อกอิน/ตรวจความสำเร็จ
        await inter.response.send_modal(WatchModal(terms, pp1))


class TermSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(TermSelect())


# ---------------- บอท ----------------
class GradeBot(commands.Bot):
    async def setup_hook(self):
        global _pw, _browser
        _pw = await g.async_playwright().start()
        _browser = await _pw.chromium.launch(headless=True)
        asyncio.create_task(_send_pump(), name="discord-pump")
        print("เปิดเบราว์เซอร์สำหรับเฝ้าเกรดแล้ว")

    async def close(self):
        for w in list(workers.values()):
            if w.get("stop"):
                w["stop"].set()
            if w.get("force"):
                w["force"].set()
        tasks = [w["task"] for w in workers.values()
                 if w.get("task") and not w["task"].done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if _browser is not None:
            try:
                await _browser.close()
            except Exception:
                pass
        if _pw is not None:
            try:
                await _pw.stop()
            except Exception:
                pass
        await super().close()


intents = discord.Intents.default()
bot = GradeBot(command_prefix="!unused!", intents=intents)  # ใช้แต่ slash command เท่านั้น
tree = bot.tree


# ---------------- คำสั่ง ----------------
@tree.command(name="watch", description="เริ่มเฝ้าเกรด: เลือกภาคที่จะดู แล้วกรอกรหัส/วันเกิด")
async def watch_cmd(inter: discord.Interaction):
    if not allowed(inter):
        return await deny(inter)
    await inter.response.send_message(
        "เลือกภาคที่จะเฝ้า (ติ๊กได้หลายอัน แล้วค่อยกรอกรหัส/วันเกิดในขั้นถัดไป):",
        view=TermSelectView(), ephemeral=True)


@tree.command(name="stop", description="หยุดเฝ้าเกรดของรหัสที่ระบุ")
@app_commands.describe(sid="รหัสนักเรียนที่จะหยุดเฝ้า")
async def stop_cmd(inter: discord.Interaction, sid: str):
    if not allowed(inter):
        return await deny(inter)
    w = workers.get(sid)
    if not w or not w.get("task") or w["task"].done():
        await inter.response.send_message(f"ไม่พบรหัส {sid} ที่กำลังเฝ้าอยู่", ephemeral=True)
        return
    w["stop"].set()
    w["force"].set()
    await inter.response.send_message(
        f"กำลังหยุดเฝ้ารหัส {sid} (จะหยุดหลังจบรอบปัจจุบัน)", ephemeral=True)


@tree.command(name="check", description="สั่งเช็คทันที ไม่ต้องรอรอบถัดไป")
@app_commands.describe(sid="รหัสนักเรียนที่จะสั่งเช็ค")
async def check_cmd(inter: discord.Interaction, sid: str):
    if not allowed(inter):
        return await deny(inter)
    w = workers.get(sid)
    if not w or not w.get("task") or w["task"].done():
        await inter.response.send_message(f"ไม่พบรหัส {sid} ที่กำลังเฝ้าอยู่", ephemeral=True)
        return
    w["force"].set()
    await inter.response.send_message(
        f"สั่งเช็ครหัส {sid} ทันทีแล้ว ผลจะแจ้งในช่อง Discord", ephemeral=True)


@tree.command(name="status", description="ดูว่ากำลังเฝ้ารหัสไหนอยู่บ้าง")
async def status_cmd(inter: discord.Interaction):
    if not allowed(inter):
        return await deny(inter)
    if not workers:
        await inter.response.send_message("ยังไม่ได้เฝ้ารหัสไหนอยู่ ใช้ /watch เพื่อเริ่ม",
                                          ephemeral=True)
        return
    lines = []
    for sid, w in workers.items():
        task = w.get("task")
        alive = "🟢 กำลังทำงาน" if task and not task.done() else "🔴 หยุดแล้ว"
        picked = ", ".join(f"ปี{y}ภาค{t}" for y, t in w["S"].get("watch_terms", [])) \
            + (" + ปพ.1" if w["S"].get("watch_pp1") else "")
        lines.append(f"**{sid}** ({w['S']['name']}): {alive} | เฝ้า: {picked}")
    await inter.response.send_message("\n".join(lines), ephemeral=True)


@tree.command(name="help_grade", description="สรุปคำสั่งของบอทเฝ้าเกรด")
async def help_cmd(inter: discord.Interaction):
    if not allowed(inter):
        return await deny(inter)
    await inter.response.send_message(
        "**คำสั่งที่ใช้ได้**\n"
        "`/watch` — เปิดฟอร์มกรอกรหัสนักเรียน/วันเกิด แล้วเริ่มเฝ้า\n"
        "`/stop <รหัส>` — หยุดเฝ้ารหัสนั้น\n"
        "`/check <รหัส>` — สั่งเช็คทันที\n"
        "`/status` — ดูสถานะทั้งหมด\n"
        "ผลลัพธ์ทุกอย่าง (เช็ครอบไหน เกรดเปลี่ยนไหม รูปแคป) "
        "จะแจ้งในช่อง Discord ที่ตั้ง Webhook ไว้ตามปกติ",
        ephemeral=True)


@bot.event
async def on_ready():
    global _announced
    guilds = [(gld.id, gld.name) for gld in bot.guilds]
    print(f"บอทเป็นสมาชิกของ {len(guilds)} เซิร์ฟเวอร์: {guilds}")
    if GUILD_ID and int(GUILD_ID) not in [gid for gid, _ in guilds]:
        print(f"[!!] GUILD_ID={GUILD_ID} ใน bot_config.json ไม่ตรงกับเซิร์ฟเวอร์ใดที่บอทอยู่เลย "
              f"ตรวจว่าคัดลอก Server ID ถูกอัน หรือยังไม่ได้เชิญบอทเข้าเซิร์ฟเวอร์นั้นจริง")
    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=int(GUILD_ID))
            tree.copy_global_to(guild=guild_obj)   # เอาคำสั่ง global มาใส่ guild นี้ก่อน sync
            cmds = await tree.sync(guild=guild_obj)
        else:
            cmds = await tree.sync()
        print(f"sync คำสั่งสำเร็จ {len(cmds)} คำสั่ง: {[c.name for c in cmds]} "
              f"(ขอบเขต: {'guild ' + GUILD_ID if GUILD_ID else 'global ใช้เวลาเข้าถึงได้นานสุด 1 ชม.'})")
    except Exception as e:
        print("sync คำสั่งไม่สำเร็จ:", e)
    print(f"บอทพร้อมใช้งาน: {bot.user} (ใช้คำสั่ง /watch ใน Discord ได้เลย)")
    if not _announced:
        _announced = True
        _queue_step("🤖 บอทเฝ้าเกรดออนไลน์แล้ว พิมพ์ `/watch` ใน Discord เพื่อเริ่ม")


if __name__ == "__main__":
    bot.run(BOT_TOKEN)
