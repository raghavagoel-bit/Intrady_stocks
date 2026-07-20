"""Single-EMA cross — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of Che_Trader's "BUY and SELL - Backtest single EMA cross": the simplest
trend follower — one EMA, long while the close is above it, flat once the close
crosses back below. No second average, no oscillator; it just rides whichever side
of a single EMA price is on. Kept as the deliberately-minimal baseline in the roster.

The EMA rolls across the whole lookback (a single continuous EMA, as on the chart).
Signals: 1 = hold long while close > EMA; 0 = flat. Flat before 09:45 and from 15:00
(DC-001). With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1
while close < EMA. The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Price-vs-single-EMA regime, intraday.

    Attributes:
        length: EMA length (bars).
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — emit −1 while close is below the EMA.
    """

    def __init__(
        self,
        length: int = 21,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.length = length
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

        ema = close.ewm(span=self.length, adjust=False).mean().to_numpy()
        c = close.to_numpy()
        # Require the EMA to have "warmed up" before trusting the cross.
        warm = np.arange(len(c)) >= self.length
        tradeable = np.array([self.trade_from <= t < self.flatten_at for t in times])

        long_ok = (c > ema) & warm & tradeable
        sig = np.where(long_ok, 1, 0)
        if self.allow_short:
            short_ok = (c < ema) & warm & tradeable
            sig = np.where(short_ok, -1, sig)
        return pd.Series(sig.astype(int), index=df.index)
