"""Nifty-50 universe scan — which stocks suit the long-only 15m roster?

For every liquid NSE large cap (approximate Nifty-50 membership; exact index
composition doesn't matter — we want liquid large caps), runs the 18
per-symbol rule strategies (rel_strength is universe-aware and excluded)
single-stock through ``IndiaIntradayEngine`` on the same train/validate day
split as ``backtest_all.py``, and combines that with two structural filters
that don't depend on P&L:

  - **price** — median close must be ≤ ``MAX_PRICE`` (the bake-off deploys
    ~₹6,250 per entry: pricier stocks lose sizing granularity or become
    unbuyable);
  - **liquidity** — average daily traded value (a 15m-bar proxy) must be
    ≥ ``MIN_TURNOVER_CR`` crore.

Ranking is train-window based; the validate window is reported as the
out-of-sample check. Output: ``docs/UNIVERSE_SCAN.md`` + ``universe_scan.json``.

Usage (from ``strategies/``):  python universe_scan.py [--refresh]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from backtest_all import (
    DOCS, STRATEGIES, load_bars, load_engine_class, run_backtest,
    split_days, slice_window,
)

#: Approximate Nifty-50 constituents (liquid NSE large caps), Yahoo tickers.
NIFTY50 = [
    "ADANIENT.NS", "ADANIPORTS.NS", "APOLLOHOSP.NS", "ASIANPAINT.NS",
    "AXISBANK.NS", "BAJAJ-AUTO.NS", "BAJAJFINSV.NS", "BAJFINANCE.NS",
    "BEL.NS", "BHARTIARTL.NS", "BPCL.NS", "BRITANNIA.NS", "CIPLA.NS",
    "COALINDIA.NS", "DRREDDY.NS", "EICHERMOT.NS", "GRASIM.NS", "HCLTECH.NS",
    "HDFCBANK.NS", "HDFCLIFE.NS", "HEROMOTOCO.NS", "HINDALCO.NS",
    "HINDUNILVR.NS", "ICICIBANK.NS", "INDUSINDBK.NS", "INFY.NS", "ITC.NS",
    "JSWSTEEL.NS", "KOTAKBANK.NS", "LT.NS", "M&M.NS", "MARUTI.NS",
    "NESTLEIND.NS", "NTPC.NS", "ONGC.NS", "POWERGRID.NS", "RELIANCE.NS",
    "SBILIFE.NS", "SBIN.NS", "SHRIRAMFIN.NS", "SUNPHARMA.NS", "TATACONSUM.NS",
    "TATAMOTORS.NS", "TATASTEEL.NS", "TCS.NS", "TECHM.NS", "TITAN.NS",
    "TRENT.NS", "ULTRACEMCO.NS", "WIPRO.NS",
]

MAX_PRICE = 3_000.0        # ₹/share — sizing granularity at ₹6,250/slot
MIN_TURNOVER_CR = 1.0      # ₹ crore average daily traded value (bar proxy)
PER_SYMBOL_STRATEGIES = [s for s in STRATEGIES if s != "rel_strength"]


def scan_stock(symbol: str, refresh: bool = False) -> Optional[dict]:
    """All per-symbol strategies on one stock; None if data unavailable."""
    try:
        df = load_bars(symbol, refresh=refresh)
    except Exception as exc:  # Yahoo hiccup / delisted alias — skip, don't die
        print(f"  {symbol:<16} SKIP ({exc})")
        return None
    if len(df) < 500:
        print(f"  {symbol:<16} SKIP (only {len(df)} bars)")
        return None

    data_map = {symbol: df}
    train_days, validate_days = split_days(data_map)
    train_map = slice_window(data_map, train_days)
    validate_map = slice_window(data_map, validate_days)

    median_price = float(df["close"].median())
    daily_value = (df["close"] * df["volume"]).groupby(df.index.date).sum()
    turnover_cr = float(daily_value.mean() / 1e7)

    train_net = validate_net = 0.0
    val_positive = 0
    best_name, best_val = "", float("-inf")
    for name in PER_SYMBOL_STRATEGIES:
        cls = load_engine_class(name)
        tr = run_backtest(cls(), train_map, name, "train")
        va = run_backtest(cls(), validate_map, name, "validate")
        train_net += tr.net
        validate_net += va.net
        if va.net > 0:
            val_positive += 1
        if va.net > best_val:
            best_val, best_name = va.net, name

    row = {
        "symbol": symbol.replace(".NS", ""),
        "median_price": round(median_price, 1),
        "turnover_cr": round(turnover_cr, 1),
        "train_net": round(train_net),
        "validate_net": round(validate_net),
        "total_net": round(train_net + validate_net),
        "val_positive_strategies": val_positive,
        "best_validate_strategy": best_name,
        "price_ok": median_price <= MAX_PRICE,
        "liquidity_ok": turnover_cr >= MIN_TURNOVER_CR,
    }
    print(f"  {row['symbol']:<16} ₹{median_price:>8,.0f}  "
          f"train {train_net:+9,.0f}  validate {validate_net:+9,.0f}  "
          f"val+ {val_positive:>2}/18  {'' if row['price_ok'] else '✗price'}")
    return row


def main(argv: Optional[List[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)

    rows = [r for s in NIFTY50 if (r := scan_stock(s, refresh=args.refresh))]
    df = pd.DataFrame(rows)

    # Eligible = passes both structural filters; rank eligible by TRAIN net
    # (selection window), report validate as the out-of-sample check.
    eligible = df[df["price_ok"] & df["liquidity_ok"]].sort_values(
        "train_net", ascending=False
    )
    shortlist = eligible.head(15)

    stamp = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d %H:%M IST")

    def _md(frame: pd.DataFrame) -> str:
        head = ("| Symbol | Median ₹ | Turnover ₹cr/day | Train net ₹ | "
                "Validate net ₹ | Val-positive | Best validate strategy |\n"
                "|---|---|---|---|---|---|---|\n")
        return head + "\n".join(
            f"| {r.symbol} | {r.median_price:,.0f} | {r.turnover_cr:,.1f} "
            f"| {r.train_net:+,.0f} | {r.validate_net:+,.0f} "
            f"| {r.val_positive_strategies}/18 | {r.best_validate_strategy} |"
            for r in frame.itertuples()
        )

    report = [
        "# Universe Scan — Nifty-50 for the long-only 15m roster",
        f"\nGenerated {stamp} by `strategies/universe_scan.py`. Each stock ran the "
        "18 per-symbol strategies single-stock (₹25k, MIS costs) on the same "
        "train/validate split as BACKTEST_REPORT.md. Structural filters: median "
        f"price ≤ ₹{MAX_PRICE:,.0f} (₹6,250/slot sizing) and ≥ "
        f"₹{MIN_TURNOVER_CR:.0f}cr/day traded value (15m-bar proxy).",
        "\n> ⚠️ Same 2-month-window caveat as the backtest: ranking is on the "
        "train window; the validate column is the out-of-sample check. Do not "
        "read exact ₹ as predictions — read ordering + consistency.",
        f"\n## Shortlist — top {len(shortlist)} eligible by train net "
        "(validate = OOS check)\n",
        _md(shortlist),
        "\n## All scanned stocks (eligible first, each group by train net)\n",
        _md(pd.concat([eligible, df[~(df["price_ok"] & df["liquidity_ok"])]
                      .sort_values("train_net", ascending=False)])),
        "\nExcluded stocks fail price (✗ sizing at ₹6,250/slot) or liquidity.",
    ]
    DOCS.mkdir(exist_ok=True)
    (DOCS / "UNIVERSE_SCAN.md").write_text("\n".join(report), encoding="utf-8")
    (DOCS / "universe_scan.json").write_text(
        json.dumps({"generated": stamp, "rows": rows}, indent=2),
        encoding="utf-8")
    print(f"\nreport → {DOCS / 'UNIVERSE_SCAN.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
