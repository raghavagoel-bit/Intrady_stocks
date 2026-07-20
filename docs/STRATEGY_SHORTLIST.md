# Strategy Shortlist — candidates for the next TradingView port batch

Curated 2026-07-19. The goal is **breadth of archetype**, not volume: every entry
below is (a) built on an **open/public indicator formula** (portable to a `SignalEngine`
without needing a specific protected Pine source), (b) **intraday-suitable** on 15m NSE
equities within the live 120-bar lookback (no repainting, no exotic multi-timeframe
`security()` calls), and (c) **an archetype we don't already run**. Each would be a
validator-clean run-dir + its `_ls` twin, ranked by `evaluate_strategies.py` before any
live promotion.

Already covered (do NOT re-port): ORB, VWAP pullback/hold, EMA trend, single-EMA cross,
RSI momentum, RSI divergence, gap go/fade, range break, MACD cross, MACD+SMA200, MACD+RSI,
Bollinger bounce/break/+RSI/Flawless, ATR trail, rel-strength, three-thrust, Supertrend,
PMax, UT Bot, squeeze momentum, WaveTrend, QQE, Hull suite, AO+Stoch, golden cross,
Ichimoku, OI-DMA-ADX.

## Tier 1 — ✅ PORTED 2026-07-19 (§3U, offline). Run-dirs + ranked; live promotion pending user OK.

> **Ranked (`evaluate_strategies.py`, one-regime relative signal):** donchian (score −38.7, 21
> trades/sym) and keltner (−61.5, 28) are the batch standouts; cpr_pivot (−101.9), connors_rsi2
> (−149.2), psar_flip (−152.6), stoch_rsi (−165.6), supertrend_vwap (−171.7) are churny fee-bleeders
> on the down window. All 7 net-negative on the backtest (least-bad keltner −₹2,691). Offline only —
> `config/intraday.json` untouched; promote survivors (donchian/keltner) as long + `_ls` twins when ready.

| # | Candidate | Archetype / gap filled | Port notes |
|---|---|---|---|
| 1 | **CPR + daily pivots** (Central Pivot Range) | Intraday pivot levels — *the* classic NSE intraday framework | Prev-day H/L/C → pivot, BC, TC, R1–R3/S1–S3; long above TC / on S1 reclaim. Needs prior-day daily aggregation from the 15m frame (doable). High value. |
| 2 | **Parabolic SAR flip** | Trailing-stop trend (not yet covered) | Wilder PSAR (AF 0.02→0.2); long while SAR below price, flip on touch. Pure open formula. |
| 3 | **Supertrend + VWAP** combo | Popular Indian intraday confluence | Long only when Supertrend up **and** price > session VWAP; both already implemented as pieces. |
| 4 | **Donchian breakout** (Turtle) | Channel breakout (distinct from range_break's session box) | Long on close > highest-high(N); exit on lowest-low(M). Classic, trivial port. |
| 5 | **Keltner Channel breakout** | EMA±ATR channel (we have BB/KC-squeeze, not standalone KC) | Long on close > upper KC(20, 1.5·ATR); Everget's is open. |
| 6 | **Stochastic RSI cross** | Double-smoothed momentum (distinct from AO+Stoch) | StochRSI %K/%D cross out of oversold; open formula. |
| 7 | **Connors RSI(2)** | Short-lookback mean reversion (Larry Connors) | RSI(2) < 5 above a 200-MA → long; exit RSI(2) > 70. Well-known open rules. |

## Tier 2 — solid, port after Tier 1 ranks
| # | Candidate | Archetype / gap filled | Port notes |
|---|---|---|---|
| 8 | **Vortex Indicator (VI+/VI−) cross** | Directional trend cross | Open formula; VI+ crossing VI− = long. |
| 9 | **CCI reversal** | Commodity Channel Index ±100 | Long on CCI cross up through −100; open. |
| 10 | **Heikin-Ashi trend** | HA-candle colour flip trend | Derive HA candles from OHLC; long while HA green. Watch: HA smooths, don't repaint. |
| 11 | **Chandelier Exit** | ATR trail off rolling high (distinct params from UT/ATR-trail) | Everget's is open; long above the exit line. |
| 12 | **TRIX signal cross** | Triple-smoothed ROC momentum | Open; TRIX crossing its signal = long. |
| 13 | **Coral Trend** (KivancOzbilgic) | Smoothed adaptive trend | Author's script is open-source; validator-clean once ported. |
| 14 | **Chaikin Money Flow filter** | Volume-flow trend gate | CMF(20) > 0 as a long gate on an MA cross; open. |

## Tier 3 — niche / more porting risk (revisit later)
Fisher Transform (Ehlers), Chande Momentum (CMO), Elder-Ray Bull/Bear Power, OBV
divergence, Klinger. All open formulas but lower incremental archetype value or fiddlier
to make fire cleanly — only if the ranker shows the covered oscillators are worth more of.

## Not portable / excluded
- **Protected / invite-only** Pine scripts (source hidden) — can't read, can't port.
- **Multi-timeframe `security()`-heavy** or **repainting** scripts — don't translate to the
  causal per-bar `SignalEngine` contract.
- **DCA / grid bots** (e.g. 3Commas Bot) and **templates** (Ultimate Strategy Template) —
  not a directional 1/0/−1 signal.

## Process (per the funnel — see IMPLEMENTATION_PLAN §3S / evaluator)
1. Port a Tier-1 sub-batch (run-dir + `_ls` twin + validators + strategy tests).
2. `evaluate_strategies.py` for the robustness rank (breadth × folds × cost) — structural
   filter, **not** a P&L verdict (one regime).
3. Promote survivors to the live paper roster (scale-checked; each = slot + `_ls` twin).
4. The **live paper weeks** rank across real regimes — the only true "best" test.
