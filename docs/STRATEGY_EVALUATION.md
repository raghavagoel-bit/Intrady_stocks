# Strategy Evaluation (robustness ranker — the live paper week is still the arbiter)

Generated 2026-07-19 16:47 IST by `strategies/evaluate_strategies.py`. **49 cached symbols**, each funded at ₹25,000 and run one at a time (no 1/N capital-split confound), full MIS cost stack, fills next-bar-open. Window ≈ **57 trading days**, **4 walk-forward folds**.

> ⚠️ One ~2-month window = **one regime** (Yahoo's 15m cap). Absolute nets are mostly negative here; the **relative** ranking — which strategies stay positive across more symbols, folds, and at higher cost — is the signal. Regime diversity only comes from the live paper weeks.

**Columns:** *Pos-rate* = % of (symbol × fold) cells net-positive (primary rank key) · *Sym+* = % of symbols net-positive full-window · *Net med/tot* = median / total net ₹ across symbols · *Trades/sym* = churn (fee-drag) flag · *2×-cost keep* = net at 2× slippage ÷ base net (a value near 1 with a positive base = cost-robust; a loss that deepens shows keep > 1).

**Score** = 100·pos_rate + net_median/50 − churn_penalty(>4 trades/sym). Transparent, consistency-led, churn-penalised — not a P&L forecast.

| # | Strategy | Score | Pos-rate | Sym+ | Net med ₹ | Net tot ₹ | Trades/sym | MaxDD % | 2×-cost keep |
|---|---|---|---|---|---|---|---|---|---|
| 1 | squeeze_momentum | +10.4 | 20% | 16% | -351 | -17,878 | 6 | 8.0 | 1.38 |
| 2 | gap_fade | +9.0 | 28% | 24% | -476 | -28,382 | 10 | 8.8 | 1.40 |
| 3 | gap_go | +1.6 | 28% | 20% | -618 | -31,691 | 13 | 11.0 | 1.48 |
| 4 | macd_rsi | -10.2 | 18% | 8% | -703 | -34,046 | 13 | 7.1 | 1.43 |
| 5 | boll_break | -12.0 | 22% | 8% | -812 | -39,900 | 16 | 9.7 | 1.44 |
| 6 | bb_rsi | -15.6 | 26% | 8% | -892 | -51,134 | 20 | 14.9 | 1.43 |
| 7 | flawless_victory | -24.3 | 13% | 2% | -1,071 | -51,458 | 15 | 8.5 | 1.32 |
| 8 | orb_intraday | -24.9 | 21% | 4% | -1,208 | -58,946 | 18 | 12.8 | 1.34 |
| 9 | rsi_div | -37.5 | 26% | 6% | -1,576 | -71,306 | 25 | 16.2 | 1.38 |
| 10 | donchian | -38.7 | 15% | 2% | -1,418 | -70,635 | 21 | 12.4 | 1.32 |
| 11 | range_break | -54.7 | 10% | 2% | -1,458 | -72,136 | 28 | 11.2 | 1.41 |
| 12 | three_thrust | -60.5 | 7% | 0% | -1,541 | -68,788 | 28 | 11.0 | 1.44 |
| 13 | keltner | -61.5 | 12% | 8% | -1,880 | -84,342 | 28 | 16.1 | 1.36 |
| 14 | boll_bounce | -62.3 | 13% | 2% | -1,739 | -84,952 | 31 | 16.6 | 1.39 |
| 15 | golden_cross | -64.5 | 17% | 0% | -1,926 | -98,927 | 33 | 17.2 | 1.35 |
| 16 | oi_dma_adx | -71.9 | 14% | 2% | -2,003 | -103,509 | 34 | 17.9 | 1.35 |
| 17 | pmax | -78.1 | 14% | 2% | -2,276 | -116,656 | 35 | 18.4 | 1.30 |
| 18 | macd_sma200 ⚠churn | -86.5 | 15% | 0% | -2,218 | -110,897 | 42 | 19.0 | 1.38 |
| 19 | ichimoku ⚠churn | -91.5 | 8% | 0% | -2,176 | -110,788 | 41 | 16.6 | 1.38 |
| 20 | momentum_rsi ⚠churn | -94.5 | 7% | 0% | -2,244 | -104,410 | 41 | 14.7 | 1.41 |
| 21 | qqe_mode ⚠churn | -99.4 | 11% | 0% | -2,546 | -120,734 | 43 | 17.2 | 1.36 |
| 22 | cpr_pivot ⚠churn | -101.9 | 11% | 2% | -2,653 | -135,193 | 44 | 22.8 | 1.33 |
| 23 | supertrend ⚠churn | -115.1 | 11% | 2% | -2,925 | -145,782 | 49 | 24.3 | 1.33 |
| 24 | ut_bot ⚠churn | -117.6 | 12% | 2% | -2,938 | -147,964 | 51 | 20.2 | 1.34 |
| 25 | wavetrend ⚠churn | -121.2 | 7% | 0% | -2,706 | -129,359 | 54 | 21.1 | 1.42 |
| 26 | atr_trail ⚠churn | -124.3 | 6% | 0% | -3,002 | -145,360 | 51 | 22.7 | 1.34 |
| 27 | ema_trend ⚠churn | -134.7 | 9% | 0% | -3,199 | -161,379 | 57 | 24.9 | 1.34 |
| 28 | rel_strength ⚠churn | -147.0 | 12% | 0% | -3,613 | -170,065 | 62 | 25.3 | 1.35 |
| 29 | connors_rsi2 ⚠churn | -149.2 | 2% | 0% | -3,010 | -153,542 | 64 | 19.3 | 1.41 |
| 30 | psar_flip ⚠churn | -152.6 | 4% | 0% | -3,410 | -171,427 | 63 | 23.4 | 1.35 |
| 31 | pullback_buy ⚠churn | -156.8 | 6% | 0% | -3,517 | -181,082 | 66 | 24.4 | 1.34 |
| 32 | vwap_hold ⚠churn | -161.9 | 7% | 0% | -3,568 | -172,660 | 69 | 23.6 | 1.38 |
| 33 | stoch_rsi ⚠churn | -165.6 | 4% | 0% | -3,451 | -165,432 | 71 | 22.4 | 1.41 |
| 34 | supertrend_vwap ⚠churn | -171.7 | 5% | 0% | -3,713 | -178,564 | 72 | 24.5 | 1.38 |
| 35 | ao_stoch ⚠churn | -177.4 | 2% | 0% | -3,634 | -177,210 | 75 | 22.3 | 1.40 |
| 36 | macd_cross ⚠churn | -189.8 | 6% | 2% | -4,318 | -192,099 | 77 | 24.6 | 1.37 |
| 37 | hull_suite ⚠churn | -191.9 | 5% | 0% | -4,029 | -196,810 | 81 | 26.1 | 1.38 |
| 38 | ema_cross ⚠churn | -214.3 | 2% | 0% | -4,504 | -222,790 | 88 | 28.2 | 1.36 |