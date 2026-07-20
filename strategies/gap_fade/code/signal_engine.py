"""Gap-down reversal ("fade the gap") — LONG-ONLY — NSE intraday, 15m bars.

If the day opens meaningfully below the previous close (a gap down), an
oversold open often snaps back. Wait for proof of the reversal — a close back
above the opening bar's high — then ride the recovery while price holds above
the day's open region. A specialist that sits out non-gap days by design.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: on a
gap-UP day, wait for a confirmed rejection (a close back BELOW the opening bar's
low) then short while price holds below the day's open. Long-only by default.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Buy a confirmed gap-down recovery; hold while it keeps recovering.

    Attributes:
        min_gap_pct: Minimum downward gap (%) to arm the day.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror short a confirmed gap-up rejection.
    """

    def __init__(
        self,
        min_gap_pct: float = 0.3,
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
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)

        sig = np.zeros(len(df), dtype=int)
        prev_close = None
        for day in sorted(set(days)):
            mask = days == day
            positions = np.where(mask)[0]
            day_open = open_[positions[0]]
            first_high = high[positions[0]]
            first_low = low[positions[0]]
            gap_pct = (
                (day_open / prev_close - 1) * 100
                if prev_close is not None and prev_close > 0
                else 0.0
            )
            gapped_down = prev_close is not None and prev_close > 0 and gap_pct <= -self.min_gap_pct
            gapped_up = prev_close is not None and prev_close > 0 and gap_pct >= self.min_gap_pct
            if gapped_down:
                long_now = False
                for i in positions:
                    t = times[i]
                    if not (self.trade_from <= t < self.flatten_at):
                        long_now = False
                        continue
                    if not long_now and close[i] > first_high:
                        long_now = True  # reversal confirmed
                    elif long_now and close[i] < day_open:
                        long_now = False  # recovery failed
                    sig[i] = 1 if long_now else 0
            elif self.allow_short and gapped_up:
                short_now = False
                for i in positions:
                    t = times[i]
                    if not (self.trade_from <= t < self.flatten_at):
                        short_now = False
                        continue
                    if not short_now and close[i] < first_low:
                        short_now = True  # rejection confirmed
                    elif short_now and close[i] > day_open:
                        short_now = False  # rejection failed
                    sig[i] = -1 if short_now else 0
            prev_close = close[positions[-1]]
        return pd.Series(sig, index=df.index)
