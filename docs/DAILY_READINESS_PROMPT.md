# Daily readiness check — Vibe-Intraday

A reusable prompt to run **before market open** to confirm the live bake-off is healthy and set
for the day. Paste the block below into a fresh Claude Code session in `c:\Raghava\Antigravity`.

Written 2026-07-20 (end of the first live day of the 64-slot roster). Read-only by design —
it diagnoses, it does not fix.

---

## The prompt

```
Pre-open readiness check for vibe_intraday/ — the live NSE intraday paper bake-off.
Read vibe_intraday/SESSION.md and CLAUDE.md first.

READ-ONLY. Do not modify any file, config, or runtime state. Do not start or stop the
bake-off. If you find something wrong, report it and propose a fix — do not apply it.
Report findings as a table: check / expected / actual / PASS-FAIL-WARN.

1. YESTERDAY'S SESSION
   - Read the newest vibe-trading/agent/logs/bakeoff-*.log. Did it run a full session
     (open through 15:15 force-flatten and EOD report), or did it die early?
   - BUG-004 is still open (host/process crash has scratched two days). Look for an
     abrupt end, a second PID starting mid-day, or a restart. Say plainly whether
     yesterday was a clean day or a scratched one.
   - Count ERROR / WARNING lines by type. Flag anything new versus the day before.

2. SCOREBOARD INTEGRITY
   - Load ~/.vibe-trading/intraday/scoreboard.json.
   - How many rows, for which dates, and how many distinct slots per date?
     Expected: 64 slots for each live day since 2026-07-20; 40 for 2026-07-17.
   - Any duplicate slot+date rows, any row with a date that is not a trading day,
     any slot name not in config/intraday.json?
   - How many slots are halted, and what is each halt reason? A slot is retired
     permanently at a Rs10k cumulative loss — list which ones have gone and how close
     the next ones are.

3. TOKEN + CREDENTIALS (the one recurring manual step)
   - Does vibe-trading/agent/.env exist and hold a DHAN access_token?
   - Dhan tokens expire every 24h. Decode the token's expiry if it is a JWT, otherwise
     report its file mtime and say whether it plausibly covers today's session.
     THIS IS THE MOST COMMON REASON A MORNING FAILS — call it out loudly either way.
   - Confirm GEMINI and TELEGRAM keys are present (do NOT print any secret value —
     report presence and length only).

4. CONFIG SANITY
   - config/intraday.json: confirm 38 universe entries, 64 roster slots, and that the
     roster is 31 rule-long + 31 _ls hybrid + 2 local-LLM.
     Every universe entry must have a real (non-placeholder) security_id.
   - Confirm the fallback config/intraday.long21.json still builds 20 long-only slots.
   - Confirm every roster run_dir actually exists on disk.

5. DEPENDENCIES
   - Is Ollama running, and are both llama3.1:8b and qwen3:8b pulled?
     (The llm_local_a / llm_local_b slots need them.)
   - Does `python -c "import dhanhq"` work?

6. TESTS
   - Run the two suites read-only and report the totals:
     agent (expected 153) and strategies+evaluator (expected 228 + 5).
     Expected grand total 386. If the number differs, say which suite moved and why.
   - Afterwards, re-check the scoreboard mtime and row count from step 2 and confirm
     the test run did NOT modify it (BUG-007 regression check).

7. VERDICT
   - GO or NO-GO for today, in one line, with the single most important reason.
   - If NO-GO, give the exact command or action needed to clear it.
   - List anything to watch during the session today.
```

---

## Why these checks, specifically

| Check | Why it earns its place |
|---|---|
| **Dhan token** | The only recurring manual step (`SESSION.md` → Blockers). It expires every 24h and is the single most likely cause of a failed morning. |
| **Yesterday's log** | BUG-004 has already scratched two trading days. A crash is silent unless someone reads the log — the process simply stops. |
| **Scoreboard integrity** | It is the ranking week's actual deliverable. Duplicate or junk rows have appeared before (BUG-007, and the 07-16 scratch rows). |
| **Roster = 64** | The preflight logs "33 long-only + 31 hybrid = 64". A mismatch means the wrong config is loaded, and the fallback exists precisely for that. |
| **Ollama** | Two roster slots depend on it. It fails quietly — the slots just go degraded. |
| **Test count 386** | A changed count means something moved underneath the live system. |
| **Post-test scoreboard re-check** | BUG-007 was tests polluting the real scoreboard. Verifying after every test run is cheap and catches a regression that would corrupt the deliverable. |

## Note for while `vibe_options/` exists

`vibe_options/` is a copy of this tree and **currently resolves `get_runtime_root()` to this
project's runtime root** (`~/.vibe-trading/intraday/`). Running anything from `vibe_options/`
can write this project's scoreboard. That is why `vibe_options/TRIPWIRE.md` exists and why step 2
of the check above is worth running even on days nothing seemed to happen.
