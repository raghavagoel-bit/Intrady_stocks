"""Supertrend — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of TradingView's classic Supertrend strategy: bands at hl2 +/- mult*ATR
with the standard ratchet (the lower band may only rise while price stays
above it, the upper band may only fall while price stays below it). Trend
flips up when the close crosses above the final upper band; we are long
while the trend is up, inside the tradeable window.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 = hold
short while the Supertrend is in a DOWN-trend. The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Supertrend flip, reset to flat outside the intraday window.

    Attributes:
        atr_window: ATR lookback (bars).
        mult: Band distance in ATRs from hl2 (TV default 3.0; 2.0 suits 15m).
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — emit −1 while the trend is down.
    """

    def __init__(
        self,
        atr_window: int = 10,
        mult: float = 2.0,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.atr_window = atr_window
        self.mult = mult
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
        high = pd.Series(df["high"].to_numpy(dtype=float))
        low = pd.Series(df["low"].to_numpy(dtype=float))
        close = pd.Series(df["close"].to_numpy(dtype=float))

        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        atr = tr.rolling(self.atr_window, min_periods=self.atr_window).mean().to_numpy()
        hl2 = ((high + low) / 2.0).to_numpy()
        c = close.to_numpy()

        # Ratcheted final bands + trend state, computed bar by bar (the ratchet
        # is inherently sequential — same as the Pine implementation).
        sig = np.zeros(len(df), dtype=int)
        up_trend = False
        final_upper = np.nan
        final_lower = np.nan
        for i in range(len(c)):
            if np.isnan(atr[i]):
                continue
            basic_upper = hl2[i] + self.mult * atr[i]
            basic_lower = hl2[i] - self.mult * atr[i]
            if np.isnan(final_upper):
                final_upper, final_lower = basic_upper, basic_lower
            else:
                if basic_upper < final_upper or c[i - 1] > final_upper:
                    final_upper = basic_upper
                if basic_lower > final_lower or c[i - 1] < final_lower:
                    final_lower = basic_lower
            if up_trend:
                if c[i] < final_lower:
                    up_trend = False
            else:
                if c[i] > final_upper:
                    up_trend = True
            t = times[i]
            in_window = self.trade_from <= t < self.flatten_at
            if up_trend and in_window:
                sig[i] = 1
            elif self.allow_short and not up_trend and in_window:
                sig[i] = -1
        return pd.Series(sig, index=df.index)
