# Dograde Crawler — เฝ้าเกรด + ส่งออก Excel

เครื่องมือสำหรับดึงผลการเรียนจาก `dograde.online/prakan/` ออกมาเป็น Excel
และเฝ้าเกรดอัตโนมัติแล้วแจ้งเตือนเข้า Discord

> ⚠️ ใช้กับบัญชีของตัวเองหรือคนที่ยินยอมให้เช็คเท่านั้น
> **วันเกิดนักเรียนคือรหัสผ่านจริงของเว็บ** — ไฟล์รายชื่อ, `bot_config.json`,
> `exports/` และ `shots/` ถูกกันไว้ใน `.gitignore` แล้ว ห้าม commit ขึ้น repo สาธารณะ

---

## สารบัญ

- [เริ่มเร็ว (คำสั่งเดียว)](#เริ่มเร็ว-คำสั่งเดียว)
- [ส่งออกเกรดเป็น Excel](#ส่งออกเกรดเป็น-excel)
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

## บอท Discord (ไม่บังคับ)

ถ้าไม่ใช้บอท ข้ามไปได้เลย — ใช้ export CLI อย่างเดียวก็เพียงพอ

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
├── bootstrap.py          # ติดตั้งทุกอย่างในคำสั่งเดียว
├── requirements.txt      # รายการแพ็กเกจ
├── setup.sh / setup.bat  # wrapper สำหรับ bootstrap.py
├── run_export.sh / .bat  # เริ่ม export (เลือกภาคได้)
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

โปรเจกต์ส่วนตัวสำหรับใช้งานในห้องเรียน
ซอร์สโค้ดเผยแพร่ที่ <https://github.com/ItsMesira/dograde-crawler>
