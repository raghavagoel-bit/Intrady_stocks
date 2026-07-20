# CLAUDE.md — Vibe-Intraday

Project-specific instructions. Inherits the global 5-phase workflow + docs autopilot.

## What this is
NSE intraday (MIS) trading assistant built on **HKUDS/Vibe-Trading** (MIT).
Dhan = data + execution. Gemini = research + oversight (NOT per-bar decisions).
Paper-first, then a small ₹25–50k live trial. **Live = long-only.** Since 2026-07-16 the
paper bake-off also runs short-capable `_ls` hybrid twins (3L A/B, **paper only** — user
decision 2026-07-15; promoting shorts to live/M2 needs its own explicit decision).
See `IMPLEMENTATION_PLAN.md` (§3L for the hybrid arm).

## Tech stack
- **Base:** Vibe-Trading `agent/` Python package (`pip install vibe-trading-ai` or clone).
- **LLM:** Gemini via `LANGCHAIN_PROVIDER=gemini`, `LANGCHAIN_MODEL_NAME=gemini-3.5-flash`, `GEMINI_API_KEY`.
- **Broker/data:** Dhan via `dhanhq` SDK. Config: `client_id` + `access_token` (24h expiry).
- **Backtest:** repo runner — run dir = `config.json` + `code/signal_engine.py` (class `SignalEngine`, no-arg ctor, `generate(data_map) -> {symbol: signal Series}` of 1/-1/0).

## Ports / entry points
- API server: `8899` (set `API_AUTH_KEY` before exposing beyond localhost).
- Frontend dev (Vite): `5899`.
- CLI: `vibe-trading ...`. Backtest: `python -m backtest.runner <run_dir>` (from `agent/`).

## Run
- Configure `agent/.env` (Gemini block + Dhan). Then `vibe-trading connector use dhan-live-sdk-readonly` → `connector check`.
- Intraday runner + scheduler: enable `VIBE_TRADING_ENABLE_SCHEDULER=1` (design in Phase 3).

## Tests + build
- Python/pytest: `python -m pytest` — **run before every build** (global rule).
- Keep `docs/UNIT_TESTS.md` + `docs/TEST_REPORT.md` current; regenerate the report before builds.
- Intraday engine needs its own tests: same-day exit allowed, MIS cost math, 15:15 flatten
  (incl. **force-cover of paper shorts** — hard invariant), long-only by default (shorts only
  via explicit `allow_short` opt-in; no-arg `SignalEngine()` must never emit −1).

## Do NOT commit
- `agent/.env`, `dhan.json`, any `access_token`/API keys, audit ledgers, run outputs, `~/.vibe-trading/`.
- `strategies/.bt_cache/` (downloaded Yahoo 15m bars for `strategies/backtest_all.py`).

## Repo gotchas (load-bearing)
- Dhan connector is **paper-only by design** (`dhan/sdk.py::_PAPER_ONLY_ERROR`). Live orders require an explicit operator-declared boundary — M2 only.
- India engine **hard-codes T+1** (`india_equity.py::can_execute`) — blocks intraday until the MIS mode (plan §3, P1) is added.

## GitHub remote / branch
- Not yet initialized. TBD in Phase 3 Step 0 (clone base repo to permanent location; decide fork vs vendored copy).
