"""EMA trend-follow — LONG-ONLY — NSE intraday, 15m bars.

A simple intraday trend rider: within the tradeable window (09:45–15:00 IST) go
long while the fast EMA is above the slow EMA (an up-trend) and flat otherwise.
Unlike the one-shot ORB, this re-enters whenever the trend re-asserts, so it
trades more and captures sustained intraday moves rather than a single breakout.

EMAs are computed **per day** (reset each morning) so an overnight gap never
leaks into the intraday trend state. Runs through `IndiaIntradayEngine`
(`intraday: true`). Fills are next-bar-open, so the strategy goes flat at 15:00
(one bar before the 15:15 close) — the square-off then lands at 15:15 same-day
(see DC-001).

Signal semantics: 1 = hold long, 0 = flat. With ``allow_short=True`` (the 3L
hybrid twin) the mirror is symmetric — −1 = hold short while the fast EMA is
BELOW the slow EMA (a down-trend). The no-arg ctor stays long-only (never −1).
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Fast/slow EMA trend filter, long-only, reset daily.

    Attributes:
        fast: Fast EMA span in bars.
        slow: Slow EMA span in bars.
        trade_from: Time (IST) trading may begin (skips the noisy open).
        flatten_at: Time (IST) from which the strategy is flat.
    """

    def __init__(
        self,
        fast: int = 9,
        slow: int = 21,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.fast = fast
        self.slow = slow
        self.trade_from = _dt.time(trade_from_hour, trade_from_minute)
        self.flatten_at = _dt.time(flatten_hour, flatten_minute)
        self.allow_short = allow_short

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """Generate long/flat signals per symbol.

        Args:
            data_map: Symbol -> 15m OHLCV DataFrame with a DatetimeIndex
                (tz-aware is converted to IST; tz-naive is treated as IST).

        Returns:
            Symbol -> signal Series (1 = long, 0 = flat).
        """
        return {code: self._generate_one(df) for code, df in data_map.items()}

    def _generate_one(self, df: pd.DataFrame) -> pd.Series:
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("Asia/Kolkata")
        times = np.array([t.time() for t in idx])
        days = np.array([t.date() for t in idx])
        close = pd.Series(df["close"].to_numpy(dtype=float))

        sig = np.zeros(len(df), dtype=int)
        for day in np.unique(days):
            mask = days == day
            day_close = close[mask]
            if len(day_close) < 2:
                continue
            fast_ema = day_close.ewm(span=self.fast, adjust=False).mean().to_numpy()
            slow_ema = day_close.ewm(span=self.slow, adjust=False).mean().to_numpy()
            day_times = times[mask]
            up = fast_ema > slow_ema
            tradeable = np.array(
                [self.trade_from <= t < self.flatten_at for t in day_times]
            )
            day_sig = np.where(up & tradeable, 1, 0)
            if self.allow_short:
                down = slow_ema > fast_ema
                day_sig = np.where(down & tradeable, -1, day_sig)
            sig[mask] = day_sig.astype(int)
        return pd.Series(sig, index=df.index)
