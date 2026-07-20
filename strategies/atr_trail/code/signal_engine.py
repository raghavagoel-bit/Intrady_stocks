"""Breakout with ATR trailing exit — LONG-ONLY — NSE intraday, 15m bars.

Enter when price makes a new local high (close above the max of the prior
lookback closes); stay in while the trend pays, and exit only when price gives
back more than ``atr_mult`` ATRs from the best close since entry. The trailing
exit is the whole point: winners run, losers are cut by volatility, not by a
fixed tick count.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 on a
new local LOW (close below the min of the prior lookback closes), exited when
price rallies more than ``atr_mult`` ATRs off the trough close. Long-only by
default.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """New-high entry + ATR trailing stop exit, reset daily.

    Attributes:
        breakout_bars: Prior closes the entry bar must exceed.
        atr_window: ATR lookback (bars).
        atr_mult: Trail distance in ATRs from the peak close since entry.
        trade_from / flatten_at: IST tradeable window bounds.
    """

    def __init__(
        self,
        breakout_bars: int = 10,
        atr_window: int = 14,
        atr_mult: float = 1.5,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.breakout_bars = breakout_bars
        self.atr_window = atr_window
        self.atr_mult = atr_mult
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

        # True range → ATR, rolling across the lookback (volatility has no
        # day boundary); entries/exits below still respect the intraday window.
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        atr = tr.rolling(self.atr_window, min_periods=self.atr_window).mean().to_numpy()
        prior_max = close.shift(1).rolling(
            self.breakout_bars, min_periods=self.breakout_bars
        ).max().to_numpy()
        prior_min = close.shift(1).rolling(
            self.breakout_bars, min_periods=self.breakout_bars
        ).min().to_numpy()
        c = close.to_numpy()

        sig = np.zeros(len(df), dtype=int)
        pos = 0
        peak = 0.0
        trough = 0.0
        for i in range(len(c)):
            t = times[i]
            if not (self.trade_from <= t < self.flatten_at):
                pos = 0
                continue
            if np.isnan(prior_max[i]) or np.isnan(prior_min[i]) or np.isnan(atr[i]):
                continue
            if pos == 0:
                if c[i] > prior_max[i]:
                    pos = 1
                    peak = c[i]
                elif self.allow_short and c[i] < prior_min[i]:
                    pos = -1
                    trough = c[i]
            elif pos == 1:
                peak = max(peak, c[i])
                if c[i] < peak - self.atr_mult * atr[i]:
                    pos = 0  # gave back too much — long trail hit
            else:  # pos == -1
                trough = min(trough, c[i])
                if c[i] > trough + self.atr_mult * atr[i]:
                    pos = 0  # rallied too much — short trail hit
            sig[i] = pos
        return pd.Series(sig, index=df.index)
