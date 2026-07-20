"""Parabolic SAR flip — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of Wilder's Parabolic SAR (Stop-And-Reverse): a trailing dot that
accelerates toward price. Long while the SAR sits BELOW price; the trend flips
when price touches the dot. The acceleration factor starts at ``af_step`` and
ratchets up by ``af_step`` on each new extreme (capped at ``af_max``), so the
trail tightens as a move extends. The dot is also clamped so it can never
penetrate the prior two bars — the standard Wilder guard. This is the
trailing-stop trend archetype not covered by our EMA/Supertrend/UT engines.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
The SAR is inherently bidirectional; long-only simply suppresses the down leg.
With ``allow_short=True`` (the 3L hybrid twin) the mirror emits −1 while the SAR
is above price (a down-trend). The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Parabolic-SAR trend state, reset to flat outside the intraday window.

    Attributes:
        af_step: Acceleration-factor step (start value and increment).
        af_max: Acceleration-factor cap.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — emit −1 while the SAR is above price.
    """

    def __init__(
        self,
        af_step: float = 0.02,
        af_max: float = 0.2,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.af_step = af_step
        self.af_max = af_max
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
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        n = len(df)

        sig = np.zeros(n, dtype=int)
        if n < 2:
            return pd.Series(sig, index=df.index)

        # Seed the trend from the first bar; the classic Wilder recursion runs
        # bar by bar (SAR is path-dependent, exactly like the Pine version).
        up_trend = True
        af = self.af_step
        ep = high[0]
        sar = low[0]
        for i in range(1, n):
            sar = sar + af * (ep - sar)
            if up_trend:
                # dot may not exceed the prior two lows
                sar = min(sar, low[i - 1], low[i - 2] if i >= 2 else low[i - 1])
                if low[i] < sar:
                    up_trend = False
                    sar = ep
                    ep = low[i]
                    af = self.af_step
                elif high[i] > ep:
                    ep = high[i]
                    af = min(af + self.af_step, self.af_max)
            else:
                sar = max(sar, high[i - 1], high[i - 2] if i >= 2 else high[i - 1])
                if high[i] > sar:
                    up_trend = True
                    sar = ep
                    ep = high[i]
                    af = self.af_step
                elif low[i] < ep:
                    ep = low[i]
                    af = min(af + self.af_step, self.af_max)
            t = times[i]
            if self.trade_from <= t < self.flatten_at:
                if up_trend:
                    sig[i] = 1
                elif self.allow_short:
                    sig[i] = -1
        return pd.Series(sig, index=df.index)
