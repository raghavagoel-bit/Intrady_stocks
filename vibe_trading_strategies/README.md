# NSE Strategy Pack for Vibe-Trading

Three ready-to-backtest strategies in the exact run-dir format Vibe-Trading's
backtest runner expects (`config.json` + `code/signal_engine.py`, class
`SignalEngine`, no-arg constructor, `generate(data_map) -> {symbol: signal Series}`).

| Strategy | Bars | Style | Fits repo's India engine? |
|---|---|---|---|
| `swing_momentum` | 1D | Trend-following, long-only delivery, holds days–weeks | ✅ Yes — native fit |
| `rsi2_mean_reversion` | 1D | Dip-buying in uptrends, long-only delivery, holds 1–7 days | ✅ Yes — native fit |
| `orb_intraday` | 15m | Opening Range Breakout, long+short MIS, EOD flatten | ⚠️ No — use its built-in simulator |

## How to run (repo runner — daily strategies)

From the Vibe-Trading checkout's `agent/` directory:

```bash
python -m backtest.runner c:\Raghava\Antigravity\vibe_trading_strategies\swing_momentum
python -m backtest.runner c:\Raghava\Antigravity\vibe_trading_strategies\rsi2_mean_reversion
```

Or through the agent chat: *"Run the backtest in <run_dir> and diagnose the results"* —
which also gets you the run card, validation suite, and benchmark comparison.

Symbols use Yahoo suffixes (`RELIANCE.NS`, `500325.BO`); the runner auto-detects
`india_equity` and applies the Indian delivery cost stack (STT 0.1% both sides,
stamp duty, GST, DP charge on sells) plus T+1 and circuit-band rules.

## Why the intraday one is different

`IndiaEquityEngine.can_execute()` hard-codes the T+1 delivery rule — a position
opened today cannot be closed the same bar-date, and there is no config knob to
disable it. Any same-day exit an intraday strategy needs is silently refused, so
intraday results from the repo engine would be meaningless.

`orb_intraday/code/signal_engine.py` therefore ships with its own standalone
simulator using correct **Dhan MIS economics** (brokerage min(₹20, 0.03%)/order,
STT 0.025% sell-side only, exchange txn, SEBI fee, 0.003% buy-side stamp, 18%
GST on charges, next-bar-open fills, configurable slippage):

```bash
pip install yfinance
python orb_intraday/run_standalone.py RELIANCE.NS HDFCBANK.NS INFY.NS
```

Yahoo limits 15m history to ~60 days. For longer intraday backtests, pull bars
through the repo's `india_broker` loader (your Dhan account gives up to 5 years
of minute data) and feed them to the same engine class.

## Cost knobs (config.json → IndiaEquityEngine)

| Key | Delivery default | Intraday (MIS) value |
|---|---|---|
| `in_brokerage` | `0.0` | `0.0003` (capped ₹20/order — cap not modelled by engine) |
| `in_stt` | `0.001` (both sides) | `0.00025` (sell only — engine applies both sides; halve it) |
| `in_stamp_duty` | `0.00015` | `0.00003` |
| `in_dp_charge` | ~`15.93` ₹/sell | `0` |
| `allow_short` | `false` | `true` |
| `slippage` | `0.001` | `0.0005`–`0.002` depending on liquidity |

## Honest-results checklist

- These configs use today's Nifty large caps → **survivorship bias**. Treat
  absolute returns as optimistic; focus on strategy behaviour (drawdown, win
  rate, cost drag) rather than the headline CAGR.
- Yahoo `.NS` daily data is adjusted for splits but occasionally misses
  corporate actions — sanity-check any suspicious jump before trusting a trade.
- Run the repo's validation suite (Monte Carlo, bootstrap, walk-forward windows)
  on anything that looks good — one backtest is one sample.
- Paper trade the survivor for 2–4 weeks on live Dhan data before any real money.
