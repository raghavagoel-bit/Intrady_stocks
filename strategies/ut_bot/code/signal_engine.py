"""UT Bot Alerts — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of QuantNomad's "UT Bot Alerts": an ATR trailing stop on the close.
The stop ratchets up underneath price while we are above it (never down),
and flips to tracking above price when we fall below it. We are long while
the close is above the trailing stop, inside the tradeable window.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 = hold
short while the close is BELOW the trailing stop. The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """ATR trailing-stop flip (UT Bot), intraday.

    Attributes:
        key: Stop distance in ATRs (TV input "Key Value", default 1.0).
        atr_window: ATR lookback (TV default 10).
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — emit −1 while close is below the stop.
    """

    def __init__(
        self,
        key: float = 2.0,
        atr_window: int = 14,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.key = key
        self.atr_window = atr_window
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
        c = close.to_numpy()

        sig = np.zeros(len(df), dtype=int)
        stop = np.nan
        for i in range(len(c)):
            if np.isnan(atr[i]):
                continue
            loss = self.key * atr[i]
            if np.isnan(stop):
                stop = c[i] - loss
            elif c[i] > stop and c[i - 1] > stop:
                stop = max(stop, c[i] - loss)      # ratchet up under price
            elif c[i] < stop and c[i - 1] < stop:
                stop = min(stop, c[i] + loss)      # ratchet down above price
            elif c[i] > stop:
                stop = c[i] - loss                 # flip: price broke above
            else:
                stop = c[i] + loss                 # flip: price broke below
            t = times[i]
            in_window = self.trade_from <= t < self.flatten_at
            if c[i] > stop and in_window:
                sig[i] = 1
            elif self.allow_short and c[i] < stop and in_window:
                sig[i] = -1
        return pd.Series(sig, index=df.index)
