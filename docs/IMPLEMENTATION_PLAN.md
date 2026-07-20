# Vibe-Intraday — File-by-File Spec (Phase 3)

Keep in sync with the code. Scope ordered by milestone. Base repo lives at
`vibe_intraday/vibe-trading/` (working copy of HKUDS/Vibe-Trading).

Legend: ✅ done · 🚧 in progress · ❌ not started

---

## M1 — Paper intraday loop

### 3A. Intraday MIS backtest engine (P1) — the T+1 fix
Foundational, offline, no credentials. Build + test first.

| File | Action | Responsibility | Status |
|---|---|---|---|
| `vibe-trading/agent/backtest/engines/india_intraday.py` | **create** | `IndiaIntradayEngine(IndiaEquityEngine)` — long-only, same-day exits (no T+1), MIS cost stack, circuit bands kept. | ✅ |
| `vibe-trading/agent/backtest/runner.py` | **edit** | In `_create_market_engine`, India branch: return `IndiaIntradayEngine` when `config["intraday"]` is truthy, else `IndiaEquityEngine`. | ✅ |
| `vibe-trading/agent/tests/test_india_intraday_engine.py` | **create** | 16 tests: same-day exit allowed, short rejected (long-only), MIS cost math (STT sell-only, stamp buy-only, brokerage cap, no DP), circuit-band block, routing, and an end-to-end same-day round-trip. All green. | ✅ |

> **Design constraint discovered building 3A:** the engine fills on the *next bar's open*.
> A strategy that emits its flat on the **last** bar (15:15) exits at the *next* bar =
> next day's 09:15 (an overnight carry). Intraday strategies must therefore go flat one bar
> **before** the close (~15:00) so the square-off executes at 15:15 same-day. Baked into 3B
> strategy tuning and the live-runtime flatten logic.

**`IndiaIntradayEngine` design**
- `__init__`: `super().__init__(config)` (delivery defaults, leverage 1.0), then override →
  `allow_short=False`; MIS cost stack: `in_brokerage=0.0003` + `in_brokerage_cap=20.0`,
  `in_stt=0.00025` (sell only), `in_stamp_duty=0.00003` (buy only), `in_exchange_txn=0.0000297`,
  `in_sebi_fee=0.000001`, `in_gst=0.18`, no DP charge; `slippage` default `0.0005`.
- `can_execute(symbol, direction, bar)`: reject `direction == -1` (long-only); **no T+1 block**
  (same-day exit allowed); keep circuit-band checks (upper blocks buy, lower blocks sell/close).
- `calc_commission(size, price, direction, is_open)`: buy leg = stamp only; sell leg = STT only;
  both legs = capped brokerage + exchange + SEBI + 18% GST on (brokerage+exchange+SEBI).
- `round_size`, `apply_slippage`: inherited from `IndiaEquityEngine`.

**Square-off boundary:** for backtest, the 15:15 flatten is enforced by the *signal engine*
(strategy emits 0 after the cutoff; next-bar-open fill closes the long). The engine does **not**
force-close — so any intraday `SignalEngine` MUST go flat by the cutoff. The **live runtime**
(3D) enforces square-off authoritatively; backtest relies on the strategy. Documented, tested
via a strategy that flattens.

### 3B. Strategies (long-only) relocation + tuning ✅
| File | Action | Responsibility | Status |
|---|---|---|---|
| `strategies/orb_intraday/` | **created** | Long-only opening-range breakout (short side removed); `intraday:true` config; flat at 15:00. | ✅ |
| `strategies/pullback_buy/` | **created** | Second long-only setup: VWAP-reclaim dip buy in an up day; keeps trade count up. | ✅ |
| `strategies/ema_trend/` | **created** | Trend-follow: long while fast>slow EMA (per-day reset), long-only. For the 4-way bake-off. | ✅ |
| `strategies/momentum_rsi/` | **created** | Momentum-pullback: buy RSI resuming up out of a dip in an SMA up-trend, long-only. | ✅ |
| `strategies/README.md` | **created** | Documents `intraday:true` run + the flat-by-15:00 contract. | ✅ |
| `strategies/tests/test_intraday_strategies.py` | **created** | 6 tests: repo validators, long-only + flat windows, long/same-day trades through the engine. Green. | ✅ |

**Real-data check (yfinance 15m, ~55d, ₹50k, through `IndiaIntradayEngine`):** both run clean
with **0 overnight-carry trades**, but both **lose net of MIS costs** (ORB −₹4.8k; pullback
−₹8.4k, overtrading at 135 trades). Expected for untuned intraday — the machinery is correct,
the edges need work. Tuning (trend filters, trade-count throttles) is a follow-up, not a blocker
for the paper loop. Full `python -m backtest.runner` needs the complete app env (fastmcp/langchain)
— deferred to 3D setup; engine-level integration is proven here.

### 3C. Data — Dhan intraday history ✅ (verified; placeholder creds)
| File | Action | Responsibility | Status |
|---|---|---|---|
| `vibe-trading/agent/backtest/loaders/india_broker_loader.py` | **verify** | Confirmed `_PERIOD_MAP` + `dhan.sdk.get_historical_bars` handle `15m` (via `intraday_daily_candle_data`). No change needed. | ✅ |
| `vibe-trading/agent/src/intraday/bars.py` | **create** | `DhanBarSource` threads the numeric `security_id`/`exchange_segment` (the loader passes only the ticker → DC-002). `ReplayBarSource` for offline runs. | ✅ |

> **3C findings (DC-002):** (1) Dhan keys on the numeric `security_id`, not the ticker — fixed at our
> layer in `DhanBarSource`; fill ids in `config/intraday.json`. (2) Dhan intraday candles ≈ 5 trading
> days → deep 15m **backtests** stay on Yahoo; the **live paper loop** uses Dhan.

### 3D. Live paper runtime + Telegram ✅ (placeholder creds; offline-tested)
Built as a self-contained `src/intraday/` overlay (never edits the protected `src/agent`/`src/session`).
The base repo's `LiveRunner` is the LLM-autonomous path (M2); the M1 paper loop is **rule-driven** per the
locked decision, so it gets its own focused runner rather than bending the agent runner.

| File | Action | Responsibility | Status |
|---|---|---|---|
| `src/intraday/config.py` | **create** | Placeholder-first config (env + JSON), `is_*_configured` predicates, `redacted()`. | ✅ |
| `src/intraday/clock.py` | **create** | IST session windows + square-off cutoff (pure/testable). | ✅ |
| `src/intraday/paper_broker.py` | **create** | Long-only MIS paper fills reusing `IndiaIntradayEngine` cost/slippage. | ✅ |
| `src/intraday/runner.py` | **create** | Market-hours IST loop; per-interval fetch → signal → paper fill; **force flatten ≥ 15:15**; dynamic strategy load; async session loop. | ✅ |
| `src/intraday/notifier.py` | **create** | ENTRY/EXIT/SQUARE-OFF/HALT/watchlist/EOD → `TelegramSink` (one-way sendMessage) or `LogSink` (§4.5). | ✅ |
| `src/intraday/gemini_jobs.py` | **create** | Pre-market watchlist + EOD review; stub caller until `GEMINI_API_KEY` set. | ✅ |
| `agent/.env(.example)` + `agent/config/intraday*.json` | **create** | Placeholder creds + universe/knobs the operator fills later. | ✅ |
| `vibe-trading/agent/tests/test_intraday_runtime.py` | **create** | 25 offline tests (green). | ✅ |

### 3D.2 Parallel multi-strategy paper bake-off (week-1 plan) ✅
User plan: run **4 strategies in parallel** for ≥1 week of paper before finalizing, then iterate or
go to a live test. Each strategy gets its **own isolated ₹25k account** (apples-to-apples ranking)
with a **₹10k per-strategy setup kill-switch** (permanent retire on breach — squares off + stops that
strategy; survivors keep trading). Telegram feed = **hourly** rollup + EOD scoreboard (not per-trade).

| File | Action | Responsibility | Status |
|---|---|---|---|
| `src/intraday/portfolio.py` | **create** | `Portfolio` — runs the roster in parallel on one shared feed, isolated `PaperBroker` each; enforces the per-strategy kill-switch; hourly rollup + EOD scoreboard + persistence. | ✅ |
| `src/intraday/scoreboard.py` | **create** | Per-strategy metrics (net P&L, return%, trades, win%, fees, max drawdown) + ranked scoreboard + weekly `ScoreboardStore` (JSON, one record per date×strategy). | ✅ |
| `src/intraday/config.py` | **extend** | `StrategyRef` + `roster`, `per_strategy_cash` (₹25k), `per_strategy_loss_cutoff` (₹10k). | ✅ |
| `src/intraday/notifier.py` | **extend** | `summary()` for pre-formatted hourly/scoreboard HTML. | ✅ |
| `config/intraday*.json` | **extend** | 4-strategy `roster` + per-strategy cash/cutoff. | ✅ |
| `vibe-trading/agent/tests/test_intraday_portfolio.py` | **create** | 13 offline tests (green): isolation, kill-switch retire, hourly, scoreboard+persistence, metric math. | ✅ |

> **Kill-switch semantics (per user):** ₹10k is **per strategy**, and it retires the *setup* for the
> whole run — not an aggregate limit and not a daily reset. Flip to permanent-whole-run vs daily is a
> config knob if the intent changes.

### 3E Live activation + launcher (creds day, 2026-07-15) ✅
Real creds landed; universe switched (user) to HDFCBANK/RELIANCE/TATASTEEL/ICICIBANK. Three live-path
defects were found the moment real services were exercised — see BUGS.md (BUG-001, BUG-002, DC-003).

| File | Action | Responsibility | Status |
|---|---|---|---|
| `src/intraday/bakeoff.py` | **create** | Launcher CLI (`python -m src.intraday.bakeoff`): validates creds/ids/roster, wires `DhanBarSource`+`Portfolio`, Gemini bookends (watchlist → wait-for-open → session → EOD review), per-day UTF-8 file log. One invocation = one trading day. | ✅ |
| `start_bakeoff.bat` (root) | **create** | Double-click morning starter: UTF-8 console, `PYTHONPATH=.`, runs the module, window persists. | ✅ |
| `src/intraday/bars.py` | **extend** | `dhan_config_from_intraday()` + `DhanBarSource(dhan_config=…)` — thread `.env` creds into the sdk (DC-003). | ✅ |
| `src/intraday/gemini_jobs.py` | **edit** | Real caller → `gemini_generate()` direct REST (BUG-001 fix). | ✅ |
| `src/trading/connectors/dhan/sdk.py` | **edit** | dhanhq 2.x compat: `DhanContext` ctor, renamed candle methods, parallel-array payload, failure envelope (BUG-002 fix; 1.x fallback kept). | ✅ |
| `config/intraday.json` + `agent/.env` | **fill** | Real creds; 4-symbol universe with scrip-master `security_id`s; `max_positions` 4. | ✅ |
| `vibe-trading/agent/tests/test_intraday_live_wiring.py` | **create** | 12 offline tests (green) over all of the above. | ✅ |

### 3F LLM trader — experimental 5th slot (user, 2026-07-15) ✅
**Decision amendment:** Gemini gets one paper-only trading slot (the rule engines stay LLM-free);
M2 promotion of this slot would need its own explicit decision.

| File | Action | Responsibility | Status |
|---|---|---|---|
| `src/intraday/llm_engine.py` | **create** | `LLMSignalEngine` (SignalEngine contract): per-tick Gemini decision for the whole universe, strict-JSON parse, keep-last on failure, code-enforced no-entry windows, flat without a key. `build_builtin_engine` registry. | ✅ |
| `src/intraday/portfolio.py` | **extend** | Resolve roster `run_dir: "builtin:<name>"` from the overlay registry (VT-001 forbids network in run-dir strategies — the LLM slot must be trusted code). | ✅ |
| `config/intraday*.json` | **extend** | 5th roster entry `llm_trader → builtin:llm_trader`. | ✅ |
| `vibe-trading/agent/tests/test_llm_engine.py` | **create** | 8 offline tests (fenced-LLM behavior + wiring). | ✅ |

### 3G Roster expansion — 15 parallel strategies (user, 2026-07-15) ✅
| File | Action | Responsibility | Status |
|---|---|---|---|
| `strategies/{gap_go, gap_fade, vwap_hold, range_break, macd_cross, boll_bounce, boll_break, atr_trail, rel_strength, three_thrust}` | **create** | 10 new long-only 15m archetypes (run-dir contract, per-day aware, 09:45–15:00 window). `rel_strength` is universe-aware (ranks across `data_map`). | ✅ |
| `src/intraday/bars.py` | **extend** | `CachedBarSource` — one upstream fetch per symbol per tick shared across all 15 runners; invalidates on cursor move or TTL. | ✅ |
| `src/intraday/notifier.py` | **extend** | `split_for_telegram` — line-boundary chunking for >4096-char reports; `TelegramSink.send` sends chunks sequentially. | ✅ |
| `src/intraday/bakeoff.py` | **edit** | Wraps the Dhan source in `CachedBarSource`. | ✅ |
| `config/intraday*.json` | **extend** | Roster → 15. | ✅ |
| `strategies/tests/test_intraday_strategies.py` | **extend** | Parametrized over 14; pattern-matched trade fixtures (gap/oscillation/surge). 42 green. | ✅ |

### 3H TradingView ports — roster to 20 (user, 2026-07-15) ✅
| File | Action | Responsibility | Status |
|---|---|---|---|
| `strategies/{supertrend, ut_bot, squeeze_momentum, wavetrend, qqe_mode}` | **create** | 5 classic TradingView strategies ported from Pine to the run-dir contract (long-only, 09:45–15:00, per-bar sequential ratchets where Pine is sequential). Documented simplifications: wavetrend buys any wt1/wt2 cross-up below zero (validator forbids negative literal defaults); squeeze entries get a ≤5-bar grace after the release because the nested-rolling momentum goes valid late. | ✅ |
| `config/intraday*.json` | **extend** | Roster → 20 (₹25k each → ₹5L total paper). | ✅ |
| `strategies/tests/test_intraday_strategies.py` | **extend** | Parametrized over 19; new `_squeeze_15m` fixture; wavetrend on a 4-day oscillation. 57 green (**140 total**). | ✅ |

### M1 backlog (queued 2026-07-15; decision checkpoint after ~3 bake-off days ≈ 2026-07-17/18)
Per-trade **stop-loss + profit-target** (user request): per-strategy `stop_pct`/`target_pct`;
`PaperBroker` checks each bar's high/low for an intra-bar touch (not just close); the identical rule
mirrored in `IndiaIntradayEngine` so backtest ↔ paper stay comparable; EXIT notifications tagged
stop/target. Re-evaluate both features against the first 3 days of observed per-trade drawdowns
before building — don't bolt stops onto strategies the bake-off is about to disqualify anyway.

### 3L Long-vs-hybrid A/B — 21 `_ls` short-capable twins (user-approved 2026-07-15 night) ✅ BUILT (Opus, 2026-07-16) — QA (Fable) + launch gate pending
**AMENDED 2026-07-15 night (user): launch the hybrid arm 07-16** — same day as the 38-stock /
tuned-params / oi_dma_adx debut. Build + QA must therefore finish **before the 09:15 IST bell**
(build tonight = Opus session; QA = Fable session). Spec written 07-15 by Fable. This section is
the complete handoff — build exactly this, in this order.

**Launch gate (07-16 09:15 IST):** if ANY §3L QA gate is not green before the bell, start the
day on the preserved 21-slot long-only config and move the hybrid launch to 07-17. Never ship
an untested broker-accounting change into a live session — the fallback costs one day, a broker
bug in a single process costs both arms' day.

**Decision amendment (user):** shorts exist in the **paper broker only**. Long-only remains the
locked rule for live/M2; promoting any short-capable setup to live needs its own explicit decision.

#### Non-negotiable invariants (QA gates — every one needs a test)
1. **The long-only arm is untouched.** Every change is additive-with-default-off
   (`allow_short=False` everywhere). The existing 143 tests must pass **unmodified**.
2. **15:15 force-cover is a HARD invariant.** An uncovered short at square-off = settlement
   failure in the real world. `_force_flatten` and the kill-switch retire path must close
   shorts (buy-to-cover) exactly as authoritatively as they sell longs — including the
   no-price fallback to `avg_price`.
3. **Per-direction P&L decomposition is mandatory.** Hybrid net = long-leg ₹ + short-leg ₹,
   attributable per fill. Reason: a short occupying a slot can block a long the twin would
   otherwise take, so pair deltas are only interpretable with legs separated.
4. **Same tuned params.** Twins share the SAME `signal_engine.py` source via a ctor flag —
   never copied run dirs (copies drift; 3I tuning must apply to both arms by construction).
5. **1x capital.** A short reserves full notional + entry commission from cash, like a long's
   outlay. No leverage; an account can never deploy more than its cash across both directions.
6. **One direction per symbol per account.** A slot is long XOR short XOR flat in a symbol;
   direction flips close first, then (same tick, cap permitting) open the other side.

#### Signal contract extension
`SignalEngine.generate` already returns 1/-1/0 series per the repo contract; until now −1 was
never emitted. Hybrid: **1 = long, −1 = short, 0 = flat**. A long-only runner receiving −1
(defensive) coerces it to 0.

#### Broker accounting model (`PaperBroker`)
- Short entry (`short()`): fill at `apply_slippage(price, -1)` (a sell fills under); commission
  `calc_commission(qty, fill, -1, True)` → **sell leg = STT** (the existing general form in
  `IndiaIntradayEngine.calc_commission` already handles direction −1 correctly — no engine
  commission change needed). Cash −= (qty·fill + commission) — the reserve.
- Cover (`cover()`): fill at `apply_slippage(price, 1)` (a buy fills over); commission
  `calc_commission(qty, fill, -1, False)` → **buy leg = stamp duty**.
  `realized = (qty·entry_fill − entry_comm) − (qty·cover_fill + cover_comm)`; cash += reserve + realized.
- Equity with an open short = cash + reserve + unrealized, `unrealized = (entry_fill − mark)·qty`
  (gains when price falls). Store whatever fields make this clean (suggest: `Position.direction`
  ∈ {1,−1} + `entry_comm`), but these **accounting identities are the spec**:
  - round-trip at one price, zero slippage → realized = −(entry_comm + cover_comm) exactly;
  - equity is continuous through every fill (jumps only by that fill's commission + slippage);
  - `cover` clamps to the holding and never flips long; `sell` still never flips short.
- New `close_position(symbol, price, timestamp)` — sells a long / covers a short. Force-flatten
  and the portfolio kill-switch call THIS (single choke point for invariant 2).
- `Fill.side` literal grows to `"buy" | "sell" | "short" | "cover"`; `realized_pnl` set on
  `sell` and `cover`.

#### File-by-file (build in this order)

| # | File | Action | Responsibility |
|---|---|---|---|
| 1 | `vibe-trading/agent/backtest/engines/india_intraday.py` | **edit** | Honor config key `allow_short` (default **False** → behavior identical). When True, `can_execute` permits direction −1; circuit bands: short entry is a sell → blocked at **lower** circuit (mirror of the existing rules). `calc_commission` unchanged (already leg-general). |
| 2 | `src/intraday/paper_broker.py` | **extend** | `short()` / `cover()` / `close_position()` + `Position.direction` per the accounting model above. `buy` refuses while short is open; `short` refuses while long is open (invariant 6). |
| 3 | `src/intraday/runner.py` | **edit** | Ctor kwarg `allow_short=False`. `_desired_positions` → `dict[str, int]` in {−1,0,1} (coerce −1→0 when not `allow_short`). `_apply_signals`: exits first — close any open position whose direction ≠ desired (via `close_position`); entries — desired 1 → `buy`, desired −1 → `short`, same `per_symbol_budget`, same position cap over both directions. `_force_flatten` → `close_position` for every open symbol (invariant 2). `load_signal_engine(run_dir, *, allow_short=False)`: instantiate `SignalEngine(allow_short=True)` for twins; a `TypeError` must **fail fast at startup** (a misconfigured twin silently running long-only would poison the A/B). |
| 4 | `src/intraday/config.py` | **extend** | `StrategyRef.allow_short: bool = False`, parsed from roster JSON key `"allow_short"`. |
| 5 | `src/intraday/portfolio.py` | **edit** | Thread `ref.allow_short` into engine load + runner ctor. Kill-switch retire uses `close_position`. **Wrap each slot's `run_tick` in try/except → halt THAT slot, not the process** (today an unexpected broker exception kills the loop; with 42 slots in one process a hybrid bug must not end the long-only arm's day). |
| 6 | `src/intraday/llm_engine.py` | **extend** | Ctor `allow_short=False`. Hybrid prompt offers `"short"`; `_parse` maps short→−1 only when `allow_short` (long-only slot keeps coercing to 0 — current behavior). Journal `decision` gains `"short"`; `exit_eval` for short round trips grades with directions flipped (stop above entry: `stop_hit = high ≥ stop`; target below: `target_hit = low ≤ target`). Note: `llm_trader` + `llm_trader_ls` = **2 Gemini calls per tick** — acceptable, watch rate limits on day 1. |
| 7 | `strategies/*/code/signal_engine.py` (all 20) | **edit** | Add `allow_short: bool = False` ctor param; no-arg ctor stays long-only (backtest run-dir contract + validators untouched). When True, emit −1 on the strategy's mirrored condition (supertrend: down-trend; ema_trend: fast<slow; oi_dma_adx: −DI>+DI; rel_strength: short the weakest-ranked; gap_go: short a gap-down; etc.). Same tuned params, same 09:45–15:00 window, flat outside it. Where a mirror is genuinely asymmetric, pick the sensible short analogue and document it in the module docstring. **Validator gotchas: no negative literal ctor defaults (compute −1 in the body), no `@staticmethod`, no network.** |
| 8 | `config/intraday.json` (+`.example`) | **extend** | Roster 21 → **42**: for each entry add `{"name": "<name>_ls", "run_dir": <same>, "allow_short": true}`; `llm_trader_ls → builtin:llm_trader`. ₹25k each → ₹10.5L total paper. Universe/caps unchanged. **First copy the current 21-slot file to `config/intraday.long21.json`** — that's the launch-gate fallback (swap back = rename over `intraday.json`). |
| 9 | `src/intraday/scoreboard.py` | **extend** | `StrategyMetrics` gains `long_pnl` (Σ realized of `sell` fills) + `short_pnl` (Σ realized of `cover` fills); trades/wins count sells **and** covers. `to_dict` adds both (store stays backward-compatible — `weekly_table` reads with `.get`). `format_scoreboard` gains `lng₹`/`sht₹` columns (0 for long-only slots). `format_hourly_detailed`: render `short`/`cover` fills (🔻 SHORT / 🔺 COVER, realized on cover) and a per-leg line for hybrid slots; open shorts marked with direction and short-side unrealized. |
| 10 | `src/intraday/bakeoff.py` | **edit** | Startup validation logs both arms (21 long / 21 hybrid) and fails fast if any twin can't load with `allow_short=True`. |
| 11 | Tests (see below) | **create/extend** | New `tests/test_intraday_shorts.py` + targeted extensions. |

#### Test plan (Fable QA session runs these + writes docs/QA.md)
- **`tests/test_intraday_shorts.py` (new):** broker accounting identities (round-trip commission
  identity, equity continuity, clamp/no-flip, one-direction-per-symbol, reserve = notional +
  commission, slippage directions, STT-on-entry/stamp-on-cover legs); runner −1 → short entry,
  direction flip closes-then-opens same tick, cap respected across directions, long-only runner
  coerces −1; **15:15 force-cover with and without a last price** (invariant 2).
- **`test_intraday_portfolio.py`:** a twin pair runs side by side isolated; kill-switch retires
  a slot holding a short (covers it); one slot raising in `run_tick` halts only that slot;
  decomposition fields populated.
- **`test_llm_engine.py`:** hybrid parse of `"short"` (and long-only coercion unchanged); short
  `exit_eval` grading.
- **`strategies/tests/test_intraday_strategies.py`:** parametrized ×20 —
  `SignalEngine(allow_short=True)` emits −1 on a mirrored fixture, never emits −1 outside the
  trade window, and the **no-arg ctor never emits −1** (regression).
- **All existing 143 tests pass unmodified.**
- Suites per SESSION.md "How to run tests"; regenerate `docs/TEST_REPORT.md` + `docs/UNIT_TESTS.md`.

#### A/B protocol (analysis rules, so nobody "concludes" early)
- Compare `<name>` vs `<name>_ls` **only over shared trading days**; pair delta ≈ value of the
  short side (± slot-interference, which the leg decomposition exposes).
- Expect **≥2 weeks across mixed regimes** before concluding anything; a one-day down-tape win
  for shorts is regime, not edge (same lesson as the 3I backtest headline).
- Weekly: `scoreboard.json` → per-pair table (long net · hybrid net · long-leg · short-leg).

#### Launch-date history
The original design staggered the launch to 07-17 because 07-16 already debuts 3 changes
(38 stocks / tuned params / oi_dma_adx), shorts touch core broker accounting, and a single
process hosts both arms — a hybrid bug could kill the long-only arm's day. **User overrode on
2026-07-15 night: launch 07-16.** The accepted risk is mitigated by (a) the per-slot exception
isolation in file #5 — now mandatory, not optional hardening — and (b) the launch gate above.

---

### 3M Deprecate the LLM trader slots — roster 42 → 40 (user, 2026-07-16) ✅ EXECUTED 2026-07-16 (post-close) — all gates green (validate_roster 40+20, 236 tests, no builtin:llm_trader in live configs)

**Decision (user, 2026-07-16 ~10:45 IST, mid-session):** retire the experimental LLM trading
slots **`llm_trader` + `llm_trader_ls`** after today's session. **Reason: cost.** This reverts the
2026-07-15 amendment and restores the original locked decision — **Gemini = research + oversight
only, never per-bar decisions**. The morning watchlist and any oversight jobs **stay** (user
choice): ~1 call/day vs the slots' 50, so cutting it would save ≈2% of spend for 100% of the
feature. Rule engines were always LLM-free and are untouched.

**Removal depth (user choice): SOFT-DISABLE via roster only.** `llm_engine.py`, its 18 tests, and
the `builtin:` extension point are **kept**. Reversible with a one-line roster edit if Gemini
pricing changes. Rejected: hard-removing the code (`llm_trader` is the only `_BUILTINS` entry, so
deleting it would also take out the whole `builtin:` run-dir mechanism — a large diff landing
hours before a bell, irreversible for a decision made on price).

#### Evidence behind the decision (measured live, 2026-07-16 ~10:40)
- **Volume:** 25 ticks × 2 slots = **50 Gemini calls/day** (+1 watchlist). Prompt ≈ **18.6k chars
  ≈ 5–6k input tokens** (38 symbols × 8 bars each), reply ≈ **1.5k output tokens** (38 ×
  decision+reason+stop+target) → **≈265k input / 76k output per day**, ≈**1.3M / 380k per 5-day
  week**. Volume is measured; actual spend is the user's (billing not visible from here).
- **Reliability:** 7 × `httpx.ReadTimeout` in the first 6 ticks. **Not** rate-limiting — zero 429s
  (the only "429" strings in the log are COALINDIA's ₹429.29 price). The fat 38-symbol prompt is
  the likely timeout cause, i.e. the same thing driving the cost drives the unreliability.
- **BUG-005:** `llm_trader_ls` frozen on stale 09:15 `forced_flat` decisions all session (0 fills)
  because every call timed out and keep-last has no staleness bound. **3M supersedes the BUG-005
  fix** — close it `WON'T FIX (slot deprecated)` rather than building bounded keep-last, slot-tagged
  logging and staggered calls for a slot being retired.
- **Not a performance verdict:** the experiment ran **one compromised day** (twin never traded;
  `llm_trader` closed nothing before the decision). Cost is knowable on day 1; edge is not. The
  soft-disable exists precisely so this stays revisitable.

#### Effect
Roster **42 → 40** = **20 long-only + 20 `_ls` hybrid twins** — pairing stays symmetric, so the 3L
A/B is unaffected (the other 20 pairs never depended on the LLM slots). Paper capital
**₹10.5L → ₹10L** (₹25k/slot unchanged; nothing to reallocate — slots are independent).
Per-tick Gemini calls **2 → 0**, removing that latency from the tick loop (a day-1 watch item).

#### Files (execute in order, **after** the 15:30 EOD scoreboard, **before** the 07-17 09:15 bell)
| # | File | Action |
|---|---|---|
| 1 | `agent/config/intraday.json` | Drop roster entries `llm_trader` (~L222) + `llm_trader_ls` (~L310). **42 → 40.** |
| 2 | `agent/config/intraday.example.json` | Same two entries (~L52, ~L140). **42 → 40.** Keep in sync — it is the committed reference. |
| 3 | `agent/config/intraday.long21.json` | Drop `llm_trader` (~L222). **21 → 20.** Rename is **out of scope** — filename stays; it is the launch-gate fallback and a rename touches `bakeoff`/docs/muscle memory for no gain. Note in-file that it is now 20. |
| 4 | `src/intraday/llm_engine.py` | **NO CHANGE** (kept, unused). |
| 5 | `tests/test_llm_engine.py` | **NO CHANGE** — 18 tests construct the engine directly, not via roster, so they stay green and keep the code honest for a future revival. |
| 6 | `tests/test_intraday_portfolio.py` | **NO CHANGE — pre-verified 2026-07-16.** Grepped clean: no `llm`, no `42`/`21`, no `IntradayConfig.load` — the portfolio tests build fixture rosters and are not coupled to the live config. (The "+5 llm" tests from 3L live in `test_llm_engine.py`, kept per file #5.) |
| 7 | `src/intraday/bakeoff.py` | **One string edit.** L133 launch-gate message hardcodes the fallback size — `"run config/intraday.long21.json (21 long-only) instead"` → **20**. Everything else stays: `validate_roster` reads the config (no hardcoded counts — pre-verified), the `build_builtin_engine` import (L51) is retained with the extension point, and `make_llm_caller` (L148) / `premarket_watchlist` (L156) / `eod_review` (L169) **all stay** — those are the research/oversight jobs the user kept. |

#### Verification gates (all must pass before the 07-17 bell)
1. `validate_roster` preflight builds **40 slots** from `intraday.json` **and 20** from
   `intraday.long21.json`, exit 0.
2. Full suite **236 tests green** (expected to stay 236 — nothing is deleted). Any drop = a test
   was roster-coupled → fix per file #6.
3. Grep: no roster references `builtin:llm_trader` in the two live configs; `_BUILTINS` still
   resolves `llm_trader` when constructed directly (extension point intact).
4. Today's `llm_trader` scoreboard row + `llm_journal-20260716.jsonl` **preserved** as the
   experiment's record — do not clean them.

#### Docs to update in the same turn (autopilot)
`BUGS.md` (BUG-005 → Resolved/Won't-fix, cite 3M), `TASK_CHECKLIST.md`, `FLOWS.md` (drop the LLM
slot from the tick flow; flow 9 = A/B now 20 pairs), `README.md`, `CLAUDE.md` (Gemini =
research/oversight only again), `UNIT_TESTS.md`, `TEST_REPORT.md`, `QA.md`, `SESSION.md`, and the
`project_vibe_intraday` memory (revert the 07-15 LLM-slot amendment; record 3M + its cost basis).

---

### 3N Ride out short Wi-Fi / data drops before a tick — no missed bar (user, 2026-07-16) ✅ EXECUTED 2026-07-16

**Decision (user, 2026-07-16):** the system must **auto-resume without human intervention** across a
Wi-Fi / data drop lasting **up to ~5 minutes**. Host/process crashes are explicitly **out of scope**
here (user: "crashes shouldn't happen now") — that stays the separate BUG-004 state-persistence track.

**What was already true (so this is a small guard, not a rewrite):** a network drop never crashed the
process — `DhanBarSource.recent_bars` catches any fetch error → empty frame; `Portfolio.run_tick`
isolates each slot. The only exposure was a drop landing **on a tick boundary**: that 15m bar fetched
nothing, so every slot held for the whole interval — a genuinely skipped decision/exit (worse now that
shorts exist). There was **no intra-tick retry**.

**Fix — bounded reconnect wait at the top of each tick (`Portfolio._await_data`):**
- Probe **one canary symbol** (`universe[0]`) through the shared cache via the existing `_last_price`.
  - **Online:** return immediately; the probe **warms that symbol's cache entry** so `run_tick` reuses
    it — **zero extra live fetches** on the happy path.
  - **Outage:** back off **5s → 30s** (capped) and re-probe until data returns or the budget lapses,
    refreshing `now` each retry so the tick is stamped with real wall-clock time after the wait. If the
    budget lapses, the tick proceeds and **degrades to the pre-3N empty-frame hold** — only that one bar
    is lost. Once connectivity returns, all other symbols that tick succeed on first try (no 38× fan-out).
- Budget is config-tunable: **`reconnect_budget_seconds` (default 300 = 5 min, < the 900s tick)**;
  `0` disables the wait (straight to hold). Sleeps use the injected `sleep_fn` (async, `asyncio.sleep`).

**Files:** `src/intraday/config.py` (new `reconnect_budget_seconds` field + float parse);
`src/intraday/portfolio.py` (`_await_data` + `_probe`; `run_session` calls it before `run_tick`).
**Tests:** `tests/test_intraday_portfolio.py` +4 (online = no wait/now unchanged; outage-then-resume;
budget-exceeded = bounded sleeps + proceed; budget 0 = disabled) → **240 total** (was 236).

**Gates (all green 2026-07-16):** 240 tests · `validate_roster` still builds 40+20 · real
`intraday.json` loads with `reconnect_budget_seconds = 300`. **Not** covered by automation: a real live
Dhan reconnection (paper-only; validated by the deterministic outage stubs instead).

---

## Tonight's batch (2026-07-17, user-approved): §3O → §3P → §3Q → §3R ✅ EXECUTED 2026-07-17 post-close
**Model split (user): plan = Fable (this spec) → build = Opus → QA = Fable.** B3 (more
strategies) is deferred to 2026-07-18 — NOT in this batch. Combined gates at the end of §3R —
**all green** (268 tests · roster 42+20 · Ollama smoke + latency llama 14.5s / qwen 20.8s ·
scoreboard integrity · BUG-006 + BUG-007 Resolved). One evidence-driven spec deviation:
`ollama_generate` uses **`num_ctx: 16384`** (not 8192 — the 38-symbol prompt measures 9.6k–13.7k
tokens and 8192 truncated it to a 1-token reply, `done_reason=length`) plus **`think: false`**
(qwen3 is a thinking model: 47s → 17s; llama3.1 ignores the flag). Details: `docs/QA.md` 07-17.

**Pre-step (BUG-007, do FIRST): ✅ DONE** `tests/test_intraday_portfolio.py::_portfolio()` defaults
`store=None` → the real `~/.vibe-trading/intraday/scoreboard.json`; `test_run_session_finalizes`
therefore pollutes the production weekly file on every suite run (found + cleaned 07-17, see
BUGS.md). Fix: `_portfolio()` builds a `tempfile`-backed `ScoreboardStore` when none is given
(never the real path from tests). Verify: run the full suite, then confirm the real
scoreboard.json still contains only the 40 rows dated 2026-07-17. BUG-007 → Resolved.

### 3O — B1: Gemini EOD feedback — reliability + usefulness (+ BUG-006 fix) ✅ EXECUTED 2026-07-17
**Context:** the 07-17 morning watchlist died on a Gemini **429 on the first call of the day**
(BUG-006 — daily free-tier quota exhausted by the 07-16 llm slots; quota resets ~12:30 IST =
midnight Pacific, so an 08:37 IST call sits in *yesterday's* Pacific quota day). `_call` in
`gemini_jobs.py` has **no retry**, and a quota-429 wouldn't be fixed by one anyway. The EOD
review also feeds `combined_fills` **raw** — with 40 slots that's hundreds of fill lines in one
prompt (cost, timeout risk, and diluted feedback).

| # | File | Action |
|---|---|---|
| 1 | `src/intraday/local_llm.py` (**new**, ~40 lines) | `ollama_generate(url, model, prompt, *, timeout=120.0) -> str`: httpx POST `{url}/api/generate`, json `{model, prompt, stream: false, options: {temperature: 0.2, num_ctx: 8192}}`, return `resp.json()["response"]`. Raise on HTTP/shape errors (callers convert to fallbacks, same contract as `gemini_generate`). Lives in the trusted overlay (VT-001: localhost is still network — never in `strategies/`). |
| 2 | `src/intraday/config.py` | New fields + parse + env map: `ollama_url` (default `"http://localhost:11434"`), `ollama_model` (default `"llama3.1:8b"`). Env: `VIBE_INTRADAY_OLLAMA_URL`, `VIBE_INTRADAY_OLLAMA_MODEL`. |
| 3 | `src/intraday/gemini_jobs.py::_call` | Bounded retry: up to 3 attempts, sleeps 2s/8s, retry **only** transient failures (timeout / 5xx / 429). On final failure, if an Ollama fallback caller is available (new optional `fallback` arg, wired from config in `make_llm_caller` → returns a `(primary, fallback)`-aware caller), run the prompt through **local Ollama** before returning the static fallback string. Message prefix `[local]` on fallback output so the feed shows which brain wrote it. |
| 4 | `src/intraday/gemini_jobs.py::eod_review` | Stop dumping raw fills when large: if `len(fills) > 40`, aggregate to **per-strategy lines** (name, trades, net ₹, fees ₹, best/worst symbol by realized) — the notifier already has the data via metrics, so accept an optional `metrics` param from `bakeoff.run_day` (it has them) and prefer it. Prompt asks for: 2–3 line market read, top-2 / bottom-2 strategies with a *why*, one cost-drag observation, one thing to change tomorrow. Plain text rule stays. |
| 5 | `docs/BUGS.md` | BUG-006 already logged (Open) — move to Resolved when this lands, fix = retry + local fallback; note the quota-reset timing as the root cause and that the §3M call-volume cut (50/day → 2/day) is the structural fix. |

**Tests (extend `tests/test_intraday_live_wiring.py` or a new `tests/test_gemini_jobs.py`):**
retry-then-success (2 failures → 3rd attempt returns), non-transient error → no retry, exhausted
retries + fallback caller → `[local]`-prefixed text, exhausted + no fallback → static fallback
string, `eod_review` aggregates when fills > 40 (prompt contains per-strategy lines, not raw
fills), `ollama_generate` parses a stubbed response + raises on non-200 (no live network in tests).

### 3P — B4: hourly + EOD report optimization ✅ EXECUTED 2026-07-17
**Context:** 40 slots × per-fill detail = huge hourly messages (chunked into several Telegram
posts). Detail must survive in the **log tape** (it already does — per-trade lines are logged);
the *feed* should lead with signal.

| # | File | Action |
|---|---|---|
| 1 | `src/intraday/scoreboard.py::format_hourly_detailed` | (a) **Collapse quiet slots**: a slot with no fills this hour, no open positions, and running net ₹0 renders no section; count them into one trailing line `— N slots idle (flat, ₹0)`. (b) **Sort sections**: slots with fills this hour first (by |net| desc), then position-holders, then nonzero-but-quiet. (c) **Cap fills** rendered per slot per hour at 8, then `… +N more (log)`. (d) Per-leg `⇅ legs` line only when a leg is nonzero. (e) Keep header math (trades/charges/net) unchanged — B2 verified it. |
| 2 | `src/intraday/scoreboard.py::format_scoreboard` | Add one **topline** above the table: `Σ net ₹X · fees ₹Y · trades N · P profitable of M` . Rows unchanged (the ranked table is the product). |
| 3 | `src/intraday/portfolio.py::_maybe_hourly` | No structural change — it already passes everything needed. Only if (1) needs a flag (e.g. slot running-net) confirm it's in the section dict (it is: `realized`). |

**Tests (`tests/test_intraday_portfolio.py` formatter tests):** quiet-slot collapse (idle slots →
one trailing line, active slots still full), sort order (fills-first by |net|), fill cap at 8,
legs line suppressed when both zero, scoreboard topline totals match the summed metrics. Keep all
existing formatter assertions green (update only where the format deliberately changed).

### 3Q — B2: trade-cost model — verification verdict + doc ✅ EXECUTED 2026-07-17 (doc-only, no code)
**Finding (verified 2026-07-17, Fable):** Dhan's published equity-intraday tariff is
**`min(₹20, 0.03%)` per executed order** — exactly `india_intraday.py:120`
(`min(in_brokerage_cap=20, notional × in_brokerage=0.0003)`). The "₹20 per order" the user heard
is the **cap**, not a flat fee; at our ~₹6k positions the 0.03% (≈₹1.80/leg) binds — the cap only
bites above ₹66,667 notional. The ~0.106% round-trip the reports show is the **all-in stack**
(brokerage×2 + STT 0.025% sell + stamp 0.003% buy + exchange 0.00297%×2 + SEBI + 18% GST), which
was hand-verified against `calc_commission` to 4 decimals on 07-17 (session log). **No code
change.** Config knobs (`in_*` keys) already exist for any future broker switch.

| # | File | Action |
|---|---|---|
| 1 | `README.md` (or `docs/FLOWS.md` appendix) | New short section **"Cost model"**: the component table with rates, the ADANIENT worked example (BUY fee ₹1.33 / SELL fee ₹2.02 breakdown), the min(₹20, 0.03%) vs flat-₹20 clarification, and the sizing note (fees ≈ flat 0.106% of notional below the cap → fee-% falls only as order size approaches ₹66.7k). |
| 2 | `docs/BUGS.md` | Nothing — this was a question, not a bug. Do NOT log a bug entry. |

### 3R — B5: local-LLM trader slots on Ollama (revive §3M's slot, zero-cost) ✅ EXECUTED 2026-07-17
**Context:** user wants the LLM trading experiment back, on **local models** ("a couple of
candidates to try" — NOT an ensemble). §3M kept `llm_engine.py`, its 18 tests and the `builtin:`
hook precisely for this. Hardware verified 07-17: Ollama 0.30.6, RTX 5070 12 GB (10.7 free);
`llama3.1:8b` already pulled. **Two candidate slots run side-by-side** (bake-off ethos: let the
scoreboard pick the model), long-only first — no `_ls` twins for these (keep scope tight; a
hybrid local slot is a later decision). Zero marginal cost + no 429/quota + no WAN timeouts kills
§3M's entire cost rationale; §3M's *performance* question stays open and this answers it properly.

| # | File | Action |
|---|---|---|
| 1 | Operator step (Opus runs it) | `ollama pull qwen3:8b` (candidate 2; ~5 GB, fits beside llama3.1:8b in 12 GB — Ollama loads one at a time anyway). Verify both respond: one `ollama_generate` smoke call each. |
| 2 | `src/intraday/config.py::StrategyRef` | Add optional `params: dict` (default empty, parsed from roster JSON) — threaded so different roster slots can carry per-slot engine kwargs. |
| 3 | `src/intraday/portfolio.py` | Pass `ref.params` into `build_builtin_engine(name, config, allow_short=…, **ref.params)`. Run-dir slots ignore params (assert empty or log-warn). |
| 4 | `src/intraday/llm_engine.py` | (a) `build_builtin_engine` + `LLMSignalEngine.__init__` accept `provider: str = "gemini"` and `model: str \| None = None`. (b) `_caller()` becomes provider-aware: `"ollama"` → `lambda p: ollama_generate(cfg.ollama_url, model or cfg.ollama_model, p)`; `"gemini"` → existing path. Ollama needs no key: the configured-check for ollama is "always constructible", fail-soft per tick like today. (c) **BUG-005 lessons, mandatory:** journal records + every log line carry the **slot name** (thread a `slot_name` from the roster ref; kill the hardcoded `"llm_trader:"` prefix); **bounded keep-last** — after 3 consecutive call failures the engine goes **degraded** (decisions → flat, `degraded: true` in journal) instead of freezing on stale state; a success resets the counter. Never let a `forced_flat` window become the frozen baseline (that IS the flat default now — degraded = flat, not = last). |
| 5 | `config/intraday.json` (+`.example`) | Two new roster entries: `{"name": "llm_local_a", "run_dir": "builtin:llm_trader", "params": {"provider": "ollama", "model": "llama3.1:8b"}}` and `llm_local_b` with `"model": "qwen3:8b"`. Roster **40 → 42**; paper ₹10L → ₹10.5L. `intraday.long21.json` untouched (fallback stays 20 rule slots). |
| 6 | `src/intraday/bakeoff.py` | Nothing structural — `validate_roster` builds the new slots via the existing builtin path. Check the L133 fallback string still says 20 (it does; don't touch). |

**Tests:** `test_llm_engine.py` +≈6: provider="ollama" caller hits a stubbed `ollama_generate`
(monkeypatch — no live server in tests); params threading builds two engines with different
models; slot name appears in journal record + failure log line; degraded after 3 consecutive
failures → flat decisions + `degraded` flag; success resets the failure counter; long-only default
regression (no-arg, no-params ctor unchanged). `test_intraday_portfolio.py` +1: roster ref with
`params` reaches `build_builtin_engine`. Config tests: `StrategyRef.params` parse + default.

**Latency gate (QA, live Ollama):** one full 38-symbol prompt through each candidate must
complete in **< 60s** (expect < 15s on the 5070); if a model misses, drop it from the roster
(one slot is acceptable) — do NOT raise the tick budget for it. Log measured times in QA.md.

#### Combined gates for the batch (all must pass before the 07-18 bell)
1. Full suites green — expected **240 + new** (≈ 240 → ~258; any existing-test failure must be a
   deliberate, spec-cited format change in §3P).
2. `validate_roster` builds **42** from `intraday.json` and **20** from `intraday.long21.json`.
3. Live smoke: `ollama_generate` returns text from both candidates; one end-to-end
   `LLMSignalEngine._decide` against replay bars with the real local model (logged, not asserted).
4. Latency gate above; BUG-006 → Resolved; docs autopilot (QA.md session, TEST_REPORT, UNIT_TESTS,
   FLOWS flow-7 note + flow-8 EOD fallback, README cost-model + roster 42, TASK_CHECKLIST B1/B2/B4/B5
   ✅, SESSION.md, project memory).

---

### 3S — B3: TradingView ports batch 2 (11 strategies) ✅ EXECUTED 2026-07-18 (offline only)
**Context:** user shared the TradingView "Strategies" shortlist screenshot: "copy the following
strategies for vibe intraday and backtest them." Portable set = 11 (of the 14 shown): skipped
`supertrend` (already ported in 3H), **3Commas Bot** (a DCA averaging bot — no directional 1/0/−1
signal), **Ultimate Strategy Template** (an empty template shell). **Offline scope only** — user
answered "backtest first, then decide" on live-roster promotion, so `config/intraday.json` was NOT
touched (no `_ls` twins added, roster stays 42).

Each is a validator-clean run-dir (`config.json` + `code/signal_engine.py`), long-only no-arg ctor +
mirrored `allow_short` branch, flat outside 09:45–15:00:
`bb_rsi` (BB+RSI reversion) · `macd_sma200` (MACD gated by a slow trend MA) · `macd_rsi` (MACD bull
cross + recent RSI dip, per-day reset) · `pmax` (ATR trail on an EMA) · `hull_suite` (HMA slope) ·
`ao_stoch` (AO gate + Stochastic cross) · `golden_cross` (fast>slow SMA regime) · `flawless_victory`
(BB+RSI+MFI reclaim) · `ema_cross` (single-EMA regime) · `ichimoku` (cloud + Tenkan/Kijun + Hull) ·
`rsi_div` (bullish regular divergence on causal pivots).

Registered in `backtest_all.py` (STRATEGIES/SHORT_NAMES/TUNE_GRIDS) + `tests/test_intraday_strategies.py`
(×31, +2 fixtures). **186 strategy + 148 agent = 334 tests green.** Backtest: all 11 net-negative on
the down-regime cached window (best `macd_rsi`, worst `ao_stoch` — the documented churn/fee-drag
pattern); `docs/BACKTEST_REPORT.md` (full 31) + `docs/BACKTEST_REPORT_TVPORTS.md` (these 11).

**Documented port adaptations** (in each module docstring): SMA200→100 & golden 50/200→25/100 (a
literal 200-bar 15m SMA can't be valid within the 120-bar live lookback); Flawless Victory = lower-band
reclaim with RSI floor 42→30 (a 2σ down-breach always coincides with a washed-out RSI on synthetic
tapes; real fat tails differ); ao_stoch's Stochastic gate = "not overbought" (an AO>0 leg keeps the
Stochastic high, so a "<50" gate is self-defeating on trends).

**PROMOTED to live (user, 2026-07-19):** all 11 added as long + `_ls` twins → **roster 42 → 64**
(33 rule/llm long + 31 `_ls`; ₹16L paper), live from Monday 2026-07-20. `config/intraday.json`
(+`.example`); fallback `intraday.long21.json` unchanged. Gates: `validate_roster` builds **64 + 20**
(exit 0, logs "33 long-only + 31 hybrid = 64"); **scale check** — one tick = 62 rule slots × 38
symbols in ~1.1 s (≈800× under the 15-min budget); EOD scoreboard 4.5k chars → 2 Telegram chunks;
334 tests green. **Follow-up (B4-2, 2026-07-20):** rework the Telegram report for 64 slots — §3P's
diet was sized for ~42; the hourly detailed + per-leg sections balloon and the EOD scoreboard already
needs 2 chunks. Ideas: top-N movers, collapse each long/`_ls` pair to one line, hard chunk cap.

---

### 3T — Robustness evaluator + strategy shortlist (user, 2026-07-19) ✅ EVALUATOR DONE; batch PENDING
**Context:** user asked "can we get all TradingView strategies and evaluate the best?" Answer (honest):
"all" is infeasible (protected/invite-only sources are unreadable, no bulk API, each needs a hand-port),
and a single-window backtest can't crown a winner. So the deliverable is a **funnel**, not a dump.
- ✅ **Evaluator** `strategies/evaluate_strategies.py` — ranks by **breadth** (49 cached symbols, one
  at a time → no 1/N capital-split confound) × **stability** (4 walk-forward folds) × **cost
  robustness** (net at 2× slippage). Composite `score` = 100·pos_rate + net_median/50 −
  churn_penalty(>4 trades/sym); primary key = pos_rate (% of symbol×fold cells net-positive). Report
  → `docs/STRATEGY_EVALUATION.md`; +5 tests. **Data-honest:** ~57-day 15m window = ONE regime, so
  the *relative* rank is the signal and the live paper weeks remain the true arbiter.
- ✅ **Shortlist** `docs/STRATEGY_SHORTLIST.md` — 14 vetted next-batch candidates (open-source formula,
  intraday-suitable, new archetype). Tier-1: CPR/pivots, Parabolic SAR, Supertrend+VWAP, Donchian
  breakout, Keltner breakout, StochRSI, Connors-RSI2.
- **Finding to act on:** the fee-bleeders **ema_cross / hull_suite / ao_stoch / macd_cross** (75–88
  trades/symbol) rank worst on robustness — candidates to drop or let the kill-switch retire live.
  **Decision (user, 2026-07-19): KEEP them — let the ₹10k kill-switch retire them live** (dropping
  roster slots on one-regime offline output is the recency-bias trap the user rejects). No roster edit.
- ✅ **Tier-1 sub-batch PORTED (user go-ahead 2026-07-19) → §3U below.**

### 3U — B7: Tier-1 shortlist port batch (7 strategies) ✅ EXECUTED 2026-07-19 (offline only)
Ported the 7 Tier-1 candidates from `docs/STRATEGY_SHORTLIST.md` as validator-clean run-dirs
(`config.json` + `code/signal_engine.py`), each long-only by default with a mirrored `allow_short`
twin and a **new archetype** not already covered. **Scope = offline only** (same as §3S's first pass):
ported + backtested + ranked; **`config/intraday.json` / the 64-slot live roster NOT touched** —
promotion is a separate user decision.
- ✅ `cpr_pivot` (Central Pivot Range; prior-day H/L/C → pivot/BC/TC, long above the top central line),
  `psar_flip` (Wilder Parabolic SAR trailing-stop flip), `supertrend_vwap` (Supertrend∧VWAP confluence),
  `donchian` (Turtle rolling-channel breakout), `keltner` (standalone EMA±ATR channel break),
  `stoch_rsi` (double-smoothed StochRSI %K/%D cross), `connors_rsi2` (RSI(2) reversion in an up-trend;
  200-SMA filter adapted to 100 for the 15m/120-bar lookback).
- ✅ Registered: `backtest_all.py` (STRATEGIES + SHORT_NAMES + TUNE_GRIDS), `evaluate_strategies.py`
  (auto via `bt.STRATEGIES`), `tests/test_intraday_strategies.py` (×38 + `_dip_uptrend_15m` fixture).
  **228 strategy tests green** (was 186), **381 total**. **BUG-008 found + fixed** (Connors RSI(2)
  degenerate zero-loss → 100, was collapsing to 50 and killing the mirrored short).
- ✅ Backtest (cached 4-stock): all 7 net-negative on the down regime (`docs/BACKTEST_REPORT_TIER1.md`
  + full 38 regenerated). Robustness rank (`docs/STRATEGY_EVALUATION.md`): **donchian** (−38.7, pos 15%)
  and **keltner** (−61.5, 12%) are the batch standouts (mid-pack); the other 5 are churny fee-bleeders
  on this one regime.
- 📨 **Pending user decision:** promote survivors (donchian / keltner most defensible) to the live paper
  roster as long + `_ls` twins → the live weeks decide. Tier-2 batch still queued.

---

## M2 — Live orders (gated; real ₹25–50k) — LATER
| File | Action | Responsibility | Status |
|---|---|---|---|
| `vibe-trading/agent/src/trading/connectors/dhan/` | **edit** | Add explicit operator-declared `dhan-live-trade` profile + lift paper cap behind that boundary only. | ❌ |
| mandate config | **create** | 2–3 symbol universe, per-order size cap, daily-loss cap, max positions. | ❌ |
| token-refresh job | **create** | Refresh Dhan 24h token before 09:15 IST. | ❌ |
| SEBI checklist | **doc** | Static IP whitelisted with Dhan, generic algo ID, < 10 OPS. | ❌ |

---

## Testing (run before every build — global rule)
- `python -m pytest agent/tests/test_india_intraday_engine.py -q` from `vibe-trading/`.
- Log coverage in `docs/UNIT_TESTS.md`, results in `docs/TEST_REPORT.md` (regenerate before builds).
- QA sessions in `docs/QA.md` (newest first). Bugs in `docs/BUGS.md`.

## This turn's increment
Added the **week-1 parallel bake-off**: 2 more long-only strategies (`ema_trend`, `momentum_rsi` → 4
diverse archetypes), the `Portfolio` orchestration (isolated ₹25k accounts, ₹10k per-strategy setup
kill-switch, hourly rollup + EOD scoreboard + weekly persistence), and config for the roster. 38 new
offline tests (13 portfolio + 25 runtime) + 12 strategy + 16 engine = **66 green**; 4-strategy E2E
smoke ran and produced a ranked scoreboard. Prior increment (this session): 3C verified + 3D paper
runtime built. Next: drop in real Dhan/Gemini/Telegram creds → run the 4-way bake-off for ≥1 week →
rank on net-of-cost → iterate or promote a survivor to M2 (gated live).
