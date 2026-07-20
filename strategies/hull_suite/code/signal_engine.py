"""Hull Suite — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of InSilico/DashTrader's "Hull Suite": trade the slope of a Hull Moving
Average. The HMA is a near-lagless weighted average
(``WMA(2·WMA(n/2) − WMA(n), √n)``); the Suite colours it green when it is rising
and red when falling, using the 2-bars-ago comparison ``HMA[i] > HMA[i−2]``. We
hold long while the HMA is green (rising), inside the tradeable window.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 while
the HMA is red (``HMA[i] < HMA[i−2]``). The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


def _wma(x: pd.Series, length: int) -> pd.Series:
    """Linearly weighted moving average (weights 1..length, newest heaviest)."""
    weights = np.arange(1, length + 1, dtype=float)
    return x.rolling(length, min_periods=length).apply(
        lambda w: float(np.dot(w, weights) / weights.sum()), raw=True
    )


class SignalEngine:
    """Hull MA slope (green/red), intraday.

    Attributes:
        length: HMA length (Hull Suite default 55; 20 suits 15m bars).
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — emit −1 while the HMA is falling.
    """

    def __init__(
        self,
        length: int = 20,
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

        half = max(1, self.length // 2)
        sqrt_len = max(1, int(round(np.sqrt(self.length))))
        raw = 2.0 * _wma(close, half) - _wma(close, self.length)
        hma = _wma(raw, sqrt_len).to_numpy()

        sig = np.zeros(len(df), dtype=int)
        for i in range(len(hma)):
            if i < 2 or np.isnan(hma[i]) or np.isnan(hma[i - 2]):
                continue
            t = times[i]
            in_window = self.trade_from <= t < self.flatten_at
            if not in_window:
                continue
            if hma[i] > hma[i - 2]:
                sig[i] = 1
            elif self.allow_short and hma[i] < hma[i - 2]:
                sig[i] = -1
        return pd.Series(sig, index=df.index)
