"""Standalone ORB backtest on Yahoo 15m NSE data with Dhan MIS costs.

Usage: python run_standalone.py [SYMBOL.NS ...]

Kept outside code/signal_engine.py because Vibe-Trading's runner rejects
executable top-level statements in user signal-engine files.
"""

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

_spec = importlib.util.spec_from_file_location(
    "orb_signal_engine", Path(__file__).parent / "code" / "signal_engine.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

CAPITAL_PER_SYMBOL = 100_000.0  # Rs. 1L notional per symbol per trade
SLIPPAGE = 0.0005

symbols = sys.argv[1:] or ["RELIANCE.NS", "HDFCBANK.NS", "INFY.NS"]
engine = _mod.SignalEngine()
total_pnl, total_trades, total_wins = 0.0, 0, 0
print(f"{'symbol':<16}{'trades':>7}{'win%':>7}{'net P&L (Rs.)':>15}")
for sym in symbols:
    df = yf.download(sym, period="55d", interval="15m", progress=False)
    if df.empty:
        print(f"{sym:<16}{'no data':>8}")
        continue
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    sig = engine.generate({sym: df})[sym]
    trades = _mod._simulate(df, sig, CAPITAL_PER_SYMBOL, SLIPPAGE)
    wins = sum(1 for t in trades if t > 0)
    pnl = sum(trades)
    win_pct = 100 * wins / len(trades) if trades else 0.0
    print(f"{sym:<16}{len(trades):>7}{win_pct:>6.1f}%{pnl:>15,.0f}")
    total_pnl += pnl
    total_trades += len(trades)
    total_wins += wins
if total_trades:
    print(
        f"{'TOTAL':<16}{total_trades:>7}"
        f"{100 * total_wins / total_trades:>6.1f}%{total_pnl:>15,.0f}"
    )
