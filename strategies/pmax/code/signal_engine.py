"""PMax (Profit Maximizer) — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of KivancOzbilgic's "PMax": a Supertrend-style ATR trailing stop, but built
around a moving average of price instead of hl2, and the trend flips when the *MA*
(not the raw close) crosses the trailing band. Smoothing the trigger with an EMA
makes PMax flip less than a bare Supertrend — fewer intraday whipsaws. We are long
while the MA sits above the PMax line (the up-trend), inside the tradeable window.

The band ratchet is inherently sequential (same as the Pine source), so it is
computed bar by bar. Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from
15:00 (DC-001). With ``allow_short=True`` (the 3L hybrid twin) the mirror is
symmetric: −1 while the MA is below the PMax line (down-trend). No-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """PMax trailing stop on an EMA of close, intraday.

    Attributes:
        ma_len: EMA length for the PMax trigger line.
        atr_window: ATR lookback (bars).
        mult: Band distance in ATRs (KivancOzbilgic default 3.0).
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — emit −1 while the MA is below the PMax line.
    """

    def __init__(
        self,
        ma_len: int = 10,
        atr_window: int = 10,
        mult: float = 3.0,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.ma_len = ma_len
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
        ma = close.ewm(span=self.ma_len, adjust=False).mean().to_numpy()

        # Ratcheted final bands + trend, triggered on the MA (PMax convention).
        sig = np.zeros(len(df), dtype=int)
        up_trend = False
        final_upper = np.nan
        final_lower = np.nan
        for i in range(len(ma)):
            if np.isnan(atr[i]):
                continue
            basic_upper = ma[i] + self.mult * atr[i]
            basic_lower = ma[i] - self.mult * atr[i]
            if np.isnan(final_upper):
                final_upper, final_lower = basic_upper, basic_lower
            else:
                if basic_upper < final_upper or ma[i - 1] > final_upper:
                    final_upper = basic_upper
                if basic_lower > final_lower or ma[i - 1] < final_lower:
                    final_lower = basic_lower
            if up_trend:
                if ma[i] < final_lower:
                    up_trend = False
            else:
                if ma[i] > final_upper:
                    up_trend = True
            t = times[i]
            in_window = self.trade_from <= t < self.flatten_at
            if up_trend and in_window:
                sig[i] = 1
            elif self.allow_short and not up_trend and in_window:
                sig[i] = -1
        return pd.Series(sig, index=df.index)
