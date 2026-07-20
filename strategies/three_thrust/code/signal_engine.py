"""Three-bar thrust — LONG-ONLY — NSE intraday, 15m bars.

Short-fuse momentum: three consecutive higher closes mark buyers in control;
join on the third and stay until the first down close breaks the sequence.
Simple, frequent, and honest — it will churn on choppy days (which is exactly
the cost-drag behaviour the bake-off should measure).

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 after
N consecutive LOWER closes, exit on the first up close. Long-only by default.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Enter after N consecutive higher closes; exit on the first down close.

    Attributes:
        thrust_bars: Consecutive higher closes required to enter.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror short after N lower closes.
    """

    def __init__(
        self,
        thrust_bars: int = 4,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.thrust_bars = thrust_bars
        self.trade_from = _dt.time(trade_from_hour, trade_from_minute)
        self.flatten_at = _dt.time(flatten_hour, flatten_minute)
        self.allow_short = allow_short

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """Generate long/flat signals per symbol (see module docstring)."""
        return {code: self._generate_one(df) for code, df in data_map.items()}

    def _generate_one(self, df: pd.DataFrame) -> pd.Series:
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("Asia/Kolkata")
        times = np.array([t.time() for t in idx])
        days = np.array([t.date() for t in idx])
        close = df["close"].to_numpy(dtype=float)

        sig = np.zeros(len(df), dtype=int)
        for day in sorted(set(days)):
            positions = np.where(days == day)[0]
            up_streak = 0
            down_streak = 0
            pos = 0
            for j, i in enumerate(positions):
                if j > 0:
                    up = close[i] > close[positions[j - 1]]
                    down = close[i] < close[positions[j - 1]]
                    up_streak = up_streak + 1 if up else 0
                    down_streak = down_streak + 1 if down else 0
                t = times[i]
                if not (self.trade_from <= t < self.flatten_at):
                    pos = 0
                    continue
                if pos == 0:
                    if up_streak >= self.thrust_bars:
                        pos = 1
                    elif self.allow_short and down_streak >= self.thrust_bars:
                        pos = -1
                elif pos == 1 and up_streak == 0:
                    pos = 0  # first non-up close ends the up thrust
                elif pos == -1 and down_streak == 0:
                    pos = 0  # first non-down close ends the down thrust
                sig[i] = pos
        return pd.Series(sig, index=df.index)
