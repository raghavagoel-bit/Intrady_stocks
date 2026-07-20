# Test Report

Regenerate before every build. Newest run at top.

## 2026-07-19 (B4-2) — Telegram report rework for the 64-slot roster

Command: agent + strategy suites, per SESSION.md "How to run tests".

| Suite | Result |
|---|---|
| Agent (`test_india_intraday_engine` / `test_intraday_runtime` / **`test_intraday_portfolio`** / **`test_intraday_live_wiring`** / `test_llm_engine` / `test_intraday_shorts` / **`test_gemini_jobs`**) — §3P formatter tests regenerated for the pair-collapsed shape; +5 net new cases | ✅ **153 passed** (was 148) |
| Strategies (`test_intraday_strategies.py`, 38 × 6) — untouched | ✅ **228 passed** |
| Evaluator (`test_evaluate_strategies.py`) — untouched | ✅ **5 passed** |
| **Total** | **✅ 386 passed, 0 failed** (was 381; +5) |

**What changed (report formatters only — no engine/strategy/config edits):**
- `scoreboard.format_hourly_detailed` — was a per-slot block (header + legs + ≤8 fills +
  positions) that ballooned to **4 Telegram chunks / 12,655 chars** at 64 slots. Now one
  row per long/`_ls` **pair** (long net · ls net · short-leg ₹ · **Δ** = ls − long · fill/hold
  counts), **all pairs** shown movers-first, halted pairs pulled out and always listed (both
  legs, ✖ on the retired leg), unpaired `llm_local_a/b` on their own line. → **1 chunk / 1,905 chars.**
- `scoreboard.format_scoreboard` (EOD) — was a flat 64-row table (**2 chunks / 4,551 chars**).
  Now one row per pair (long vs ls side-by-side + short leg), ranked by best leg, halted last
  (✖). → **1 chunk / 1,931 chars.**
- Both run through `_cap_report(…)` → hard **≤3-chunk** cap (measured with the real
  `notifier.split_for_telegram`); over-cap content truncates with a `… +N more pairs (log)` pointer.
- `gemini_jobs.eod_review` — the past-40-fills aggregation is pair-collapsed to match (one line
  per pair, long-vs-twin, combined best/worst symbol); prompt now asks whether the short leg helped.

**Chunk-count verification (synthetic 64-slot mid-day portfolio, `scratchpad/b42_mockup.py`,
rendered through the real formatters + chunker):**

| Report | Before (42-slot §3P diet, at 64) | After (B4-2) |
|---|---|---|
| Hourly detailed | 12,655 chars / **4 chunks** | 1,905 chars / **1 chunk** |
| EOD scoreboard | 4,551 chars / **2 chunks** | 1,931 chars / **1 chunk** |

**Caught during the rework (pre-ship, no shipped bug):** the initial pairing sent a *halted*
unpaired slot (e.g. a kill-switched `llm_local_a`) to the plain `llm:` line with no ✖ — the old
per-slot format always showed a halt. Fixed in the same pass: both formatters flag a halted
unpaired slot with ✖ (halted-always-visible rule preserved).

## 2026-07-19 (later) — §3U Tier-1 shortlist port batch (B7, +7 strategies, offline)

Command: strategy suite + agent suites, per SESSION.md "How to run tests".

| Suite | Result |
|---|---|
| Strategies (`test_intraday_strategies.py`, **38 strategies × 6 checks**) — +7 Tier-1 ports (cpr_pivot, psar_flip, supertrend_vwap, donchian, keltner, stoch_rsi, connors_rsi2); +1 fixture `_dip_uptrend_15m` (Connors RSI(2): up-trend + sharp 2-bar dips) | ✅ **228 passed** (was 186) |
| Evaluator (`test_evaluate_strategies.py`) — untouched | ✅ **5 passed** |
| Agent suites (untouched by §3U — this batch only added `strategies/` run-dirs; no agent/config edits) | ✅ **148 passed** |
| **Total** | **✅ 381 passed, 0 failed** (was 339; +42 = 7 strategies × 6) |

Each new strategy passes all 6 checks (AST/class validators; long-only + flat outside 09:45–15:00;
`allow_short` twin emits ≥1 short on the mirror; no-arg ctor never shorts; both directions produce
same-day-only MIS trades). **Found + fixed during the run:** `connors_rsi2._rsi` used `fillna(50)` for
the RSI's degenerate zero-loss case, which on a 2-bar RSI collapsed a should-be-100 (fully overbought)
value to a neutral 50 → the mirrored short never armed. Corrected to the standard convention (avg_loss
== 0 & avg_gain > 0 → RSI = 100); the all-down long case (RSI → 0) was already correct (BUG-008).

**Offline runs (second opinion, not tests):**
- `backtest_all.py` (cached 4-stock Yahoo 15m) — all 7 net-negative on this down regime (least-bad
  `keltner` −₹2,691/95 trades; worst `stoch_rsi` −₹7,920/261). Focused report:
  `docs/BACKTEST_REPORT_TIER1.md`; full 38-strategy report regenerated (`docs/BACKTEST_REPORT.md`).
- `evaluate_strategies.py` (49 cached symbols × 4 folds × 2× slippage) — of the batch, **donchian**
  (score −38.7, pos-rate 15%, 21 trades/sym) and **keltner** (−61.5, 12%, 28) rank respectably
  (mid-pack, ~rsi_div tier); cpr_pivot (−101.9), connors_rsi2 (−149.2), psar_flip (−152.6),
  stoch_rsi (−165.6), supertrend_vwap (−171.7) are churny fee-bleeders on this one regime. Overall
  top unchanged (squeeze_momentum, gap_fade, gap_go). Report: `docs/STRATEGY_EVALUATION.md`.
  **Offline only — no live-roster promotion** (pending user go-ahead per the funnel).

## 2026-07-19 — §3T robustness evaluator + §3S roster promotion (42 → 64)

| Suite | Result |
|---|---|
| Strategies (`test_intraday_strategies.py`, 31 × 6) | ✅ **186 passed** |
| **Evaluator (`test_evaluate_strategies.py`, new)** — fold partition/degenerate, score (consistency dominates + churn penalty + median bonus), cache-filename → ticker recovery (incl. `M&M`, `BAJAJ-AUTO`), one real `evaluate()` over a 2-symbol synthetic set | ✅ **5 passed** |
| Agent suites (untouched by §3S/§3T) | ✅ **148 passed** |
| **Total** | **✅ 339 passed, 0 failed** (was 334; +5 evaluator) |

**§3S promotion gate:** `validate_roster` builds **64 + 20 fallback** (exit 0); scale check ~1.1 s/tick
(62 rule slots × 38 symbols, ≈800× headroom). **§3T evaluator run:** 31 strategies × 49 cached symbols
× (full + 4 folds + 2× slippage) → `docs/STRATEGY_EVALUATION.md`; top by robustness = squeeze_momentum,
gap_fade, gap_go, macd_rsi, boll_break, bb_rsi; worst = ema_cross/hull_suite/macd_cross/ao_stoch (churn).

## 2026-07-18 — §3S TradingView ports batch 2 (11 strategies, offline)

Command: strategy suite + agent suites, per SESSION.md "How to run tests".

| Suite | Result |
|---|---|
| Strategies (`test_intraday_strategies.py`, **31 strategies × 6 checks**) — +11 TV ports (bb_rsi, macd_sma200, macd_rsi, pmax, hull_suite, ao_stoch, golden_cross, flawless_victory, ema_cross, ichimoku, rsi_div); +2 fixtures (`_long_uptrend_15m` for the slow-MA/cloud ports, `_divergence_15m` for rsi_div) | ✅ **186 passed** (was 120) |
| Agent suites (`test_india_intraday_engine` / `test_intraday_runtime` / `test_intraday_portfolio` / `test_intraday_live_wiring` / `test_llm_engine` / `test_intraday_shorts` / `test_gemini_jobs`) — **untouched** (this batch only added `strategies/` run-dirs; no agent/config edits) | ✅ **148 passed** |
| **Total** | **✅ 334 passed, 0 failed** (was 268; +66 = 11 strategies × 6) |

Each new strategy passes all 6 checks: repo AST/class validators accept the source (no decorators,
literal defaults, no network); long-only + flat outside 09:45–15:00 on the no-arg ctor; the
`allow_short` twin emits ≥1 short on the mirrored fixture; the no-arg ctor never shorts; and both
directions produce same-day-only (MIS, no overnight carry) trades through `IndiaIntradayEngine`.

**Backtest (offline second opinion, not a test):** `backtest_all.py` over the cached 4-stock Yahoo
15m window — all 11 net-negative on this down regime (best `macd_rsi` −₹1,819/34 trades; worst
`ao_stoch` −₹8,639/268 trades). Validate-window OOS ranking least-bad → worst: macd_rsi, rsi_div,
bb_rsi, golden_cross, flawless_victory, pmax, macd_sma200, hull_suite, ichimoku, ema_cross, ao_stoch.
Low-frequency ports lose least; high-churn ones bleed fees — the documented cost-drag pattern, not a
verdict. Reports: `docs/BACKTEST_REPORT.md` (full 31), `docs/BACKTEST_REPORT_TVPORTS.md` (these 11).

## 2026-07-17 (post-close) — Tonight's batch: BUG-007 + §3O + §3P + §3R (+ §3Q doc-only)

Command: agent suites (now incl. `tests/test_gemini_jobs.py`) + strategy suite, per SESSION.md
"How to run tests".

| Suite | Result |
|---|---|
| `test_gemini_jobs.py` (**new**, §3O: transient-only retry w/ 2s/8s sleeps, no-retry on non-transient/4xx, `[local]` Ollama fallback + fallback-failure path, `make_llm_caller` fallback attach, stub has none, EOD per-strategy aggregation >40 fills + small-session regression, `ollama_generate` parse/HTTP-error, ollama config fields) | ✅ **13 passed** |
| `test_intraday_portfolio.py` (**31** = 22 + 6 §3P formatter: idle collapse, halted-still-renders, movers-first sort, 8-fill cap, legs-line suppression, scoreboard topline + 2 §3R: `StrategyRef.params` parse/default, roster params → builtin engine + BUG-007 tempfile store) | ✅ **31 passed** |
| `test_llm_engine.py` (**25** = 18 + 7 §3R: ollama provider routing + config-default model, params build two engines, unknown param TypeError, slot-tagged journal/log, degraded-after-3 → flat, success resets counter, no-params ctor regression) | ✅ **25 passed** |
| `test_india_intraday_engine.py` / `test_intraday_runtime.py` / `test_intraday_live_wiring.py` / `test_intraday_shorts.py` (untouched baselines; live-wiring includes the pre-3P hourly format test — still green, the changed sections were additive for its cases) | ✅ 16 / 25 / 16 / 23 |
| Strategies (`test_intraday_strategies.py`, 20 × 6) | ✅ 120 passed |
| **Total** | **✅ 268 passed, 0 failed** (was 240; +28) |

**Launch-gate preflight (real configs):** `validate_roster` builds **42** slots from
`config/intraday.json` (20 rule + 20 `_ls` + `llm_local_a`/`llm_local_b`) and **20** from
`config/intraday.long21.json`, exit 0. Preflight now mirrors the portfolio exactly (threads
`params` + `slot_name`) so a bad per-slot kwarg is a launch-gate failure, not a mid-session one.

**BUG-007 verify:** after the full suite, the real `~/.vibe-trading/intraday/scoreboard.json`
holds exactly **40 rows, all dated 2026-07-17** — test writes now land in tempfile stores.

**Live Ollama (not in pytest — real GPU):** 38-symbol prompt latency **llama3.1:8b 14.5s /
qwen3:8b 20.8s** (< 60s gate, both slots stay); e2e `generate` with real llama3.1:8b 19.3s,
38/38 decisions parsed. Found + fixed: spec'd `num_ctx 8192` truncated the 9.6k–13.7k-token
prompt (`done_reason=length`) → **16384**, plus `think: false` (qwen3: 47s → 17s; llama ignores it).

### Notes
- No existing test changed meaning; the single §3P-sensitive legacy test
  (`test_format_hourly_detailed_shows_fills_positions_and_halts`) passes unmodified because its
  two sections are active/halted (neither collapses) and under the 8-fill cap.
- The engines' `_decide` now also counts an **unparseable reply** toward degradation (not just a
  raised call) — deliberate widening of the §3R spec: chatty local models fail exactly that way,
  and BUG-005's freeze must be unreachable via garbage output too.

## 2026-07-16 (post-close) — 3N: ride out short Wi-Fi/data drops before a tick

Command: agent suites + strategy suite. Adds 4 portfolio tests for the reconnect-wait guard.

| Suite | Result |
|---|---|
| Agent (`test_india_intraday_engine` 16 + `test_intraday_runtime` 25 + `test_intraday_portfolio` **22** + `test_intraday_live_wiring` 16 + `test_llm_engine` 18 + `test_intraday_shorts` 23) | ✅ **120 passed** |
| Strategies (`test_intraday_strategies.py`, 20 × 6) | ✅ 120 passed |
| **Total** | **✅ 240 passed, 0 failed** (was 236; +4 for 3N) |

**New (3N) — `Portfolio._await_data` reconnect wait:**
- `test_await_data_online_does_not_wait` — canary probe succeeds → 0 sleeps, `now` unchanged (happy path adds no live fetch: the probe warms the shared cache `run_tick` reuses).
- `test_await_data_rides_out_outage_then_resumes` — 2 failed probes → 2 backoffs (5s,10s) → 3rd probe OK → `now` refreshed to real wall-clock.
- `test_await_data_gives_up_after_budget_and_proceeds` — sustained outage → total sleep ≤ budget (60s), then proceeds (degrades to today's empty-frame hold).
- `test_reconnect_budget_zero_disables_wait` — `reconnect_budget_seconds=0` → no waiting.

**Config/preflight:** real `config/intraday.json` loads with `reconnect_budget_seconds = 300` (5 min); `validate_roster` still builds 40 + 20, exit 0.

## 2026-07-16 (post-close) — 3M: LLM trader slots removed (roster 42 → 40)

Command: agent suites + strategy suite, per SESSION.md "How to run tests". Config/string edits only — no code touched, so counts are expected to hold at 236.

| Suite | Result |
|---|---|
| Agent (`test_india_intraday_engine` 16 + `test_intraday_runtime` 25 + `test_intraday_portfolio` 18 + `test_intraday_live_wiring` 16 + `test_llm_engine` 18 + `test_intraday_shorts` 23) | ✅ 116 passed |
| Strategies (`test_intraday_strategies.py`, 20 × 6) | ✅ 120 passed |
| **Total** | **✅ 236 passed, 0 failed** |

**Launch-gate preflight (real configs):** `bakeoff.validate_roster` built all **40** slots of `config/intraday.json` (20 long + 20 `_ls`) and all **20** of `config/intraday.long21.json`, exit 0. `intraday.example.json` matches (40). `grep builtin:llm_trader` = 0 across all three live configs; `_BUILTINS` still resolves `llm_trader` when constructed directly (`test_llm_engine.py` green), so the soft-disable is reversible.

### Notes
- `test_llm_engine.py` (18) stays green: it constructs `LLMSignalEngine` directly, not via roster, so the retained-but-unused code stays honest for a future revival.
- Per-tick Gemini calls now **0** (were 2) — removes the day-1 rate/latency watch item and 7×/day httpx timeouts observed on 07-16.

## 2026-07-16 (~01:00, pre-bell QA gate) — 3L: hybrid (long+short) A/B build

Command: agent suites (now incl. `tests/test_intraday_shorts.py`) + strategy suite,
per SESSION.md "How to run tests". Fable QA session over the Opus 3L build.

| Suite | Result |
|---|---|
| `test_intraday_shorts.py` (**new** — broker short accounting identities, slippage/STT-stamp legs, one-direction-per-symbol, runner −1 handling, **15:15 force-cover with & without a last price**) | ✅ 23 passed |
| `test_intraday_portfolio.py` (+5: twin-pair isolation, kill-switch covers a short, **per-slot exception isolation**, leg decomposition, lng₹/sht₹ columns) | ✅ 18 passed |
| `test_llm_engine.py` (+5: hybrid "short" parse, long-only coercion regression, hybrid prompt, flipped short exit_eval, builtin hybrid wiring) | ✅ 18 passed |
| `test_india_intraday_engine.py` (allow_short opt-in + lower-circuit-blocks-short; default still long-only) | ✅ 16 passed |
| `test_intraday_runtime.py` / `test_intraday_live_wiring.py` (**files untouched by the build** — baseline regression) | ✅ 25 / 16 |
| `test_intraday_strategies.py` (**20 strategies × 6** — 3 original checks + hybrid emits −1 on a price-mirrored tape, hybrid same-day short trades through the engine, **no-arg ctor never emits −1**) | ✅ 120 passed |
| **Total** | **✅ 236 passed, 0 failed** |

**Launch-gate preflight (manual, real configs):** `bakeoff.validate_roster` built all
**42** slots of `config/intraday.json` (21 long-only + 21 hybrid `_ls`, `llm_trader_ls →
builtin:llm_trader`) and all **21** slots of the fallback `config/intraday.long21.json`.
`intraday.example.json` matches (42/21). **All §3L QA gates GREEN → launch gate OPEN for 07-16.**

### Baseline accounting (the "existing 143 unmodified" gate)
- 142 of 143 pass byte-identical or in untouched files. The single exception is deliberate:
  `test_short_blocked_even_if_allow_short_requested` asserted the **pre-3L hard rule** that
  config could never re-enable shorting — 3L repeals exactly that rule (user decision,
  paper-only), so it was replaced by `test_short_permitted_when_allow_short_opted_in`.
  Long-only-by-default is still enforced by `test_short_always_blocked` (no-arg engine).

### Notes / warnings
- The strategy suite doubled (60 → 120) via the `_mirror` fixture: each engine's short
  mirror must fire on a price-reflected copy of the tape that triggers its long side.
- QA initially ran against a **moving target** (the Opus session was still writing) and saw
  phantom collection counts — all numbers above are from the settled tree, re-run clean.
- Not covered by automation: live Dhan short fills (paper-only by design), Gemini rate
  behavior with 2 llm calls/tick (watch on day 1), report size with 42 sections (watch day 1).

## 2026-07-16 (pre-launch) — 3K: 38-stock universe + oi_dma_adx

Command: strategy suite + all agent suites.

| Suite | Result |
|---|---|
| `test_intraday_strategies.py` (**20 strategies × 3**, incl. new `oi_dma_adx`) | ✅ 60 passed |
| Agent suites (engine/runtime/portfolio/wiring/llm) against the 38-stock config | ✅ 83 passed |
| **Total** | **✅ 143 passed, 0 failed** |

Manual checks: 21/21 roster slots load through `Portfolio`'s loader; 38/38 security_ids
resolved from the scrip master (4 previously-live ids matched → method verified);
scoreboard.json junk rows removed (backup kept). 38-stock roster backtest →
`docs/BACKTEST_REPORT_ALL38.md`.

## 2026-07-15 (night, cont.) — 3I.2: full-roster tuned defaults applied

Command: strategy suite + all agent suites (as below).

| Suite | Result |
|---|---|
| `test_intraday_strategies.py` (19 × 3; boll_bounce now on the `_vshape_15m` fat-tail fixture) | ✅ 57 passed |
| Agent suites (engine/runtime/portfolio/wiring/llm) | ✅ 83 passed |
| **Total** | **✅ 140 passed, 0 failed** |

Default changes covered: momentum_rsi, ut_bot, three_thrust, squeeze_momentum, boll_bounce,
gap_go, macd_cross (7 tuned; OOS-validated). `docs/BACKTEST_REPORT.md` regenerated on final
defaults; tuning evidence archived in `docs/backtest_tuning_20260715.json`.

## 2026-07-15 (late night) — 3I: orb re-tune applied, suite re-run

Command: `cd strategies && PYTHONPATH=. python -m pytest tests/test_intraday_strategies.py -q`

| Suite | Result |
|---|---|
| `test_intraday_strategies.py` (19 × 3, after orb `vol_mult 1.3→1.5`, `vol_window 20→12`) | ✅ 57 passed |
| Agent suites (unchanged since the 3H run below) | ✅ 83 passed |
| **Total** | **✅ 140 passed, 0 failed** |

Backtest artifacts regenerated: `docs/BACKTEST_REPORT.md` (+ postscript), `docs/backtest_daily_pnl.csv`,
`docs/backtest_results.json`. Yahoo 15m cache in `strategies/.bt_cache/` (gitignore when repo is initialized).

## 2026-07-15 (night) — 3H: TradingView ports, roster → 20

Command: `cd vibe-trading/agent && PYTHONPATH=. python -m pytest tests/test_india_intraday_engine.py tests/test_intraday_runtime.py tests/test_intraday_portfolio.py tests/test_intraday_live_wiring.py tests/test_llm_engine.py -q` + `cd strategies && PYTHONPATH=. python -m pytest tests/test_intraday_strategies.py -q`

| Suite | Result |
|---|---|
| `test_intraday_strategies.py` (**19 strategies × 3 checks**; new `_squeeze_15m` fixture, wavetrend on 4-day oscillation) | ✅ 57 passed |
| `test_intraday_live_wiring.py` | ✅ 16 passed |
| `test_llm_engine.py` | ✅ 13 passed |
| `test_intraday_portfolio.py` / `test_intraday_runtime.py` / `test_india_intraday_engine.py` | ✅ 13 / 25 / 16 |
| **Total** | **✅ 140 passed, 0 failed** |

**Manual smoke:** all **20** roster entries in the real `config/intraday.json` load through
`Portfolio`'s loader (repo AST + interface validators; builtin llm_trader skipped offline).
Live from the **2026-07-16** launch (₹25k × 20 = ₹5L total paper).

### Notes / warnings
- Two port-specific findings fixed during the run: (1) the repo validator rejects **negative
  literal defaults** (`-20.0` is a unary op in the AST) — wavetrend's oversold threshold now
  defaults to the zero line; (2) squeeze momentum's linreg goes NaN-valid a few bars **after**
  the squeeze fires (nested rolling warm-up) — entries allow a ≤5-bar grace after the release.
- The 5 TV ports are unbacktested on real data by choice (same stance as 3G) — the paper week ranks them.

## 2026-07-15 (evening) — 3G: 15-strategy roster + scale infra

Command: agent suites as below + `cd strategies && PYTHONPATH=. python -m pytest tests/test_intraday_strategies.py -q`

| Suite | Result |
|---|---|
| `test_intraday_strategies.py` (**14 strategies × 3 checks**, pattern-matched fixtures) | ✅ 42 passed |
| `test_intraday_live_wiring.py` (+`CachedBarSource` share/invalidations, Telegram chunking) | ✅ 16 passed |
| `test_llm_engine.py` | ✅ 13 passed |
| `test_intraday_portfolio.py` / `test_intraday_runtime.py` / `test_india_intraday_engine.py` | ✅ 13 / 25 / 16 |
| **Total** | **✅ 125 passed, 0 failed** |

**Manual smoke:** real `config/intraday.json` builds all **15 slots** (₹25k each, ₹3.75L total paper).
Live from the **2026-07-16** launch.

### Notes / warnings
- Specialist strategies (gap_go/gap_fade/boll_bounce/boll_break) are tested on fixtures showing their
  target pattern — on a pattern-free day they correctly sit flat (that's design, not a gap).
- `CachedBarSource` invalidates on tick change (`set_now`) or 300s TTL; empty fetches aren't cached
  (a failed symbol retries next runner).
- None of the 10 new strategies is backtested on real data yet — the paper bake-off is the arbiter
  (same stance as 3B: mechanical correctness proven, profitability measured live).

## 2026-07-15 (later) — LLM trader (5th slot) + detailed hourly report

Command: `cd vibe-trading/agent && PYTHONPATH=. python -m pytest tests/test_india_intraday_engine.py tests/test_intraday_runtime.py tests/test_intraday_portfolio.py tests/test_intraday_live_wiring.py tests/test_llm_engine.py -q` (+ strategies suite)

| Suite | Result |
|---|---|
| `test_llm_engine.py` (**new**: fenced-LLM slot — guard rails, JSON parse, keep-last, builtin wiring, **decision journal + exit_eval grading**) | ✅ 13 passed |
| `test_intraday_live_wiring.py` (now incl. detailed hourly report) | ✅ 13 passed |
| `test_intraday_portfolio.py` / `test_intraday_runtime.py` / `test_india_intraday_engine.py` | ✅ 13 / 25 / 16 |
| `test_intraday_strategies.py` | ✅ 12 passed |
| **Total** | **✅ 92 passed, 0 failed** |

**Manual smoke:** real `config/intraday.json` builds a **5-slot** portfolio
(orb/pullback/ema_trend/momentum_rsi/**llm_trader**), the builtin slot is an armed `LLMSignalEngine`
(gemini configured), ₹25k account. Both features go live at the **2026-07-16** launch — the running
day-1 process was deliberately not restarted (it holds open paper positions).

### Notes / warnings
- The LLM slot is **not backtestable** (no reproducible history) — its 12 strategy-suite checks don't
  apply; it is judged purely on live paper forward results.
- ~23 extra Gemini calls/day (one per 15m tick) — negligible for flash.

## 2026-07-15 — Live activation (real creds + launcher + dhanhq 2.x fixes)

Command: `cd vibe-trading/agent && PYTHONPATH=. python -m pytest tests/test_india_intraday_engine.py tests/test_intraday_runtime.py tests/test_intraday_portfolio.py tests/test_intraday_live_wiring.py -q`
(strategies: `cd strategies && PYTHONPATH=. python -m pytest tests/test_intraday_strategies.py -q`)

| Suite | Result |
|---|---|
| `test_intraday_live_wiring.py` (**new**: dhanhq 1.x/2.x payloads, DC-003 cred threading, Gemini REST, launcher helpers, detailed hourly report) | ✅ 13 passed |
| `test_intraday_portfolio.py` | ✅ 13 passed |
| `test_intraday_runtime.py` | ✅ 25 passed |
| `test_india_intraday_engine.py` | ✅ 16 passed |
| `test_intraday_strategies.py` | ✅ 12 passed |
| **Total** | **✅ 79 passed, 0 failed** |

**Live smoke (real creds, scratch script through the real code paths):** config predicates all
true · Telegram real send 200 + received · Dhan real 15m bars for all 4 universe symbols
(HDFCBANK/RELIANCE/TATASTEEL/ICICIBANK) · Gemini real generateContent echo OK.
**Day-1 bake-off launched** 08:56 IST via `start_bakeoff.bat` — watchlist posted, session armed for the 09:15 bell.

### Notes / warnings
- dhanhq **2.2.0** installed this session; the vendored connector was patched for 2.x with a 1.x
  fallback (BUG-002). If dhanhq is ever upgraded again, re-run `test_intraday_live_wiring.py` first.
- Dhan access token in `agent/.env` **expires every 24h** — refresh each morning before `start_bakeoff.bat`.
- Console is cp1252: the launcher/bat set UTF-8 (`chcp 65001` + `PYTHONIOENCODING`) so ₹ prints; the
  per-day file log (`agent/logs/bakeoff-YYYYMMDD.log`) is always UTF-8.

## 2026-07-15 — Phase 3, increment 3D.2 (parallel bake-off + 2 strategies)

Command: `cd vibe-trading/agent && PYTHONPATH=. python -m pytest tests/test_intraday_runtime.py tests/test_intraday_portfolio.py tests/test_india_intraday_engine.py -q`
(strategies: `cd strategies && PYTHONPATH=../vibe-trading/agent python -m pytest -q`)

| Suite | Result |
|---|---|
| `test_intraday_portfolio.py` (isolation, kill-switch, hourly, scoreboard, persistence, metrics) | ✅ 13 passed |
| `test_intraday_runtime.py` (3C/3D regression) | ✅ 25 passed |
| `test_india_intraday_engine.py` (3A regression) | ✅ 16 passed |
| `test_intraday_strategies.py` (4 strategies × 3 checks) | ✅ 12 passed |
| **Total** | **✅ 66 passed, 0 failed** |

**Manual E2E smoke (no creds):** `IntradayConfig.load()` resolved the 4-strategy roster; `Portfolio`
loaded all four **real** `SignalEngine`s and ran a synthetic day in parallel — each in its own ₹25k
account — producing a ranked EOD scoreboard (pullback +₹77, ema_trend +₹41, orb +₹3, momentum_rsi
−₹16 on the synthetic data), 6 hourly summaries, 4 persisted scoreboard rows, all flat at close.

### Notes / warnings
- `momentum_rsi` entry was reworked to "RSI resumes up out of a dip in an up-trend" (level-agnostic)
  after an absolute-threshold version never triggered on the clean synthetic uptrend — honest fix, not
  overfit; it now trades on real oscillation.
- Live paths (real Telegram send, live Dhan bars, real Gemini) still unexercised — activate with creds.

## 2026-07-14 — Phase 3, increment 3C+3D (paper runtime, placeholder creds)

Command: `cd vibe-trading/agent && PYTHONPATH=. python -m pytest tests/test_intraday_runtime.py -q`
(regression: `... tests/test_india_intraday_engine.py -q` and strategies suite)

| Suite | Result |
|---|---|
| `test_intraday_runtime.py` (config, paper_broker, notifier, clock, bars/3C, gemini, runner) | ✅ 25 passed in ~2.1s |
| `test_india_intraday_engine.py` (3A regression) | ✅ 16 passed |
| `test_intraday_strategies.py` (3B regression) | ✅ 6 passed |
| **Total across targeted suites** | **✅ 47 passed, 0 failed** |

**Manual E2E smoke (no creds):** `IntradayConfig.load()` resolved the real 3-symbol universe from
`config/intraday.json`; all `is_*_configured` False → `LogSink` selected; the **real ORB `SignalEngine`**
loaded via `load_signal_engine`; a full synthetic breakout day ran open → strategy exit →
**15:15 force square-off**, flat at close. Confirms the dynamic strategy import + config wiring for real.

### Notes / warnings
- Dropping real Dhan/Gemini/Telegram values into the placeholders activates the live paths with no code
  change; those network paths (real Telegram send, live Dhan bars, real Gemini) are still unexercised.
- `pytest-asyncio` not required — the async `run_session` test drives the loop via `asyncio.run`.
- Paper fills at the observed bar's close vs backtest next-bar-open — documented basis (not a defect).

## 2026-07-13 — Phase 3, increment 3B (long-only strategies)

Command: `cd vibe_intraday/strategies && python -m pytest tests/test_intraday_strategies.py -q`

| Suite | Result |
|---|---|
| `test_intraday_strategies.py` (orb_intraday + pullback_buy) | ✅ 6 passed |

Covers, per strategy: repo AST/interface validators accept it; signals are long-only (0/1)
and flat before 09:45 / from 15:00; execution through `IndiaIntradayEngine` yields only long,
same-day trades (0 overnight carries).

**Real-data smoke (manual, yfinance 15m, ~55d, ₹50k):**
| Strategy | Trades | Win% | Gross | Costs | Net |
|---|---|---|---|---|---|
| orb_intraday | 45 | 38% | −₹2,847 | ₹1,932 | **−₹4,778** |
| pullback_buy | 135 | 29% | −₹4,946 | ₹3,487 | **−₹8,433** |

Both correct mechanically (0 carries); both unprofitable net of costs → strategies need tuning.
Not a blocker for building the paper loop. Full `backtest.runner` deferred (needs full app env).

## 2026-07-13 — Phase 3, increment 3A (intraday engine)

Command: `cd vibe-trading/agent && PYTHONPATH=. python -m pytest tests/test_india_intraday_engine.py tests/test_india_equity_engine.py -q`

| Suite | Result |
|---|---|
| `test_india_intraday_engine.py` (IndiaIntradayEngine) | ✅ 16 passed |
| `test_india_equity_engine.py` (IndiaEquityEngine, upstream regression check) | ✅ 17 passed |
| **Total** | **✅ 33 passed, 0 failed, in ~0.5s** |

Environment: Python 3.11, pandas + numpy (pre-installed), plus `pytest`, `defusedxml`,
`pydantic` installed this session to satisfy repo imports.

### Notes / warnings
- Full-suite run (`tests/`) not yet executed — the repo has heavy optional deps
  (langchain, broker SDKs) not needed for the engine. Targeted suites are green.
  Broaden to the full suite once more modules are touched.
- No coverage gaps in 3A: can_execute, calc_commission, routing, and the execution
  loop are all exercised.

### Fixed during this run
- Integration test initially failed: a flat emitted on the 15:15 bar exited at next
  day's 09:15 (next-bar-open fill). Corrected the strategy-level square-off to 15:00 so
  the exit lands at 15:15 same-day. Logged in `BUGS.md` as a design constraint.
