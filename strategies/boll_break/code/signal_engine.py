"""Bollinger upper-band breakout — LONG-ONLY — NSE intraday, 15m bars.

Volatility-expansion breakout: a close above the upper Bollinger band with
above-average volume marks range compression resolving upward. Ride it while
price stays above the middle band (the rolling mean).

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 on a
volume-backed close BELOW the lower band, held while price stays below the middle
band. Long-only by default.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Buy the volume-backed close above the upper band; exit under the mean.

    Attributes:
        window: Rolling window (bars) for the band mean/std and volume average.
        band_k: Band width in standard deviations.
        vol_mult: Entry-bar volume must exceed this multiple of average volume.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror short the volume-backed lower breakdown.
    """

    def __init__(
        self,
        window: int = 14,
        band_k: float = 2.0,
        vol_mult: float = 1.2,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.window = window
        self.band_k = band_k
        self.vol_mult = vol_mult
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
        volume = pd.Series(df["volume"].to_numpy(dtype=float))

        mean = close.rolling(self.window, min_periods=self.window).mean()
        std = close.rolling(self.window, min_periods=self.window).std()
        upper = (mean + self.band_k * std).to_numpy()
        lower = (mean - self.band_k * std).to_numpy()
        mid = mean.to_numpy()
        vol_avg = volume.rolling(self.window, min_periods=self.window).mean().to_numpy()
        c = close.to_numpy()
        v = volume.to_numpy()

        sig = np.zeros(len(df), dtype=int)
        pos = 0
        for i in range(len(c)):
            t = times[i]
            if not (self.trade_from <= t < self.flatten_at):
                pos = 0
                continue
            if np.isnan(upper[i]):
                continue
            vol_ok = v[i] > self.vol_mult * vol_avg[i]
            if pos == 0:
                if c[i] > upper[i] and vol_ok:
                    pos = 1
                elif self.allow_short and c[i] < lower[i] and vol_ok:
                    pos = -1
            elif pos == 1:
                if c[i] < mid[i]:
                    pos = 0  # up-expansion over — back inside the range
            else:  # pos == -1
                if c[i] > mid[i]:
                    pos = 0  # down-expansion over — back inside the range
            sig[i] = pos
        return pd.Series(sig, index=df.index)
