# QA Log

Newest session at top. ✅ pass · ⚠️ partial · ❌ fail

## 2026-07-19 (B4-2) — Telegram report rework for the 64-slot roster ✅ ALL GREEN (build = Opus)

Mockup-first per the user gate: rendered the CURRENT report at 64 slots from a synthetic mid-day
portfolio through the REAL formatters + chunker, showed the spill, proposed the pair-collapsed shape,
and **got approval before touching any file** (user amendment: hourly shows *all* pairs, not top-N).
Scope was report formatters only — no engine/strategy/`config/intraday.json` edits (authorized B4-2 exception).

| Gate | Result |
|---|---|
| Agent suites (portfolio/live-wiring/gemini_jobs reworked; rest untouched) | ✅ **153 passed** (was 148; +5 net) |
| Strategy suite (×38 × 6) | ✅ **228 passed** (untouched) |
| Evaluator tests | ✅ **5 passed** (untouched) |
| **Total** | ✅ **386 passed, 0 failed** (was 381; +5) |
| Hourly chunk count @64 (synthetic, real `split_for_telegram`) | ✅ **4 chunks / 12,655 chars → 1 chunk / 1,905 chars** |
| EOD scoreboard chunk count @64 | ✅ **2 chunks / 4,551 chars → 1 chunk / 1,931 chars** |
| Hard chunk cap | ✅ 400-pair stress input truncates to **≤3 chunks** with a `… +N more pairs (log)` pointer (both reports) |
| Halted-always-visible rule | ✅ halted pairs listed with both legs (✖ on the retired leg); halted **unpaired** `llm_*` slots flagged ✖ (gap caught + fixed pre-ship) |

**Shape:** one row per long/`_ls` pair — `long · ls · sht · Δ(=ls−long) · f · h` in the hourly (all
pairs, movers-first) and `# · pair · long · ls · sht · trd · flag` in the EOD (ranked by best leg,
halted last). `eod_review`'s past-40-fills aggregation pair-collapsed to match (asks whether the short
leg helped). Params: **top-N dropped** (user: show all pairs), **chunk cap 3**, hourly sort =
max(|long|,|ls|) desc, EOD sort = best leg desc.

**Independent QA (Fable, 2026-07-19) — CONFIRMED.** All five gates re-run from scratch: tests 386
(agent 153 / strategies 228 / evaluator 5, zero fail); live formatters @64 reproduced to the character
(hourly 1,905/1 chunk, EOD 1,931/1 chunk); Fable's own 400-pair stress hit the cap at **exactly 3
chunks** with an arithmetically-exact `… +N more pairs (log)` pointer kept inside `<pre>`; halted long /
halted `_ls` / halted unpaired `llm_*` all visible with ✖ on the correct leg (BUG-009 fix confirmed
live); no engine/strategy/`config` edits (repo-wide mtime sweep). **Two caveats, neither live-blocking:**
(1) **EOD halted-pair rows are not truncation-proof** — in `format_scoreboard` halted pairs are body
rows sorted last, so under the 3-chunk cap they drop *first* (the halted-`llm` tail still survives). The
"halted always visible" invariant strictly holds for the **hourly** (halted pairs live in the never-
dropped tail) but for the EOD only until ~150 pairs of content — **unreachable at 64 slots** (1,931 chars
vs a ~12,000 budget, ~6× headroom). Logged as a known limitation (BUGS.md) for if the roster grows past
~100 pairs. (2) the "before" figures (4/2 chunks) are historical — pre-B4-2 code is gone, so only the
"after" numbers were re-verified.

## 2026-07-19 (later) — §3U Tier-1 shortlist port batch (B7, +7 strategies, offline) ✅ ALL GREEN

User go-ahead on B7: port the Tier-1 shortlist sub-batch → rank with `evaluate_strategies.py`. Ported
7 new-archetype run-dirs (cpr_pivot, psar_flip, supertrend_vwap, donchian, keltner, stoch_rsi,
connors_rsi2), long-only + `allow_short` twin. **Offline only** — `config/intraday.json` / the 64-slot
live roster **not** touched (promotion is a separate user decision, per the funnel + the standing guardrail).

| Gate | Result |
|---|---|
| Strategy validators + shape (×38 × 6) | ✅ **228 passed** (was 186); each new engine is validator-clean (no decorators, literal defaults, no network), long-only + flat outside 09:45–15:00, mirror emits ≥1 short, no-arg never shorts, same-day MIS both directions |
| Evaluator tests | ✅ **5 passed** (untouched) |
| Agent suites | ✅ **148 passed** (untouched — no agent/config edits) |
| **Total** | ✅ **381 passed, 0 failed** (was 339; +42) |
| Backtest (`backtest_all.py`, cached 4-stock) | ✅ all 7 run + produce trades; all net-negative on the down regime (least-bad keltner −₹2,691/95; worst stoch_rsi −₹7,920/261). Reports `BACKTEST_REPORT_TIER1.md` + full 38 regenerated |
| Robustness rank (`evaluate_strategies.py`, 49 sym × 4 folds × 2× slip) | ✅ batch standouts **donchian** (−38.7, pos 15%, 21 trades/sym) + **keltner** (−61.5, 12%, 28); the other 5 are churny fee-bleeders on this one regime. Report `STRATEGY_EVALUATION.md` |

**Found + fixed (BUG-008):** connors_rsi2's RSI(2) helper used the §3S `fillna(50)` house style, which
on a 2-bar RSI turned a fully-overbought (should-be-100) zero-loss window into a neutral 50 → the
mirrored short never armed. Fixed to the standard `avg_loss==0 & avg_gain>0 → 100` convention; the
long side (RSI→0) was already correct. Caught by the suite pre-ship — never reached any config.

**Decision surfaced to user:** promote survivors (donchian / keltner most defensible) to the live paper
roster as long + `_ls` twins, or hold for the Tier-2 batch first — the live weeks are the real arbiter.

## 2026-07-19 — §3S promotion: roster 42 → 64 (live from 2026-07-20) ✅ GATES GREEN

User: "add these to the plan so they also run from Monday." Promoted all 11 §3S ports as long + `_ls`
twins (per 3L) in `config/intraday.json` (+`.example`). Roster 42 → 64 (33 rule/llm long + 31 `_ls`),
₹16L paper. Fallback `intraday.long21.json` untouched.

| Gate | Result |
|---|---|
| Roster integrity | ✅ 64 slots, unique names, all 31 `_ls` twins pair to a rule-long run_dir |
| `validate_roster` (launch gate) | ✅ builds **64 + 20 fallback**, exit 0; preflight logs "33 long-only + 31 hybrid (_ls) = 64 slots" (count is computed, no code edit) |
| Scale check — tick-loop time | ✅ one tick = **62 rule slots × 38 symbols in ~1.1 s** (≈800× under the 15-min budget); slot count is not the bottleneck. (2 builtin llm slots excluded — separately gated < 60s in §3R.) |
| Scale check — report size | ⚠️ EOD scoreboard 4,526 chars → **2 Telegram chunks** (max 3,975 < 4,000, chunks cleanly) — but the hourly *detailed* report will be larger at 64 → **B4-2 rework queued for 2026-07-20** |
| Tests | ✅ **334 green** (agent 148 untouched — portfolio tests are not roster-coupled; strategies 186) |

**Follow-up B4-2 (2026-07-20):** rework the Telegram report for 64 slots (top-N movers, collapse
long/`_ls` pairs, hard chunk cap). Tracked in TASK_CHECKLIST + SESSION.

## 2026-07-18 — §3S TradingView ports batch 2 (11 strategies, offline backtest) ✅ ALL GREEN

User request: "copy the strategies from the TradingView shortlist and backtest them." Ported the 11
portable strategies from the screenshot (skipped supertrend = already in 3H, 3Commas Bot = a DCA bot
not a directional signal, Ultimate Strategy Template = an empty template). Offline only — user chose
"backtest first, then decide" on live-roster promotion, so `config/intraday.json` was **not** touched.

| Gate | Result |
|---|---|
| Strategy suite | ✅ **186 passed** (31 strategies × 6 checks; was 120) — validators, long-only+windows, hybrid-short-on-mirror, no-arg-never-shorts, both-directions same-day MIS trades |
| Agent suites | ✅ **148 passed**, untouched (no agent/config edits this batch) → **334 total, 0 failed** |
| Validator acceptance | ✅ all 11 pass `_validate_signal_engine_source` (no decorators, literal defaults) + `_validate_signal_engine_class` (no-arg ctor + `generate`) |
| Backtest ran (offline) | ✅ `backtest_all.py` over cached 4-stock Yahoo 15m; all 11 net-negative on the down window (best `macd_rsi` −₹1,819/34 trades, worst `ao_stoch` −₹8,639/268) — expected fee-drag/regime signal, not a verdict; full 31-strategy `BACKTEST_REPORT.md` regenerated + focused `BACKTEST_REPORT_TVPORTS.md` |
| Docs autopilot | ✅ TASK_CHECKLIST (§3S + B3), TEST_REPORT, UNIT_TESTS, QA (this), README, IMPLEMENTATION_PLAN, SESSION, memory |

**Port adaptations (documented in each module docstring, not bugs):** two ChartArt "SMA 200"
strategies were scaled to the live 120-bar lookback (macd_sma200 trend MA 200→100; golden_cross
50/200→25/100) — a literal 200-bar 15m SMA (~15 sessions) can never be valid live. Flawless Victory
was ported as a lower-band **reclaim** (snap-back) with its RSI floor tuned 42→30, because a 2σ
down-breach on any synthetic tape always coincides with a washed-out RSI (real fat-tailed markets
differ) — the reclaim is the "buy strength returning, not the falling knife" spirit of the original,
gated by its signature MFI. ao_stoch's Stochastic gate is "not overbought" (%D<80) rather than
"<50", since an AO>0 momentum leg keeps the Stochastic high (the <50 gate is self-defeating on trends).

**Two synthetic fixtures added** (offline, no network): `_long_uptrend_15m(days)` (enough bars for the
slow-MA / Ichimoku-cloud ports to warm up) and `_divergence_15m` (a deep first low then a lower second
low after a modest recovery, so dip 2's 14-bar RSI window keeps up-bars → higher RSI at a lower price
= textbook bullish divergence; mirrored → bearish, for the short twin).

## 2026-07-17 (post-close) — Tonight's batch: BUG-007 → §3O → §3P → §3Q → §3R ✅ ALL GATES GREEN

Executed the full user-approved batch from `docs/IMPLEMENTATION_PLAN.md` (build = Opus per the
model split). Gemini bookend hardening + local-Ollama fallback (BUG-006), 40-slot report diet,
cost-model doc, and the two local-LLM trader slots (roster 40 → 42 for 07-18).

| Gate | Result |
|---|---|
| Full suites | ✅ **268 green** (agent **148** = engine 16 + runtime 25 + portfolio **31** + live-wiring 16 + llm_engine **25** + shorts 23 + **gemini_jobs 13 (new)**; strategies 120) — was 240, +28, 0 failed |
| BUG-007 verify | ✅ full suite run, then real `~/.vibe-trading/intraday/scoreboard.json` still **exactly 40 rows, all dated 2026-07-17** (tests now default to a tempfile store) |
| `validate_roster` | ✅ builds **42** from `intraday.json` (22 long incl. `llm_local_a/b` + 20 `_ls`) and **20** from `intraday.long21.json`, exit 0 — preflight now threads `params` + `slot_name`, so a bad provider/model kwarg fails at the launch gate |
| §3O retry/fallback | ✅ transient-only retry (2 failures → 3rd succeeds; 401/ValueError → no retry); exhausted retries → `[local]`-prefixed Ollama text; no fallback → static string; stub caller carries no fallback |
| §3O EOD aggregation | ✅ >40 fills + metrics → per-strategy lines (trades/net/fees/best/worst/[RETIRED]), raw fill dump gone; small sessions unchanged |
| §3P report diet | ✅ idle slots collapse to `— N slots idle (flat, ₹0)` (halted slots always render); movers-first sort; 8-fill cap + `… +N more (log)`; `⇅ legs` only when a leg ≠ 0; scoreboard topline `Σ net · fees · trades · P of M profitable`; header math unchanged |
| §3Q cost model | ✅ doc-only — README "Cost model" section (component table, ADANIENT ₹1.33/₹2.02 worked example, cap-vs-flat clarification, sizing note). No bug entry, per spec |
| §3R live Ollama smoke | ✅ both candidates answer the **real 38-symbol prompt** with valid 38/38-parsed JSON; e2e `LLMSignalEngine.generate` with real llama3.1:8b: 19.3s, 0/38 longs on the synthetic tape, not degraded |
| §3R latency gate (< 60s) | ✅ **llama3.1:8b 14.5s · qwen3:8b 20.8s** (RTX 5070, warm) — **both slots stay** |
| §3R degraded mode (BUG-005 lessons) | ✅ slot-tagged journal (`slot` field) + log lines; 3 consecutive failures (call raised OR unparseable reply) → degraded = **flat** (closes the stale position), success resets; no-arg ctor regression (gemini/long-only/`llm_trader`) intact |
| Docs autopilot | ✅ BUGS (006+007 → Resolved), TEST_REPORT, UNIT_TESTS, FLOWS, README, TASK_CHECKLIST, IMPLEMENTATION_PLAN, SESSION.md, memory |

**Found + fixed during QA (spec deviation, evidence-driven):** the spec'd `num_ctx: 8192` silently
**truncated the 38-symbol prompt** — it measures **9.6k (llama) / 13.7k (qwen) tokens**, so Ollama
cut it and both models stopped after ~1 token (`done_reason=length`; first gate run returned `"{\n"`
and `""`). Fix in `local_llm.py`: `num_ctx: 16384` + `"think": false` (qwen3 is a thinking model —
47.1s with thinking, 17.2s without; llama3.1 ignores the flag). Also: local `llama3.1` was only
tagged `:latest` — `ollama pull llama3.1:8b` (tag-only) + `ollama pull qwen3:8b` (~5 GB) both done.

**Verdict:** ✅ batch complete. 07-18 runs **42 slots** (₹10.5L paper): 20 rule + 20 `_ls` + 2
local-LLM candidates picked by scoreboard. Bookends can no longer die silently on a quota-429.

**Independent QA (Fable, same evening) — CONFIRMED, all gates re-run from scratch:**
suites re-run: **268 green** (148 agent + 120 strategies) · scoreboard.json re-checked *after* the
suite: exactly 40 rows / 2026-07-17 / no A-B (BUG-007 fix holds end-to-end) · `validate_roster`
re-run: 42 + 20, `llm_local_a/b` params correct · fresh e2e `generate()` through **both** live
models: llama3.1:8b **19.4s**, qwen3:8b **22.3s** (< 60s gate; 0 longs explained — synthetic tape's
last bar hit the ≥15:00 no-entry window, journal `forced_flat: true` with real model reasons =
parse verified) · journal schema carries `slot` + `degraded`; `portfolio.py:145`/`bakeoff.py:65`
thread `slot_name=ref.name` (the smoke's `llm_trader` tag was the QA harness's own default-arg
call, not a wiring bug) · code spot-checks: transient-only retry + `[local]` fallback chain,
degraded=flat + reset-on-success, idle-collapse/topline, README cost-model section — all per spec.

## 2026-07-16 (post-close) — 3N: ride out short Wi-Fi/data drops before a tick ✅ ALL GATES GREEN

Executed §3N (`docs/IMPLEMENTATION_PLAN.md`) — auto-resume across a data drop up to 5 min without human intervention (host crashes out of scope per user). New `Portfolio._await_data` reconnect-wait guard + tunable `reconnect_budget_seconds` (default 300).

| Gate | Result |
|---|---|
| Full suite | ✅ **240 green** (120 agent + 120 strategy) — +4 portfolio tests for the reconnect guard |
| Happy path is free | ✅ online probe → 0 sleeps, `now` unchanged; probe warms the shared cache so `run_tick` reuses it (no extra live fetch) |
| Rides out an outage | ✅ failed probes → exponential backoff (5s→30s), resumes the moment data returns, `now` refreshed to real wall-clock |
| Bounded by budget | ✅ sustained outage → total sleep ≤ `reconnect_budget_seconds`, then proceeds and degrades to the pre-3N empty-frame *hold* (only that bar lost) |
| Config tunable / disable | ✅ `intraday.json` loads with `reconnect_budget_seconds = 300`; `0` disables the wait |
| Preflight unaffected | ✅ `validate_roster` still builds 40 + 20, exit 0 |

**Verdict:** ✅ 3N complete. A Wi-Fi drop ≤ 5 min no longer costs a 15m bar — the tick waits it out and resumes automatically. **Scope note:** this covers *network* drops while the process lives; *process/host death* (BUG-004) is a separate track the user is handling elsewhere.

## 2026-07-16 (post-close) — 3M: LLM trader slots removed (roster 42 → 40) ✅ ALL GATES GREEN

Executed §3M (`docs/IMPLEMENTATION_PLAN.md`) — soft-disable the two LLM slots on cost grounds. Config/string edits only; no code deleted (`llm_engine.py` + 18 tests retained). Verified before the 07-17 bell.

| Gate | Result |
|---|---|
| `validate_roster` preflight | ✅ builds **40** slots from `intraday.json` **and 20** from `intraday.long21.json`, exit 0 |
| Full suite | ✅ **236 green** (116 agent + 120 strategy) — unchanged, nothing deleted (portfolio tests not roster-coupled, as pre-verified) |
| No live LLM roster refs | ✅ `grep builtin:llm_trader` = 0 in `intraday.json`, `intraday.long21.json`, `intraday.example.json` |
| Extension point intact | ✅ `_BUILTINS` still resolves `llm_trader` when constructed directly — `test_llm_engine.py` (18) green |
| Roster counts | ✅ `intraday.json` = 40, `intraday.long21.json` = 20, `intraday.example.json` = 40 (all valid JSON) |
| Experiment record preserved | ✅ today's `llm_trader` scoreboard row + `llm_journal-20260716.jsonl` untouched |

**Verdict:** ✅ 3M complete. Roster is 40 (20 long + 20 `_ls`), ₹10L paper, Gemini = research/oversight only again. BUG-005 closed WON'T FIX. Ready for the 07-17 clean day-1 (after the 07-16 scoreboard-row deletion + Dhan token refresh).

## 2026-07-16 (~01:00, pre-bell) — 3L QA gate: hybrid (long+short) A/B build ✅ → LAUNCH GATE OPEN

Fable QA session over the Opus build (model split per user). Gates from `docs/IMPLEMENTATION_PLAN.md` §3L.

| Gate | Result |
|---|---|
| Full suites on the settled tree | ✅ **236 green** (116 agent + 120 strategy), 0 failed |
| Existing-143 baseline | ✅ 142/143 byte-level intact (runtime + live-wiring files untouched); **1 deliberate replacement**: the engine test asserting the pre-3L "config can never enable shorts" rule — repealed by the 3L decision itself; default long-only still tested |
| **15:15 force-cover (invariant 2, HARD)** | ✅ tests with & without a last price; `_force_flatten` + kill-switch + slot-halt all route through `close_position` with `avg_price` fallback (no path leaves a short uncovered) |
| Broker accounting identities | ✅ round-trip at one price = −(entry+cover commissions) exactly; equity continuous; STT on short entry / stamp on cover; reserve ≤ budget |
| One direction per symbol (invariant 6) | ✅ buy↔short mutual refusal; cover/sell clamp, never flip |
| Long-only arm untouched (invariant 1) | ✅ no-arg ctors never emit −1 (×20, mirrored tape); runner coerces −1→0 belt-and-braces; long-only slots unchanged in config |
| Twins share ONE engine source (invariant 4) | ✅ `_ls` roster entries reuse the same `run_dir`; `load_signal_engine` **fails fast on TypeError** (never silently long-only) |
| Per-slot exception isolation (mandatory per launch-history) | ✅ a slot raising in `run_tick` is squared off best-effort + halted alone; tested |
| Per-direction P&L decomposition (invariant 3) | ✅ `long_pnl`/`short_pnl` in metrics + `lng₹`/`sht₹` scoreboard columns; 🔻 SHORT / 🔺 COVER in hourly detail |
| LLM hybrid twin | ✅ "short" → −1 only when `allow_short`; flipped exit_eval grading; long-only coercion regression kept |
| **Launch-gate preflight on real configs** | ✅ `validate_roster`: all **42** slots of `intraday.json` build (21+21, `llm_trader_ls → builtin:llm_trader`); fallback `intraday.long21.json` builds 21/21; `.example` matches |

**Verdict: all §3L gates GREEN — the 09:15 launch gate is OPEN for 07-16 (42 × 38, ₹10.5L paper).**
QA note: the first test pass ran while the Opus session was still writing (phantom collection
counts); everything above is from the settled tree. Day-1 watch items: Gemini 2 calls/tick
(llm_trader + llm_trader_ls), report size with 42 sections, first real short entries + the
15:15 force-cover line in the log.

## 2026-07-16 (pre-launch) — 3K: 38-stock universe live + oi_dma_adx (21st slot) ✅
| Check | Result |
|---|---|
| 38 `security_id`s extracted from the Dhan scrip master; 4 previously-live ids matched exactly (extraction verified) | ✅ |
| `config/intraday.json`: 38-stock universe · roster 21 · `lookback_bars` 120 · `max_positions` 4 (explicit) | ✅ |
| `oi_dma_adx` passes repo validators; trades the default trending fixture; OI gate pass-through documented (spot has no OI — FNO feed backlogged) | ✅ |
| All 21 roster slots load through `Portfolio`'s loader | ✅ |
| Junk scoreboard rows (A/B, 07-14) removed — week starts clean (backup `scoreboard.json.bak-20260715`) | ✅ |
| Full regression on new config | ✅ **143 green** (60 strategy + 83 agent) |

**Verdict:** launch-ready. From 2026-07-16: **21 strategies × 38 stocks**, ₹25k each (₹5.25L
total paper). Universe chosen structurally (price/liquidity only) per user's anti-overfitting
call — no performance-based stock selection. Watch item: llm_trader's prompt now carries 38
symbols' tape — monitor its decision journal for quality degradation (cap its watchlist if so).

## 2026-07-15 (late night) — 3J: Nifty-50 universe scan + candidate-12 validation ✅
| Check | Result |
|---|---|
| 48/50 stocks scanned (MARUTI retried OK; TATAMOTORS ticker dead post-demerger) × 18 strategies × 2 windows | ✅ |
| Structural filters applied (price ≤ ₹3,000 → excludes MARUTI/ULTRACEMCO/BAJAJ-AUTO/APOLLOHOSP/EICHERMOT/HEROMOTOCO/BRITANNIA/LT/M&M/GRASIM/TITAN; all pass ₹1cr/day liquidity) | ✅ |
| Current 4-stock universe scored near-bottom (TATASTEEL/HDFCBANK/ITC-class: 0–1 of 18 validate-positive) | ✅ (finding) |
| Candidate-12 roster backtest: validate window 8/19 gross-positive, gap_fade net +₹120 (vs 0/19 on current 4) | ✅ |
| Allocation caveat documented (backtest splits 1/12; live concentrates ₹6,250×4 → live fees lower) | ✅ |
| Config untouched pending user's universe decision + Dhan security_ids | ✅ |

**Verdict:** scan accepted as selection evidence, not prophecy (train↔validate stock ranks flipped
with the IT rally — regime moves). Recommendation: 12-stock universe led by INDUSINDBK/HCLTECH/
TCS/TECHM; awaiting user pick before touching `config/intraday.json`.

## 2026-07-15 (night, cont.) — 3I.2: full-roster tuning, 19/19 grids ✅
| Check | Result |
|---|---|
| 19 grids (115 combos total) ranked on train only; every winner judged on untouched validate | ✅ |
| **7 applied** (OOS gain ≥ ₹300): momentum_rsi, ut_bot, three_thrust, squeeze_momentum, boll_bounce, gap_go, macd_cross | ✅ |
| **3 marginal YESes skipped as noise** (ema_trend +₹48, supertrend +₹103, wavetrend +₹237) — anti-overfit discipline | ✅ |
| 9 with no OOS improvement left untouched | ✅ |
| boll_bounce fixture replaced (`_vshape_15m`) — a pure sine can't close 2σ outside its own band (max ≈1.41σ) | ✅ |
| Roster full-window total: −₹89.4k → **−₹71.8k** (~20% less loss); tuning evidence archived in `backtest_tuning_20260715.json` | ✅ |
| Full regression after all default changes | ✅ **140 green** |

**Verdict:** accepted; tuned defaults live from the 2026-07-16 launch. Still all-negative on the
window — tuning cannot beat a down-tape for long-only intraday; it reduced bleed, mostly by
cutting churn (e.g. three_thrust 223→95 trades). The paper week starts tomorrow on these params.

## 2026-07-15 (late night) — 3I: batch backtest of all 19 + orb/pullback tuning ✅
| Check | Result |
|---|---|
| `backtest_all.py`: 19/19 strategies run through `IndiaIntradayEngine` on 57 days of real Yahoo 15m bars | ✅ |
| Train/validate split honest (grids ranked on train only; winner judged on untouched validate) | ✅ |
| Day-on-day P&L matrix (57 days × 19 strategies + TOTAL) in report + CSV | ✅ |
| orb grid (8 combos): train winner `vol_mult 1.5 / vol_window 12` confirmed better out-of-sample (−₹1,271 vs −₹2,095) → **applied** | ✅ |
| pullback grid (9 combos): zero out-of-sample sensitivity → defaults kept (honest no-op) | ✅ |
| Strategy suite re-run after the orb change | ✅ **57 green** |

**Verdict:** harness accepted; one tuning applied. Headline: **all 19 net-negative** on the
window — but the tape was down (TATASTEEL −12.7%, RELIANCE −4.3%), so this reads as regime +
cost drag, not 19 broken strategies. Fee share of losses is the actionable signal: high-churn
engines are structurally handicapped at ₹25k. The live paper week (starting 2026-07-16 with
20 slots) remains the arbiter; rerun the harness weekly as fresh Yahoo days roll in.

## 2026-07-15 (night) — 3H: TradingView ports, roster → 20 (live 2026-07-16) ✅
| Check | Result |
|---|---|
| 5 TV ports (supertrend, ut_bot, squeeze_momentum, wavetrend, qqe_mode) pass repo validators + long-only/flat-window/same-day (19 × 3 = 57) | ✅ |
| squeeze_momentum trades the compression→release fixture (`_squeeze_15m`); wavetrend trades the 4-day oscillation | ✅ |
| Validator quirk handled: negative literal defaults rejected → wavetrend threshold defaults to the zero line | ✅ |
| Momentum warm-up lag after a squeeze fire covered by a ≤5-bar entry grace (nested rolling windows go valid late) | ✅ |
| Real `config/intraday.json`: all **20** roster entries load through `Portfolio`'s loader (offline check) | ✅ |
| Full regression | ✅ **140 green** |

**Verdict:** accepted. From 2026-07-16 the bake-off runs **20 parallel strategies** (19 rule +
llm_trader; ₹25k each → ₹5L total paper). The TV ports are faithful to the published Pine formulas
with documented simplifications, and — like 3G — deliberately unbacktested on real data: the paper
week ranks them. Same-day scratch note: day 1's 4-strategy run was killed ~14:03 by the host
shutdown (BUG-004), so 07-16 is the ranking week's true day 1 for everyone.

## 2026-07-15 (evening) — 3G: 15-strategy roster + scale infra (live 2026-07-16) ✅
| Check | Result |
|---|---|
| 10 new strategies pass repo validators + long-only/flat-window/same-day (14 × 3 = 42) | ✅ |
| Specialists trade their target pattern (gap up/down, oscillation, volatility surge fixtures) | ✅ |
| `CachedBarSource`: 15 runners share ONE fetch per symbol; invalidates on tick change only | ✅ |
| Telegram chunking: >4096-char report split on line boundaries, nothing lost | ✅ |
| Real config builds 15 slots · ₹25k each · ₹3.75L total paper | ✅ |
| Full regression | ✅ **125 green** |

**Verdict:** accepted. From 2026-07-16 the bake-off runs 15 parallel strategies (4 original rules +
llm_trader + 10 new archetypes: 2 gap specialists, VWAP rider, mid-day range break, MACD, 2 Bollinger,
ATR trail, cross-sectional relative strength, three-bar thrust). New strategies are unbacktested on
real data by choice — the paper week ranks them.

## 2026-07-15 (later) — LLM 5th slot + detailed hourly report (both live 2026-07-16) ✅
| Check | Result |
|---|---|
| `LLMSignalEngine`: long decision on last bar only; long-only 0/1 | ✅ |
| Guard rails outrank the LLM (<09:45 and ≥15:00 → 0 despite "long" reply) | ✅ |
| API failure / bad JSON → **keeps last decision** (no churn, no raise, no halt) | ✅ |
| Fenced ```json parsed; invented symbols ignored; "short" → flat; no key → flat | ✅ |
| `builtin:llm_trader` roster wiring → real config builds **5 slots**, LLM slot armed, ₹25k | ✅ |
| Decision tracking: reason/stop/target parsed + journaled per tick (daily JSONL); `exit_eval` grades each round trip vs the LLM's own levels | ✅ |
| Detailed hourly report: fills w/ price+fee+realized, open positions w/ unrealized, halts | ✅ |
| Full regression | ✅ **92 green** |

**Verdict:** accepted. Both features activate at the 2026-07-16 launch (day-1 process not restarted —
it holds open paper positions). Decision amendment recorded: Gemini gets ONE experimental paper
trading slot; rule engines stay LLM-free; the LLM slot is not backtestable and is judged on live
paper forward results only.

## 2026-07-15 — Live activation: real creds smoke-tested, launcher built, **day-1 bake-off started** ✅
| Check | Result |
|---|---|
| Real creds in `agent/.env` picked up; all `is_*_configured` predicates true; `redacted()` clean | ✅ |
| Universe switched to **HDFCBANK / RELIANCE / TATASTEEL / ICICIBANK** (user), `security_id`s filled from Dhan scrip master (1333/2885/3499/4963), `max_positions` 3→4 | ✅ |
| Telegram: real `sendMessage` through `TelegramSink` (HTTP 200, message received) | ✅ |
| Dhan: real 15m bars for **all 4 symbols** via `DhanBarSource` after dhanhq 2.x fix (BUG-002) + `.env` cred threading (DC-003) | ✅ |
| Gemini: real `generateContent` echo test after REST rewrite (BUG-001) | ✅ |
| New launcher `src/intraday/bakeoff.py` (`--help`, config validation, bookends, wait-for-open) | ✅ |
| New live-wiring tests (`test_intraday_live_wiring.py`, 12) | ✅ |
| Full regression: engine 16 + runtime 25 + portfolio 13 + wiring 12 = **66**, strategies **12** → **78 green** | ✅ |
| **Day-1 session launched** 08:56 IST via `start_bakeoff.bat` (independent window): Telegram sink active, watchlist generated (Gemini 200) + posted (Telegram 200), waiting for 09:15 bell | ✅ |

**Verdict:** live activation accepted. Three live-path defects found and fixed on creds day
(BUG-001 Gemini factory, BUG-002 dhanhq 2.x, DC-003 creds source) — each now unit-covered and
verified against the real services. Week-1 bake-off is running; operator routine = refresh the
Dhan token in `agent/.env` each morning, double-click `start_bakeoff.bat`.

## 2026-07-15 — 3D.2 parallel bake-off + 2 new strategies ✅
| Check | Result |
|---|---|
| 4 strategies pass validators + long-only/flat-window/same-day (`test_intraday_strategies.py`, 12) | ✅ |
| Portfolio tests (`test_intraday_portfolio.py`, 13) | ✅ |
| Full regression: runtime (25) + portfolio (13) + engine (16) + strategies (12) | ✅ **66 green** |
| Isolation: each strategy its own ₹25k account; sizing uses strategy cash not config cash | ✅ |
| Per-strategy ₹10k **setup kill-switch**: retires the strategy (squares off + stops), survivors continue | ✅ |
| Cutoff disabled when 0; retired strategy books nothing further | ✅ |
| Hourly rollup emitted on IST hour change; EOD scoreboard posted + persisted (idempotent) | ✅ |
| Weekly `ScoreboardStore`: per-date replace + weekly aggregation | ✅ |
| Metric math: win%, net P&L, fees, max drawdown, ranking (halted last) | ✅ |
| E2E: all 4 **real** strategies loaded via `config.load()`, ran a synthetic day in parallel → ranked scoreboard, 6 hourly summaries, 4 persisted rows, all flat at close | ✅ |

**Verdict:** week-1 bake-off harness accepted (offline). Four diverse long-only archetypes
(breakout/mean-reversion/trend/momentum) run in parallel with isolated ₹25k accounts and a ₹10k
per-strategy permanent kill-switch; results roll up hourly + persist to a weekly scoreboard. Ready to
run for real once creds land. Net-of-cost ranking over the week decides which (if any) graduates to M2.

## 2026-07-14 — 3C verify + 3D paper runtime (placeholder creds) ✅
| Check | Result |
|---|---|
| Intraday runtime unit tests (`test_intraday_runtime.py`, 25) | ✅ |
| Regression: 3A engine (16) + 3B strategies (6) still green | ✅ |
| Config: placeholders detected; env/JSON overlay activates creds; `redacted()` leaks no secret | ✅ |
| PaperBroker: long-only, sell clamped (never shorts), MIS costs + realized P&L booked | ✅ |
| Notifier: log sink when unconfigured, Telegram sink when creds real; sink failure swallowed | ✅ |
| Clock: IST open/close/square-off + weekend guard | ✅ |
| 3C — Dhan 15m path verified; `DhanBarSource` threads numeric `security_id` (DC-002) | ✅ |
| 3C — non-ok/empty Dhan envelope + missing id handled (symbol skipped, tick not aborted) | ✅ |
| Gemini jobs: deterministic stub until key set (watchlist + EOD over fills) | ✅ |
| Runner E2E (stub engine): open on signal, exit on drop, **force square-off at 15:15** (idempotent), position cap, halt-on-error, async loop | ✅ |
| Runner E2E with the **real ORB `SignalEngine`** (dynamic load) on a synthetic breakout day | ✅ open→exit→square-off, flat at close |

**Verdict:** 3C accepted (verified; live activation needs Dhan ids + creds — DC-002). 3D paper
runtime accepted offline: full signal→paper-fill→notify→15:15-flatten loop is unit-tested and
runs the real strategy end-to-end. Everything is placeholder-driven, so dropping in real
Dhan/Gemini/Telegram values activates the live paths with no code change. Real-network sends
(Telegram) + live Dhan bars + real Gemini remain to be exercised once creds land.

## 2026-07-13 — 3B long-only strategies ✅
| Check | Result |
|---|---|
| ORB + pullback pass repo AST/interface validators | ✅ |
| Long-only (signals ∈ {0,1}), flat before 09:45 and from 15:00 | ✅ |
| Only long, same-day trades through `IndiaIntradayEngine` (0 carries) | ✅ |
| Strategy regression tests (6) | ✅ |
| Real NSE 15m data run (yfinance) | ✅ ran; both **negative net-of-cost** (need tuning) |

**Verdict:** 3B accepted mechanically. Both strategies correct + long-only + no overnight carry.
Neither is profitable yet (ORB −₹4.8k, pullback −₹8.4k / ~55d / ₹50k) — tuning is a follow-up,
not a blocker for the paper loop (3D). Full-runner run deferred to 3D (needs full app env).

## 2026-07-13 — 3A intraday engine ✅
| Check | Result |
|---|---|
| `IndiaIntradayEngine` unit tests (16) | ✅ |
| Delivery engine regression after routing change (17) | ✅ |
| Same-day round-trip executes through the real loop | ✅ |
| Long-only enforced (short rejected, config can't override) | ✅ |
| MIS cost math (STT sell-only, stamp buy-only, ₹20 cap, no DP) | ✅ |
| MIS cheaper than delivery round-trip | ✅ |
| Routing: `intraday` flag selects the right engine | ✅ |

**Verdict:** 3A accepted. 33/33 tests green. One design constraint surfaced and documented
(DC-001, flatten one bar before close). Not yet exercised: real Dhan 15m data (needs creds),
live runtime, Telegram — those are 3C/3D.
