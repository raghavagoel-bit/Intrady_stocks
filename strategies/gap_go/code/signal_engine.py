"""Gap-up continuation — LONG-ONLY — NSE intraday, 15m bars.

If the day opens meaningfully above the previous day's close (a gap up), the
crowd that missed the move tends to chase it: stay long while the gap "goes"
(price holds above the day's open). No gap, no trade — this is a specialist
that sits out most days by design.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: on a
gap-DOWN day, short while price holds BELOW the day's open. Long-only by default.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Long while a gap-up day holds above its open.

    Attributes:
        min_gap_pct: Minimum open-vs-prev-close gap (%) to arm the day.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror short a gap-down day below its open.
    """

    def __init__(
        self,
        min_gap_pct: float = 0.5,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.min_gap_pct = min_gap_pct
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
        open_ = df["open"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)

        sig = np.zeros(len(df), dtype=int)
        prev_close = None
        for day in sorted(set(days)):
            mask = days == day
            day_open = open_[mask][0]
            if prev_close is not None and prev_close > 0:
                gap_pct = (day_open / prev_close - 1) * 100
                tradeable = np.array(
                    [self.trade_from <= t < self.flatten_at for t in times[mask]]
                )
                if gap_pct >= self.min_gap_pct:
                    holding = close[mask] > day_open
                    sig[mask] = np.where(tradeable & holding, 1, 0).astype(int)
                elif self.allow_short and gap_pct <= -self.min_gap_pct:
                    shorting = close[mask] < day_open
                    sig[mask] = np.where(tradeable & shorting, -1, 0).astype(int)
            prev_close = close[mask][-1]
        return pd.Series(sig, index=df.index)
