"""VWAP rider — LONG-ONLY — NSE intraday, 15m bars.

The day's volume-weighted average price is the institutional "fair value"
anchor: staying long while price trades above VWAP (and flat below) captures
the persistent one-sided days without predicting anything. A small hysteresis
band around VWAP reduces churn when price hugs the line.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 = hold
short while price trades BELOW VWAP (with the same hysteresis). Long-only by
default.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Long above day-VWAP (with hysteresis), flat below — reset daily.

    Attributes:
        entry_band: Fraction above VWAP required to enter (hysteresis).
        exit_band: Fraction below VWAP that forces the exit.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror short below VWAP.
    """

    def __init__(
        self,
        entry_band: float = 0.001,
        exit_band: float = 0.001,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.entry_band = entry_band
        self.exit_band = exit_band
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
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)

        sig = np.zeros(len(df), dtype=int)
        for day in sorted(set(days)):
            positions = np.where(days == day)[0]
            typical = (high[positions] + low[positions] + close[positions]) / 3.0
            vol = np.maximum(volume[positions], 1.0)
            vwap = np.cumsum(typical * vol) / np.cumsum(vol)
            pos = 0
            for j, i in enumerate(positions):
                t = times[i]
                if not (self.trade_from <= t < self.flatten_at):
                    pos = 0
                    continue
                if pos == 0:
                    if close[i] > vwap[j] * (1 + self.entry_band):
                        pos = 1
                    elif self.allow_short and close[i] < vwap[j] * (1 - self.entry_band):
                        pos = -1
                elif pos == 1 and close[i] < vwap[j] * (1 - self.exit_band):
                    pos = 0
                elif pos == -1 and close[i] > vwap[j] * (1 + self.exit_band):
                    pos = 0
                sig[i] = pos
        return pd.Series(sig, index=df.index)
