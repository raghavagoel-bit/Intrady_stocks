"""Mid-day range breakout — LONG-ONLY — NSE intraday, 15m bars.

Like ORB but patient: let the whole morning (09:15–11:00) define the range, so
the level is better tested than a 30-minute opening range, then go long when
price closes above the morning high after 11:00. Holds while the breakout
level holds.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: short
when price closes BELOW the 09:15–11:00 morning LOW after 11:00. Long-only by
default.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Break of the 09:15–11:00 high, traded after 11:00, reset daily.

    Attributes:
        range_until: IST time the morning range stops building (11:00).
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror short the morning-low breakdown.
    """

    def __init__(
        self,
        range_until_hour: int = 11,
        range_until_minute: int = 0,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.range_until = _dt.time(range_until_hour, range_until_minute)
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

        sig = np.zeros(len(df), dtype=int)
        for day in sorted(set(days)):
            mask = days == day
            day_times = times[mask]
            in_range = np.array([t < self.range_until for t in day_times])
            if not in_range.any() or in_range.all():
                continue  # need both a range and bars after it
            range_high = high[mask][in_range].max()
            range_low = low[mask][in_range].min()
            tradeable = np.array(
                [
                    (t >= self.range_until) and (self.trade_from <= t < self.flatten_at)
                    for t in day_times
                ]
            )
            above = close[mask] > range_high
            day_sig = np.where(tradeable & above, 1, 0)
            if self.allow_short:
                below = close[mask] < range_low
                day_sig = np.where(tradeable & below, -1, day_sig)
            sig[mask] = day_sig.astype(int)
        return pd.Series(sig, index=df.index)
