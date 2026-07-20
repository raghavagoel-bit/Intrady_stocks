"""Batch backtest harness — all rule strategies through IndiaIntradayEngine.

Downloads ~60 calendar days of 15m Yahoo bars for the bake-off universe
(Yahoo's hard limit for 15m history), caches them under ``.bt_cache/``, and
runs every run-dir strategy at the bake-off's ₹25k with the full MIS cost
stack. Reports a ranked scoreboard over the full window plus a train/validate
split (first ~60% of trading days vs the rest) so parameter tuning can stay
honest — tuning only ever ranks on the train window.

Usage (from ``strategies/``):
    python backtest_all.py                    # all strategies, report to docs/
    python backtest_all.py --tune             # + grid-tune orb_intraday & pullback_buy
    python backtest_all.py --refresh          # force re-download of Yahoo data

Not part of the live bake-off runtime — purely an offline second opinion.
The llm_trader slot is not backtestable (no reproducible LLM history).
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

_STRAT = Path(__file__).resolve().parent
_AGENT = _STRAT.parent / "vibe-trading" / "agent"
sys.path.insert(0, str(_AGENT))

from backtest.engines.base import _align  # noqa: E402
from backtest.engines.india_intraday import IndiaIntradayEngine  # noqa: E402

UNIVERSE = ["HDFCBANK.NS", "RELIANCE.NS", "TATASTEEL.NS", "ICICIBANK.NS"]
INITIAL_CASH = 25_000.0
CACHE_DIR = _STRAT / ".bt_cache"
DOCS = _STRAT.parent / "docs"
TRAIN_FRACTION = 0.6

STRATEGIES = [
    "orb_intraday", "pullback_buy", "ema_trend", "momentum_rsi",
    "gap_go", "gap_fade", "vwap_hold", "range_break", "macd_cross",
    "boll_bounce", "boll_break", "atr_trail", "rel_strength", "three_thrust",
    "supertrend", "ut_bot", "squeeze_momentum", "wavetrend", "qqe_mode",
    "oi_dma_adx",
    # TradingView ports added 2026-07-18 (B3 batch — offline backtest first).
    "bb_rsi", "macd_sma200", "macd_rsi", "pmax", "hull_suite", "ao_stoch",
    "golden_cross", "flawless_victory", "ema_cross", "ichimoku", "rsi_div",
    # Tier-1 shortlist batch added 2026-07-19 (B7 — offline; STRATEGY_SHORTLIST.md).
    "cpr_pivot", "psar_flip", "supertrend_vwap", "donchian", "keltner",
    "stoch_rsi", "connors_rsi2",
]

#: Tuning grids — evaluated on the TRAIN window only; the winner is then
#: compared against the current defaults on the untouched VALIDATE window.
#: Values may be non-literal here (runtime kwargs); only engine DEFAULTS must
#: stay literal for the repo validator.
TUNE_GRIDS: Dict[str, Dict[str, list]] = {
    "orb_intraday": {"vol_mult": [1.0, 1.15, 1.3, 1.5], "vol_window": [12, 20]},
    "pullback_buy": {"touch_band": [0.001, 0.002, 0.003],
                     "exit_band": [0.002, 0.003, 0.005]},
    "ema_trend": {"fast": [5, 9, 13], "slow": [21, 34]},
    "momentum_rsi": {"sma": [14, 20], "rsi_len": [7, 9, 14],
                     "rsi_pullback": [70.0, 78.0]},
    "gap_go": {"min_gap_pct": [0.2, 0.3, 0.5]},
    "gap_fade": {"min_gap_pct": [0.2, 0.3, 0.5]},
    "vwap_hold": {"entry_band": [0.0005, 0.001, 0.002],
                  "exit_band": [0.001, 0.002, 0.003]},
    "range_break": {"range_until_hour": [10, 11], "range_until_minute": [0, 30]},
    "macd_cross": {"fast": [6, 8, 12], "slow": [17, 26]},
    "boll_bounce": {"window": [14, 20], "band_k": [1.25, 1.5, 2.0]},
    "boll_break": {"window": [14, 20], "band_k": [1.5, 2.0],
                   "vol_mult": [1.0, 1.2, 1.5]},
    "atr_trail": {"breakout_bars": [6, 10, 14], "atr_mult": [1.0, 1.5, 2.0]},
    "rel_strength": {"min_ret_pct": [0.05, 0.1, 0.2]},
    "three_thrust": {"thrust_bars": [2, 3, 4]},
    "supertrend": {"atr_window": [7, 10, 14], "mult": [1.5, 2.0, 3.0]},
    "ut_bot": {"key": [1.0, 2.0, 3.0], "atr_window": [10, 14]},
    "squeeze_momentum": {"length": [14, 20], "kc_mult": [1.0, 1.5],
                         "fire_grace": [3, 5]},
    "wavetrend": {"channel_len": [7, 10], "average_len": [14, 21],
                  "oversold": [0.0, -10.0]},
    "qqe_mode": {"rsi_window": [9, 14], "smooth": [3, 5],
                 "qqe_factor": [2.618, 4.238]},
    # TradingView ports (2026-07-18) — grids for a future --tune pass.
    # Tier-1 shortlist batch (2026-07-19) — grids for a future --tune pass.
    "cpr_pivot": {"buffer_pct": [0.0, 0.001, 0.002]},
    "psar_flip": {"af_step": [0.01, 0.02, 0.03], "af_max": [0.1, 0.2]},
    "supertrend_vwap": {"atr_window": [7, 10, 14], "mult": [1.5, 2.0, 3.0]},
    "donchian": {"entry_bars": [10, 20, 30], "exit_bars": [5, 10]},
    "keltner": {"ema_len": [14, 20], "atr_window": [10, 20], "mult": [1.0, 1.5, 2.0]},
    "stoch_rsi": {"rsi_len": [9, 14], "stoch_len": [14], "smooth_k": [3, 5]},
    "connors_rsi2": {"rsi_entry": [5.0, 10.0], "trend_ma": [50, 100],
                     "rsi_exit": [65.0, 70.0]},
    "bb_rsi": {"window": [14, 20], "band_k": [1.5, 2.0], "rsi_low": [30.0, 35.0, 40.0]},
    "macd_sma200": {"fast": [8, 12], "slow": [17, 26], "trend_ma": [80, 100]},
    "macd_rsi": {"rsi_os": [35.0, 40.0, 45.0], "recent": [4, 6, 8]},
    "pmax": {"ma_len": [8, 10, 14], "atr_window": [10, 14], "mult": [2.0, 3.0]},
    "hull_suite": {"length": [16, 20, 27, 34]},
    "ao_stoch": {"k_len": [9, 14], "cross_zone": [40.0, 50.0]},
    "golden_cross": {"fast": [20, 25], "slow": [80, 100]},
    "flawless_victory": {"band_k": [1.5, 2.0], "rsi_floor": [40.0, 42.0, 46.0]},
    "ema_cross": {"length": [13, 21, 34]},
    "ichimoku": {"hull_len": [16, 20], "kijun": [20, 26]},
    "rsi_div": {"pivot": [2, 3], "rsi_len": [9, 14]},
}


# ---------------------------------------------------------------- data layer

def load_bars(symbol: str, refresh: bool = False) -> pd.DataFrame:
    """15m bars for ``symbol`` from cache, else Yahoo (last ~60 days)."""
    CACHE_DIR.mkdir(exist_ok=True)
    cached = CACHE_DIR / f"{symbol.replace('.', '_')}_15m.csv"
    if cached.exists() and not refresh:
        df = pd.read_csv(cached, index_col=0, parse_dates=True)
        df.index = pd.DatetimeIndex(df.index).tz_convert("Asia/Kolkata")
        return df

    import yfinance as yf

    raw = yf.download(symbol, period="60d", interval="15m",
                      auto_adjust=False, progress=False)
    if raw is None or raw.empty:
        raise RuntimeError(f"Yahoo returned no 15m data for {symbol}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    df.index = pd.DatetimeIndex(df.index).tz_convert("Asia/Kolkata")
    # Keep only regular-session bars (Yahoo occasionally emits strays).
    t = df.index.time
    df = df[(t >= pd.Timestamp("09:15").time()) & (t < pd.Timestamp("15:30").time())]
    df = df.dropna(subset=["close"])
    df.to_csv(cached)
    return df


def load_universe(refresh: bool = False) -> Dict[str, pd.DataFrame]:
    return {sym: load_bars(sym, refresh=refresh) for sym in UNIVERSE}


def split_days(data_map: Dict[str, pd.DataFrame]) -> tuple:
    """(train_days, validate_days) — unique IST trading dates, ~60/40."""
    days = sorted({d for df in data_map.values() for d in df.index.date})
    cut = int(len(days) * TRAIN_FRACTION)
    return days[:cut], days[cut:]


def slice_window(data_map: Dict[str, pd.DataFrame], days: list) -> Dict[str, pd.DataFrame]:
    keep = set(days)
    return {s: df[[d in keep for d in df.index.date]] for s, df in data_map.items()}


# ------------------------------------------------------------- engine layer

def load_engine_class(name: str):
    path = _STRAT / name / "code" / "signal_engine.py"
    spec = importlib.util.spec_from_file_location(f"bt_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SignalEngine


#: Column headers for the day-on-day matrix (full names are too wide).
SHORT_NAMES = {
    "orb_intraday": "orb", "pullback_buy": "pullback", "ema_trend": "ema",
    "momentum_rsi": "mom_rsi", "gap_go": "gap_go", "gap_fade": "gap_fade",
    "vwap_hold": "vwap", "range_break": "range", "macd_cross": "macd",
    "boll_bounce": "bounce", "boll_break": "bbreak", "atr_trail": "atr",
    "rel_strength": "rel_str", "three_thrust": "thrust", "supertrend": "supert",
    "ut_bot": "ut_bot", "squeeze_momentum": "squeeze", "wavetrend": "wavetr",
    "qqe_mode": "qqe", "oi_dma_adx": "oi_dma",
    "bb_rsi": "bb_rsi", "macd_sma200": "macd200", "macd_rsi": "macd_rsi",
    "pmax": "pmax", "hull_suite": "hull", "ao_stoch": "ao_stoch",
    "golden_cross": "golden", "flawless_victory": "flawless", "ema_cross": "ema_x",
    "ichimoku": "ichi", "rsi_div": "rsi_div",
    "cpr_pivot": "cpr", "psar_flip": "psar", "supertrend_vwap": "st_vwap",
    "donchian": "donch", "keltner": "kelt", "stoch_rsi": "stochrsi",
    "connors_rsi2": "connors",
}


@dataclass
class Result:
    name: str
    window: str
    net: float = 0.0
    gross: float = 0.0
    fees: float = 0.0
    trades: int = 0
    wins: int = 0
    max_dd_pct: float = 0.0
    params: dict = field(default_factory=dict)
    daily: dict = field(default_factory=dict)  # "YYYY-MM-DD" -> net ₹

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0


def run_backtest(engine_obj, data_map: Dict[str, pd.DataFrame],
                 name: str, window: str, params: Optional[dict] = None) -> Result:
    """One strategy over one window through IndiaIntradayEngine."""
    codes = list(data_map)
    signals = engine_obj.generate(data_map)
    dates, close_df, target_pos, _ = _align(data_map, signals, codes)
    eng = IndiaIntradayEngine({"initial_cash": INITIAL_CASH, "intraday": True})
    eng._execute_bars(dates, data_map, close_df, target_pos, codes)

    res = Result(name=name, window=window, params=params or {})
    res.trades = len(eng.trades)
    res.fees = float(sum(t.commission for t in eng.trades))
    net_per_trade = [t.pnl - t.commission for t in eng.trades]
    res.net = float(sum(net_per_trade))
    res.gross = float(sum(t.pnl for t in eng.trades))
    res.wins = int(sum(1 for p in net_per_trade if p > 0))
    for t in eng.trades:
        day = str(pd.Timestamp(t.exit_time).date())
        res.daily[day] = res.daily.get(day, 0.0) + float(t.pnl - t.commission)
    if eng.equity_snapshots:
        eq = pd.Series([s.equity for s in eng.equity_snapshots])
        peak = eq.cummax()
        res.max_dd_pct = float(((eq - peak) / peak).min() * -100.0)
    return res


# ------------------------------------------------------------------- report

def _table(results: List[Result]) -> str:
    head = ("| # | Strategy | Net ₹ | Gross ₹ | Fees ₹ | Trades | Win % | MaxDD % |\n"
            "|---|---|---|---|---|---|---|---|\n")
    rows = []
    for i, r in enumerate(sorted(results, key=lambda r: r.net, reverse=True), 1):
        rows.append(
            f"| {i} | {r.name} | {r.net:+,.0f} | {r.gross:+,.0f} | {r.fees:,.0f} "
            f"| {r.trades} | {r.win_rate * 100:.0f} | {r.max_dd_pct:.1f} |"
        )
    return head + "\n".join(rows)


def daily_matrix(full_results: List[Result], all_days: list) -> pd.DataFrame:
    """Days × strategies net-₹ matrix (0 = flat/no exits that day) + TOTAL."""
    df = pd.DataFrame(
        {SHORT_NAMES.get(r.name, r.name): pd.Series(r.daily) for r in full_results}
    )
    df = df.reindex([str(d) for d in all_days]).fillna(0.0).round(0)
    df["TOTAL"] = df.sum(axis=1)
    return df


def _daily_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    head = "| Date | " + " | ".join(cols) + " |\n"
    head += "|---|" + "---|" * len(cols) + "\n"
    rows = [
        "| " + day + " | " + " | ".join(f"{v:+,.0f}" if v else "0" for v in df.loc[day])
        + " |"
        for day in df.index
    ]
    total = df.sum()
    rows.append("| **SUM** | " + " | ".join(f"**{v:+,.0f}**" for v in total) + " |")
    return head + "\n".join(rows)


def tune(name: str, grid: Dict[str, list], train_map, validate_map) -> dict:
    """Grid search on TRAIN only; best-vs-default comparison on VALIDATE."""
    cls = load_engine_class(name)
    combos = [dict(zip(grid, vals)) for vals in itertools.product(*grid.values())]
    train_scores = [run_backtest(cls(**p), train_map, name, "train", p) for p in combos]
    train_scores.sort(key=lambda r: r.net, reverse=True)
    best = train_scores[0].params

    val_default = run_backtest(cls(), validate_map, name, "validate", {})
    val_best = run_backtest(cls(**best), validate_map, name, "validate", best)
    return {
        "strategy": name,
        "grid_size": len(combos),
        "train_top5": [{"params": r.params, "net": round(r.net, 2),
                        "trades": r.trades} for r in train_scores[:5]],
        "best_params": best,
        "validate_default_net": round(val_default.net, 2),
        "validate_best_net": round(val_best.net, 2),
        "validate_default_trades": val_default.trades,
        "validate_best_trades": val_best.trades,
        "improves_out_of_sample": val_best.net > val_default.net,
    }


def main(argv: Optional[List[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # ₹ on cp1252 consoles
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="re-download Yahoo data")
    parser.add_argument("--tune", action="store_true", help="grid-tune orb + pullback")
    parser.add_argument("--only", nargs="*", default=None, help="subset of strategies")
    parser.add_argument("--symbols", nargs="*", default=None,
                        help="override universe (Yahoo tickers)")
    parser.add_argument("--suffix", default="",
                        help="output-file suffix, e.g. _CANDIDATE (protects the main report)")
    args = parser.parse_args(argv)

    universe = args.symbols or UNIVERSE
    data_map = {sym: load_bars(sym, refresh=args.refresh) for sym in universe}
    days = sorted({d for df in data_map.values() for d in df.index.date})
    train_days, validate_days = split_days(data_map)
    train_map = slice_window(data_map, train_days)
    validate_map = slice_window(data_map, validate_days)
    names = args.only or STRATEGIES

    full, train, validate = [], [], []
    for name in names:
        cls = load_engine_class(name)
        full.append(run_backtest(cls(), data_map, name, "full"))
        train.append(run_backtest(cls(), train_map, name, "train"))
        validate.append(run_backtest(cls(), validate_map, name, "validate"))
        print(f"  {name:<18} net ₹{full[-1].net:+9,.0f}  "
              f"({full[-1].trades} trades, fees ₹{full[-1].fees:,.0f})")

    tuning = [tune(n, g, train_map, validate_map)
              for n, g in TUNE_GRIDS.items() if args.tune and n in names]

    stamp = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d %H:%M IST")
    report = [
        "# Backtest Report (offline second opinion — the paper bake-off is the arbiter)",
        "",
        f"Generated {stamp} by `strategies/backtest_all.py`. Universe: "
        f"{', '.join(universe)} · 15m Yahoo bars · ₹{INITIAL_CASH:,.0f}/strategy · "
        "full MIS cost stack · fills next-bar-open (paper fills at bar close — "
        "small documented basis).",
        f"\nWindow: **{days[0]} → {days[-1]}** ({len(days)} trading days — Yahoo's "
        f"15m history cap). Train = first {len(train_days)} days, validate = "
        f"last {len(validate_days)} days.",
        "\n> ⚠️ One ~2-month window, one regime. A negative number here is a "
        "cost-structure warning, not a verdict; the live paper week decides.",
        "\n## Full window\n", _table(full),
        "\n## Train window\n", _table(train),
        "\n## Validate window\n", _table(validate),
    ]
    dm = daily_matrix(full, days)
    report += [
        "\n## Day-on-day net P&L (₹, exits attributed to their day; 0 = no round trips)\n",
        _daily_table(dm),
        "\nAlso written to `docs/backtest_daily_pnl.csv` for spreadsheet analysis.",
    ]
    if tuning:
        report.append("\n## Tuning (grid on train only; judged on validate)\n")
        for t in tuning:
            report.append(
                f"### {t['strategy']} ({t['grid_size']} combos)\n"
                f"- Best train params: `{t['best_params']}`\n"
                f"- Validate net — default: ₹{t['validate_default_net']:+,.0f} "
                f"({t['validate_default_trades']} trades) · tuned: "
                f"₹{t['validate_best_net']:+,.0f} ({t['validate_best_trades']} trades)\n"
                f"- Out-of-sample improvement: "
                f"**{'YES' if t['improves_out_of_sample'] else 'NO'}**\n"
                f"- Train top-5: " + "; ".join(
                    f"`{r['params']}`→₹{r['net']:+,.0f}" for r in t["train_top5"]) + "\n"
            )

    DOCS.mkdir(exist_ok=True)
    sfx = args.suffix
    dm.to_csv(DOCS / f"backtest_daily_pnl{sfx}.csv")
    (DOCS / f"BACKTEST_REPORT{sfx}.md").write_text("\n".join(report), encoding="utf-8")
    payload = {
        "generated": stamp,
        "days": [str(d) for d in (days[0], days[-1])],
        "results": [r.__dict__ | {"win_rate": r.win_rate} for r in full + train + validate],
        "tuning": tuning,
    }
    (DOCS / f"backtest_results{sfx}.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nreport → {DOCS / f'BACKTEST_REPORT{sfx}.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
