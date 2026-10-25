# AGENTS.md

Thai-language grade watcher/exporter for `dograde.online/prakan/`. Flat scripts, no package boundary, no tests, no CI, no lint/typecheck. `requirements.txt` + `bootstrap.py` now provide the dependency setup. `README.md` is the Thai user manual.

## Entry points

| File | Run it | Role |
|---|---|---|
| `bootstrap.py` | `./setup.sh` (macOS/Linux) / `setup.bat` (Windows) | One-command setup: `.venv`, `requirements.txt`, Chromium, config/roster templates. |
| `grade_bot.py` | `./run_bot.sh` / `run_bot.bat` | Discord bot on the async engine (one browser, one `StudentSession` per student). |
| `grade_watch_v3.py` | `python grade_watch_v3.py` | Async Playwright engine + standalone CLI watcher. |
| `export_grades.py` | `./run_export.sh` / `run_export.bat` | Batch scrape → `.xlsx`; interactive term menu or `--term 1..6`. |

All files sit flat in the repo root and must stay importable from there. `grade_bot.py` and `export_grades.py` both do `import grade_watch_v3 as g`.

## Current state (read before changing anything)

- `grade_bot.py` is now ported to the async engine. It creates one Chromium in `setup_hook`, one `StudentSession` per student, and runs each student as an `asyncio.Task` on the bot loop with `asyncio.Event` for stop/force. Do not reintroduce threads.
- `g.step` and `g.alert` are patched at import to push into `_outbox`; `_send_pump` drains it with `asyncio.to_thread`. This is deliberate: `discord()` uses `time.sleep` and `alert()` sleeps for `SPAM_COUNT × SPAM_DELAY` (~20 s), which would stall the bot heartbeat if called inline.
- `StudentSession` is used by the bot and `bench/live_engine_test.py`. `check_student`/`fan_out` are still bench-only. The standalone CLI watcher still calls `run_cycle()`, which opens a fresh context every cycle.
- `bench/live_session_test.py` is stale: it drives `sync_playwright` against now-async `g.login/g.settle/g.go_term/g.read_page`, so it silently does nothing. The live engine test is `bench/live_engine_test.py`.
- The old `sweep()` bug (missing `await` on `process_term`) is fixed. Keep that `await`.
- `/watch` sorts the selection; if you pick only ปพ.1 it injects ปี1ภาค1 as the primary term (grade_bot.py). That term is still monitored by `sweep()`.

## Setup / commands

```bash
./setup.sh                                 # macOS/Linux — venv + deps + chromium + templates
setup.bat                                  # Windows

./run_export.sh                            # menu: 1..6, 0 = all six
./run_export.sh --term 1                   # ปี1ภาค1
./run_export.sh --term 0                   # all six terms
python export_grades.py --dry-run          # validate students.csv, no browser
python export_grades.py --limit 1 --headed # smoke test one student

./run_bot.sh                               # Discord bot
python grade_watch_v3.py --test            # send one test webhook + spam
python grade_watch_v3.py --debug           # headed browser, one cycle, sweep all terms, then exit
python grade_watch_v3.py --discover        # dump site select/button/link names to shots/<sid>/discover.txt
```

- `--test` short-circuits before prompting. **`--debug` and `--discover` do not** — `main()` reads student ID + birthday from stdin first, so they can't run non-interactively.
- **Always run from the repo root.** `bot_config.json` resolves via `Path(__file__)`, but the engine's `BASE_DIR = Path("shots")` is **CWD-relative**. `export_grades.py` and `grade_bot.py` pin `g.BASE_DIR` to the repo root; `run_bot.*`/`run_export.*`/`setup.*` `cd` to the script directory. Manual `python` runs don't.

## Export (`export_grades.py`)

- Roster: `students.csv` with `sid,birthday[,name,room,seat]`, or `.xlsx` with the same headers. **All `*.csv`/`*.xlsx`/`*.xls` are gitignored** because birthday = site password; `students.example.csv` is the single negated exception and is the tracked 28-row template. `allnuminorder.md`, `exports/`, `shots/`, and `data/` are ignored too.
- Term selection: `--term N` where 1..6 maps to ปี1ภาค1 … ปี3ภาค2, `0` = all six. No flag → interactive menu if stdin is a TTY, otherwise defaults to `1-1`. `--terms 1-1,1-2` is the explicit multi-term form; don't pass both flags.
- Defaults are `--workers 3 --stagger 2`: 4+ concurrent logins produced HTTP 500s from the school site. The script retries only transient errors (5xx/timeouts), never wrong credentials.
- Export is **read-only**: it must never call `process_term()`/`image_check()`, or it will fire real grade alerts and overwrite `baseline.png`.
- It sets `g.WEBHOOK = ""`. Without that, every `step()` posts to Discord, and the placeholder `bot_config.json` makes each call stall ~8 s (4 retries × 2 s).
- Workbook sheets: `รายชื่อ` (status per student), `สรุป` (GPA/credits), `รวม` (one row per subject, all 13 site columns), and one wide sheet per term (students × subject codes). Terms with no data are skipped. Output goes to `exports/` (gitignored).
- `read_term_table()` parses the ปพ.5 table generically (header→cell zip, so new site columns survive), reads student info from `#fid/#fName/#fRoom/#fOrdinal`, and **verifies the page heading** (`ชั้นมัธยมศึกษาปีที่ X ภาคเรียนที่ Y`, with ปี1..3 = ม.4..6) before accepting a term. Without that check a failed `go_term()` silently copies the previous term's rows.
- Heading/term mismatches and missing buttons are stored with `"skipped": True`; they don't make `_status()` report failure. This is what makes `--term 0` usable before later terms are released.

## How "grade released" is actually detected

**It is a pixel diff of a full-page screenshot, not a DOM check.** Do not "fix" `read_grades`/`read_page`/`text_changes` expecting them to drive alerts:

- `image_check()` copies the first screenshot of a term to `shots/<sid>/<term>/baseline.png`, then each cycle compares against it. `diff_pct > IMG_DIFF_THRESHOLD` (0.4%) ⇒ alert ⇒ **baseline is overwritten with the new shot** so it doesn't re-fire.
- `text_changes()` is explicitly informational — it only decorates the alert message.
- **Pillow missing ⇒ `Image is None` ⇒ `image_diff_percent` returns `None` ⇒ `changed=False` forever. Silent total failure**, no warning beyond a line in the cycle log. Pillow is not optional despite the try/except import.

Two more consequences:

- **First cycle for a term never alerts** — it only records the baseline. Deleting `shots/<sid>/` (or one `baseline.png`) resets that term to "first time" and suppresses its next real alert.
- **The first term in `watch_terms` is the gate.** If it yields no parsable grades, `sweep()` raises and the whole cycle restarts — later terms are never checked.

## Async / threads

The engine is a single asyncio loop per process. The bot keeps all students on that loop.

- `discord()` uses `time.sleep` for throttling, so it blocks. Inside async code use `astep()` (which wraps it in `asyncio.to_thread`), or `await asyncio.to_thread(health_report)`. In the bot, `step`/`alert` go through `_outbox`/`_send_pump`.
- Playwright's async API: `dialog.accept()` is a **coroutine**. Dialogs are wired through `_on_dialog` + `asyncio.ensure_future`; a bare lambda `d.accept()` silently stops dismissing them.
- Never share a `page`/`browser` across event loops or threads. One browser with one context per student (`StudentSession`), not one Chromium per thread.
- The bot uses `asyncio.Event` (`stop`, `force`) and `_wait_any()`; don't switch back to `threading.Event`.
- `_student_loop` calls `sess.wake()` between sweeps and re-logins via `park()` + `login()` if the session is gone. Login failures containing `"ล็อกอินไม่ผ่าน"` are retried 3 times, then the worker stops to avoid an infinite wrong-password loop.

## Benchmarks (`bench/`)

Synthetic measurements; no live site needed. Requires `.venv` with `playwright`, `pillow`, `psutil`.

```bash
.venv/bin/python bench/fanout_bench.py
DOGRADE_SID=<id> DOGRADE_PW=<dd/mm/yyyy> .venv/bin/python bench/live_engine_test.py
```

- `live_engine_test.py` is the current, unattended live smoke test (login → go_term → read_page → park/wake → `check_student(full=False)`). It covers the fast path only, not the full sweep.
- `session_reuse_test.py` is a synthetic counter-example; `storage_state` **fails** on the real site (server-side session binding, one `SSUser` cookie, no localStorage). Held contexts parked on `about:blank` do survive. `live_session_test.py` measured that but is now stale (sync API).

## Secrets

`bot_config.json` holds `BOT_TOKEN` / `WEBHOOK_URL` / `ALLOWED_USER_ID` / `GUILD_ID` and is shared by both scripts. It is **untracked and ignored**; `bot_config.example.json` exists and is tracked. Don't re-add the real file.

Env overrides (`grade_watch_v3.py:52`) apply to the engine only: `DISCORD_WEBHOOK` and `MENTION_ID`. **`BOT_TOKEN` has no env fallback** — `grade_bot.py` exits without the file.

Placeholder config values are non-empty Thai strings, so `WEBHOOK` is truthy and `discord()` will try to POST them. Always zero it out in scripts/tests (`g.WEBHOOK = ""`).

## Editing constraints

- **All comments, docstrings, user-facing strings, and regex/selectors matching the site are Thai.** Thai literals are load-bearing: `GRADE_COLUMN = "ระดับคะแนน"`, `NAME_RE` title prefixes, `term_patterns()` year/term forms, and the `"ปรับปรุง"` / `"ปี1ภาค1"` login-success checks. Translating any of them breaks detection silently. Keep files UTF-8 and don't strip `sys.stdout.reconfigure(encoding="utf-8")` — Thai crashes the Windows console otherwise.
- Site scraping is intentionally defensive (ASP.NET postback, multiple fallback click strategies in `go_term()`/`js_click()`). If term selection breaks, run `--discover` first and read the dump before changing selectors.
- Student info on the grades page is in disabled inputs `#fid` / `#fName` / `#fRoom` / `#fOrdinal`, not in body text. Don't try to parse it with regex on `inner_text`.
- When adding an XPath/locator lookup, check `locator.count()` first. `inner_text()` on a non-matching XPath waits the full 15 s default timeout and can hang a batch.

## Dead knobs

`MONITOR` (grade_watch_v3.py:40) and `SWEEP_EVERY_MIN` (:57) are defined but never read. `run_cycle(..., force_sweep=...)` accepts the arg and ignores it; every cycle sweeps all terms anyway. `alert()` fires `SPAM_COUNT` (10) mentions at `SPAM_DELAY` (2 s); `discord()` self-throttles to ~2 msg/s and retries HTTP 429. Files over `MAX_UPLOAD` (8 MB) stay local.
