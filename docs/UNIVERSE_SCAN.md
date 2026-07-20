# Universe Scan — Nifty-50 for the long-only 15m roster

Generated 2026-07-15 21:00 IST by `strategies/universe_scan.py`. Each stock ran the 18 per-symbol strategies single-stock (₹25k, MIS costs) on the same train/validate split as BACKTEST_REPORT.md. Structural filters: median price ≤ ₹3,000 (₹6,250/slot sizing) and ≥ ₹1cr/day traded value (15m-bar proxy).

> ⚠️ Same 2-month-window caveat as the backtest: ranking is on the train window; the validate column is the out-of-sample check. Do not read exact ₹ as predictions — read ordering + consistency.

## Shortlist — top 15 eligible by train net (validate = OOS check)

| Symbol | Median ₹ | Turnover ₹cr/day | Train net ₹ | Validate net ₹ | Val-positive | Best validate strategy |
|---|---|---|---|---|---|---|
| ADANIENT | 2,946 | 670.1 | -6,158 | -7,027 | 3/18 | gap_fade |
| BHARTIARTL | 1,859 | 1,503.1 | -11,745 | -12,546 | 0/18 | supertrend |
| BPCL | 304 | 273.6 | -12,375 | -16,357 | 0/18 | three_thrust |
| RELIANCE | 1,327 | 2,162.2 | -13,958 | -23,601 | 1/18 | gap_go |
| SUNPHARMA | 1,842 | 604.6 | -14,554 | -23,672 | 0/18 | squeeze_momentum |
| AXISBANK | 1,306 | 874.4 | -19,979 | -23,884 | 1/18 | squeeze_momentum |
| SHRIRAMFIN | 975 | 557.3 | -20,185 | -17,412 | 3/18 | boll_break |
| INDUSINDBK | 920 | 211.5 | -20,238 | +1,145 | 11/18 | ut_bot |
| CIPLA | 1,398 | 250.4 | -20,779 | -20,495 | 0/18 | gap_fade |
| COALINDIA | 456 | 580.0 | -21,243 | -15,270 | 2/18 | orb_intraday |
| WIPRO | 189 | 468.8 | -21,591 | -17,510 | 2/18 | gap_fade |
| TECHM | 1,447 | 345.0 | -21,687 | -4,457 | 7/18 | squeeze_momentum |
| KOTAKBANK | 382 | 668.7 | -21,720 | -10,536 | 3/18 | gap_fade |
| ICICIBANK | 1,297 | 2,009.5 | -22,573 | -19,790 | 1/18 | gap_fade |
| BEL | 418 | 501.5 | -23,340 | -13,203 | 1/18 | squeeze_momentum |

## All scanned stocks (eligible first, each group by train net)

| Symbol | Median ₹ | Turnover ₹cr/day | Train net ₹ | Validate net ₹ | Val-positive | Best validate strategy |
|---|---|---|---|---|---|---|
| ADANIENT | 2,946 | 670.1 | -6,158 | -7,027 | 3/18 | gap_fade |
| BHARTIARTL | 1,859 | 1,503.1 | -11,745 | -12,546 | 0/18 | supertrend |
| BPCL | 304 | 273.6 | -12,375 | -16,357 | 0/18 | three_thrust |
| RELIANCE | 1,327 | 2,162.2 | -13,958 | -23,601 | 1/18 | gap_go |
| SUNPHARMA | 1,842 | 604.6 | -14,554 | -23,672 | 0/18 | squeeze_momentum |
| AXISBANK | 1,306 | 874.4 | -19,979 | -23,884 | 1/18 | squeeze_momentum |
| SHRIRAMFIN | 975 | 557.3 | -20,185 | -17,412 | 3/18 | boll_break |
| INDUSINDBK | 920 | 211.5 | -20,238 | +1,145 | 11/18 | ut_bot |
| CIPLA | 1,398 | 250.4 | -20,779 | -20,495 | 0/18 | gap_fade |
| COALINDIA | 456 | 580.0 | -21,243 | -15,270 | 2/18 | orb_intraday |
| WIPRO | 189 | 468.8 | -21,591 | -17,510 | 2/18 | gap_fade |
| TECHM | 1,447 | 345.0 | -21,687 | -4,457 | 7/18 | squeeze_momentum |
| KOTAKBANK | 382 | 668.7 | -21,720 | -10,536 | 3/18 | gap_fade |
| ICICIBANK | 1,297 | 2,009.5 | -22,573 | -19,790 | 1/18 | gap_fade |
| BEL | 418 | 501.5 | -23,340 | -13,203 | 1/18 | squeeze_momentum |
| HDFCBANK | 781 | 2,664.7 | -24,891 | -19,075 | 0/18 | gap_go |
| ITC | 291 | 466.3 | -25,745 | -20,134 | 0/18 | squeeze_momentum |
| ADANIPORTS | 1,802 | 425.1 | -25,849 | -14,712 | 2/18 | gap_go |
| POWERGRID | 290 | 312.2 | -26,497 | -17,083 | 2/18 | boll_bounce |
| SBIN | 1,025 | 1,432.3 | -26,530 | -15,881 | 1/18 | squeeze_momentum |
| BAJAJFINSV | 1,774 | 194.2 | -26,780 | -7,640 | 3/18 | macd_cross |
| HCLTECH | 1,163 | 473.9 | -26,818 | -4,008 | 8/18 | gap_fade |
| ONGC | 265 | 445.1 | -27,400 | -14,780 | 2/18 | orb_intraday |
| TATACONSUM | 1,142 | 241.3 | -27,963 | -16,565 | 3/18 | gap_go |
| BAJFINANCE | 942 | 816.4 | -28,313 | -6,790 | 5/18 | orb_intraday |
| DRREDDY | 1,302 | 325.7 | -28,713 | -24,636 | 1/18 | squeeze_momentum |
| HINDUNILVR | 2,195 | 412.8 | -28,733 | -23,536 | 1/18 | gap_go |
| INFY | 1,151 | 1,586.2 | -28,912 | -11,583 | 5/18 | qqe_mode |
| NESTLEIND | 1,428 | 287.7 | -29,654 | -28,069 | 0/18 | squeeze_momentum |
| ASIANPAINT | 2,660 | 314.3 | -30,447 | -21,559 | 1/18 | boll_break |
| JSWSTEEL | 1,274 | 201.2 | -30,602 | -21,127 | 1/18 | three_thrust |
| SBILIFE | 1,817 | 204.8 | -30,909 | -14,082 | 3/18 | momentum_rsi |
| TCS | 2,231 | 1,079.8 | -31,662 | -3,465 | 8/18 | ema_trend |
| TATASTEEL | 207 | 587.7 | -31,863 | -22,825 | 0/18 | squeeze_momentum |
| NTPC | 367 | 418.5 | -32,552 | -18,911 | 0/18 | gap_go |
| TRENT | 2,772 | 371.1 | -32,829 | -10,338 | 3/18 | gap_go |
| HDFCLIFE | 589 | 255.0 | -33,558 | -20,475 | 1/18 | gap_go |
| HINDALCO | 1,042 | 582.0 | -35,212 | -22,919 | 1/18 | squeeze_momentum |
| TITAN | 4,297 | 457.5 | -12,996 | -9,759 | 1/18 | gap_fade |
| GRASIM | 3,103 | 249.2 | -15,443 | -16,865 | 0/18 | gap_fade |
| APOLLOHOSP | 8,363 | 315.9 | -16,870 | -13,921 | 2/18 | gap_go |
| MARUTI | 13,320 | 636.5 | -19,281 | -9,776 | 1/18 | gap_go |
| ULTRACEMCO | 11,535 | 366.9 | -23,432 | -16,871 | 0/18 | gap_go |
| BAJAJ-AUTO | 10,184 | 395.2 | -24,200 | -9,032 | 2/18 | gap_fade |
| EICHERMOT | 7,242 | 402.6 | -24,441 | -11,954 | 2/18 | boll_bounce |
| M&M | 3,111 | 916.5 | -28,285 | -13,048 | 1/18 | gap_fade |
| LT | 4,003 | 875.4 | -29,924 | -13,220 | 1/18 | boll_break |
| BRITANNIA | 5,326 | 209.1 | -30,101 | -18,477 | 0/18 | gap_fade |
| HEROMOTOCO | 4,974 | 328.1 | -35,919 | -10,811 | 1/18 | boll_bounce |

Excluded stocks fail price (✗ sizing at ₹6,250/slot) or liquidity.