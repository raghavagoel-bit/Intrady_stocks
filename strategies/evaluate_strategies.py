"""Robustness evaluator — rank strategies by consistency, not one lucky window.

`backtest_all.py` gives a quick single-window P&L opinion on the 4-stock bake-off
universe. This module is the stronger *ranker*: it scores each strategy on
**breadth** (every cached symbol, one at a time — no 1/N capital-split confound),
**stability** (walk-forward time folds), and **cost robustness** (net at 2× / 3×
slippage), then ranks by a transparent composite.

Honest limit (state it, don't paper over it): Yahoo caps 15m history at ~57 days,
and that window is **one regime**. No offline metric can manufacture a bull-vs-bear
test from it — real regime diversity only comes from the live paper weeks. What this
*can* surface is which strategies hold up **across symbols, across sub-periods, and
as costs rise** — i.e. which are least likely to be a single-window artefact. In a
down tape most absolute nets are negative; the **relative** ranking is the signal.

Metrics per strategy (each symbol funded at ₹25k, full MIS cost stack, fills next
bar open):
  - pos_rate   : fraction of (symbol × fold) cells with net > 0   [primary rank key]
  - sym_pos    : fraction of symbols net-positive over the full window
  - net_median : median full-window net ₹ across symbols (per ₹25k)
  - net_total  : summed full-window net ₹ across all symbols
  - trades_avg : mean round trips per symbol (churn / fee-drag flag)
  - dd_max     : worst per-symbol max drawdown %
  - cost_keep  : net_total at 2× slippage ÷ net_total (how much survives; flags fragility)
  - score      : 100·pos_rate + median-rank bonus − churn penalty  (see `_score`)

Usage (from ``strategies/``):
    python evaluate_strategies.py                 # all strategies, all cached symbols
    python evaluate_strategies.py --only bb_rsi macd_rsi --folds 4
    python evaluate_strategies.py --symbols HDFCBANK.NS RELIANCE.NS
"""
from __future__ import annotations

import argparse
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import backtest_all as bt  # reuse the data + engine plumbing

_AGENT = Path(__file__).resolve().parent.parent / "vibe-trading" / "agent"
sys.path.insert(0, str(_AGENT))
from backtest.engines.base import _align  # noqa: E402
from backtest.engines.india_intraday import IndiaIntradayEngine  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs"
CAPITAL = bt.INITIAL_CASH
BASE_SLIPPAGE = 0.0005


def cached_symbols() -> List[str]:
    """Yahoo tickers recoverable from ``.bt_cache/*_15m.csv`` filenames."""
    out = []
    for p in sorted(bt.CACHE_DIR.glob("*_15m.csv")):
        stem = p.name[: -len("_15m.csv")]        # e.g. "ADANIENT_NS"
        base, suffix = stem.rsplit("_", 1)        # -> ("ADANIENT", "NS")
        out.append(f"{base}.{suffix}")
    return out


def _run(engine, df: pd.DataFrame, sym: str, slippage: float) -> tuple:
    """One strategy on one symbol → (net ₹, trades, max_dd_%)."""
    signals = engine.generate({sym: df})
    dates, close_df, target_pos, _ = _align({sym: df}, signals, [sym])
    eng = IndiaIntradayEngine(
        {"initial_cash": CAPITAL, "intraday": True, "slippage": slippage}
    )
    eng._execute_bars(dates, {sym: df}, close_df, target_pos, [sym])
    net = float(sum(t.pnl - t.commission for t in eng.trades))
    dd = 0.0
    if eng.equity_snapshots:
        eq = pd.Series([s.equity for s in eng.equity_snapshots])
        dd = float(((eq - eq.cummax()) / eq.cummax()).min() * -100.0)
    return net, len(eng.trades), dd


def _folds(df: pd.DataFrame, k: int) -> List[pd.DataFrame]:
    """Split one symbol's bars into ``k`` contiguous trading-day folds."""
    days = sorted({d for d in df.index.date})
    if len(days) < k:
        return [df]
    edges = np.linspace(0, len(days), k + 1, dtype=int)
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        keep = set(days[a:b])
        out.append(df[[d in keep for d in df.index.date]])
    return out


@dataclass
class Eval:
    name: str
    pos_rate: float = 0.0
    sym_pos: float = 0.0
    net_median: float = 0.0
    net_total: float = 0.0
    trades_avg: float = 0.0
    dd_max: float = 0.0
    cost_keep: float = 0.0
    score: float = 0.0
    per_symbol: dict = field(default_factory=dict)


def _score(pos_rate: float, net_median: float, trades_avg: float) -> float:
    """Transparent composite: consistency-led, churn-penalised.

    pos_rate dominates (× 100). A small bonus for a higher median net (₹ per
    ₹25k, scaled). A churn penalty grows past ~4 trades/symbol (fee-drag) — the
    documented failure mode where trade count, not edge, drives the P&L.
    """
    churn_penalty = max(0.0, trades_avg - 4.0) * 1.5
    return 100.0 * pos_rate + net_median / 50.0 - churn_penalty


def evaluate(name: str, data: Dict[str, pd.DataFrame], folds: int) -> Eval:
    cls = bt.load_engine_class(name)
    cells_pos = cells_tot = 0
    sym_nets, sym_trades, sym_dds, sym_pos = [], [], [], 0
    net_total = net_total_2x = 0.0
    per_symbol = {}
    for sym, df in data.items():
        net, trades, dd = _run(cls(), df, sym, BASE_SLIPPAGE)
        net_2x, _, _ = _run(cls(), df, sym, BASE_SLIPPAGE * 2.0)
        sym_nets.append(net); sym_trades.append(trades); sym_dds.append(dd)
        sym_pos += int(net > 0); net_total += net; net_total_2x += net_2x
        per_symbol[sym] = round(net, 0)
        for fold in _folds(df, folds):
            if fold.empty:
                continue
            fnet, _, _ = _run(cls(), fold, sym, BASE_SLIPPAGE)
            cells_tot += 1
            cells_pos += int(fnet > 0)
    n = max(1, len(data))
    pos_rate = cells_pos / cells_tot if cells_tot else 0.0
    net_median = float(statistics.median(sym_nets)) if sym_nets else 0.0
    trades_avg = float(statistics.mean(sym_trades)) if sym_trades else 0.0
    # "how much of the P&L survives 2× slippage" — >1 or negative when the base
    # is a loss (a loss that deepens has keep < 1); clamp for display sanity.
    cost_keep = (net_total_2x / net_total) if net_total else 0.0
    return Eval(
        name=name, pos_rate=pos_rate, sym_pos=sym_pos / n, net_median=net_median,
        net_total=net_total, trades_avg=trades_avg, dd_max=max(sym_dds or [0.0]),
        cost_keep=cost_keep, score=_score(pos_rate, net_median, trades_avg),
        per_symbol=per_symbol,
    )


def _report(rows: List[Eval], symbols: List[str], folds: int, days: int) -> str:
    rows = sorted(rows, key=lambda r: r.score, reverse=True)
    head = (
        "| # | Strategy | Score | Pos-rate | Sym+ | Net med ₹ | Net tot ₹ | Trades/sym | MaxDD % | 2×-cost keep |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
    )
    body = []
    for i, r in enumerate(rows, 1):
        churn = " ⚠churn" if r.trades_avg > 40 else ""
        body.append(
            f"| {i} | {r.name}{churn} | {r.score:+.1f} | {r.pos_rate*100:.0f}% | "
            f"{r.sym_pos*100:.0f}% | {r.net_median:+,.0f} | {r.net_total:+,.0f} | "
            f"{r.trades_avg:.0f} | {r.dd_max:.1f} | {r.cost_keep:.2f} |"
        )
    stamp = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d %H:%M IST")
    return "\n".join([
        "# Strategy Evaluation (robustness ranker — the live paper week is still the arbiter)",
        "",
        f"Generated {stamp} by `strategies/evaluate_strategies.py`. **{len(symbols)} cached "
        f"symbols**, each funded at ₹{CAPITAL:,.0f} and run one at a time (no 1/N capital-split "
        f"confound), full MIS cost stack, fills next-bar-open. Window ≈ **{days} trading days**, "
        f"**{folds} walk-forward folds**.",
        "",
        "> ⚠️ One ~2-month window = **one regime** (Yahoo's 15m cap). Absolute nets are mostly "
        "negative here; the **relative** ranking — which strategies stay positive across more "
        "symbols, folds, and at higher cost — is the signal. Regime diversity only comes from the "
        "live paper weeks.",
        "",
        "**Columns:** *Pos-rate* = % of (symbol × fold) cells net-positive (primary rank key) · "
        "*Sym+* = % of symbols net-positive full-window · *Net med/tot* = median / total net ₹ "
        "across symbols · *Trades/sym* = churn (fee-drag) flag · *2×-cost keep* = net at 2× "
        "slippage ÷ base net (a value near 1 with a positive base = cost-robust; a loss that "
        "deepens shows keep > 1).",
        "",
        "**Score** = 100·pos_rate + net_median/50 − churn_penalty(>4 trades/sym). Transparent, "
        "consistency-led, churn-penalised — not a P&L forecast.",
        "",
        head + "\n".join(body),
    ])


def main(argv: Optional[List[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="*", default=None, help="subset of strategies")
    ap.add_argument("--symbols", nargs="*", default=None, help="override cached symbols")
    ap.add_argument("--folds", type=int, default=4, help="walk-forward folds (default 4)")
    ap.add_argument("--suffix", default="", help="output-file suffix")
    args = ap.parse_args(argv)

    symbols = args.symbols or cached_symbols()
    if not symbols:
        print("no cached symbols — run backtest_all.py once to populate .bt_cache/")
        return 1
    data = {s: bt.load_bars(s) for s in symbols}
    days = len({d for df in data.values() for d in df.index.date})
    names = args.only or bt.STRATEGIES

    rows = []
    for name in names:
        ev = evaluate(name, data, args.folds)
        rows.append(ev)
        print(f"  {name:<18} score {ev.score:+7.1f}  pos {ev.pos_rate*100:3.0f}%  "
              f"net_med ₹{ev.net_median:+8,.0f}  trades/sym {ev.trades_avg:4.0f}")

    DOCS.mkdir(exist_ok=True)
    out = DOCS / f"STRATEGY_EVALUATION{args.suffix}.md"
    out.write_text(_report(rows, symbols, args.folds, days), encoding="utf-8")
    print(f"\nreport → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
