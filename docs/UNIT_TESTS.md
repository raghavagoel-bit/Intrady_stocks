# Unit Tests

Where tests live and what they cover. Run before every build (global rule):
```
cd vibe-trading/agent && set PYTHONPATH=. && python -m pytest tests/ -q
```

## `tests/test_india_intraday_engine.py` — IndiaIntradayEngine (16 tests)
The intraday MIS engine is the foundation of the whole system, so it's tested first and hardest.

**`TestCanExecute`** — market rules
- `test_long_allowed` — a long entry is permitted.
- `test_short_always_blocked` — short entry rejected by default (long-only remains the no-config behaviour).
- `test_short_permitted_when_allow_short_opted_in` — **3L:** `allow_short=True` in config permits a short entry; the entry (a sell) is blocked at the **lower** circuit and unaffected by the upper. *(Replaced the pre-3L `test_short_blocked_even_if_allow_short_requested`, which asserted the now-repealed "config can never re-enable shorting" rule.)*
- `test_same_bar_sell_allowed` — **the T+1 fix**: a position can be sold on its entry bar-date (delivery engine forbids this).
- `test_upper_circuit_blocks_buy` / `test_lower_circuit_blocks_sell` — circuit bands still enforced.
- `test_circuit_disabled_allows_trade_at_limit` — `price_limit=0` disables the band.

**`TestCommission`** — MIS cost stack
- `test_nonzero_cost` — sanity.
- `test_stt_on_sell_leg_only` — STT charged on the sell leg only.
- `test_stamp_on_buy_leg_only` — stamp duty on the buy leg only.
- `test_brokerage_capped_at_20` — per-order brokerage capped at ₹20 (0.03% cap binds on large orders).
- `test_no_dp_charge` — no delivery DP charge on MIS sells.
- `test_cheaper_than_delivery_roundtrip` — MIS round-trip costs less than the delivery stack.

**`TestIntradayRoundTripExecution`** — end-to-end
- `test_same_day_round_trip_is_recorded` — runs the real `_align` + `_execute_bars` loop on 2 days of 15m bars; asserts every recorded trade is long and opens+closes the **same calendar day**. Encodes the flatten-one-bar-before-close constraint.

**`TestRouting`**
- `test_intraday_flag_selects_intraday_engine` — `config["intraday"]=True` → `IndiaIntradayEngine`.
- `test_no_flag_selects_delivery_engine` — no flag → `IndiaEquityEngine` (unchanged default).

## `tests/test_india_equity_engine.py` — IndiaEquityEngine (17 tests, upstream)
Delivery engine (T+1, both-sided STT, DP charge). Re-run to confirm our shared-runner
routing change didn't regress delivery behaviour.

## `tests/test_intraday_runtime.py` — intraday paper runtime (25 tests, 3C/3D)
Covers `src/intraday/` end-to-end, fully offline (stubs + replay bars — no live Dhan/Gemini/Telegram).

**config** — `is_placeholder` detection; defaults are placeholders (all `is_*_configured` False);
env overlay activates creds + numeric knobs; `redacted()` leaks no secret; segment inferred from suffix.

**paper_broker** — buy→sell books MIS costs + realized P&L; sell **clamped** to holding (never shorts);
sell with no position → `None`; unaffordable buy → `None`.

**notifier** — `build_sink` returns `LogSink` when unconfigured / `TelegramSink` when creds real;
ENTRY/EXIT/HALT lines emitted with PAPER/side/symbol; a sink exception is swallowed (never breaks the loop).

**clock** — IST open/close/square-off boundaries + weekend guard.

**bars (3C)** — `DhanBarSource` threads numeric `security_id`/`period` (the DC-002 fix) and parses
epoch→IST OHLCV; skips a symbol with no `security_id` (never calls Dhan); handles a non-ok envelope.

**gemini_jobs** — stub caller when key unset: pre-market watchlist references the universe; EOD review over fills.

**runner** — open long on signal; exit when signal drops; **force square-off at 15:15** (idempotent);
position-cap respected; no-op outside session; halt-on-engine-error latches; async `run_session` loop
drives buy→square-off. Plus a manual smoke with the **real ORB `SignalEngine`** (dynamic load).

## `tests/test_intraday_shorts.py` — 3L short path (23 tests, new)
The paper-broker short accounting model and the runner's −1 handling, fully offline.
The **accounting identities are the spec** (see `docs/IMPLEMENTATION_PLAN.md` §3L):

**broker accounting** — short entry reserves `qty·fill + commission` from cash; a round trip
at one price with zero slippage realizes **exactly −(entry_comm + cover_comm)**; P&L positive
when price falls; equity continuous through every fill (jumps only by that fill's
commission + slippage, checked with and without slippage); equity gains as price falls while short.

**legs & slippage** — short entry fills *under* / cover fills *over* the reference
(slippage directions); short entry pays **STT** (sell leg), cover pays **stamp** (buy leg);
the reserve never exceeds the per-symbol budget.

**one direction per symbol (invariant 6)** — `cover` clamps to the holding and never flips
long; `sell` still never flips short; `buy` refuses while a short is open and `short` refuses
while a long is open; `sell` on a short / `cover` on a long → `None`;
`close_position` sells a long and covers a short (single choke point).

**runner** — −1 opens a short (hybrid); the **long-only runner coerces −1 → flat**;
a direction flip closes-then-opens in the same tick; the position cap holds across both
directions; **15:15 force-cover with and without a last price** (falls back to `avg_price` —
invariant 2, an uncovered short is a settlement failure).

## `tests/test_intraday_portfolio.py` — parallel bake-off (35 tests, 3D.2 + 3L + 3N + 3P→B4-2 + 3R)
Covers `src/intraday/portfolio.py` + `scoreboard.py`, fully offline. **BUG-007:** the shared
`_portfolio()` helper now defaults to a **tempfile-backed** `ScoreboardStore` — no test in this
file can ever write the real `~/.vibe-trading/intraday/scoreboard.json`.

**B4-2 formatter tests (10, replaced the §3P diet tests) — 64-slot pair-collapse:** the hourly
report renders **one row per long/`_ls` pair** — a `gap_fade` + `gap_fade_ls` pair collapses to a
single row carrying long ₹, ls ₹, the twin's short leg, and **Δ = ls − long**; **all pairs render**
(no idle-collapse line at 64 slots); a **halted pair is always shown** on its own `⚠ …` line with
**both legs** (✖ on the retired leg, so a surviving twin stays visible); **unpaired** `llm_local_*`
slots render on a `llm:` line and a halted one is flagged ✖; live pairs **sort movers-first** by
max(|long|,|ls|); a 400-pair input **truncates under the 3-chunk cap** with a `… +N more pairs (log)`
pointer. The EOD `format_scoreboard` collapses to **one pair row** (long vs ls + short leg), ranks
by **best leg** (halted pairs last, ✖), renders an unpaired-`llm` line, keeps the `Σ net · fees ·
trades · P of M slots profitable` topline, and honours the same 3-chunk cap. Both caps are measured
with the real `notifier.split_for_telegram`.

**3R additions (2)** — `StrategyRef.params` parses from roster JSON (default `{}`); a roster ref
with `params={"provider": "ollama", "model": ...}` reaches `build_builtin_engine` and produces a
provider/model/slot_name-configured engine.

**3N additions (4) — reconnect wait (`_await_data`, ride out a Wi-Fi/data drop ≤ 5 min):**
online canary probe → **no sleep, `now` unchanged** (happy path adds no live fetch — the probe warms
the shared cache `run_tick` reuses); an outage of a few probes is **ridden out** (backoff 5s→30s) then
the tick resumes on real data with `now` refreshed to wall-clock; a **sustained** outage stops at the
budget (total sleep ≤ `reconnect_budget_seconds`) and proceeds to the pre-3N empty-frame *hold*;
`reconnect_budget_seconds=0` **disables** the wait. Stubs: `_AlwaysEmpty`, `_FlakyBars(fail_n)`.

**3L additions (5)** — a long/hybrid twin pair runs side by side with only the hybrid
shorting; the kill-switch retiring a slot **covers its open short**; a slot raising inside
`run_tick` is squared off best-effort and **halts only that slot** (the other 41 keep
trading); metrics decompose `long_pnl` (Σ realized of sells) vs `short_pnl` (Σ realized of
covers); the scoreboard renders the pair `long`/`ls`/`sht` leg columns (B4-2; was `lng₹`/`sht₹`).

**isolation** — each strategy gets its own ₹25k `PaperBroker`; per-symbol budget sizes off the
strategy's cash, not the shared `config.initial_cash`.

**setup kill-switch** — a strategy whose cumulative loss (realized + open MTM) hits
`per_strategy_loss_cutoff` is squared off + retired (permanent); survivors keep trading; retired
strategy books nothing further; cutoff disabled when 0.

**reporting** — hourly rollup emitted on IST hour change; `finalize` persists the day + posts the EOD
scoreboard (idempotent); `ScoreboardStore` replaces same-date records + aggregates a weekly table.

**metric math** — win rate, net P&L, fees, max drawdown over the realized-equity curve; `rank` puts
halted strategies last regardless of P&L; scoreboard renders Telegram HTML.

**async** — `run_session` drives to close and finalizes.

## `tests/test_intraday_live_wiring.py` — live-activation wiring (16 tests, creds day + 3G infra)
Covers the pieces added when real creds landed (BUG-001/BUG-002/DC-003), fully offline.

**dhan sdk payload compat (BUG-002)** — `get_historical_bars` parses dhanhq **2.x parallel arrays**
(and asserts the 2.x call passes `interval` minutes + an exclusive `to_date` one day ahead) and still
parses **1.x `data.candles`** lists; a Dhan `failure` status returns an error envelope with remarks.

**cred threading (DC-003)** — `dhan_config_from_intraday` is `None` until Dhan creds are real, then
carries client id + token as a paper/readonly `DhanConfig`; `DhanBarSource` passes it through as the
`config=` kwarg (and omits the kwarg entirely when unset, preserving the saved-file fallback).

**gemini REST (BUG-001)** — `gemini_generate` posts to `models/<model>:generateContent` with the
`x-goog-api-key` header and concatenates candidate text parts; `make_llm_caller` routes a real key
to it (stub path already covered in `test_intraday_runtime.py`).

**bakeoff launcher** — `interval_seconds` token parsing (`15m`/`5m`/`1h`, rejects `1d`);
`wait_for_open` polls until the bell and bails (False) on weekends / after close.

**hourly report (B4-2 pair-collapse)** — `format_hourly_detailed` collapses the `orb` + `orb_ls`
pair to ONE row (long ₹ · ls ₹ · short leg · **Δ = ls − long**), and shows a halted `pullback` pair
on its own `⚠ …` line with both legs + ✖ + the kill-switch loss. (Was: per-fill BUY/SELL detail,
open positions, in-market/cash split — that detail now lives in the log tape.)

## `tests/test_gemini_jobs.py` — 3O bookend reliability (13 tests, new)
Covers the BUG-006 hardening in `gemini_jobs._call` + the new `local_llm.ollama_generate`,
fully offline (httpx used only to build exception/response objects):

**retry** — 2 transient failures (ReadTimeout, 429) → 3rd attempt returns, sleeps exactly
[2s, 8s]; a non-transient error (ValueError) or a non-429 4xx (401) is **not** retried (1 call);
**fallback** — exhausted retries + an attached `fallback` caller → `[local] `-prefixed text;
no fallback → the static fallback string; a *failing* fallback still returns the static string;
`make_llm_caller` attaches the config-wired Ollama fallback to the real Gemini caller and the
offline stub carries none. **EOD aggregation** — >40 fills + `metrics` → per-strategy lines
(name/trades/net/fees/best/worst symbol by realized/[RETIRED]) and no raw fill lines; a small
session keeps the raw journal. **ollama_generate** — posts `model/prompt/stream:false/think:false/
options{num_ctx:16384}` to `<url>/api/generate` (trailing slash stripped), returns `response`,
raises on non-2xx. **config** — `ollama_url`/`ollama_model` defaults + env overrides.

## `tests/test_llm_engine.py` — LLM bake-off slot (25 tests, 3F + 3L + 3R)
The LLM is a fake in every test; what's under test is the deterministic fence around it:
decision lands on the **last bar only** (0/1, long-only); the no-entry windows (<09:45, ≥15:00)
outrank a "long" reply; an API failure or unparseable reply **keeps the last decision** (never
churns, never raises → the runner can't halt the slot); ```json fences parsed; invented symbols
ignored / "short" mapped to flat; no key → permanently flat; the prompt carries tape + holdings +
the long-only/no-leverage rules; `build_builtin_engine` registry + `Portfolio` `builtin:` wiring.

**Decision tracking** — the rich reply (`{"decision","reason","stop","target"}`) fills `meta` and
journals a `decision` record per symbol per tick (reason, stated SL/target, price, changed flag);
a 1→0 flip writes an `exit_eval` record with `stop_hit`/`target_hit` graded from the bar highs/lows
since entry + entry/exit reasons + `move_pct`; legacy bare-string replies still parse;
`DecisionJournal` appends daily JSONL files; the prompt explicitly asks for reason/stop/target.

**3L hybrid twin (5)** — with `allow_short=True` a `"short"` reply maps to −1 (and the
long-only slot still coerces it to 0 — regression); the hybrid prompt offers "short" and the
HOLDING-a-short state; a short round trip's `exit_eval` grades with **directions flipped**
(stop above entry: `stop_hit = high ≥ stop`; target below: `target_hit = low ≤ target`);
`build_builtin_engine(..., allow_short=True)` arms the twin (`llm_trader_ls`).

> **Post-3M (2026-07-16):** the `llm_trader`/`llm_trader_ls` **Gemini** slots were removed from
> every live roster on cost grounds. **3R (2026-07-17) revived the slot on local Ollama** — two
> long-only roster entries (`llm_local_a`/`llm_local_b`) share `builtin:llm_trader` with per-slot
> `params`.

**3R additions (7) — local-LLM slots + BUG-005 lessons:** `provider="ollama"` routes `_caller` to
a (monkeypatched) `ollama_generate` with the per-slot model — and needs **no Gemini key** (always
constructible; also verifies the config-default model when none is given); `build_builtin_engine`
params build two engines with different models/slot names; an unknown param key raises TypeError
(caught by the preflight launch gate); the **slot name** appears in journal records (`slot` field)
and failure log lines; **3 consecutive failures → degraded**: decisions go FLAT (closing the stale
position — never the BUG-005 freeze) and the journal records carry `degraded: true`; a success
**resets** the counter (unparseable replies count as failures too); the no-arg ctor regression
stays gemini/long-only/`llm_trader`-tagged.

## Strategy coverage (`strategies/tests/test_intraday_strategies.py`)
Parametrized over all **38** run-dir strategies (the 4 originals + 3G's ten:
gap_go, gap_fade, vwap_hold, range_break, macd_cross, boll_bounce, boll_break, atr_trail,
rel_strength, three_thrust + 3H's five TradingView ports: supertrend, ut_bot, squeeze_momentum,
wavetrend, qqe_mode + 3K's oi_dma_adx + 3S's eleven TradingView ports: bb_rsi, macd_sma200,
macd_rsi, pmax, hull_suite, ao_stoch, golden_cross, flawless_victory, ema_cross, ichimoku, rsi_div
+ **3U's seven Tier-1 shortlist ports**: cpr_pivot, psar_flip, supertrend_vwap, donchian, keltner,
stoch_rsi, connors_rsi2):
repo AST/interface validators accept each; signals long-only (0/1) +
flat before 09:45 / from 15:00 (on the default trending fixture); only long, same-day trades
through `IndiaIntradayEngine`. The trades test feeds specialists their target pattern
(`TRADE_FIXTURES`: gap-up/gap-down days, sine oscillation, flat-then-surge, 3H's
`_squeeze_15m` compression→release day for squeeze_momentum, wavetrend's 4-day oscillation,
and 3S's two: **`_long_uptrend_15m`** — a long multi-day drift so the slow-MA / Ichimoku-cloud ports
(macd_sma200, golden_cross, ichimoku) warm up — and **`_divergence_15m`** — a deep low then a lower
low after a modest recovery, the textbook bullish-divergence tape for rsi_div; bb_rsi & flawless_victory
reuse `_vshape_15m`, macd_rsi the sine oscillation; and 3U's **`_dip_uptrend_15m`** — a steady multi-day
climb with a sharp 2-bar afternoon dip each session, so Connors RSI(2) sees price above its 100-SMA AND
a violent oversold pullback at once; connors_rsi2 uses it, stoch_rsi the sine oscillation) — a specialist
on the wrong day correctly produces zero signals.

**3L short mirrors (×3 more per strategy, → 6 × 38 = 228 tests)** — via the `_mirror` fixture
(the strategy's trade fixture price-reflected around 2× its first open, so the long trigger
becomes the exact short trigger; rsi_div's mirror is a textbook bearish divergence):
`SignalEngine(allow_short=True)` emits −1 on the mirrored
tape and stays flat outside the 09:45–15:00 window; hybrid execution through
`IndiaIntradayEngine(allow_short=True)` yields same-day short round trips (0 overnight);
and the **no-arg ctor never emits −1** on the mirrored tape (regression — the backtest
run-dir contract stays long-only).
**228 tests.** (Plus `strategies/tests/test_evaluate_strategies.py` — 5 tests over the
robustness ranker: fold partition/degenerate, score composite, cache-filename → ticker recovery,
one real `evaluate()` — so the `strategies/tests/` dir totals **233**.)

**Infra at 15-strategy scale** (in `test_intraday_live_wiring.py`) — `CachedBarSource` serves 15
runners from one upstream fetch, honors a smaller lookback from cache, and invalidates only when
the tick cursor moves; `split_for_telegram` chunks >4096-char reports on line boundaries losslessly.

## When to add tests
- New engine behaviour (leverage, square-off enforcement) → extend `TestCanExecute` / add a class.
- New strategy → add it to the `STRATEGIES` param list (auto-covered) + a shape test if it has novel logic.
- New runtime behaviour (mandate, kill switch, token refresh — M2) → extend `test_intraday_runtime.py`/`_portfolio.py`.
- Live send paths (real Telegram, real Gemini) → an opt-in integration test gated on creds (kept out of the default run).
