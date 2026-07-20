"""Relative-strength leader — LONG-ONLY — NSE intraday, 15m bars.

Cross-sectional momentum inside the universe: at each bar, rank every symbol
by its return from the day's open and hold ONLY the current leader — and only
when the leader is actually going up (return above a small threshold). The
idea: on any given day, money concentrates in the strongest name; owning the
laggards is dead weight.

This engine is universe-aware — it looks across the whole ``data_map`` rather
than deciding each symbol in isolation.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 on the
current WEAKEST symbol when its day-open return is at/below ``−min_ret_pct``
(short the laggard). A symbol is never both leader and laggard, so long and short
signals never collide. Long-only by default.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Hold the strongest symbol vs day open; flat when nothing is rising.

    Attributes:
        min_ret_pct: Leader's day-open return (%) required to be held at all.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror short the weakest laggard.
    """

    def __init__(
        self,
        min_ret_pct: float = 0.1,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.min_ret_pct = min_ret_pct
        self.trade_from = _dt.time(trade_from_hour, trade_from_minute)
        self.flatten_at = _dt.time(flatten_hour, flatten_minute)
        self.allow_short = allow_short

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """Generate long/flat signals per symbol (see module docstring)."""
        rets = {code: _day_open_returns(df) for code, df in data_map.items()}
        table = pd.DataFrame(rets)  # outer-joined on the union of timestamps

        out: Dict[str, pd.Series] = {}
        for code, df in data_map.items():
            sig = np.zeros(len(df), dtype=int)
            idx = df.index
            ist = idx.tz_convert("Asia/Kolkata") if getattr(idx, "tz", None) else idx
            for i, stamp in enumerate(df.index):
                t = ist[i].time()
                if not (self.trade_from <= t < self.flatten_at):
                    continue
                row = table.loc[stamp] if stamp in table.index else None
                if row is None or row.isna().all():
                    continue
                leader = row.idxmax()
                if leader == code and row[leader] >= self.min_ret_pct:
                    sig[i] = 1
                elif self.allow_short:
                    laggard = row.idxmin()
                    if laggard == code and row[laggard] <= -self.min_ret_pct:
                        sig[i] = -1
            out[code] = pd.Series(sig, index=df.index)
        return out


def _day_open_returns(df: pd.DataFrame) -> pd.Series:
    """Percent return of each bar's close vs that day's opening price.

    Module-level (not a method): the repo's signal-engine validator forbids
    decorators such as ``@staticmethod`` on ``SignalEngine`` methods.
    """
    idx = df.index
    ist = idx.tz_convert("Asia/Kolkata") if getattr(idx, "tz", None) else idx
    days = np.array([t.date() for t in ist])
    open_ = df["open"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    ret = np.zeros(len(df))
    for day in sorted(set(days)):
        mask = days == day
        day_open = open_[mask][0]
        if day_open > 0:
            ret[mask] = (close[mask] / day_open - 1) * 100
    return pd.Series(ret, index=df.index)
