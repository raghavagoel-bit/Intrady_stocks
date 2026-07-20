"""Bollinger lower-band bounce — LONG-ONLY — NSE intraday, 15m bars.

Intraday mean reversion: when price stretches below the lower Bollinger band
and then closes back above it (the snap-back), buy the bounce and take profit
at the middle band (the rolling mean). The band multiplier is deliberately
tighter than the daily-chart 2.0 — 15m stretches are smaller.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 when
price pokes ABOVE the upper band and closes back inside it (the fade), with the
middle band as the take-profit. Long-only by default.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Buy the close back above the lower band; exit at the middle band.

    Attributes:
        window: Rolling window (bars) for the band mean/std.
        band_k: Band width in standard deviations (tight for 15m bars).
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror short the upper-band fade.
    """

    def __init__(
        self,
        window: int = 20,
        band_k: float = 2.0,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.window = window
        self.band_k = band_k
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
        close = pd.Series(df["close"].to_numpy(dtype=float))

        # Bands roll across the whole lookback (not per-day): a 14-bar window
        # spanning yesterday's close is still a valid local mean for reversion.
        mean = close.rolling(self.window, min_periods=self.window).mean()
        std = close.rolling(self.window, min_periods=self.window).std()
        lower = (mean - self.band_k * std).to_numpy()
        upper = (mean + self.band_k * std).to_numpy()
        mid = mean.to_numpy()
        c = close.to_numpy()

        sig = np.zeros(len(df), dtype=int)
        pos = 0
        for i in range(len(c)):
            t = times[i]
            if not (self.trade_from <= t < self.flatten_at):
                pos = 0
                continue
            if np.isnan(lower[i]):
                continue
            if pos == 0:
                dipped = i > 0 and not np.isnan(lower[i - 1]) and c[i - 1] < lower[i - 1]
                poked = i > 0 and not np.isnan(upper[i - 1]) and c[i - 1] > upper[i - 1]
                if dipped and c[i] >= lower[i]:
                    pos = 1  # lower-band snap-back confirmed
                elif self.allow_short and poked and c[i] <= upper[i]:
                    pos = -1  # upper-band fade confirmed
            elif pos == 1:
                if c[i] >= mid[i] or c[i] < lower[i]:
                    pos = 0  # target (mid) reached, or bounce failed
            else:  # pos == -1
                if c[i] <= mid[i] or c[i] > upper[i]:
                    pos = 0  # target (mid) reached, or fade failed
            sig[i] = pos
        return pd.Series(sig, index=df.index)
