"""MACD crossover — LONG-ONLY — NSE intraday, 15m bars.

The classic momentum-of-trend gauge, compressed for 15m intraday bars
(8/17/9 spans instead of the daily 12/26/9): long while the MACD line is above
its signal line, flat otherwise. Computed per day so overnight gaps never leak
into the oscillator state.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 while
the MACD line is BELOW its signal line. The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Intraday MACD(8, 17, 9) long/flat filter, reset daily.

    Attributes:
        fast / slow / signal_span: EMA spans (bars) of the MACD stack.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — emit −1 while MACD is below its signal.
    """

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal_span: int = 9,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.fast = fast
        self.slow = slow
        self.signal_span = signal_span
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
        close = pd.Series(df["close"].to_numpy(dtype=float))

        sig = np.zeros(len(df), dtype=int)
        for day in sorted(set(days)):
            mask = days == day
            day_close = close[mask]
            if len(day_close) < 3:
                continue
            macd = (
                day_close.ewm(span=self.fast, adjust=False).mean()
                - day_close.ewm(span=self.slow, adjust=False).mean()
            )
            signal = macd.ewm(span=self.signal_span, adjust=False).mean()
            up = (macd > signal).to_numpy()
            tradeable = np.array(
                [self.trade_from <= t < self.flatten_at for t in times[mask]]
            )
            day_sig = np.where(up & tradeable, 1, 0)
            if self.allow_short:
                down = (signal > macd).to_numpy()
                day_sig = np.where(down & tradeable, -1, day_sig)
            sig[mask] = day_sig.astype(int)
        return pd.Series(sig, index=df.index)
