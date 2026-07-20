## Current task
**Vibe-Intraday** — NSE intraday (MIS) trading assistant on HKUDS/Vibe-Trading.
**Ranking week started 2026-07-17** (07-15/07-16 scratched by host crashes, BUG-004; day 1 clean).
**From Monday 2026-07-20 the config is 64 slots × 38-stock Nifty universe** (₹25k each = **₹16L
paper**): 31 rule-long + 31 `_ls` hybrid twins (3L A/B) + 2 local-LLM slots (`llm_local_a` llama3.1:8b
/ `llm_local_b` qwen3:8b on Ollama). The 64 = the prior 42 + **§3S's 11 TradingView ports × long/`_ls`**
(bb_rsi, macd_sma200, macd_rsi, pmax, hull_suite, ao_stoch, golden_cross, flawless_victory, ema_cross,
ichimoku, rsi_div), promoted 07-19. Fallback `config/intraday.long21.json` (20 long-only) unchanged.
**386 tests green** (was 381; +5 = B4-2 formatter tests). **B7 DONE 2026-07-19 (§3U below).**
**B4-2 DONE 2026-07-19 (§3V below)** — Telegram report reworked for 64 slots (mockup-approved,
build=Opus). Nothing now queued for the 07-20 live session. See §3V / §3U / §3S / §3T blocks below.

## §3V — B4-2 Telegram report rework for the 64-slot roster ✅ DONE 2026-07-19 (build=Opus, mockup-approved)
Report formatters ONLY (authorized B4-2 exception; no engine/strategy/`config/intraday.json` edits).
User gate honoured: rendered CURRENT @64 from a synthetic mid-day portfolio through the REAL formatters +
chunker, showed the spill, proposed the shape, **got approval before writing code** (user amendment:
hourly shows *all* pairs, not top-N). Shipped:
- **`scoreboard.format_hourly_detailed`** — was a per-slot block (header + legs + ≤8 fills + positions)
  → **4 chunks / 12,655 chars** @64. Now **one row per long/`_ls` pair**: `long · ls · sht · Δ(=ls−long)
  · f · h`, **all pairs** movers-first (max |leg net|), halted pairs pulled out + always listed (both
  legs, ✖ on the retired leg), unpaired `llm_local_a/b` on a `llm:` line (halted → ✖). **→ 1 chunk / 1,905.**
- **`scoreboard.format_scoreboard`** (EOD) — flat 64-row table (**2 chunks / 4,551**) → one pair row
  (long vs ls + short leg), ranked by best leg, halted last (✖), `llm (unpaired):` line. **→ 1 chunk / 1,931.**
- **`scoreboard._cap_report`** (new) — hard **≤3-chunk** cap measured with the real
  `notifier.split_for_telegram`; over-cap truncates with `… +N more pairs (log)` (tail — retired/llm —
  never dropped). Reused the chunker, didn't rewrite it.
- **`gemini_jobs.eod_review`** — past-40-fills aggregation pair-collapsed to match (`_strategy_lines`:
  one line/pair long-vs-twin + combined best/worst symbol); prompt now asks whether the short leg helped.
- **BUG-009 caught+fixed pre-ship:** halted *unpaired* slot lost its ✖ on the `llm:` line → fixed.
- Tests: §3P formatter tests regenerated (`test_intraday_portfolio.py` +10 B4-2 cases, replaced 6 diet
  cases; `test_intraday_live_wiring.py` hourly test → pair shape; `test_gemini_jobs.py` → pair-collapsed
  prompt). **386 green** (agent 153 + strategies 228 + evaluator 5). Params: top-N dropped (show all),
  chunk cap 3, hourly sort=max(|long|,|ls|), EOD sort=best leg. Mockup script: `scratchpad/b42_mockup.py`.
- **Independent QA (Fable) — CONFIRMED 2026-07-19:** all 5 gates re-run from scratch (386 tests; @64
  renders reproduced to the char; Fable's own 400-pair stress → exactly 3 chunks + exact pointer; all
  three halted cases visible with ✖; guardrail clean via repo-wide mtime sweep). **Found DC-004**
  (non-blocking, logged in BUGS): the EOD scoreboard's halted rows are droppable *body* rows, so the
  "halted always visible" invariant is truncation-proof only for the hourly (halted lives in the never-
  dropped tail); for the EOD it holds only until ~150 pairs — **unreachable at 64 slots** (~6× headroom).
  No code change (user scope = formatters-for-64). **B4-2 CONFIRMED safe for the 07-20 live session.**

## §3U — B7 Tier-1 shortlist port batch ✅ DONE 2026-07-19 (offline only — read first)
User picked B7 over B4-2 (B4-2 still pending). Ported the 7 Tier-1 candidates from
`docs/STRATEGY_SHORTLIST.md` as validator-clean run-dirs + `allow_short` twins, each a NEW archetype:
**cpr_pivot** (Central Pivot Range), **psar_flip** (Wilder Parabolic SAR), **supertrend_vwap**
(Supertrend∧VWAP confluence), **donchian** (Turtle channel), **keltner** (EMA±ATR channel),
**stoch_rsi** (double-smoothed StochRSI cross), **connors_rsi2** (RSI(2) reversion, 200-SMA→100 for
the 15m/120-bar lookback). **OFFLINE ONLY — `config/intraday.json` / the 64-slot live roster NOT
touched** (promotion is a separate user decision, per the funnel + guardrail).
- Registered in `backtest_all.py` (STRATEGIES/SHORT_NAMES/TUNE_GRIDS), `evaluate_strategies.py`
  (auto via `bt.STRATEGIES`), `test_intraday_strategies.py` (×38 + `_dip_uptrend_15m` fixture).
  **228 strategy tests green** (was 186); total **381** (agent 148 + strategies 228 + evaluator 5).
- **BUG-008 found + fixed** (pre-ship, caught by the suite): connors RSI(2) `_rsi` used the §3S
  `fillna(50)` house style → a 2-bar all-up (zero-loss) window collapsed a should-be-100 overbought
  RSI to 50, so the mirrored short never armed. Fixed to `avg_loss==0 & avg_gain>0 → 100`.
- Backtest (cached 4-stock): all 7 net-negative on the down regime (`docs/BACKTEST_REPORT_TIER1.md` +
  full 38 regenerated). Robustness rank (`docs/STRATEGY_EVALUATION.md`): **donchian** (score −38.7,
  pos-rate 15%, 21 trades/sym) + **keltner** (−61.5, 12%, 28) = batch standouts (mid-pack, ~rsi_div
  tier); cpr_pivot/connors_rsi2/psar_flip/stoch_rsi/supertrend_vwap = churny fee-bleeders on this one regime.
- **DECISION open for user:** promote survivors (donchian/keltner most defensible) to the live roster as
  long + `_ls` twins, or hold for the Tier-2 batch first. Fee-bleeders (ema_cross/hull_suite/ao_stoch):
  user chose **KEEP — let the ₹10k kill-switch retire them live** (no roster edit).

## §3S — TradingView ports batch 2 ✅ DONE + PROMOTED TO LIVE 2026-07-18/19 (read first)
User shared the TradingView "Strategies" shortlist screenshot: "copy the strategies and backtest
them" → then "add these to the plan so they also run from Monday." Ported the **11 portable ones**
(skipped supertrend = already in 3H; 3Commas Bot = a DCA bot, not a directional signal; Ultimate
Strategy Template = an empty template) as validator-clean run-dirs in `strategies/`: bb_rsi,
macd_sma200, macd_rsi, pmax, hull_suite, ao_stoch, golden_cross, flawless_victory, ema_cross,
ichimoku, rsi_div. Backtested via `backtest_all.py` (cached 4-stock Yahoo 15m): all 11 net-negative
on the down window (best macd_rsi −₹1,819/34 trades; worst ao_stoch −₹8,639/268 — fee-drag/churn;
regime signal, not a verdict).
**PROMOTED (user, 2026-07-19): all 11 added as long + `_ls` twins → roster 42 → 64** (33 rule/llm
long + 31 `_ls`; ₹25k each = **₹16L paper**) in `config/intraday.json` (+`.example`). Engines already
carry the `allow_short` mirror (3L). **Runs from Monday 2026-07-20.** Gates green:
`validate_roster` builds **64 + 20 fallback** (exit 0; preflight logs "33 long-only + 31 hybrid = 64");
**scale check** — one tick = all 62 rule slots × 38 symbols in **~1.1 s** (≈800× under the 15-min
budget); EOD scoreboard 4,526 chars → 2 Telegram chunks (max 3,975 < 4,000). **334 tests green**
(strategies 186, agent 148 untouched). Fallback `intraday.long21.json` unchanged (20 long-only).
**→ Telegram report needs a proper 64-slot rework — queued for 2026-07-20 (see B4-2 / Exact next step).**

## Phase
Phase 3 (Develop). §3S + §3T (07-18/19) done ON TOP of Tonight's batch (07-17), 3L (07-16), §3M +
§3N (07-16 post-close), and the clean 07-17 day 1, then §3U (B7 Tier-1 ports, 07-19), then §3V
(B4-2 report rework, 07-19). **386 tests green** (agent 153 = engine 16 + runtime 25 + portfolio 35
+ live-wiring 16 + llm_engine 25 + shorts 23 + gemini_jobs 13; **strategies 228** = 38 run-dir
strategies × 6 checks; **evaluator 5** = `test_evaluate_strategies.py`).
Docs all regenerated. M2 (gated live) not started. **BUG-004 (host/process crash) still OPEN —
user-deferred**; §3N covers network drops only. Day-2 watch items: first live 3P hourly format;
the two llm_local slots' fills + journal (`slot` field, `degraded` flag); `[local]` fallback
should NOT appear on the bookends unless Gemini actually failed.

## §3T — Robustness evaluator + shortlist ✅ DONE 2026-07-19 (user: "get more TV strategies + evaluate the best")
Honest framing given: "all of TradingView" is infeasible (protected sources unreadable, no bulk API,
each needs a hand-port) and one 15m window (~57 days = ONE regime) can't crown a winner. Built a
**funnel** instead:
- **`strategies/evaluate_strategies.py`** — robustness ranker: each strategy over **49 cached symbols
  one-at-a-time** (no 1/N confound) × **4 walk-forward folds** × **2× slippage** cost check →
  composite `score` (consistency-led, churn-penalised). Report `docs/STRATEGY_EVALUATION.md`. +5 tests.
- **`docs/STRATEGY_SHORTLIST.md`** — 14 vetted next-batch candidates (Tier-1: CPR/pivots, Parabolic
  SAR, Supertrend+VWAP, Donchian, Keltner, StochRSI, Connors-RSI2). **Pending user go-ahead to port.**
- **Finding:** fee-bleeders **ema_cross(88)/hull_suite(81)/macd_cross(77)/ao_stoch(75)** trades/sym
  rank worst; top = squeeze_momentum, gap_fade, gap_go, macd_rsi, boll_break, bb_rsi. Kill-switch will
  likely retire the churners in live paper. **339 tests green** (agent 148 + strategies 186 + evaluator 5).

## Last files touched (2026-07-19 — §3V B4-2 report rework; formatters only)
- **`src/intraday/scoreboard.py`** — rewrote `format_hourly_detailed` (pair-collapse, all pairs,
  movers-first, retired-line, unpaired-llm line) + `format_scoreboard` (pair rows, best-leg rank);
  new `_pair_items` / `_slot_net` / `_slot_halted` / `_pair_halted` / `_pair_best_net` / `_pair_mag` /
  `_cap_report` helpers + `_CHUNK_CAP=3`; imports `notifier.split_for_telegram`; removed the §3P
  `_is_idle` / `_hourly_sort_key` / `_HOURLY_FILL_CAP` diet helpers.
- **`src/intraday/gemini_jobs.py`** — `_strategy_lines` pair-collapsed (+ `_best_worst` helper); EOD
  prompt reworded (pairs, "did the short leg help").
- **`tests/test_intraday_portfolio.py`** — replaced the 6 §3P diet tests with 10 B4-2 cases;
  updated `test_hourly_summary_emitted_on_hour_change` + `test_format_scoreboard_has_leg_columns`.
- **`tests/test_intraday_live_wiring.py`** — `test_format_hourly_detailed_*` → pair-collapse shape.
- **`tests/test_gemini_jobs.py`** — `test_eod_review_aggregates_per_pair_*` (pair-collapsed prompt).
- Docs: TEST_REPORT (386), TASK_CHECKLIST (B4-2 ✅), UNIT_TESTS, QA, FLOWS (flow 8/9), README,
  BUGS (BUG-009), this SESSION, project memory. **NOT touched (guardrail):** `config/intraday.json`,
  agent engine/strategy code.

## Last files touched (2026-07-19 — §3U B7 Tier-1 port batch, offline)
- **7 new run-dirs** `strategies/{cpr_pivot,psar_flip,supertrend_vwap,donchian,keltner,stoch_rsi,
  connors_rsi2}/` — each `config.json` + `code/signal_engine.py` (long-only + `allow_short` mirror).
- **`strategies/backtest_all.py`** — STRATEGIES 31→38, SHORT_NAMES + TUNE_GRIDS for the 7.
- **`strategies/tests/test_intraday_strategies.py`** — STRATEGIES ×38; +1 fixture `_dip_uptrend_15m`;
  TRADE_FIXTURES for stoch_rsi (sine) + connors_rsi2 (dip-uptrend). **228 strategy tests green.**
- **`strategies/connors_rsi2/code/signal_engine.py`** — BUG-008 fix (degenerate RSI(2) → 100).
- Reports regenerated: `docs/BACKTEST_REPORT.md` (full 38), `docs/BACKTEST_REPORT_TIER1.md` (the 7),
  `docs/STRATEGY_EVALUATION.md` (38-strategy robustness rank).
- Docs: TASK_CHECKLIST (§3U + B7 ✅), IMPLEMENTATION_PLAN (§3U), STRATEGY_SHORTLIST (Tier-1 ported),
  TEST_REPORT (381), UNIT_TESTS (38/228), QA (§3U session), BUGS (BUG-008), README, this SESSION, memory.
- **NOT touched (guardrail):** `config/intraday.json` roster (still 64), agent code.

## Last files touched (2026-07-19 — §3T evaluator + shortlist)
- **`strategies/evaluate_strategies.py`** (new) — breadth × folds × cost-robustness ranker → `docs/STRATEGY_EVALUATION.md`.
- **`strategies/tests/test_evaluate_strategies.py`** (new, 5) — folds/score/name-recovery/one-eval.
- **`docs/STRATEGY_SHORTLIST.md`** (new) — curated next-batch candidates + why "all TV" is infeasible.
- Docs: TASK_CHECKLIST (B6/B7), IMPLEMENTATION_PLAN (§3T), README, this SESSION, project memory.

## Last files touched (2026-07-19 — §3S roster promotion 42 → 64)
- **`config/intraday.json` (+`.example`)** — roster 42 → **64**: added the 11 new run-dirs as
  rule-long slots + their 11 `_ls` twins (`allow_short:true`, same run_dir). `_comment` updated
  (64 slots, ₹16L). Fallback `intraday.long21.json` unchanged.
- Verified: `validate_roster` builds 64 + 20 (exit 0); scale check ~1.1 s/tick (62 rule slots ×
  38 sym); agent suite still 148 green (no roster-coupled tests).

## Earlier (2026-07-18 — §3S build + offline backtest)
- **11 new run-dirs** `strategies/{bb_rsi,macd_sma200,macd_rsi,pmax,hull_suite,ao_stoch,golden_cross,
  flawless_victory,ema_cross,ichimoku,rsi_div}/` — each `config.json` + `code/signal_engine.py`.
- `strategies/backtest_all.py` — STRATEGIES 20→31, SHORT_NAMES + TUNE_GRIDS for the 11.
- `strategies/tests/test_intraday_strategies.py` — STRATEGIES ×31; +2 fixtures `_long_uptrend_15m`
  (slow-MA/cloud warm-up) + `_divergence_15m` (bullish divergence); TRADE_FIXTURES for the reversion/
  slow ports. **186 strategy tests green.**
- Docs: TASK_CHECKLIST (§3S + B3), TEST_REPORT (334), QA, UNIT_TESTS (31/186), README,
  IMPLEMENTATION_PLAN (§3S), BACKTEST_REPORT.md (full 31) + BACKTEST_REPORT_TVPORTS.md, project memory.

## Last files touched (2026-07-17 post-close — tonight's batch)
- **BUG-007:** `tests/test_intraday_portfolio.py::_portfolio` → tempfile-backed `ScoreboardStore`
  default (real scoreboard verified: 40 rows, 2026-07-17, after full suite).
- **§3O:** `src/intraday/local_llm.py` (**new** `ollama_generate` — **`num_ctx 16384` +
  `think:false`**, spec deviation w/ evidence: 8192 truncated the 9.6k–13.7k-token prompt);
  `src/intraday/gemini_jobs.py` (`_call` retry 3× 2s/8s transient-only + `[local]` fallback;
  `make_llm_caller` attaches it; `eod_review` aggregates via new `metrics`/`fills_by_strategy`);
  `src/intraday/config.py` (`ollama_url`/`ollama_model` + env); `bakeoff.run_day` (passes
  metrics); **`tests/test_gemini_jobs.py` (new, 13)**.
- **§3P:** `src/intraday/scoreboard.py` — `format_hourly_detailed` (idle collapse → `— N slots
  idle`, movers-first sort, 8-fill cap `… +N more (log)`, legs line only when nonzero),
  `format_scoreboard` topline. +6 formatter tests.
- **§3R:** `src/intraday/config.py` (`StrategyRef.params`); `src/intraday/llm_engine.py`
  (`provider`/`model`/`slot_name` ctor, ollama `_caller` — no key needed, slot-tagged
  journal/logs, **degraded after 3 consecutive failures → flat**, success resets; unparseable
  replies count); `portfolio.py` + `bakeoff.validate_roster` thread `params`+`slot_name`;
  `config/intraday.json` + `.example` roster 40→42 + ollama keys. +7 llm, +3 portfolio/config
  tests. `ollama pull llama3.1:8b` (tag) + `qwen3:8b` done.
- **Docs:** BUGS (006+007 → Resolved), QA (07-17 batch session), TEST_REPORT, UNIT_TESTS, FLOWS
  (flows 7/8/9), README (roster 42, §3O/§3P notes, **Cost model** §3Q, Status refreshed),
  TASK_CHECKLIST (batch section + B1/B2/B4/B5 ✅), IMPLEMENTATION_PLAN (batch ✅ EXECUTED +
  num_ctx deviation), project memory.

- **Broker core** `src/intraday/paper_broker.py` — `Position.direction`; `short()`/`cover()`/
  `close_position()`; 1x reserve = notional + entry comm; identities verified (round-trip at one
  price = −Σcomm; equity continuous, jumps only by commission+slippage; STT-on-short / stamp-on-cover;
  cover clamps/no-flip; buy⊥short per symbol). `_size_within(direction=)` sizes off the correct leg.
- `backtest/engines/india_intraday.py` — honors `allow_short` (default off = byte-identical); short
  entry blocked at the **lower** circuit. `runner.py` — `allow_short` ctor + fail-fast engine load;
  desired ∈{−1,0,1}; close-then-flip exits; force-flatten covers shorts. `config.py` —
  `StrategyRef.allow_short`. `portfolio.py` — threads it; kill-switch covers; **per-slot try/except**
  isolates one slot (both arms in one process); hourly per-leg decomposition. `llm_engine.py` —
  hybrid prompt/parse + flipped short `exit_eval` (stop above / target below).
- **All 20** `strategies/*/code/signal_engine.py` — `allow_short=False` ctor + mirrored −1 branch
  (see each module docstring); no-arg ctor stays long-only; validator-clean.
- `config/intraday.json`(+`.example`) — roster **42** (`_ls` twins, same run_dir + `allow_short:true`);
  **`config/intraday.long21.json`** = verbatim 21-slot launch-gate fallback. `scoreboard.py` —
  `long_pnl`/`short_pnl`, `lng₹`/`sht₹` columns, 🔻SHORT/🔺COVER + per-leg hourly. `bakeoff.py` —
  `validate_roster` preflight (fails fast → fallback).
- **Tests:** new `tests/test_intraday_shorts.py` (23); +5 portfolio, +5 llm, +60 strategy
  (`_mirror` price-reflection fixture; bespoke `_rally_then_plunge_15m` for QQE's trailing-line flip).

## Earlier this session — 3H TV ports + 3I batch backtest/tuning (prior context)
- **`strategies/backtest_all.py` (new)** — batch backtest harness: 19 strategies ×
  `IndiaIntradayEngine` × 57 days Yahoo 15m (₹25k, MIS costs), train/validate split,
  `--tune` grids, day-on-day P&L matrix → `docs/BACKTEST_REPORT.md` +
  `backtest_daily_pnl.csv` + `backtest_results.json`. Cache: `strategies/.bt_cache/`.
- **Backtest headline: ALL 19 net-negative** (tape was down: TATASTEEL −12.7%,
  RELIANCE −4.3%); churners lost most (fees 30–50% of losses). Regime signal, not verdict.
- `strategies/orb_intraday/code/signal_engine.py` — **tuned defaults applied:**
  `vol_mult 1.3→1.5`, `vol_window 20→12` (OOS-validated: −₹1,271 vs −₹2,095), live 07-16.
  pullback tuning = honest no-op (no OOS sensitivity). 57 tests re-run green.
- **3I.2 — full-roster tuning (19 grids, 115 combos):** 7 more defaults applied (OOS gain
  ≥₹300): momentum_rsi (rsi_len 14, pullback 70), ut_bot (key 2, atr 14), three_thrust (4),
  squeeze_momentum (kc_mult 1.0), boll_bounce (20/2.0), gap_go (0.5%), macd_cross (12/26);
  3 marginal skipped as noise (ema_trend/supertrend/wavetrend); 9 unchanged. Roster window
  total −₹89.4k → −₹71.8k. boll_bounce fixture → `_vshape_15m` (2σ needs fat tails, sine
  maxes ~1.41σ). Evidence: `docs/backtest_tuning_20260715.json`. **140 tests green.**

## Earlier this session — 3H TradingView ports
- **`strategies/{supertrend, ut_bot, squeeze_momentum, wavetrend, qqe_mode}` (new)** — 5 TV
  strategies ported from Pine (user picked from a shortlist), long-only 15m run-dirs.
- `vibe-trading/agent/config/intraday.json` (+example) — roster 15 → **20**.
- `strategies/tests/test_intraday_strategies.py` — parametrized ×19; new `_squeeze_15m`
  fixture; wavetrend on a 4-day oscillation. 57 strategy tests.
- Docs: TASK_CHECKLIST (3H), IMPLEMENTATION_PLAN (3H), UNIT_TESTS, TEST_REPORT, QA, README,
  BUGS (BUG-004 logged earlier today for the day-1 host-shutdown abort).
- Gotchas hit: repo validator rejects **negative literal defaults** (unary minus ≠ literal);
  squeeze momentum's nested-rolling linreg goes valid a few bars after the fire → ≤5-bar
  entry grace.

## Previous session — creds day
- `agent/.env` — real GEMINI/DHAN/TELEGRAM creds (user); `MAX_POSITIONS` 3→4.
- `config/intraday.json` (+example) — universe switched (user) to **HDFCBANK(1333) /
  RELIANCE(2885) / TATASTEEL(3499) / ICICIBANK(4963)**, ids from the Dhan scrip master.
- **`src/intraday/bakeoff.py` (new)** — launcher CLI: validate → watchlist → wait-for-open →
  `Portfolio.run_session` → EOD review; per-day UTF-8 log in `agent/logs/`.
- **`start_bakeoff.bat` (new, project root)** — morning double-click starter.
- `src/intraday/bars.py` — `dhan_config_from_intraday` + `DhanBarSource(dhan_config=…)` (DC-003).
- `src/intraday/gemini_jobs.py` — real caller → direct REST `gemini_generate` (BUG-001).
- `src/trading/connectors/dhan/sdk.py` — dhanhq **2.x** compat w/ 1.x fallback (BUG-002).
- **`tests/test_intraday_live_wiring.py` (new)** — 12 tests over all of the above.
- Docs: BUGS (BUG-001/002, DC-003), QA, TASK_CHECKLIST (3E), IMPLEMENTATION_PLAN (3E),
  UNIT_TESTS, TEST_REPORT, README (bake-off run section), FLOWS (flow 8).

## Locked decisions (from user)
- Paper-first → small ₹25–50k live trial. Long-only everywhere.
- Gemini = research/oversight only **AMENDED 2026-07-15: plus ONE experimental paper trading
  slot (`llm_trader`, 5th roster member, live 2026-07-16)** — the 4 rule engines stay LLM-free;
  M2 promotion of the LLM slot needs its own decision.
- Universe (2026-07-15): HDFC Bank, Reliance, Tata Steel, ICICI Bank.
- **20 strategies** in parallel ≥1 week (5 → 15 on 2026-07-15 evening; 15 → 20 with the 5
  TradingView ports the same night, user-picked: supertrend, ut_bot, squeeze_momentum,
  wavetrend, qqe_mode); ₹25k independent per strategy (total ₹5L); **₹10k per-strategy loss
  cutoff = permanent setup kill-switch** (not aggregate, not daily). Hourly rollup + EOD
  scoreboard → Telegram (auto-chunked >4096 chars); per-trade events → log only, tagged
  `[PAPER·<strategy>]`.

## Universe DECIDED + switched (3K, 2026-07-15 night → live 07-16)
User rejected performance-based stock picking (rightly — recency bias) → **whole feasible
Nifty pool: 38 stocks**, structural filters only (median ≤ ₹3,000 + liquidity; 11 too-pricey
excluded, TATAMOTORS ticker dead post-demerger). `config/intraday.json` updated: 38 universe
entries w/ scrip-master-verified security_ids, `lookback_bars` 120, `max_positions` 4,
roster 21 (**new `oi_dma_adx`**: 3-day DMA × ADX(14)≥20 w/ +DI>−DI × OI gate — OI is
pass-through until a Dhan FNO futures-OI feed is wired = backlog). Scoreboard junk rows
removed (backup .bak-20260715). **143 tests green.** Backtests: `BACKTEST_REPORT_ALL38.md`
(note: backtest splits capital 1/38 — live concentrates ₹6,250×4, so live fee drag is much
lower; treat as signal check only). Capital stays ₹25k/strategy (₹50k question answered:
costs proportional below the ₹66.7k/order brokerage cap; 2× capital ≈ 2× both directions).
**Shorting = user question, assessment given (see QA/notes): decision NOT made.**

## 3L plan — long-only vs hybrid (long+short) A/B — USER-APPROVED DESIGN, NOT BUILT
- Keep the 21 long-only slots untouched; add **21 hybrid twins** (`<name>_ls`) that may emit
  −1 — SAME tuned params, same ₹25k + ₹10k kill-switch, same universe → any pair delta =
  value of the short side alone. **One process, 42 slots** (shared CachedBarSource, one
  report). Total paper ₹10.5L.
- Strategies decide direction from data (single bidirectional engine per twin, e.g.
  supertrend long in uptrend / short in downtrend); hybrid llm twin honors Gemini "short"
  (long-only slot keeps coercing to flat).
- **Per-direction P&L decomposition is mandatory** (hybrid = long-leg ₹ + short-leg ₹) —
  a short occupying a slot can block a long the twin takes, so legs must be attributable.
- Safety: 15:15 force-cover becomes a HARD invariant for shorts (uncovered short =
  settlement failure); per-trade SL more urgent (gap-up tail) — aligns w/ the ≈07-17/18
  SL/TP checkpoint. Capital req unchanged at 1x (short reserves notional like a long).
- Build order per workflow: 3L spec in docs/IMPLEMENTATION_PLAN.md §3L ✅ WRITTEN (07-15,
  Fable), then engine `allow_short` path + PaperBroker shorts + runner −1 handling + 20
  engines' short logic + test rework. **Build tonight (Opus), QA (Fable), launch 07-16**
  (user amended 07-15 night; was 07-17). Compare pairs only over shared days; expect
  ≥2 weeks (mixed regimes) before concluding.
- Stacking risk (accepted by user): 07-16 now debuts 4 changes in one process. Mitigations
  mandatory per §3L: per-slot exception isolation in Portfolio.run_tick + the 09:15 launch
  gate (any QA gate red → run `intraday.long21.json`, hybrid slips to 07-17).

## ⚠️ 07-16 was scratched by a SECOND host crash — read before doing anything
The host died again mid-session (BUG-004, 2nd day running). PID 19800 (08:16) died holding
positions; **a fresh process PID 26628 started 12:56:36** and is trading now with **all 42 slots
reset to ₹25k** — the morning (incl. `llm_trader`'s 4 longs ≈−₹66) survives **only in
`logs/bakeoff-20260716.log` + Telegram**. Dhan token unaffected (valid to 07-17 08:15).
Old process's uncovered paper shorts = **inert** (in-memory fictions, no settlement risk).
**User decision (~13:00): run on, exclude today.** The afternoon is live-fire validation of the
3L short path only (real SHORTs confirmed on squeeze_momentum_ls / wavetrend_ls / qqe_mode_ls).
**07-15 scratch + 07-16 scratch → ranking week starts 07-17, clean, on 40 slots.**

## Exact next step — 2026-07-20 morning (FIRST live day of the 64-slot roster)
Refresh the Dhan token in `agent/.env` → double-click `start_bakeoff.bat` (the preflight must log
**"33 long-only + 31 hybrid = 64"**; a failure exits 2 → run `config/intraday.long21.json`). Ollama must
be running locally (it's a service; both models pulled). Then **watch the first live hourly + EOD Telegram
render on the new B4-2 pair-collapsed report** — confirm 1 chunk each, halted pairs visible with ✖, and
the Δ column (ls − long) reads sensibly. Nothing to build; today is operate + observe.
**B4-2 DONE + Fable-QA CONFIRMED (§3V, 2026-07-19):** report reworked (pair-collapse, all pairs, hard
3-chunk cap); 386 green; DC-004 (EOD halted-row truncation) logged as non-blocking backlog (unreachable
at 64 slots). **No task queued.** Session wrapped 2026-07-19 EOD — resume here tomorrow.
**B7 DONE (§3U, 2026-07-19):** Tier-1 sub-batch ported + ranked offline (donchian/keltner the standouts);
roster NOT touched. **Open user decision:** promote donchian/keltner (as long + `_ls` twins) to the live
roster, or hold for the Tier-2 batch. **Fee-bleeder decision made:** KEEP ema_cross/hull_suite/ao_stoch,
let the ₹10k kill-switch retire them live (no roster edit). Still open at the ≈07-18 checkpoint: per-trade
SL/TP decision; BUG-004 state persistence (user-deferred). Weekly: rerun backtest_all.py +
evaluate_strategies.py as the Yahoo window rolls.

## DONE TONIGHT (07-17 post-close): full batch ✅ — BUG-007 → §3O → §3P → §3Q → §3R
**Independent QA (Fable) CONFIRMED same evening** — all gates re-run from scratch (268 tests,
scoreboard purity post-suite, roster 42+20, live e2e both models 19.4s/22.3s < 60s, code
spot-checks per spec). See the QA block in QA.md 07-17.
All five parts executed + gated (see QA.md 07-17 for the full gate table). Highlights: Gemini
bookends now retry transient failures and fall back to local Ollama with a `[local]` prefix
(BUG-006 Resolved); tests can no longer pollute the real scoreboard (BUG-007 Resolved); hourly
Telegram is movers-first with idle slots collapsed; EOD scoreboard has a Σ topline; README
documents the verified cost model; roster is 42 with two local-LLM candidate slots (llama3.1:8b
vs qwen3:8b — the scoreboard picks). One spec deviation, evidence-driven: `num_ctx` 16384 (8192
truncated the 38-symbol prompt to a 1-token reply) + `think:false` (qwen3 47s → 17s).

## DONE EARLIER (07-16 post-close → 07-17): §3M ✅, §3N ✅, day-1 clean ✅
- **§3M (07-16):** LLM slots out (42→40, ₹10L), Gemini research-only; BUG-005 WON'T FIX. All gates green.
- **§3N (07-16):** Wi-Fi-drop auto-resume ≤5 min (`_await_data`, `reconnect_budget_seconds=300`). 240 tests.
- **07-17 day 1 ran clean 08:37→15:37** (no crash — first uninterrupted day; BUG-004 didn't recur).
  Morning watchlist 429'd (= BUG-006, quota from 07-16's llm slots; structural fix = §3M volume cut,
  hardening = §3O). Mid-day P&L check (12:35): **0/38 active slots profitable**, aggregate ≈ −₹3.7k
  closed-trade; losses scale with trade count = fee drag on ₹6k positions, charges VERIFIED correct
  (hand-computed = engine to 4 decimals, matches Dhan published tariff). Scoreboard cleaned post-close:
  07-16 scratch rows (42) + A/B junk (2, = BUG-007) deleted, `.bak-20260717`; **now exactly 40 rows, 2026-07-17.**

## 3M — deprecate LLM trader slots (user, 2026-07-16 ~10:45) ✅ EXECUTED 2026-07-16 post-close
**Decision: retire `llm_trader` + `llm_trader_ls` after today's session. Reason = COST** (not
performance — see below). Reverts the 07-15 amendment → **Gemini is research/oversight only
again**. Watchlist + `eod_review` **stay** (user choice: ~1 call/day vs the slots' 50).
- **Depth (user choice): SOFT-DISABLE via roster only.** `llm_engine.py` + its 18 tests + the
  `builtin:` extension point are **kept** → reversible with a one-line edit. Rejected hard-remove
  (`llm_trader` is the only `_BUILTINS` entry — deleting it kills the whole `builtin:` mechanism).
- **Effect:** roster **42 → 40** (20 long + 20 `_ls` — pairing stays symmetric, 3L A/B unaffected),
  paper **₹10.5L → ₹10L**, Gemini calls/tick **2 → 0** (also removes that tick-loop latency).
- **Measured basis (07-16 ~10:40):** 50 calls/day, ~5–6k input tokens each (38 symbols × 8 bars) +
  ~1.5k output → **~265k in / 76k out per day**, ~1.3M/380k per week. Volume measured; spend is
  the user's to see. Reliability: **7 × `httpx.ReadTimeout` in 6 ticks, zero 429s** (the "429" hits
  in the log are COALINDIA's ₹429.29 price) — the fat prompt drives both cost and timeouts.
- **Not a performance verdict:** one compromised day (twin frozen by BUG-005, `llm_trader` closed
  nothing). Cost is knowable day 1; edge isn't. Soft-disable keeps it revisitable.
- **Pre-verified 07-16 (so tonight is mechanical):** `test_intraday_portfolio.py` is NOT
  roster-coupled (no `llm`/`42`/`21`/config-load) → **tests stay 236**; `validate_roster` has no
  hardcoded counts; the only code edit is `bakeoff.py` **L133** ("21 long-only" → **20**).
- **Gates:** `validate_roster` builds 40 + 20 fallback (exit 0) · 236 green · no `builtin:llm_trader`
  in the live configs · **preserve** today's `llm_trader` scoreboard row + `llm_journal-20260716.jsonl`.
- **BUG-005 → closes WON'T FIX on execution** (superseded — don't build the keep-last fix).
Scoreboard junk rows: DONE (removed 07-15, backup `.bak-20260715`). Consider deferring
Windows-Update restarts during market hours (BUG-004).

## How to run tests
Agent (148): `cd vibe-trading/agent && set PYTHONPATH=. && python -m pytest
tests/test_india_intraday_engine.py tests/test_intraday_runtime.py tests/test_intraday_portfolio.py
tests/test_intraday_live_wiring.py tests/test_llm_engine.py tests/test_intraday_shorts.py
tests/test_gemini_jobs.py -q`
Strategies (228) + evaluator (5): `cd strategies && set PYTHONPATH=../vibe-trading/agent && python -m pytest tests/ -q`
Backtests: `cd strategies && python backtest_all.py [--tune] [--symbols …] [--suffix _X]`

## Blockers
- None. Only recurring friction: the 24h Dhan token refresh is manual (automation = M2 item).

## Notes
- **TONIGHT's backlog (user, 2026-07-17) → see `docs/TASK_CHECKLIST.md` "Added 2026-07-17":**
  **B1** review Gemini day-end feedback (`eod_review`); **B2** trade-cost model vs real brokers
  (₹20/order — note the engine already does `min(₹20, 0.03%)`; at ₹6k sizing the 0.03% binds, and
  ~0.106% is the all-in round trip, not brokerage alone — decide if it matches the user's broker);
  **B3** add a lot more strategies (scale-check the tick loop + report size first); **B4** optimize the
  hourly + day-end reports (40 slots = too much Telegram text → summarize/collapse quiet slots);
  **B5** local-LLM trader — revive the §3M-killed LLM slot on **local models** (Ollama/llama.cpp),
  zero cost + no 429; soft-disable was reversible by design (llm_engine.py + builtin: hook kept) →
  new local caller + one roster line. Scope clarified: a couple of models as **candidates to try**
  (pick one), NOT an ensemble. Watch latency (38-sym prompt/tick) + re-apply the BUG-005 keep-last fix.
  Context for all four is in today's conversation: charges verified correct (match Zerodha to the paisa),
  and 0/38 strategies profitable at 12:35 (losses scale with trade count = fee-drag/churn, not a bug).
- **3G (2026-07-15 evening):** 10 new run-dir strategies (gap_go, gap_fade, vwap_hold,
  range_break, macd_cross, boll_bounce, boll_break, atr_trail, rel_strength, three_thrust) +
  scale infra: `CachedBarSource` (one Dhan fetch/symbol/tick shared by 15 runners; invalidates
  on tick move or 300s TTL) and `split_for_telegram` chunking. Strategy tests parametrized ×14
  with pattern-matched fixtures (`TRADE_FIXTURES`). New strategies are UNBACKTESTED on real
  data by choice — the paper week ranks them. rel_strength is universe-aware (ranks data_map).
  Repo validator bans @staticmethod in engines — helpers go module-level.
- **LLM trader (3F)** built 2026-07-15, live from 2026-07-16: `src/intraday/llm_engine.py`
  (`LLMSignalEngine`), roster `run_dir: "builtin:llm_trader"` (repo VT-001 validator forbids
  network in `strategies/` run dirs → LLM slot lives in the trusted overlay). One Gemini call per
  15m tick, strict-JSON parse, keep-last on failure, code-enforced no-entry windows, flat w/o key.
  Not backtestable — judged on live paper only. 13 tests (`tests/test_llm_engine.py`); **92 total**.
- **LLM decision tracking** (user): Gemini replies `{"decision","reason","stop","target"}` per
  symbol; daily JSONL journal `~/.vibe-trading/intraday/llm_journal-YYYYMMDD.jsonl` records every
  tick's decision (reason + stated SL/target + price) and an `exit_eval` per round trip grading
  the LLM against its own levels (`stop_hit`/`target_hit`/`move_pct`). SL/targets are tracked
  intentions only — execution is the backlogged M1 SL/TP feature (checkpoint ≈ 2026-07-17/18).
- Per-trade log lines now stamped `[PAPER·<strategy>]` (attribution across parallel slots was
  ambiguous in day-1 logs) — live 2026-07-16, same launch as the detailed report.
- **Detailed hourly report** built 2026-07-15 mid-session (user request): per-strategy fills
  (time/side/qty/price/fee/realized), open positions w/ unrealized P&L, equity,
  **in-market ₹ vs cash ₹ split** and **P&L decomposition (trades gross · charges · net)** in both
  the hourly header and the EOD scoreboard (gross/fees/net columns replace ret%), halt reasons —
  `format_hourly_detailed`. **Applies from the 2026-07-16 session** (day-1 process not restarted:
  it was already holding positions; a restart wipes in-memory paper state). 79 tests green.
- BUG-003 (fixed, applies from tomorrow's watchlist): day-1 Gemini watchlist invented "5x
  leverage / ₹25L buying power" — prompt now roster-aware (₹25k × 4) and forbids leverage talk.
  Engine was never affected: PaperBroker is strictly 1x cash.
- Creds-day bugs (all fixed + tested): BUG-001 Gemini caller imported nonexistent
  `src.llm.factory`; BUG-002 vendored Dhan connector was dhanhq-1.x-only (2.2.0 installed:
  DhanContext ctor, renamed methods, parallel-array payload); DC-003 sdk reads creds from
  `~/.vibe-trading/dhan.json`, not env → threaded via `dhan_config_from_intraday`.
- Day-1 log: `agent/logs/bakeoff-20260715.log`. Scoreboard JSON: `~/.vibe-trading/intraday/`.
- ORB + pullback were net-negative on the Yahoo backtest — the bake-off is the arbiter;
  tuning is a candidate task while it runs.
- DC-001 (flat by 15:00, runtime force-flatten 15:15) and DC-002 (numeric security_id,
  Dhan intraday history ≈5 days) still hold.
