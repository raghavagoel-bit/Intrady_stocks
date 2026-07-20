"""AO + Stochastic — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of SerdarYILMAZ's "Buy&Sell Strategy depends on AO + Stoch": pair a momentum
gate (Awesome Oscillator above zero) with a timing trigger (a Stochastic %K/%D
bullish cross out of the lower half). The AO keeps entries on the right side of the
swing; the Stochastic cross times the pullback. Exit when %K crosses back below %D
or momentum rolls over (AO below zero).

AO (median-price SMA5 − SMA34) and the Stochastic roll across the whole lookback.
Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001). With
``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: short on a %K/%D
bearish cross from the upper half while AO < 0, cover on the bullish cross or AO > 0.
The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Awesome Oscillator momentum gate + Stochastic cross trigger, intraday.

    Attributes:
        ao_fast / ao_slow: median-price SMA lengths for the Awesome Oscillator.
        k_len: Stochastic %K lookback; d_len: %D smoothing.
        cross_zone: a long only triggers with %D below this (skip the overbought
            top); the short mirror needs %D above its complement (100 − cross_zone).
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror the bearish cross while AO < 0.
    """

    def __init__(
        self,
        ao_fast: int = 5,
        ao_slow: int = 34,
        k_len: int = 14,
        d_len: int = 3,
        cross_zone: float = 80.0,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.ao_fast = ao_fast
        self.ao_slow = ao_slow
        self.k_len = k_len
        self.d_len = d_len
        self.cross_zone = cross_zone
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

        median = (high + low) / 2.0
        ao = (
            median.rolling(self.ao_fast, min_periods=self.ao_fast).mean()
            - median.rolling(self.ao_slow, min_periods=self.ao_slow).mean()
        ).to_numpy()

        ll = low.rolling(self.k_len, min_periods=self.k_len).min()
        hh = high.rolling(self.k_len, min_periods=self.k_len).max()
        rng = (hh - ll).replace(0.0, np.nan)
        k = (100.0 * (close - ll) / rng).fillna(50.0)
        d = k.rolling(self.d_len, min_periods=self.d_len).mean()
        k = k.to_numpy()
        d = d.to_numpy()
        zone_hi = 100.0 - self.cross_zone

        sig = np.zeros(len(df), dtype=int)
        pos = 0
        for i in range(len(close)):
            t = times[i]
            if not (self.trade_from <= t < self.flatten_at):
                pos = 0
                continue
            if i < 1 or np.isnan(ao[i]) or np.isnan(d[i]) or np.isnan(d[i - 1]):
                sig[i] = pos
                continue
            cross_up = k[i] > d[i] and k[i - 1] <= d[i - 1]
            cross_dn = k[i] < d[i] and k[i - 1] >= d[i - 1]
            if pos == 0:
                if ao[i] > 0 and cross_up and d[i] < self.cross_zone:
                    pos = 1
                elif self.allow_short and ao[i] < 0 and cross_dn and d[i] > zone_hi:
                    pos = -1
            elif pos == 1:
                if cross_dn or ao[i] < 0:
                    pos = 0
            else:  # pos == -1
                if cross_up or ao[i] > 0:
                    pos = 0
            sig[i] = pos
        return pd.Series(sig, index=df.index)
