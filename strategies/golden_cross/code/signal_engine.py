"""Golden Cross — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of ChartArt's "Golden Cross, SMA 200 Moving Average Strategy": be long while a
fast SMA sits above a slow SMA (the golden-cross regime), flat after the death cross.
The daily original uses 50/200; on 15m bars a 200-bar slow SMA (~15 sessions) exceeds
the live 120-bar lookback, so the pair is scaled to 25/100 (~2 vs ~7½ sessions) — the
same fast-above-slow trend regime sized for intraday.

Both SMAs roll across the whole lookback (a golden cross is a multi-day regime by
nature). Signals: 1 = hold long while fast > slow; 0 = flat. Flat before 09:45 and
from 15:00 (DC-001). With ``allow_short=True`` (the 3L hybrid twin) the mirror is
symmetric: −1 while fast < slow (the death-cross regime). No-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Fast-SMA-above-slow-SMA regime filter, intraday.

    Attributes:
        fast: Fast SMA window (the "50" leg, scaled to 15m).
        slow: Slow SMA window (the "200" leg, scaled to 15m).
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — emit −1 in the death-cross regime.
    """

    def __init__(
        self,
        fast: int = 25,
        slow: int = 100,
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
        """Generate long/flat signals per symbol (see module docstring)."""
        return {code: self._generate_one(df) for code, df in data_map.items()}

    def _generate_one(self, df: pd.DataFrame) -> pd.Series:
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("Asia/Kolkata")
        times = np.array([t.time() for t in idx])
        close = pd.Series(df["close"].to_numpy(dtype=float))

        fast = close.rolling(self.fast, min_periods=self.fast).mean().to_numpy()
        slow = close.rolling(self.slow, min_periods=self.slow).mean().to_numpy()
        valid = ~(np.isnan(fast) | np.isnan(slow))
        tradeable = np.array([self.trade_from <= t < self.flatten_at for t in times])

        long_ok = (fast > slow) & valid & tradeable
        sig = np.where(long_ok, 1, 0)
        if self.allow_short:
            short_ok = (fast < slow) & valid & tradeable
            sig = np.where(short_ok, -1, sig)
        return pd.Series(sig.astype(int), index=df.index)
