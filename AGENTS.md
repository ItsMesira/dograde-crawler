# AGENTS.md

Thai-language grade watcher for `dograde.online/prakan/`. No package, no deps manifest, no tests, no CI, no lint/typecheck. Just two scripts run directly. `README.md` is the user manual (Thai) — it is accurate about *usage* but stale in a few spots flagged below.

## Entry points

| File | Run it | Role |
|---|---|---|
| `grade_bot.py` | `python grade_bot.py` (Windows users double-click `run_bot.bat`) | **The real product.** Discord bot; slash commands drive everything. |
| `grade_watch_v3.py` | `python grade_watch_v3.py` | The engine: Playwright scraping + image-diff + webhook sender. Also a standalone CLI. |

`grade_bot.py` does `import grade_watch_v3 as g` and calls into it. There is no package boundary — both files sit flat in the repo root and must stay importable from the repo root.

## Commands

```bash
pip install discord.py playwright requests pillow psutil
python -m playwright install chromium      # separate step, easy to forget

python grade_bot.py                        # normal: Discord bot
python grade_watch_v3.py --test            # send one test webhook + spam
python grade_watch_v3.py --debug           # headed browser, one cycle, sweep all terms, then exit
python grade_watch_v3.py --discover        # dump site select/button/link names to shots/<sid>/discover.txt
```

- `--test` short-circuits before prompting. **`--debug` and `--discover` do not** — `main()` reads student ID + birthday from stdin first, so they can't run non-interactively.
- **Always run from the repo root.** `bot_config.json` resolves via `Path(__file__)`, but `BASE_DIR = Path("shots")` (grade_watch_v3.py:71) is **CWD-relative**. Running from elsewhere finds the config but writes `shots/` to a different tree. `run_bot.bat` guards this with `cd /d %~dp0`; manual `python` runs don't.
- Verification is manual only: `--test` proves the webhook, `--debug` proves one cycle. Both need real credentials and the live site. There is nothing to run offline.

## Benchmarks (`bench/`)

Scaling measurements, run against a local synthetic server (no live site needed). Use these to re-validate load assumptions before changing the crawling architecture. Requires `.venv` with `playwright`, `pillow`, `psutil`.

```bash
.venv/bin/python bench/fanout_bench.py                       # concurrent-context cost + RAM
DOGRADE_SID=<id> DOGRADE_PW=<dd/mm/yyyy> \
  .venv/bin/python bench/live_session_test.py                # real-site session behaviour
```

### Session reuse does NOT work on the real site — measured, not assumed

`storage_state` round-trip **fails** at `dograde.online`. Tested against the live site: login succeeds and yields exactly one cookie (`SSUser`, persistent) and zero localStorage. Restoring that state into a fresh context *does* re-apply the cookie, but the site still bounces to the login page on both `/prakan/` and `/prakan/DooTermX.aspx`. The session is bound to server-side state, not the cookie. **A synthetic local server passes this test and is a false positive** — only `live_session_test.py` is authoritative.

What *does* work: the session survives as long as the browser context stays open, including a detour through `about:blank` and back. So the workable shape is **hold contexts open and park them on `about:blank` between checks**, rather than serializing sessions.

### Measured costs (16 GB / 10-core Mac, 28 students)

| Scenario | RAM |
|---|---|
| Transient contexts (create/close per check) | ~170–240 MB |
| Held open, pages loaded | ~2050 MB |
| Held open, parked on `about:blank` | ~1310 MB |

One browser with 28 contexts is ~240 MB, not the ~5 GB that 28 separate Chromium processes would cost. Parking reclaims roughly a third of the held-context cost, because a live rendered page is the expensive part.

**Real-site login takes ~5.3–6 s.** That is the dominant per-student cost, and the reason session reuse mattered enough to test.

Wall times are unreliable and load-dependent: the same 28-student full sweep measured 4.3 s on an idle machine and 21.8 s under load. Do not quote a single number as a capacity plan.

### Still unknown

- How long a held session stays valid server-side before the site forces re-login (must be detected and handled — see the login-success check in `login()`).
- Whether the school tolerates ~28 simultaneous sessions from one IP. Untested; stage the rollout.

## How "grade released" is actually detected

**It is a pixel diff of a full-page screenshot, not a DOM check.** Do not "fix" `read_grades`/`read_page`/`text_changes` expecting them to drive alerts:

- `image_check()` (grade_watch_v3.py:457) copies the first screenshot of a term to `shots/<sid>/<term>/baseline.png`, then each cycle compares against it. `diff_pct > IMG_DIFF_THRESHOLD` (0.4%) ⇒ alert ⇒ **baseline is overwritten with the new shot** so it doesn't re-fire.
- `text_changes()` is explicitly informational — it only decorates the alert message.
- **Pillow missing ⇒ `Image is None` ⇒ `image_diff_percent` returns `None` ⇒ `changed=False` forever. Silent total failure**, no warning beyond a line in the cycle log. Pillow is not optional despite the try/except import.

Two more consequences:

- **First cycle for a term never alerts** — it only records the baseline. Deleting `shots/<sid>/` (or one `baseline.png`) resets that term to "first time" and suppresses its next real alert.
- **The first term in `watch_terms` is the gate.** If it yields no parsable grades, `sweep()` raises and the whole cycle restarts — later terms are never checked (grade_watch_v3.py:564, :586). `/watch` sorts the selection; if you pick only ปพ.1 it silently injects ปี1ภาค1 as an unmonitored primary (grade_bot.py:119).

## Threads

`grade_bot.py` runs one daemon thread per student ID via `g.student_worker`, each with **its own `sync_playwright()` context and its own Chromium**. Never share a `page`/`browser` across threads or move Playwright calls onto the event loop. Control is via two `threading.Event`s: `stop_event` (graceful) and `force_event` (`/check`). `discord.py` is only used for the gateway/commands — all result traffic goes out via raw `requests` to `WEBHOOK`, from worker threads.

## Secrets

`bot_config.json` holds `BOT_TOKEN` / `WEBHOOK_URL` / `ALLOWED_USER_ID` / `GUILD_ID` and is shared by **both** files.

> **It is already tracked by git** despite `.gitignore` listing it — `git check-ignore` exits 1. Dropping a real token in it *will* be committed. Fix with `git rm --cached bot_config.json` before adding secrets; `shots/` is untracked so it stays ignored.

Env overrides (`grade_watch_v3.py:52`) apply to the engine only: `DISCORD_WEBHOOK` and `MENTION_ID`. **`BOT_TOKEN` has no env fallback** — `grade_bot.py` will raise `SystemExit` without the file.

## Editing constraints

- **All comments, docstrings, user-facing strings, and the regex/selectors matching the site are Thai.** Thai literals are load-bearing: `GRADE_COLUMN = "ระดับคะแนน"`, `NAME_RE` title prefixes, `term_patterns()` year/term forms, and the `"ปรับปรุง"` / `"ปี1ภาค1"` login-success checks. Translating any of them breaks detection silently. Keep the files UTF-8 and don't strip `sys.stdout.reconfigure(encoding="utf-8")` (grade_watch_v3.py:20) — Thai crashes the Windows console otherwise.
- Site scraping is intentionally defensive (ASP.NET postback, multiple fallback click strategies in `go_term()`/`js_click()`). If term selection breaks, run `--discover` first and read the dump before changing selectors.

## Known-stale bits (README is wrong or dead here)

- `README.md` and `grade_bot.py`'s docstring say to copy **`bot_config.example.json` — that file does not exist.** The committed `bot_config.json` is a Thai placeholder template instead.
- `MONITOR` (grade_watch_v3.py:40) and `SWEEP_EVERY_MIN` (:57) are **defined but never read**. Editing them does nothing. Likewise `run_cycle(..., force_sweep=...)` accepts the arg and ignores it; every cycle sweeps all terms anyway.
- README's tunables section is otherwise accurate: `INTERVAL`, `RETRY_FAST`, `TIMEOUT_MS`, `IMG_DIFF_THRESHOLD`, `SLOW_MS`, `VERY_SLOW_MS`, `SPAM_COUNT`, `SPAM_DELAY` at the top of `grade_watch_v3.py`.
- Failure handling is by design: the workers never self-terminate on site/login/browser errors — they retry every `RETRY_FAST` (~20s) and relaunch Chromium after 15s indefinitely until `/stop`. Don't "fix" this into an exception unless asked; a raise here just gets logged and retried anyway.
- `alert()` fires `SPAM_COUNT` (10) mentions at `SPAM_DELAY` (2s) spacing; `discord()` self-throttles to ~2 msg/s and retries on HTTP 429. Files over `MAX_UPLOAD` (8 MB) are kept locally but not uploaded.
