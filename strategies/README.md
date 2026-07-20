# Intraday Strategies (long-only)

Runner-compatible strategies for **Vibe-Intraday**. Each folder is a backtest
run-dir: `config.json` + `code/signal_engine.py` (class `SignalEngine`, no-arg
constructor, `generate(data_map) -> {symbol: signal Series}` of **1 / 0** — long
or flat, never -1).

| Strategy | Archetype | Idea | Signals/day |
|---|---|---|---|
| `orb_intraday` | breakout | Opening-range breakout, upside only | ~1 per symbol |
| `pullback_buy` | mean-reversion | Buy the VWAP reclaim in an up day | several per symbol |
| `ema_trend` | trend-follow | Long while fast EMA > slow EMA (per-day reset) | several per symbol |
| `momentum_rsi` | momentum-pullback | Buy RSI resuming up out of a dip, in an SMA up-trend | selective |
| `gap_go` | gap continuation | Day opens ≥0.3% up → long while it holds above day open | gap days only |
| `gap_fade` | gap reversal | Day opens ≥0.3% down → buy the recovery above bar-1 high | gap days only |
| `vwap_hold` | trend-follow | Long above day-VWAP (hysteresis band vs churn) | several per symbol |
| `range_break` | breakout | 09:15–11:00 range high broken after 11:00 | ≤1 per symbol |
| `macd_cross` | momentum | Intraday MACD(8,17,9) above signal, per-day reset | several per symbol |
| `boll_bounce` | mean-reversion | Lower-band snap-back, take profit at the mean | selective |
| `boll_break` | vol expansion | Upper-band close on ≥1.2× volume, exit under the mean | selective |
| `atr_trail` | trend-follow | New-high entry, 1.5×ATR trailing exit | selective |
| `rel_strength` | cross-sectional | Hold ONLY the strongest symbol vs day open | rotates |
| `three_thrust` | momentum | 3 consecutive higher closes, out on first down close | frequent |

**Fourteen diverse archetypes on purpose** (plus the `builtin:llm_trader` Gemini slot in the
overlay = 15 in the bake-off) so the parallel paper run learns which *style* of edge (if any)
survives net-of-cost at ₹25k. Each runs in its own isolated ₹25k paper account with a ₹10k
per-strategy setup kill-switch; see `src/intraday/portfolio.py` and the plan's 3D/3G.
Specialists (gap/reversion/expansion) sit flat on days without their pattern — that's design.

## Long-only + the 15:00 flatten contract
- Every signal is 1 (long) or 0 (flat). No shorting anywhere.
- Both engines go flat at **15:00**, not 15:15. The backtest fills on the *next*
  bar's open, so a flat emitted on the 15:15 close would execute at next day's
  09:15 — an overnight carry. Flattening at 15:00 makes the square-off land at
  15:15 the same day. (See `docs/BUGS.md` DC-001.) The live runtime enforces the
  square-off independently as a backstop.

## Running a backtest
From `vibe-trading/agent/` (`config.json` sets `"intraday": true`, which routes to
`IndiaIntradayEngine` — long-only, same-day exits, MIS cost stack):

```bash
set PYTHONPATH=.
python -m backtest.runner ../../strategies/orb_intraday
python -m backtest.runner ../../strategies/pullback_buy
python -m backtest.runner ../../strategies/ema_trend
python -m backtest.runner ../../strategies/momentum_rsi
```

`source: yahoo` gives ~60 days of 15m history (Yahoo's cap). For deeper intraday
history, switch `source` to `india_broker` once Dhan credentials are configured —
Dhan serves up to 5 years of minute data (Milestone 3C).

## Cost model
`intraday: true` applies the MIS stack automatically (STT 0.025% sell-only,
stamp 0.003% buy-only, brokerage capped ₹20/order, 18% GST, no DP charge). Override
any rate in `config.json` (`in_stt`, `in_brokerage`, `in_brokerage_cap`, ...).

## Honest-results note
`initial_cash` is ₹50k to mirror the real trial. At that size, per-trade costs are a
large share of a thin intraday edge — that's the point of paper-testing before live.
Judge on **net-of-cost** P&L and drawdown, and run the repo's validation suite
(Monte Carlo / walk-forward) before trusting anything.
