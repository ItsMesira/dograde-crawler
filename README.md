# Dograde Crawler — เฝ้าเกรด + ส่งออก Excel

เครื่องมือสำหรับดึงผลการเรียนจาก `dograde.online/prakan/` ออกมาเป็น Excel
และเฝ้าเกรดอัตโนมัติ: แจ้งเตือนเข้า Discord หรือ export ทั้งห้องเมื่อเกรดเปลี่ยน

> ⚠️ ใช้กับบัญชีของตัวเองหรือคนที่ยินยอมให้เช็คเท่านั้น
> **วันเกิดนักเรียนคือรหัสผ่านจริงของเว็บ** — ไฟล์รายชื่อ, `bot_config.json`,
> `exports/` และ `shots/` ถูกกันไว้ใน `.gitignore` แล้ว ห้าม commit ขึ้น repo สาธารณะ

---

## สารบัญ

- [เริ่มเร็ว (คำสั่งเดียว)](#เริ่มเร็ว-คำสั่งเดียว)
- [ส่งออกเกรดเป็น Excel](#ส่งออกเกรดเป็น-excel)
- [เฝ้าเกรดแล้ว export อัตโนมัติ (Auto Export)](#เฝ้าเกรดแล้ว-export-อัตโนมัติ-auto-export)
- [บอท Discord (ไม่บังคับ)](#บอท-discord-ไม่บังคับ)
- [หลักการตรวจจับ "เกรดออก"](#หลักการตรวจจับ-เกรดออก)
- [ปรับแต่งค่า](#ปรับแต่งค่า)
- [แก้ปัญหาที่พบบ่อย](#แก้ปัญหาที่พบบ่อย)
- [ความปลอดภัย](#ความปลอดภัย)
- [โครงสร้างไฟล์](#โครงสร้างไฟล์)

---

## เริ่มเร็ว (คำสั่งเดียว)

ต้องมี **Python 3.10+** ([ดาวน์โหลด](https://www.python.org/downloads/)) แล้วรัน:

```bash
git clone https://github.com/ItsMesira/dograde-crawler.git
cd dograde-crawler
```

| ระบบ | คำสั่ง |
|---|---|
| Windows | `setup.bat` (ดับเบิลคลิกได้) |
| macOS / Linux | `./setup.sh` |

สคริปต์เดียวจะทำให้ทั้งหมด:

1. สร้าง `.venv`
2. ติดตั้งแพ็กเกจจาก `requirements.txt`
3. ติดตั้ง Chromium ของ Playwright
4. สร้าง `bot_config.json` และ `students.csv` จากไฟล์ตัวอย่าง (ถ้ายังไม่มี)
5. ตรวจว่า import แพ็กเกจครบ

รันซ้ำได้ปลอดภัย ของเดิมไม่ถูกเขียนทับ ถ้าอยากสร้าง `.venv` ใหม่ให้ใช้ `--force`
และถ้าไม่ต้องการโหลด Chromium ใหม่ให้ใช้ `--skip-browser`

> **Linux:** ถ้าเปิด Chromium ไม่ได้ ให้ติดตั้งไลบรารีของระบบด้วย
> `.venv/bin/python -m playwright install-deps chromium`

### หลังติดตั้งแล้ว เริ่มอะไรดี?

| ต้องการ | macOS / Linux | Windows |
|---|---|---|
| ดึงเกรดทั้งห้องเป็น Excel | `./run_export.sh` | `run_export.bat` |
| เฝ้าเกรดแล้ว export อัตโนมัติ | `./run_autoexport.sh --term 1` | `run_autoexport.bat --term 1` |
| เปิด GUI auto-export | `./run_autoexport_gui.sh` | `run_autoexport_gui.bat` |
| เปิดบอท Discord | `./run_bot.sh` | `run_bot.bat` |

macOS ดับเบิลคลิก `run_autoexport_gui.command` เพื่อเปิด GUI ได้เลย

---

## ส่งออกเกรดเป็น Excel

### 1. ใส่รายชื่อใน `students.csv`

เปิด `students.csv` (สร้างจาก `students.example.csv` แล้ว) แล้วใส่ข้อมูลจริง:

```csv
sid,birthday,name,room,seat
99901,01/01/2550,ตัวอย่าง 01,15,1
99902,02/01/2550,ตัวอย่าง 02,15,2
```

| คอลัมน์ | จำเป็น | ความหมาย |
|---|---|---|
| `sid` | ✅ | รหัสนักเรียน |
| `birthday` | ✅ | วันเกิดรูปแบบ `วว/ดด/ปปปป` พ.ศ. — ใช้เป็นรหัสผ่านล็อกอิน |
| `name` | — | ชื่อ-สกุล (ถ้าเว็บอ่านได้จะใช้ค่าจากเว็บก่อน) |
| `room` | — | ห้อง |
| `seat` | — | เลขที่ |

- ใช้ไฟล์ Excel แทน CSV ได้: `--roster รายชื่อ.xlsx` (หัวคอลัมน์เดียวกัน)
- ชื่อคอลัมน์ใช้ภาษาไทยก็ได้ เช่น `รหัสนักเรียน`, `วันเกิด`, `ชื่อ`, `ห้อง`, `เลขที่`
- ถ้าเปิดไฟล์ใน Excel ให้ตั้งรูปแบบเซลล์เป็น **Text** หรือพิมพ์ `01/01/2550` ตรง ๆ

### 2. เลือกภาคที่จะดึง

```bash
./run_export.sh      # macOS / Linux
run_export.bat       # Windows (ดับเบิลคลิกได้)
```

จะมีเมนูให้เลือก:

```
1) ปี1 ภาค1
2) ปี1 ภาค2
3) ปี2 ภาค1
4) ปี2 ภาค2
5) ปี3 ภาค1
6) ปี3 ภาค2
0) ทั้ง 6 ภาค
```

เลือกแล้วรอได้เลย ไฟล์จะถูกบันทึกที่ `exports/`

ถ้าไม่ต้องการเมนู (เช่นเขียนสคริปต์) ให้ระบุตรง ๆ:

```bash
python export_grades.py --term 1          # ปี1ภาค1
python export_grades.py --term 0          # ทั้ง 6 ภาค
python export_grades.py --terms 1-1,1-2   # ระบุหลายภาค
```

### 3. ไฟล์ผลลัพธ์

`exports/grades_<วันเวลา>.xlsx` มีชีต:

| ชีต | เนื้อหา |
|---|---|
| `รายชื่อ` | สถานะการดึงของนักเรียนแต่ละคน + หมายเหตุ |
| `สรุป` | GPA, หน่วยกิตพื้นฐาน/เพิ่มเติม/รวม, จำนวนวิชา, เกรดที่ออกแล้ว |
| `รวม` | 1 แถว = 1 วิชา ทุกคน ทุกภาค — เอาไปทำ Pivot ต่อได้ |
| `ปี1ภาค1` | ตารางกว้าง นักเรียน × รหัสวิชา (สร้างเฉพาะภาคที่มีข้อมูล) |

### ตัวเลือกที่มีประโยชน์

| flag | ใช้ทำอะไร |
|---|---|
| `--dry-run` | ตรวจ `students.csv` แล้วจบ ไม่เปิดเว็บ |
| `--limit 1` | ลองแค่คนแรก |
| `--headed` | เปิดหน้าจอเบราว์เซอร์ให้ดู |
| `--workers 3` | จำนวนคนที่ล็อกอินพร้อมกัน (ค่าเริ่มต้น 3) |
| `--stagger 2` | หน่วงเวลาระหว่างชุด (วินาที) |
| `--retries 2` | ลองใหม่เมื่อเจอเว็บ 5xx/หมดเวลา |
| `--out ชื่อ.xlsx` | กำหนดชื่อไฟล์เอง |
| `--save-html` | เก็บ HTML ไว้ debug parser |
| `--shots` | เก็บภาพหน้าจอแต่ละภาค |
| `--verbose` | แสดงทุกขั้นตอนของเอนจิน |

> **export เป็น read-only** — ไม่เรียก `process_term()` / `image_check()`
> จึงไม่ยิงแจ้งเตือน Discord และไม่ overwrite `baseline.png`
>
> เว็บโรงเรียนตอบ HTTP 500 ถ้าล็อกอินพร้อมกัน 4+ คน ค่าเริ่มต้นจึงเป็น
> `--workers 3 --stagger 2` ไม่แนะนำให้เพิ่มเกิน 3

---

## เฝ้าเกรดแล้ว export อัตโนมัติ (Auto Export)

โหมดนี้ใช้ **บัญชีเดียว** (บัญชีกระตุ้น) เฝ้าเฉพาะภาคที่เลือก
เมื่อภาพหน้าเว็บเปลี่ยน (เทียบแบบ pixel diff) จะดึงผลการเรียนของ **ทุกคนใน `students.csv`**
เป็นไฟล์ Excel ให้อัตโนมัติ — ใช้ได้ 3 ทาง: CLI, GUI (เว็บในเครื่อง), Discord

> **สรุปสั้น:** `./run_autoexport.sh --term 1` ใช้บัญชีแรกใน `students.csv`
> เฝ้าปี 1 ภาค 1 เมื่อหน้าเว็บเปลี่ยนจะ export ทั้งห้องเป็น
> `exports/auto_Y1T1_<วันเวลา>.xlsx`

### ใช้งานผ่าน CLI

```bash
./run_autoexport.sh                       # macOS/Linux: เมนูเลือกภาค
run_autoexport.bat                        # Windows (ดับเบิลคลิก)
./run_autoexport.sh --term 1              # ระบุภาค
./run_autoexport.sh --term 1 --trigger-sid 12345
./run_autoexport.sh --term 1 --check      # ตรวจรอบเดียว ไม่ export
./run_autoexport.sh --term 1 --keep-watching
```

- ค่าเริ่มต้น: ใช้คนแรกใน `students.csv` เป็นบัญชีกระตุ้น, ตรวจทุก 60 วินาที,
  หยุดหลัง export ครั้งแรก
- `--trigger-sid 12345` เลือกบัญชีอื่น, `--interval 30` ปรับความถี่,
  `--keep-watching` เฝ้าต่อ (รอ `--cooldown` 300 วินาที)
- `--check` ไว้ทดสอบ: รอบแรกสร้าง baseline, รอบที่สองเริ่มเทียบและรายงาน % ต่าง
- `--limit 1` ไว้ทดสอบ export แค่คนเดียว (ปกติ export ทั้งหมด)
- ไฟล์ออกที่ `exports/auto_Y<ปี>T<ภาค>_<วันเวลา>.xlsx`

### GUI (เปิดในเบราว์เซอร์)

```bash
./run_autoexport_gui.sh                   # macOS/Linux
run_autoexport_gui.bat                    # Windows (ดับเบิลคลิก)
```

macOS ดับเบิลคลิก `run_autoexport_gui.command` ได้เลย
หน้าจอจะเปิดที่ `http://127.0.0.1:<port>/` — เลือกภาค/บัญชี, กดเริ่ม,
ดู log และหยุดได้ ไม่ต้องติดตั้ง tkinter หรือแพ็กเกจเพิ่ม (ใช้ stdlib)

### ใช้งานผ่าน Discord

ถ้าบอทกำลังรันอยู่:

| คำสั่ง | ใช้ทำอะไร |
|---|---|
| `/autoexport term:1` | ใช้คนแรกใน `students.csv` เฝ้า ปี1 ภาค1 |
| `/autoexport term:1 sid:12345` | เลือกบัญชีกระตุ้น |
| `/autoexport term:1 keep:true` | เฝ้าต่อหลัง export |
| `/autoexport_stop` | หยุด auto-export |
| `/status` | ดูสถานะ auto-export |

เมื่อพบการเปลี่ยน บอทจะ export ทั้งห้อง แล้วแนบ `.xlsx` ในช่อง Webhook

### ข้อควรรู้

- **รอบแรกของแต่ละภาคยังไม่ trigger** — ใช้สร้าง baseline ก่อน (เหมือนบอท)
  ถ้าเกรดออกไปแล้วและต้องการไฟล์ทันที ให้ใช้ `./run_export.sh` ก่อน
  auto-export จะเริ่มตรวจการเปลี่ยนจากตอนที่เริ่มเฝ้า
- บัญชีกระตุ้นต้องเป็นคนที่หน้าเกรดเปลี่ยนตอนเกรดออกจริง ๆ
  ถ้าเกรดของคนนั้นออกช้ากว่าเพื่อน อาจตรวจไม่พบ — เลือกบัญชีที่คิดว่าเกรดออกพร้อมห้อง
- baseline ของ auto-export เก็บแยกที่ `shots/<รหัส>/autoexport_Y<ปี>T<ภาค>/`
  จึงไม่ทับ baseline ของ `/watch`
- ก่อนเริ่ม export ระบบจะปิด session ของบัญชีกระตุ้นก่อน
  เพราะ export จะล็อกอินบัญชีนั้นใหม่ (กัน session ชนกัน)
- export จะล็อกอิน **ทุกคน** ใน `students.csv` รวมคนที่ `/watch` อยู่
  จึงไม่ควรใช้ `/watch` พร้อม `/autoexport` — ถ้าจำเป็นให้หยุด `/watch` ก่อน
- ถ้าใช้ `/autoexport` กับรหัสที่ `/watch` อยู่ ระบบจะไม่ให้เริ่ม
  (และ `/watch` จะไม่ให้ใช้รหัสที่ auto-export กำลังเฝ้าอยู่)
- ต้องมี Pillow (setup ติดตั้งให้แล้ว) ไม่งั้นเทียบภาพไม่ได้

---

## บอท Discord (ไม่บังคับ)

ถ้าไม่ใช้บอท ข้ามไปได้เลย — ใช้ export CLI หรือ auto-export CLI/GUI อย่างเดียวก็เพียงพอ

### 1. สร้าง Discord Bot

1. เข้า <https://discord.com/developers/applications> → **New Application**
2. แท็บ **Bot** → **Reset Token** → คัดลอก Token เก็บไว้ (ห้ามให้ใครเห็น)
3. แท็บ **Installation** → **Guild Install**
   - Scopes: `bot`, `applications.commands`
   - Permissions: Send Messages, Embed Links, Attach Files, Use Slash Commands,
     Read Message History, View Channel
4. แท็บ **OAuth2 → URL Generator** → ติ๊ก scope/permission ชุดเดียวกัน →
   เปิดลิงก์ → เลือกเซิร์ฟเวอร์ → Authorize
5. (แนะนำ) เปิด Developer Mode แล้วคลิกขวาชื่อเซิร์ฟเวอร์ → **Copy Server ID**

### 2. สร้าง Webhook

ช่องที่ต้องการให้แจ้งเตือน → แก้ไขช่อง → การเชื่อมต่อ → เว็บฮุค → เว็บฮุคใหม่
→ คัดลอก URL

### 3. ตั้งค่า `bot_config.json`

ไฟล์นี้ถูกสร้างจาก `bot_config.example.json` แล้วโดย `setup.sh` / `setup.bat`
เปิดแล้วใส่ค่าจริง:

```json
{
  "BOT_TOKEN": "Bot Token จากขั้นที่ 1",
  "ALLOWED_USER_ID": "Discord User ID ของคุณ",
  "GUILD_ID": "Server ID (เว้นว่างได้ แต่คำสั่งจะขึ้นช้า)",
  "WEBHOOK_URL": "URL เว็บฮุคจากขั้นที่ 2"
}
```

- `ALLOWED_USER_ID` กันคนอื่นสั่งบอท และเป็นคนที่ถูกแท็กรัวตอนเกรดออก
- `WEBHOOK_URL` ใช้ร่วมกันทั้งบอทและเอนจิ้น
- ไฟล์นี้อยู่ใน `.gitignore` แล้ว

### 4. เริ่มบอท

```bash
./run_bot.sh      # macOS / Linux
run_bot.bat       # Windows
```

ปล่อยหน้าต่างไว้ เปิดบอทค้างตลอด แล้วไปใช้คำสั่งใน Discord

### คำสั่งบน Discord

| คำสั่ง | ใช้ทำอะไร |
|---|---|
| `/watch` | เลือกภาคที่จะเฝ้า แล้วกรอกรหัส/วันเกิด เริ่มเฝ้าใหม่ |
| `/stop <รหัส>` | หยุดเฝ้ารหัสนั้น (หลังจบรอบปัจจุบัน) |
| `/check <รหัส>` | สั่งเช็คทันที |
| `/autoexport <ภาค>` | เฝ้าบัญชีเดียว แล้ว export ทั้งห้องเมื่อเกรดเปลี่ยน |
| `/autoexport_stop` | หยุด auto-export |
| `/status` | ดูว่ากำลังเฝ้ารหัสไหน ภาคอะไร |
| `/help_grade` | สรุปคำสั่งทั้งหมด |

ทุกคำสั่งใช้ได้เฉพาะ user ที่ตรงกับ `ALLOWED_USER_ID`

---

## หลักการตรวจจับ "เกรดออก"

1. **ล็อกอิน** ด้วยรหัสนักเรียน + วันเกิด
2. **เลือกภาค** ตามลำดับที่ติ๊กไว้ (ลองหลายวิธี: ปุ่มตรงชื่อ, dropdown, JavaScript สำรอง)
3. **แคปภาพ** หน้าเว็บของแต่ละภาค
4. **เทียบภาพ** กับ `baseline.png` ของภาคนั้น:
   - รอบแรก → บันทึกเป็นภาพฐาน (ยังไม่แจ้ง)
   - รอบถัดไป → ถ้าต่างเกิน `IMG_DIFF_THRESHOLD` (0.4%) → ถือว่าเกรดออก
   - เมื่อแจ้งแล้วจะเลื่อน baseline เป็นภาพล่าสุด กันแจ้งซ้ำ
5. **แจ้ง Discord** แบบแท็กรัว พร้อมรูปหลักฐาน
6. ถ้าล้มเหลว (เว็บล่ม/ล็อกอินไม่ผ่าน) จะลองใหม่ทุก ~20 วินาที ไม่หยุดเอง

> **Pillow จำเป็น** — ถ้าไม่มี `PIL` จะเทียบภาพไม่ได้และ **ไม่แจ้งเตือนเลย**
> `setup.sh` / `setup.bat` ติดตั้งให้แล้ว

> **Auto Export** ใช้หลักการ pixel diff เดียวกัน แต่เก็บ baseline แยกที่
> `shots/<รหัส>/autoexport_Y<ปี>T<ภาค>/` และเมื่อเปลี่ยนจะไม่ส่งแจ้งเตือนเกรด
> แต่จะ export ทั้งห้องเป็น Excel แทน (ดูหัวข้อ Auto Export ด้านบน)

---

## ปรับแต่งค่า

แก้ที่ต้นไฟล์ `grade_watch_v3.py`:

```python
INTERVAL = 60              # วินาที พักระหว่างรอบปกติ
RETRY_FAST = 20            # วินาที พักตอนรอบล้มเหลว
TIMEOUT_MS = 15000         # รอแต่ละขั้นบนหน้าเว็บ (ms)
IMG_DIFF_THRESHOLD = 0.4   # % ความต่างของภาพที่ถือว่าเกรดออก
SLOW_MS = 2500             # เว็บตอบช้ากว่านี้ = 🟡
VERY_SLOW_MS = 6000        # เว็บตอบช้ากว่านี้ = 🟠
SPAM_COUNT = 10            # จำนวนครั้งที่แท็กรัว
SPAM_DELAY = 2             # วินาทีระหว่างแต่ละครั้ง
```

แก้แล้วต้องหยุดบอท (`Ctrl + C`) แล้วรันใหม่

---

## แก้ปัญหาที่พบบ่อย

| อาการ | สาเหตุ | วิธีแก้ |
|---|---|---|
| `ไม่พบ Python 3` | ยังไม่ได้ติดตั้ง/ไม่อยู่ใน PATH | ติดตั้ง Python 3.10+ แล้วเปิด terminal ใหม่ |
| `No module named ...` | ยังไม่ได้รัน setup หรือใช้ Python คนละตัว | รัน `./setup.sh` / `setup.bat` |
| `Executable doesn't exist` (Playwright) | ยังไม่ได้ติดตั้ง Chromium | `.venv/bin/python -m playwright install chromium` |
| `Discord ตอบกลับ 404: Unknown Webhook` | Webhook ถูกลบ/ผิด | สร้างใหม่แล้วแก้ `WEBHOOK_URL` |
| `/watch` ไม่ขึ้นใน Discord | ยังไม่ sync หรือแคช client | รอสักครู่, `Ctrl + R`, เชิญบอทใหม่ให้ครบ scope |
| `Server Error in '/prakan'` | เว็บโรงเรียนล่ม | รอ สคริปต์จะลองใหม่เอง |
| ล็อกอินไม่ผ่านซ้ำ ๆ | รหัส/วันเกิดผิด หรือเว็บเปลี่ยนโครงสร้าง | ลองล็อกอินเองในเบราว์เซอร์, ดู `shots/<รหัส>/error/` |
| เกรดออกแล้วแต่ไม่แจ้ง | ไม่มี Pillow | รัน setup ใหม่ |
| auto-export ยังไม่ trigger | รอบแรกเพิ่งสร้าง baseline | ปล่อยให้ตรวจอีกรอบ หรือใช้ `--check` สองครั้ง |
| auto-export ตรวจไม่เจอการเปลี่ยน | ภาพต่างน้อยกว่า 0.4% | ปรับ `IMG_DIFF_THRESHOLD` ใน `grade_watch_v3.py` |
| GUI ไม่เปิดเบราว์เซอร์ | ไม่มี browser ในเครื่อง/รันบนเซิร์ฟเวอร์ | เปิด URL ที่พิมพ์ใน terminal เอง หรือใช้ `--no-browser` |
| `/autoexport` ไม่ขึ้น | บอทยังไม่ sync คำสั่ง | รอสักครู่, `Ctrl + R`, เชิญบอทใหม่ให้ครบ scope |
| แจ้งถี่เกินไป | หน้าเว็บขยับเล็กน้อย | เพิ่ม `IMG_DIFF_THRESHOLD` |
| export ได้ 0 วิชา | ยังไม่เปิดภาคนั้น หรือหน้าเว็บเปลี่ยน | ลอง `--limit 1 --headed --save-html` |

---

## ความปลอดภัย

- ใช้กับบัญชีของตัวเองหรือคนที่ยินยอมเท่านั้น
- `bot_config.json` มี Bot Token และ Webhook — **ห้าม commit**
- `students.csv`, `*.xlsx`, `*.csv`, `allnuminorder.md`, `exports/`, `shots/`, `data/`
  ถูก ignore ทั้งหมด (ยกเว้น `students.example.csv` ที่เป็นข้อมูลปลอม)
- ถ้า Token/Webhook หลุด ให้ Reset Token และสร้าง Webhook ใหม่ทันที
- รูปใน `shots/` และไฟล์ใน `exports/` เป็นข้อมูลผลการเรียนจริง ไม่ควรแชร์
- GUI เปิดเฉพาะ `127.0.0.1` (localhost) และไม่ได้ส่งวันเกิดออกไปในหน้าเว็บ
  แต่ยังควรปิดเมื่อไม่ใช้ เพราะเซิร์ฟเวอร์ในเครื่องจะรับคำสั่ง start/stop ได้

ตรวจก่อน push ทุกครั้ง:

```bash
git status --short          # ต้องไม่เห็นไฟล์ส่วนตัว
git ls-files | grep -Ei '\.(csv|xlsx|xls)$|student|roster|allnum' | grep -v 'students.example.csv'   # ควรว่าง
```

---

## โครงสร้างไฟล์

```
dograde-crawler/
├── grade_watch_v3.py     # เอนจิ้น: ล็อกอิน, อ่านเว็บ, เทียบภาพ, ส่ง Discord
├── grade_bot.py          # บอท Discord (async, ใช้ StudentSession)
├── export_grades.py      # ส่งออก Excel (CLI + เมนูเลือกภาค)
├── auto_export.py        # เฝ้าบัญชีเดียว -> export ทั้งห้องเมื่อเกรดเปลี่ยน (CLI)
├── auto_export_gui.py    # GUI เว็บในเครื่องสำหรับ auto-export
├── bootstrap.py          # ติดตั้งทุกอย่างในคำสั่งเดียว
├── requirements.txt      # รายการแพ็กเกจ
├── setup.sh / setup.bat  # wrapper สำหรับ bootstrap.py
├── run_export.sh / .bat  # เริ่ม export (เลือกภาคได้)
├── run_autoexport.sh / .bat       # เริ่ม auto-export CLI
├── run_autoexport_gui.sh / .bat   # เริ่ม auto-export GUI
├── run_autoexport_gui.command     # macOS: ดับเบิลคลิกเปิด GUI
├── run_bot.sh / .bat     # เริ่มบอท Discord
├── students.example.csv  # ตัวอย่างรายชื่อ (ข้อมูลปลอม)
├── bot_config.example.json
├── shots/                # รูปแคป (ignore)
│   └── <รหัสนักเรียน>/ปี1_ภาค1/baseline.png
├── exports/              # ไฟล์ Excel (ignore)
└── data/                 # สถานะ/ประวัติ (ignore)
```

---

## เครดิต
*ขอขอบคุณ : <https://github.com/IamKUN67/prakan-dograde-watcher>*

โปรเจกต์ส่วนตัวสำหรับใช้งานในห้องเรียน
ซอร์สโค้ดเผยแพร่ที่ <https://github.com/ItsMesira/dograde-crawler>
