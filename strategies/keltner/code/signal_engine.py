"""Keltner Channel breakout — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of the standalone Keltner Channel breakout (Everget's is open source). The
channel is an EMA middle line with an ATR envelope: ``upper = EMA + mult·ATR``.
Long when the close breaks above the upper channel (a volatility-scaled trend
thrust); exit back at the EMA middle line. We already run BB/KC-squeeze
(``squeeze_momentum``), but not the standalone EMA±ATR channel as its own trend
signal — that is the archetype this fills.

The EMA and ATR roll across the whole lookback (no day boundary); entries/exits
respect the intraday window. Signals: 1 = hold long, 0 = flat. Flat before 09:45
and from 15:00 (DC-001). With ``allow_short=True`` (the 3L hybrid twin) the mirror
is symmetric: −1 on a close below the lower channel, covered back at the middle.
The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Break of the EMA±ATR Keltner channel, exit at the middle line.

    Attributes:
        ema_len: EMA length for the channel middle line.
        atr_window: ATR lookback (bars) for the envelope.
        mult: Envelope width in ATRs.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror short on a lower-channel break.
    """

    def __init__(
        self,
        ema_len: int = 20,
        atr_window: int = 20,
        mult: float = 1.5,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.ema_len = ema_len
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

        ema = close.ewm(span=self.ema_len, adjust=False).mean().to_numpy()
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        atr = tr.rolling(self.atr_window, min_periods=self.atr_window).mean().to_numpy()
        upper = ema + self.mult * atr
        lower = ema - self.mult * atr
        c = close.to_numpy()

        sig = np.zeros(len(df), dtype=int)
        pos = 0
        for i in range(len(c)):
            t = times[i]
            if not (self.trade_from <= t < self.flatten_at):
                pos = 0
                continue
            if np.isnan(atr[i]) or i < self.ema_len:
                continue
            if pos == 0:
                if c[i] > upper[i]:
                    pos = 1
                elif self.allow_short and c[i] < lower[i]:
                    pos = -1
            elif pos == 1:
                if c[i] < ema[i]:
                    pos = 0  # back inside the channel
            else:  # pos == -1
                if c[i] > ema[i]:
                    pos = 0
            sig[i] = pos
        return pd.Series(sig, index=df.index)
