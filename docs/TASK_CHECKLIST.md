# Task Checklist

✅ done · 🚧 in progress · ❌ not started

## Phase 1–2 (Plan + Document)
- ✅ `IMPLEMENTATION_PLAN.md` (root) — objective, decisions, milestones
- ✅ `README.md` — architecture + account linking + quick start
- ✅ `docs/FLOWS.md` — 5 Mermaid diagrams
- ✅ `CLAUDE.md`, `SESSION.md`
- ✅ `docs/IMPLEMENTATION_PLAN.md` — file-by-file spec

## Phase 3 — M1 (paper intraday loop)
### 3A Intraday MIS engine ✅
- ✅ `vibe-trading/agent/backtest/engines/india_intraday.py` — `IndiaIntradayEngine`
- ✅ `vibe-trading/agent/backtest/runner.py` — routing on `intraday` flag
- ✅ `vibe-trading/agent/tests/test_india_intraday_engine.py` — 16 tests, green
- ✅ Delivery-engine regression re-checked (17 tests, green)

### 3B Strategies (long-only) ✅ — 4 diverse archetypes for the bake-off
- ✅ `strategies/orb_intraday` — long-only ORB (breakout)
- ✅ `strategies/pullback_buy` — VWAP-reclaim long (mean-reversion)
- ✅ `strategies/ema_trend` — fast/slow EMA trend-follow (per-day reset)
- ✅ `strategies/momentum_rsi` — RSI resume-from-dip in an SMA up-trend (momentum-pullback)
- ✅ Intraday configs (`intraday:true`), flat-by-15:00 contract, `strategies/README.md`
- ✅ `strategies/tests/test_intraday_strategies.py` — 12 tests green (4 strategies × 3 checks)
- ✅ Real-data run (yfinance): 0 carries; ORB/pullback negative net-of-cost (need tuning)
- 🚧 Strategy tuning + week-1 paper bake-off will decide which survive — not a blocker

### 3C Data — Dhan 15m history ✅ (verified; placeholder creds)
- ✅ Verified `india_broker` loader + `dhan.sdk.get_historical_bars` handle `15m` (period map + `intraday_daily_candle_data`)
- ✅ Gap found + fixed at our layer: Dhan keys on numeric `security_id`, not the ticker → `src/intraday/bars.py::DhanBarSource` threads `security_id`/`exchange_segment` explicitly (see DC-002)
- ✅ Documented limitation: Dhan intraday candles ≈ last 5 trading days → deep 15m backtests keep using Yahoo (DC-002)

### 3D Live paper runtime + Telegram ✅ (placeholder creds; offline-tested)
- ✅ `src/intraday/config.py` — placeholder-first config (env + JSON), `is_*_configured` predicates, `.env`/`.env.example`/`config/intraday*.json`
- ✅ `src/intraday/clock.py` — IST session windows + square-off cutoff
- ✅ `src/intraday/paper_broker.py` — long-only MIS paper fills (reuses `IndiaIntradayEngine` cost/slippage)
- ✅ `src/intraday/notifier.py` — ENTRY/EXIT/SQUARE-OFF/HALT/watchlist/EOD → Telegram sink or log sink (placeholder-safe)
- ✅ `src/intraday/bars.py` — `DhanBarSource` (live) + `ReplayBarSource` (offline)
- ✅ `src/intraday/runner.py` — market-hours IST loop, per-interval signal→fill, **force-flatten ≥ 15:15**, dynamic strategy load
- ✅ `src/intraday/gemini_jobs.py` — pre-market watchlist + EOD review (stub caller until Gemini key set)
- ✅ `vibe-trading/agent/tests/test_intraday_runtime.py` — 25 tests green
- ✅ Live activation (2026-07-15) — real creds landed; Telegram/Dhan/Gemini all verified against the real services

### 3D.2 Parallel multi-strategy paper bake-off (week-1 plan) ✅
- ✅ `src/intraday/portfolio.py` — 4 strategies in parallel, one shared feed, isolated ₹25k accounts
- ✅ Per-strategy **₹10k setup kill-switch** (permanent retire; survivors continue)
- ✅ `src/intraday/scoreboard.py` — per-strategy metrics + ranked scoreboard + weekly JSON persistence
- ✅ Hourly Telegram rollup + EOD scoreboard (per-trade events → log, not the feed)
- ✅ `config/intraday*.json` roster (orb/pullback/ema_trend/momentum_rsi) + per-strategy cash/cutoff
- ✅ `vibe-trading/agent/tests/test_intraday_portfolio.py` — 13 tests green; 4-strategy E2E smoke ran

### 3E Live activation + launcher (creds day, 2026-07-15) ✅
- ✅ Real creds in `agent/.env` (Gemini, Dhan, Telegram); universe → **HDFCBANK/RELIANCE/TATASTEEL/ICICIBANK** with `security_id`s from the Dhan scrip master (1333/2885/3499/4963)
- ✅ BUG-001 fixed — Gemini real caller rewritten as direct REST (`gemini_generate`); old `src.llm.factory` import never existed
- ✅ BUG-002 fixed — vendored Dhan connector patched for dhanhq **2.x** (DhanContext ctor, renamed candle methods, parallel-array payload) with 1.x fallback; `dhanhq 2.2.0` installed
- ✅ DC-003 fixed — `dhan_config_from_intraday` + `DhanBarSource(dhan_config=…)` thread `.env` creds into the sdk (no `~/.vibe-trading/dhan.json` needed)
- ✅ `src/intraday/bakeoff.py` — launcher CLI (`python -m src.intraday.bakeoff`): config validation, pre-market watchlist, wait-for-open, `Portfolio.run_session`, EOD review, per-day UTF-8 file log
- ✅ `start_bakeoff.bat` (project root) — double-click morning starter (UTF-8 console, PYTHONPATH, window persists)
- ✅ `vibe-trading/agent/tests/test_intraday_live_wiring.py` — 13 tests green (**79 total**)
- ✅ **Detailed hourly report** (user, 2026-07-15): every fill this hour (time/side/qty/price/fee/realized),
  open positions marked to market with unrealized P&L, day P&L + equity per strategy, halt reasons
  (`scoreboard.format_hourly_detailed` + `Portfolio._maybe_hourly`). Live from the 2026-07-16 session
  (day-1 process keeps the old compact rollup — restarting mid-day would wipe paper positions)
- ✅ Live smoke: Telegram send 200 · Dhan 15m bars all 4 symbols · Gemini echo OK
- 🚧 **Week-1 bake-off running** — day 1 started 2026-07-15 08:56 IST; operator refreshes the Dhan token in `agent/.env` each morning + runs `start_bakeoff.bat`

### 3F LLM trader — experimental 5th bake-off slot (user, 2026-07-15) ✅
Amends "Gemini = research/oversight only": Gemini gets ONE paper slot to prove it can trade,
under identical constraints (long-only, ₹25k cash, no leverage, ₹10k kill-switch, 15:15 flatten).
The 4 rule engines stay LLM-free. Live from the **2026-07-16** session.
- ✅ `src/intraday/llm_engine.py` — `LLMSignalEngine`: one Gemini call per 15m tick (whole universe),
  strict-JSON `{"SYMBOL": "long"|"flat"}` parsing, **keep-last-decision on any failure** (never churns,
  never raises), no-entry windows (<09:45, ≥15:00) enforced in code over the LLM, flat without a key
- ✅ `builtin:` roster scheme — lives in the trusted overlay because the repo's VT-001 validator
  (correctly) forbids network/env access in `strategies/` run-dir code; `Portfolio` resolves
  `run_dir: "builtin:llm_trader"` via `build_builtin_engine`
- ✅ Roster now **5** in `config/intraday.json` (+example); total paper capital ₹1.25L
- ✅ **Decision tracking** (user, 2026-07-15): Gemini now replies per symbol with
  `{"decision", "reason", "stop", "target"}`; every tick's decision is appended to a daily JSONL
  journal (`~/.vibe-trading/intraday/llm_journal-YYYYMMDD.jsonl`) with reason + stated SL/target +
  price; on every exit an `exit_eval` record grades the round trip against the LLM's own levels
  (`stop_hit`/`target_hit`/`move_pct`, entry+exit reasons). Stated SL/targets are **tracked, not
  executed** (execution = the backlogged M1 SL/TP feature)
- ✅ `tests/test_llm_engine.py` — 13 tests green (**92 total**); real-config 5-slot build verified
- ❌ Not backtestable by design (no reproducible LLM history) — judged on live paper forward results only

### 3G Roster expansion to 15 strategies (user, 2026-07-15) ✅
10 new long-only archetypes for the parallel bake-off, live from **2026-07-16** (roster 15 =
4 original + llm_trader + 10 new; ₹25k each → ₹3.75L total paper capital).
- ✅ `strategies/gap_go` — gap-up continuation (holds above day open on ≥0.3% gap days)
- ✅ `strategies/gap_fade` — gap-down reversal (buys recovery above opening-bar high)
- ✅ `strategies/vwap_hold` — long above day-VWAP with hysteresis band
- ✅ `strategies/range_break` — 09:15–11:00 range high broken after 11:00
- ✅ `strategies/macd_cross` — intraday MACD(8,17,9), per-day reset
- ✅ `strategies/boll_bounce` — lower-Bollinger snap-back, take-profit at the mean
- ✅ `strategies/boll_break` — upper-band breakout on ≥1.2× volume, exit under the mean
- ✅ `strategies/atr_trail` — new-high entry + 1.5×ATR trailing exit
- ✅ `strategies/rel_strength` — cross-sectional: hold only the strongest symbol vs day open
- ✅ `strategies/three_thrust` — 3 consecutive higher closes, exit on first down close
- ✅ **Infra for 15-strategy scale:** `CachedBarSource` (ONE Dhan fetch per symbol per tick shared
  by all runners — was heading for ~60 API hits/tick) + `TelegramSink` message chunking
  (15-section hourly reports exceed Telegram's 4096-char cap; split on line boundaries)
- ✅ Tests: strategy suite parametrized over **14** run-dir strategies with pattern-matched fixtures
  (gap days / oscillation / volatility surge) → 42 green; +3 infra tests → **125 total**
- ✅ Real-config smoke: 15 slots build, ₹25k each

### 3H TradingView ports — roster to 20 (user, 2026-07-15) ✅
5 classic TradingView strategies ported from Pine to run-dir engines (user picked from a shortlist),
live from **2026-07-16** with the rest of the roster (20 = 19 rule + llm_trader; ₹25k each → ₹5L total paper).
- ✅ `strategies/supertrend` — hl2 ± 2×ATR(10) ratcheted bands, long while trend is up
- ✅ `strategies/ut_bot` — QuantNomad's ATR(10) trailing stop on close (key = 1), long above the stop
- ✅ `strategies/squeeze_momentum` — LazyBear: BB(20,2) inside KC(20,1.5) = squeeze; enter on release
  with positive linreg momentum (≤5-bar grace for momentum warm-up), exit when momentum ≤ 0
- ✅ `strategies/wavetrend` — LazyBear/Cipher B WaveTrend(10,21): wt1/wt2 cross up below the zero line,
  exit on cross down
- ✅ `strategies/qqe_mode` — Wilder RSI(14) → ema5, QQE 4.238 trailing line; long while RSI-ma above
  the trail AND above 50
- ✅ Ports are faithful to the Pine formulas but simplified where documented (WaveTrend buys any
  below-zero cross-up, not only ≤−53; validator forbids negative literal defaults)

### 3S TradingView ports — batch 2 (B3, user 2026-07-18) ✅ BUILT + BACKTESTED, then PROMOTED to live 2026-07-19 (roster 42 → 64, runs 2026-07-20)
11 more TradingView community strategies ported from the user's shortlist screenshot (all 14 shown,
minus 3: `supertrend` already ported in 3H; **3Commas Bot** = a DCA averaging bot, not a 1/0/−1
signal; **Ultimate Strategy Template** = an empty template shell). Each is a validator-clean run-dir
(`config.json` + `code/signal_engine.py`), long-only by default with a mirrored `allow_short` twin.
Backtested offline first (`backtest_all.py`, cached 4-stock Yahoo 15m window); user then said "add
these so they run from Monday" → **PROMOTED 2026-07-19**: each added as a long slot + its `_ls` twin
per 3L, roster 42 → 64 (₹16L), live from 2026-07-20. Config `config/intraday.json` (+`.example`).
- ✅ `strategies/bb_rsi` — ChartArt "Bollinger + RSI Double": lower-band + oversold-RSI reversion, exit at mid band
- ✅ `strategies/macd_sma200` — ChartArt "MACD + SMA 200": MACD stack gated by a slow trend MA (200→100, scaled for 15m/120-bar lookback)
- ✅ `strategies/macd_rsi` — Trebor_Namor "MACD Bull Crossover + RSI Oversold": bull cross confirmed by a recent RSI dip, per-day reset
- ✅ `strategies/pmax` — KivancOzbilgic "PMax": Supertrend-style ATR trail around an EMA, trend flips on the MA
- ✅ `strategies/hull_suite` — DashTrader "Hull Suite": long while the HMA slope is up (`HMA[i] > HMA[i−2]`)
- ✅ `strategies/ao_stoch` — SerdarYILMAZ "AO + Stoch": Awesome-Oscillator gate + Stochastic %K/%D cross trigger
- ✅ `strategies/golden_cross` — ChartArt "Golden Cross SMA 200": fast > slow SMA regime (50/200 → 25/100, scaled)
- ✅ `strategies/flawless_victory` — Trebor_Namor "Flawless Victory 15min": BB + RSI + MFI reclaim (snap-back, RSI floor tuned to 30 for 15m)
- ✅ `strategies/ema_cross` — Che_Trader "single EMA cross": long while close > one EMA (minimal baseline)
- ✅ `strategies/ichimoku` — SeaSide420 "Ichimoku + HULL-MA": above-cloud + Tenkan>Kijun + rising Hull
- ✅ `strategies/rsi_div` — eemani123 "RSI Divergence": confirmed bullish regular divergence on causal pivots
- ✅ Registered in `backtest_all.py` (STRATEGIES + SHORT_NAMES + TUNE_GRIDS) and
  `tests/test_intraday_strategies.py` (×31, +2 fixtures `_long_uptrend_15m` / `_divergence_15m`);
  **186 strategy tests green** (was 120). Adaptations documented in each module docstring
  (SMA200→100, golden 50/200→25/100, Flawless RSI floor 42→30 as a 15m reclaim, ao_stoch gate = "not
  overbought"). Backtest: all 11 net-negative on the down-regime window (best = `macd_rsi` −₹1,819/34
  trades; worst = `ao_stoch` −₹8,639/268 trades — the documented churn/fee-drag pattern). Focused
  report: `docs/BACKTEST_REPORT_TVPORTS.md`; full 31-strategy report regenerated.
- ✅ Tests: strategy suite parametrized over **19** run-dirs (+ `_squeeze_15m` compression-release
  fixture; wavetrend on a 4-day oscillation) → 57 green; **140 total**
- ✅ Real-config check: all 20 roster entries load through `Portfolio`'s loader (repo validators pass)
- ❌ Unbacktested on real data by choice (same stance as 3G) — the paper week ranks them

### 3I Batch backtest harness + first tuning pass (user, 2026-07-15) ✅
- ✅ `strategies/backtest_all.py` — runs all 19 rule strategies through `IndiaIntradayEngine`
  on ~57 days of Yahoo 15m bars (the 15m history cap), ₹25k + full MIS costs, train/validate
  split (34/23 days), ranked scoreboards + **day-on-day net P&L matrix** →
  `docs/BACKTEST_REPORT.md`, `docs/backtest_results.json`, `docs/backtest_daily_pnl.csv`.
  Yahoo data cached in `strategies/.bt_cache/` (do not commit). `--tune` runs the param grids.
- ✅ **Headline finding:** ALL 19 net-negative over 2026-04-23→07-15; 18/19 negative even
  before fees. Context: the tape itself was weak (TATASTEEL −12.7%, RELIANCE −4.3% buy&hold);
  long-only intraday had nothing to ride. Cost-structure signal is real: churners
  (macd_cross 316 trades, three_thrust, boll_bounce) lost the most; selective strategies
  (gap_fade 39 trades, orb 62) lost the least. One window ≠ verdict — the paper week decides.
- ✅ **orb tuned:** `vol_mult 1.3→1.5`, `vol_window 20→12` (best on train, confirmed better
  out-of-sample: −₹1,271 vs −₹2,095) — applied to defaults, live 2026-07-16.
- ✅ **pullback tuning: no change** — grid showed no out-of-sample sensitivity; defaults kept.
- ✅ **3I.2 full-roster tuning (user, same night):** grids for all 19 (115 combos). **7 more
  applied** (OOS gain ≥ ₹300): momentum_rsi `rsi_len 14 / pullback 70`, ut_bot `key 2 / atr 14`,
  three_thrust `4 bars`, squeeze_momentum `kc_mult 1.0`, boll_bounce `window 20 / k 2.0`,
  gap_go `min_gap 0.5`, macd_cross `12/26`. 3 marginal YESes skipped as noise (ema_trend +₹48,
  supertrend +₹103, wavetrend +₹237); 9 no-OOS-gain kept. Roster window total −₹89.4k → −₹71.8k.
  Evidence: `docs/backtest_tuning_20260715.json`. boll_bounce test fixture → `_vshape_15m`
  (2σ bounce needs fat tails; a sine maxes at ~1.41σ). **140 tests green** on final defaults.

### 3J Nifty-50 universe scan (user, 2026-07-15 night) ✅ — awaiting user's stock pick
- ✅ `strategies/universe_scan.py` — 48 Nifty stocks × 18 per-symbol strategies × train/validate
  (~1,700 single-stock backtests) + structural filters (median price ≤ ₹3,000 for ₹6,250-slot
  sizing; ≥ ₹1cr/day turnover) → `docs/UNIVERSE_SCAN.md` + `universe_scan.json`.
  (TATAMOTORS skipped — Yahoo ticker dead post-demerger.)
- ✅ Findings: train↔validate stock ranks flipped (IT rallied late-window) → selection on
  breadth/consistency, not raw rank. **Current 4 all near the bottom** (TATASTEEL & HDFCBANK
  0/18 validate-positive strategies). Standouts: INDUSINDBK (only validate-net-positive stock,
  11/18), HCLTECH & TCS (8/18), TECHM (7/18), BAJFINANCE & INFY (5/18), ADANIENT (best total).
- ✅ Candidate-12 roster backtest (`BACKTEST_REPORT_CANDIDATE.md`): validate window has
  **8/19 strategies gross-positive** (gap_fade net **+₹120**) vs 0/19 on the current universe.
  Caveat: backtest splits capital across all 12; live loop concentrates ₹6,250 × max 4 —
  live fee drag will be lower than the backtest shows.
- ❌ `config/intraday.json` NOT changed — universe is a user decision; also needs Dhan
  `security_id` per new stock from the scrip master before going live.

### 3K Universe switch to 38 + oi_dma_adx strategy (user, 2026-07-15 night) ✅
- ✅ User decision: **trade the whole feasible Nifty pool, no performance-based selection** —
  38 stocks (structural filters only: median ≤ ₹3,000 for ₹6,250-slot sizing + ₹1cr/day
  liquidity; excludes 11 too-pricey names + TATAMOTORS whose ticker died in the demerger).
- ✅ `config/intraday.json`: 38-entry universe, every `security_id` extracted + verified from
  the Dhan scrip master (the 4 previously-live ids matched exactly → extraction sound);
  `lookback_bars` 60→120 (oi_dma_adx warm-up; Dhan 15m history ≈5 days ≈125 bars covers it);
  `max_positions` stays 4. Junk scoreboard rows (A/B, 07-14) removed (backup kept).
- ✅ **`strategies/oi_dma_adx` (new, 21st slot):** daily-anchored 3-day DMA filter × Wilder
  ADX(14) ≥ 20 with +DI>−DI × OI long-buildup gate. **OI gate is pass-through for now** — spot
  equities have no OI; wiring the stock-futures OI feed from Dhan FNO is backlogged. Trades as
  DMA×ADX until then (documented in the engine docstring).
- ✅ Tests: 60 strategy (20 × 3) + 83 agent = **143 green**; all 21 roster slots load through
  `Portfolio`'s loader.
- ✅ 38-stock full-roster backtest → `docs/BACKTEST_REPORT_ALL38.md`.

### 3L Long-vs-hybrid A/B — 21 short-capable `_ls` twins (user-approved 2026-07-15 night) ✅ BUILT + QA GREEN
- ✅ **Spec written** (2026-07-15, Fable) → `docs/IMPLEMENTATION_PLAN.md` §3L — complete
  file-by-file handoff incl. broker accounting identities, invariants, and test plan.
- ✅ **Build (Opus, 2026-07-16) — all 11 files in the listed order:**
  - ✅ `india_intraday.py` — honors config `allow_short` (default off = identical); short entry
    (a sell) blocked at the **lower** circuit; parent engine's short machinery reused.
  - ✅ `paper_broker.py` — `short()`/`cover()`/`close_position()` + `Position.direction`;
    1x reserve = notional + entry comm; accounting identities hold (round-trip = −Σcomm; equity
    continuous, jumps only by commission+slippage; STT on the short leg, stamp on the cover;
    cover clamps/no-flip; buy⊥short per symbol — invariant 6).
  - ✅ `runner.py` — `allow_short` ctor + `load_signal_engine(..., allow_short=)` (TypeError =
    fail-fast); desired ∈ {−1,0,1} (−1→0 on the long-only arm); exits close-then-flip via
    `close_position`; `_force_flatten` covers shorts (invariant 2, incl. no-price fallback).
  - ✅ `config.py` — `StrategyRef.allow_short` parsed from roster JSON.
  - ✅ `portfolio.py` — threads `allow_short`; kill-switch retire covers shorts; **per-slot
    try/except in `run_tick` isolates one slot's failure from the other 41** (mandatory — one
    process hosts both arms); hourly sections carry per-leg decomposition.
  - ✅ `llm_engine.py` — hybrid `allow_short` ctor; prompt offers `"short"`; `_parse` maps
    short→−1 only on a twin; direction-aware open/close/flip journaling; **short `exit_eval`
    grades with stop ABOVE / target BELOW entry** (`high≥stop` / `low≤target`).
  - ✅ All **20** `strategies/*/code/signal_engine.py` — `allow_short=False` ctor param; mirrored
    −1 branch (documented per engine); no-arg ctor stays long-only; validator-clean (no negative
    literal defaults, no `@staticmethod`, no network).
  - ✅ `config/intraday.json` (+`.example`) — roster **21 → 42** (`<name>_ls`, same run_dir +
    `"allow_short": true`; `llm_trader_ls → builtin:llm_trader`); **₹10.5L** total paper.
    21-slot fallback preserved verbatim as **`config/intraday.long21.json`**.
  - ✅ `scoreboard.py` — `StrategyMetrics.long_pnl`/`short_pnl` (Σ realized of sell vs cover),
    trades/wins count both; `lng₹`/`sht₹` scoreboard columns; hourly renders 🔻SHORT/🔺COVER,
    per-leg line for hybrids, open shorts marked 📉 with short-side unrealized.
  - ✅ `bakeoff.py` — `validate_roster` preflight logs both arms (21 long / 21 hybrid) and
    **fails fast** (exit 2 → launch-gate fallback) if any twin can't build with `allow_short=True`.
  - ✅ Tests: new **`tests/test_intraday_shorts.py`** (23 — broker identities, runner −1/flip/cap/
    coercion, 15:15 force-cover with & without a last price) + `test_intraday_portfolio.py` (+5:
    twin isolation, kill-switch covers a short, one-slot exception isolation, leg decomposition) +
    `test_llm_engine.py` (+5: short parse/coercion, hybrid prompt, flipped short `exit_eval`) +
    `test_intraday_strategies.py` (+60: ×20 hybrid emits −1 on a mirrored fixture, never shorts
    outside the window, no-arg ctor never shorts, short round-trips run same-day MIS).
- ✅ **Existing 143 pass** — with ONE spec-mandated edit: the old
  `test_short_blocked_even_if_allow_short_requested` asserted the very "config can't re-enable
  shorting" contract File 1 reverses; rewritten as `test_short_permitted_when_allow_short_opted_in`
  (default still long-only via `test_short_always_blocked`). Grand total **236 green**
  (agent 116 + strategies 120).
- ✅ Integration smoke: 42-slot config builds (21 long + 21 hybrid, every twin `allow_short=True`);
  replay session with a hybrid short renders per-leg hourly + `lng₹`/`sht₹` scoreboard, pair delta
  isolates the short side.
- ✅ **QA (Fable, 2026-07-16 ~01:00)** — **all §3L gates GREEN: 236 tests** (116 agent +
  120 strategy), 15:15 force-cover hard gate passed (with & without last price), baseline
  142/143 intact + 1 deliberate replacement (the repealed "config can never enable shorts"
  engine test), `validate_roster` preflight built all 42 slots + the 21-slot fallback.
  `docs/QA.md` session + `TEST_REPORT.md`/`UNIT_TESTS.md` regenerated.
- 🚧 **Launch hybrid arm 07-16** (user amended 07-15 night; was 07-17) — **launch gate OPEN**
  (all QA green). Morning: refresh Dhan token → `start_bakeoff.bat` → 42 × 38, ₹10.5L paper.
  Fallback `intraday.long21.json` stays available. Paper-only: live/M2 shorting stays a
  separate user decision.

### 3M Deprecate the LLM trader slots — roster 42 → 40 (user 2026-07-16, cost) ✅ EXECUTED
- ✅ **Decision:** retire `llm_trader` + `llm_trader_ls` on **cost** grounds (measured live 07-16:
  ~50 Gemini calls/day, ≈265k in / 76k out tokens/day + 7 httpx timeouts). Reverts the 07-15
  amendment → **Gemini = research/oversight only again**. Watchlist + `eod_review` kept (~1 call/day).
- ✅ **Soft-disable via roster only** — `llm_engine.py` + its 18 tests + the `builtin:` extension
  point retained (one-line revert if pricing changes). No code deleted.
- ✅ `config/intraday.json` (+`.example`) — dropped both entries: **42 → 40** (20 long + 20 `_ls`;
  pairing stays symmetric, 3L A/B unaffected). Paper **₹10.5L → ₹10L**. Per-tick Gemini calls **2 → 0**.
- ✅ `config/intraday.long21.json` — dropped `llm_trader`: **21 → 20** (filename kept; `_roster_comment` notes it).
- ✅ `src/intraday/bakeoff.py` L133 — launch-gate message "21 long-only" → "20 long-only". `make_llm_caller`/
  `premarket_watchlist`/`eod_review` all kept (the research jobs).
- ✅ **Gates GREEN (2026-07-16):** `validate_roster` builds **40 + 20** (exit 0) · **236 tests** (116 agent
  + 120 strategy) · no `builtin:llm_trader` in the two live configs · today's `llm_trader` scoreboard row +
  `llm_journal-20260716.jsonl` preserved.
- ✅ BUG-005 closed **WON'T FIX** (slot deprecated) — see `docs/BUGS.md`.

### 3N Ride out short Wi-Fi / data drops before a tick (user 2026-07-16) ✅ EXECUTED
- ✅ **Requirement:** auto-resume without human intervention across a data drop **up to ~5 min**.
  Host/process crashes explicitly **out of scope** (user: "crashes shouldn't happen now" → stays the
  separate BUG-004 track).
- ✅ `src/intraday/portfolio.py` — new **`_await_data`** (+ `_probe`) called at the top of each tick in
  `run_session`: probe one canary symbol; **online → return instantly** (probe warms the shared cache →
  `run_tick` reuses it, zero extra live fetch); **outage → backoff 5s→30s, re-probe until data returns
  or the budget lapses**, refreshing `now` each retry; on lapse, proceed and degrade to the pre-3N
  empty-frame *hold* (only that bar lost).
- ✅ `src/intraday/config.py` — new **`reconnect_budget_seconds`** (default **300 = 5 min**, `< 900s`
  tick; `0` disables). Config-tunable, no code change to retune.
- ✅ `tests/test_intraday_portfolio.py` **+4** (online no-wait; outage-then-resume; budget-bounded;
  disabled) → **240 total** (was 236). `validate_roster` still builds 40 + 20; real config loads with 300.

### 3O–3R + BUG-007 — tonight's batch ✅ EXECUTED 2026-07-17 post-close (build = Opus; gates all green)
- ✅ **BUG-007 pre-step** — `tests/test_intraday_portfolio.py::_portfolio()` now defaults to a
  **tempfile-backed** `ScoreboardStore`; the real scoreboard.json verified untouched after the full
  suite (exactly 40 rows, 2026-07-17). BUG-007 → Resolved.
- ✅ **§3O (B1)** — `src/intraday/local_llm.py::ollama_generate` (**new**); `gemini_jobs._call` retries
  transient failures 3× (2s/8s) then runs the prompt through local Ollama (`[local]` prefix) before the
  static fallback; `make_llm_caller` attaches the fallback; `eod_review` aggregates **per-strategy
  lines** (name/trades/net/fees/best/worst symbol) past 40 fills via new `metrics` +
  `fills_by_strategy` params (wired from `bakeoff.run_day`); config `ollama_url`/`ollama_model`
  (+ env vars). New `tests/test_gemini_jobs.py` (13). BUG-006 → Resolved.
- ✅ **§3P (B4)** — `format_hourly_detailed`: idle slots collapse to one `— N slots idle` line,
  sections sort movers-first (fills by |net| → holders → nonzero-quiet), fills capped at 8/slot
  (`… +N more (log)`), `⇅ legs` line only when a leg ≠ 0; `format_scoreboard` topline
  `Σ net · fees · trades · P of M profitable`. +6 formatter tests. **The hourly per-slot shape was
  superseded by B4-2 (pair-collapse) for the 64-slot roster; the `Σ …` topline carries over.**
- ✅ **§3Q (B2)** — doc-only: README **"Cost model"** section (component table, ADANIENT worked
  example ₹1.33/₹2.02, min(₹20, 0.03%) vs flat-₹20, sizing note). Engine verified correct — no bug entry.
- ✅ **§3R (B5)** — `StrategyRef.params` (per-slot kwargs) → roster slots **`llm_local_a`**
  (llama3.1:8b) / **`llm_local_b`** (qwen3:8b, pulled); `LLMSignalEngine` provider-aware
  (`provider="ollama"`, per-slot `model`, no key needed), **slot-tagged** journal/logs, **bounded
  keep-last** (3 consecutive failures → degraded = flat, success resets); `build_builtin_engine`
  takes `slot_name` + `**params` (portfolio + `validate_roster` both thread them). Roster **40 → 42**
  (₹10.5L). Long-only, no `_ls` twins. +7 llm tests, +3 portfolio/config tests.
  - Gate results: **268 tests green** (agent 148 + strategies 120) · `validate_roster` 42 + 20 ·
    live smoke + latency **llama3.1:8b 14.5s / qwen3:8b 20.8s** (< 60s, both slots stay; found +
    fixed: `num_ctx` 8192 truncated the 9.6k–13.7k-token prompt → 16384, `think: false` for qwen3).

### Added 2026-07-19 (user) — "get more TradingView strategies + evaluate the best"
- ✅ **B6 · Robustness evaluator** — `strategies/evaluate_strategies.py`: ranks every strategy by
  **breadth** (each of the 49 cached symbols run one-at-a-time — no 1/N capital-split confound) ×
  **stability** (4 walk-forward folds) × **cost robustness** (net at 2× slippage), with a transparent
  consistency-led, churn-penalised `score`. Report → `docs/STRATEGY_EVALUATION.md`. +5 tests
  (`tests/test_evaluate_strategies.py`). **Honest limit documented:** Yahoo's ~57-day 15m cap = one
  regime, so offline can't test bull-vs-bear; the *relative* rank is the signal, live weeks are the
  arbiter. **Finding:** top by robustness = squeeze_momentum, gap_fade, gap_go, macd_rsi, boll_break,
  bb_rsi; worst = the fee-bleeders **ema_cross (88 trades/sym), hull_suite (81), macd_cross (77),
  ao_stoch (75)** — the ₹10k kill-switch will likely retire those live. Of §3S's ports, macd_rsi /
  bb_rsi / rsi_div rank well; ema_cross / hull_suite / ao_stoch are the churners.
- ✅ **B7 · Curated shortlist for the next port batch** → `docs/STRATEGY_SHORTLIST.md` (14 vetted
  candidates, Tier 1–2, open-source + intraday-suitable + new archetype). Tier-1 next batch: CPR/pivots,
  Parabolic SAR, Supertrend+VWAP, Donchian breakout, Keltner breakout, StochRSI, Connors-RSI2.
  Also documented **why "all of TradingView" is infeasible** (protected sources, no bulk API, each
  needs a hand-port). **Tier-1 batch PORTED 2026-07-19 → §3U below.**

### 3U Tier-1 shortlist port batch (B7, user go-ahead 2026-07-19) ✅ BUILT + BACKTESTED + RANKED (offline only)
7 Tier-1 candidates from `docs/STRATEGY_SHORTLIST.md` ported as validator-clean run-dirs
(`config.json` + `code/signal_engine.py`), long-only by default with a mirrored `allow_short` twin,
each a **new archetype** not already covered. **Scope = OFFLINE ONLY** — same stance as §3S's first
pass: ported + backtested + ranked, but **`config/intraday.json` / the 64-slot live roster NOT
touched** (no `_ls` twins added to the roster; promotion is a separate user decision).
- ✅ `strategies/cpr_pivot` — Central Pivot Range: prior-day H/L/C → pivot/BC/TC, long above the top
  central line, flat back at the pivot (the classic NSE intraday framework; needs one prior session)
- ✅ `strategies/psar_flip` — Wilder Parabolic SAR flip: long while the accelerating trail sits below
  price (trailing-stop trend archetype; sequential recursion + prior-two-bar clamp)
- ✅ `strategies/supertrend_vwap` — confluence gate: long only when Supertrend-up AND close > session
  VWAP (both pieces reused from `supertrend` / `vwap_hold`; ANDed)
- ✅ `strategies/donchian` — Turtle channel breakout: long > prior-`entry_bars` high, exit < prior-`exit_bars`
  low (rolling channel, distinct from `range_break`'s fixed session box)
- ✅ `strategies/keltner` — standalone EMA±ATR channel breakout, exit at the EMA middle line
- ✅ `strategies/stoch_rsi` — double-smoothed StochRSI %K/%D cross out of the extreme zones
- ✅ `strategies/connors_rsi2` — Larry Connors RSI(2) reversion in an up-trend (200-SMA filter adapted
  to 100 for the 15m/120-bar lookback, same as `golden_cross`/`macd_sma200`)
- ✅ Registered in `backtest_all.py` (STRATEGIES + SHORT_NAMES + TUNE_GRIDS) and
  `tests/test_intraday_strategies.py` (×38, +1 fixture `_dip_uptrend_15m`; stoch_rsi → oscillation,
  connors_rsi2 → dip-uptrend). **228 strategy tests green** (was 186); **381 total** (agent 148 +
  strategies 228 + evaluator 5). **BUG-008 found + fixed** (connors RSI(2) degenerate zero-loss → 100).
- ✅ Backtest (cached 4-stock Yahoo 15m): all 7 net-negative on the down regime (least-bad `keltner`
  −₹2,691/95 trades; worst `stoch_rsi` −₹7,920/261 — the documented churn/fee-drag pattern). Focused
  report `docs/BACKTEST_REPORT_TIER1.md`; full 38-strategy report regenerated.
- ✅ Robustness rank (`evaluate_strategies.py`, 49 symbols × 4 folds × 2× slippage): **donchian**
  (−38.7, pos-rate 15%, 21 trades/sym) and **keltner** (−61.5, 12%, 28) are the batch standouts
  (mid-pack, ~rsi_div tier); cpr_pivot / connors_rsi2 / psar_flip / stoch_rsi / supertrend_vwap are
  churny fee-bleeders on this one regime (kill-switch candidates if ever promoted).
- 📨 **Pending user decision:** promote survivors (donchian / keltner most defensible) to the live
  paper roster as long + `_ls` twins → the live weeks are the real arbiter. Tier-2 batch (Vortex,
  CCI, Heikin-Ashi, Chandelier, TRIX, Coral, CMF) still queued.

## Backlog — M1 (queued)
- ❌ **Per-trade stop-loss + profit-target (user, 2026-07-15):** per-strategy `stop_pct` / `target_pct`
  config; paper broker checks each bar's **high/low** (not just close) to simulate an intra-bar touch;
  the same logic mirrored in `IndiaIntradayEngine` so backtests stay comparable to paper; exits notified
  as EXIT with a stop/target tag. **Decision checkpoint: after ~3 trading days of the bake-off
  (≈ 2026-07-17/18), re-evaluate both features** against the observed per-trade drawdowns before building.
- ⚠️ Strategy tuning — first pass done in 3I (orb re-tuned, pullback unchanged); broader
  tuning of the other 17 deliberately deferred until the bake-off produces live rankings.

### Added 2026-07-17 (user) — B1/B2/B4/B5 ✅ EXECUTED 2026-07-17 post-close (see "3O–3R + BUG-007" above). B3 deferred to 2026-07-18 (user).
- ✅ **B1 · Gemini day-end feedback (`eod_review`) → §3O:** review the EOD journal-review bookend
  (`src/intraday/gemini_jobs.py::eod_review`) — is the feedback actually useful/actionable, and does it
  even run given the 429 quota risk (see BUG-006)? The EOD call fires ~15:30 IST, which is *after* the
  ~12:30 IST Pacific quota reset, so it likely succeeds even when the 08:37 watchlist 429s — confirm.
  Consider: richer per-strategy context in the prompt, and a retry/backoff so a transient failure doesn't
  drop the review.
- ✅ **B2 · Trade-cost model vs real brokers (₹20/order) → §3Q (verified: Dhan tariff = min(₹20, 0.03%) = engine's exact model; doc-only):** user flag — Zerodha & most discount brokers
  charge brokerage = **min(₹20, 0.03%) per order**, i.e. a **flat ₹20 cap**. The engine **already** models
  this (`india_intraday.py:120` `min(in_brokerage_cap=20, notional×0.0003)`), but at our ~₹6k position
  sizes the 0.03% (≈₹1.80) binds, not the ₹20 cap (cap only bites above ~₹66.7k notional). The ~**0.106%**
  I showed is the **all-in round trip** (brokerage + STT + stamp + exchange + GST + SEBI), *not* brokerage
  alone. **Task tonight:** decide whether the model matches the user's actual broker bill — e.g. some
  brokers are **zero-brokerage on equity delivery / flat ₹20 on all intraday**; if the user's broker is
  flat-₹20-always or zero-brokerage, the `in_brokerage`/`in_brokerage_cap` config needs adjusting. Also
  re-examine whether ₹6k sizing makes fees an unwinnable drag (ties to B-sizing / fewer-trades ideas).
- ✅ **B3 · Add a lot more strategies (2026-07-18/19):** 11 TradingView ports built + backtested
  offline (§3S) **and PROMOTED to the live roster** (user, 2026-07-19): all 11 added as long + `_ls`
  twins → **roster 42 → 64** (₹16L paper), runs from Monday 2026-07-20. Gates green: `validate_roster`
  builds 64 + 20 fallback; scale check ~1.1 s/tick (62 rule slots × 38 symbols, ≈800× headroom);
  334 tests green. Config: `config/intraday.json` (+`.example`); fallback `intraday.long21.json`
  unchanged. Each is a validator-clean run-dir (no `@staticmethod`, no negative-literal defaults, no network).
- ✅ **B4-2 · Telegram report reworked for the 64-slot roster (user, 2026-07-19; DONE, mockup-approved):**
  §3P's diet (idle-collapse, movers-first, 8-fill cap) was sized for 40–42 slots; at 64 the hourly
  **detailed** report ballooned to **4 chunks / 12,655 chars** and the EOD scoreboard to **2 chunks /
  4,551 chars**. Reworked (report formatters only — no engine/strategy/config edits):
  `format_hourly_detailed` now renders **one row per long/`_ls` pair** (long · ls · short-leg ₹ ·
  **Δ = ls − long** · fill/hold counts), **all pairs** shown movers-first, halted pairs always listed
  (both legs, ✖), unpaired `llm_local_a/b` on their own line → **1 chunk / 1,905 chars**;
  `format_scoreboard` collapses to one pair row (long vs ls + short leg), ranked by best leg, halted
  last → **1 chunk / 1,931 chars**; both enforce a hard **≤3-chunk** cap (`_cap_report` +
  `notifier.split_for_telegram`) with a `… +N more pairs (log)` truncation pointer. `eod_review`'s
  past-40-fills aggregation pair-collapsed to match. Formatter tests regenerated for the new shape
  (+5 net; **386 green**). Params: top-N dropped (user: show all pairs), chunk cap 3, hourly sort =
  max(|long|,|ls|) desc / EOD sort = best leg. User-approved via a text mockup before any code.
- ✅ **B4 · Optimize hourly + day-end reports → §3P:** rework `format_hourly_detailed` / `format_scoreboard`
  (+ `eod_review`) for signal-over-noise — 40 slots × per-fill detail is a lot of Telegram text. Ideas:
  summarize/collapse quiet slots, lead with movers + P&L leaders, tighten the per-leg decomposition,
  maybe a compact top-N + "N others flat" rollup. Keep the full detail in the log tape.
- ✅ **B5 · Local-LLM trader → §3R (hw verified: Ollama 0.30.6, RTX 5070 12GB, llama3.1:8b pulled; candidates = llama3.1:8b + qwen3:8b as two slots):** revive the LLM trading slot
  killed in §3M, but driven by **local LLMs** instead of Gemini → **zero marginal cost, no 429/quota, no
  network ReadTimeouts** (kills the entire §3M cost rationale). §3M was a soft-disable *by design* — 
  `src/intraday/llm_engine.py` + its 18 tests + the `builtin:` extension point are all retained, so this
  is mostly: (a) a **new caller** alongside `make_llm_caller` that hits a local endpoint (Ollama
  `localhost:11434`, or an OpenAI-compatible llama.cpp / LM Studio server) instead of `gemini_generate`;
  (b) re-add the `builtin:llm_trader` roster entry (+ `_ls` twin) — one line each. **Keep it in the
  trusted overlay** (VT-001 forbids network in `strategies/` run dirs — localhost still counts).
  **Scope (user, 2026-07-17): "a couple of local LLMs" = CANDIDATES to try** (evaluate a couple of
  models for the slot, pick one) — **not** an ensemble/agreement gate. Still open: which models +
  what's the PC's GPU/VRAM? **Latency is the real risk** —
  the prompt is 38 symbols × 8 bars; local inference on a fat prompt every 15m tick must finish well
  inside the tick, especially ×2 slots ×2 models. **Re-apply the BUG-005 lesson:** bound keep-last (no
  `forced_flat` freeze) and put the slot name in the journal + every log line before relaunching.

## Phase 3 — M2 (gated live) ❌
- ❌ `dhan-live-trade` profile + lift paper cap behind operator boundary
- ❌ Mandate config (universe, size cap, daily-loss cap, max positions)
- ❌ Daily 24h token refresh before 09:15
- ❌ SEBI checklist (static IP, generic algo ID, < 10 OPS)

## Known limitations
- Backtest square-off is strategy-driven (DC-001); the live paper runtime now enforces it independently (`runner._force_flatten`).
- Full pytest suite not yet run (heavy optional deps); targeted suites green (engine 16 + runtime 25 + portfolio 13 + wiring 16 + llm 13 + strategies 57 = **140**).
- ₹25–50k universe: costs are a large share of edge — validate net-of-cost in paper before live.
- Dhan intraday history ≈ 5 trading days (DC-002): live paper bars come from Dhan; deep 15m backtests stay on Yahoo.
- Paper fills at the observed bar's **close** vs the backtest's next-bar-open — a small, documented paper-vs-backtest basis.
- Dhan access token **expires every 24h** — manual morning refresh in `agent/.env` for now (automated refresh is an M2 item).
- One `start_bakeoff.bat` invocation = one trading day; no multi-day daemon (Task Scheduler is the M2-era answer).
