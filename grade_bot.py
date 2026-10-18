"""
บอทควบคุมระบบเฝ้าเกรดผ่าน Discord ล้วนๆ

วิธีใช้งาน (หลังตั้งค่าครั้งแรกตามคู่มือ):
    ดับเบิลคลิก run_bot.bat (หรือรัน python grade_bot.py) ครั้งเดียว
    ที่เหลือสั่งผ่าน Discord:
        /watch   เปิดฟอร์มกรอกรหัสนักเรียน + วันเกิด (ไม่โชว์ในแชท) แล้วเริ่มเฝ้า
        /stop    หยุดเฝ้ารหัสที่ระบุ
        /check   สั่งเช็คทันที ไม่ต้องรอรอบถัดไป
        /status  ดูว่ากำลังเฝ้ารหัสไหนอยู่บ้าง
        /help_grade  สรุปคำสั่งทั้งหมด

ติดตั้งก่อนใช้ (ครั้งเดียว):
    pip install discord.py playwright requests pillow psutil
    python -m playwright install chromium

ต้องมีไฟล์ bot_config.json อยู่โฟลเดอร์เดียวกัน (คัดลอกจาก bot_config.example.json แล้วใส่ค่าจริง)
ไฟล์เดียวกันนี้ยังเก็บ WEBHOOK_URL ที่ grade_watch_v3.py ใช้ส่งผลลัพธ์ด้วย
"""
import json, re, threading
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

import grade_watch_v3 as g   # ใช้เอนจิ้นเดิมทั้งหมด (login, run_cycle, health_report, discord(), ฯลฯ)

# ---------------- ตั้งค่า ----------------
CONFIG_PATH = Path(__file__).with_name("bot_config.json")
if not CONFIG_PATH.exists():
    raise SystemExit(f"ไม่พบไฟล์ตั้งค่า {CONFIG_PATH}\nสร้างไฟล์นี้ก่อนตามตัวอย่างในคู่มือ")

cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
BOT_TOKEN = cfg.get("BOT_TOKEN", "").strip()
ALLOWED_USER_ID = int(cfg.get("ALLOWED_USER_ID") or g.MENTION_ID)
GUILD_ID = str(cfg.get("GUILD_ID") or "").strip()

if not BOT_TOKEN:
    raise SystemExit("ยังไม่ได้ใส่ BOT_TOKEN ใน bot_config.json")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!unused!", intents=intents)  # ใช้แต่ slash command เท่านั้น
tree = bot.tree

# sid -> {"S":state dict, "stop":Event, "force":Event, "thread":Thread}
workers: dict[str, dict] = {}
LOCK = threading.Lock()


def allowed(inter: discord.Interaction) -> bool:
    return inter.user.id == ALLOWED_USER_ID


async def deny(inter: discord.Interaction):
    await inter.response.send_message("คุณไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)


def start_worker(sid: str, pw: str, watch_terms: list, watch_pp1: bool) -> str:
    with LOCK:
        w = workers.get(sid)
        if w and w["thread"].is_alive():
            return f"กำลังเฝ้ารหัส {sid} อยู่แล้ว"
        S = {"sid": sid, "pw": pw, "name": sid, "state": g.load_or_new_state(sid),
             "watch_terms": watch_terms, "watch_pp1": watch_pp1}
        stop_e, force_e = threading.Event(), threading.Event()
        th = threading.Thread(target=g.student_worker, args=(S, stop_e, force_e), daemon=True)
        workers[sid] = {"S": S, "stop": stop_e, "force": force_e, "thread": th}
        th.start()
        picked = ", ".join(f"ปี{y}ภาค{t}" for y, t in watch_terms) + (" + ปพ.1" if watch_pp1 else "")
        return f"เริ่มเฝ้ารหัส {sid} แล้ว ✅ (เลือก: {picked})\n(ข้อความทั้งหมดจะแจ้งในช่อง Discord ที่ตั้งเว็บฮุคไว้)"


# ---------------- ฟอร์มกรอกรหัส/วันเกิด (ไม่โชว์ในแชท) ----------------
class WatchModal(discord.ui.Modal, title="เริ่มเฝ้าเกรด"):
    sid_in = discord.ui.TextInput(label="รหัสนักเรียน", max_length=20, placeholder="48610")
    pw_in = discord.ui.TextInput(label="วันเกิด (วว/ดด/ปปปป พ.ศ.)", max_length=12, placeholder="18/04/2554")

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
            await inter.response.send_message("รูปแบบวันเกิดไม่ถูกต้อง ต้องเป็นแบบ 18/04/2554", ephemeral=True)
            return
        msg = await bot.loop.run_in_executor(None, start_worker, sid, pw, self.watch_terms, self.watch_pp1)
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


# ---------------- คำสั่ง ----------------
@tree.command(name="watch", description="เริ่มเฝ้าเกรด: เลือกภาคที่จะดู แล้วกรอกรหัส/วันเกิด")
async def watch_cmd(inter: discord.Interaction):
    if not allowed(inter):
        return await deny(inter)
    await inter.response.send_message("เลือกภาคที่จะเฝ้า (ติ๊กได้หลายอัน แล้วค่อยกรอกรหัส/วันเกิดในขั้นถัดไป):",
                                       view=TermSelectView(), ephemeral=True)


@tree.command(name="stop", description="หยุดเฝ้าเกรดของรหัสที่ระบุ")
@app_commands.describe(sid="รหัสนักเรียนที่จะหยุดเฝ้า")
async def stop_cmd(inter: discord.Interaction, sid: str):
    if not allowed(inter):
        return await deny(inter)
    w = workers.get(sid)
    if not w or not w["thread"].is_alive():
        await inter.response.send_message(f"ไม่พบรหัส {sid} ที่กำลังเฝ้าอยู่", ephemeral=True)
        return
    w["stop"].set()
    w["force"].set()
    await inter.response.send_message(f"กำลังหยุดเฝ้ารหัส {sid} (จะหยุดหลังจบรอบปัจจุบัน)", ephemeral=True)


@tree.command(name="check", description="สั่งเช็คทันที ไม่ต้องรอรอบถัดไป")
@app_commands.describe(sid="รหัสนักเรียนที่จะสั่งเช็ค")
async def check_cmd(inter: discord.Interaction, sid: str):
    if not allowed(inter):
        return await deny(inter)
    w = workers.get(sid)
    if not w or not w["thread"].is_alive():
        await inter.response.send_message(f"ไม่พบรหัส {sid} ที่กำลังเฝ้าอยู่", ephemeral=True)
        return
    w["force"].set()
    await inter.response.send_message(f"สั่งเช็ครหัส {sid} ทันทีแล้ว ผลจะแจ้งในช่อง Discord", ephemeral=True)


@tree.command(name="status", description="ดูว่ากำลังเฝ้ารหัสไหนอยู่บ้าง")
async def status_cmd(inter: discord.Interaction):
    if not allowed(inter):
        return await deny(inter)
    if not workers:
        await inter.response.send_message("ยังไม่ได้เฝ้ารหัสไหนอยู่ ใช้ /watch เพื่อเริ่ม", ephemeral=True)
        return
    lines = []
    for sid, w in workers.items():
        alive = "🟢 กำลังทำงาน" if w["thread"].is_alive() else "🔴 หยุดแล้ว"
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
        "ผลลัพธ์ทุกอย่าง (เช็ครอบไหน เกรดเปลี่ยนไหม รูปแคป) จะแจ้งในช่อง Discord ที่ตั้ง Webhook ไว้ตามปกติ",
        ephemeral=True)


@bot.event
async def on_ready():
    guilds = [(gld.id, gld.name) for gld in bot.guilds]
    print(f"บอทเป็นสมาชิกของ {len(guilds)} เซิร์ฟเวอร์: {guilds}")
    if GUILD_ID and int(GUILD_ID) not in [gid for gid, _ in guilds]:
        print(f"[!!] GUILD_ID={GUILD_ID} ใน bot_config.json ไม่ตรงกับเซิร์ฟเวอร์ใดที่บอทอยู่เลย "
              f"ตรวจว่าคัดลอก Server ID ถูกอัน หรือยังไม่ได้เชิญบอทเข้าเซิร์ฟเวอร์นั้นจริง")
    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=int(GUILD_ID))
            tree.copy_global_to(guild=guild_obj)   # เอาคำสั่งที่ประกาศแบบ global มาใส่ guild นี้ก่อน sync
            cmds = await tree.sync(guild=guild_obj)
        else:
            cmds = await tree.sync()
        print(f"sync คำสั่งสำเร็จ {len(cmds)} คำสั่ง: {[c.name for c in cmds]} "
              f"(ขอบเขต: {'guild ' + GUILD_ID if GUILD_ID else 'global ใช้เวลาเข้าถึงได้นานสุด 1 ชม.'})")
    except Exception as e:
        print("sync คำสั่งไม่สำเร็จ:", e)
    print(f"บอทพร้อมใช้งาน: {bot.user} (ใช้คำสั่ง /watch ใน Discord ได้เลย)")
    g.discord("🤖 บอทเฝ้าเกรดออนไลน์แล้ว พิมพ์ `/watch` ใน Discord เพื่อเริ่ม")


if __name__ == "__main__":
    bot.run(BOT_TOKEN)