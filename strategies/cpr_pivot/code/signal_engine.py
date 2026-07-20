"""CPR + daily pivots — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of the Central Pivot Range (CPR), *the* classic NSE intraday framework.
From the PRIOR trading day's high/low/close we build the pivot ``P=(H+L+C)/3``,
the central range ``[BC=(H+L)/2, TC=2P−BC]`` (top/bottom taken as max/min of the
two, since TC can sit either side of BC), and use them as the day's fixed value
area. Price trading ABOVE the top of the central range is the bullish zone — we
hold long there and step aside when price falls back to/under the pivot ``P``.
The levels are computed once from yesterday and never change intraday, so there
is no repainting.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001). The
levels need one prior session, so day 1 of any tape is flat. With
``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 while price
trades BELOW the bottom of the central range, covered when it climbs back above
``P``. The no-arg ctor stays long-only.

Port note: ``buffer_pct`` (default 0) is a confirmation cushion beyond the level
(a fraction of price) to damp knife-edge flip-flops when price hugs the band.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Long above the central pivot range, flat back at the pivot — reset daily.

    Attributes:
        buffer_pct: Fractional cushion beyond a level required to act.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror short below the central range.
    """

    def __init__(
        self,
        buffer_pct: float = 0.0,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.buffer_pct = buffer_pct
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
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)

        # Prior-day H/L/C keyed by each trading date (the CPR anchor).
        uniq = sorted(set(days))
        prior = {}
        prev = None
        for d in uniq:
            if prev is not None:
                m = days == prev
                prior[d] = (float(high[m].max()), float(low[m].min()), float(close[m][-1]))
            prev = d

        sig = np.zeros(len(df), dtype=int)
        for d in uniq:
            if d not in prior:
                continue
            h, l, c = prior[d]
            p = (h + l + c) / 3.0
            bc = (h + l) / 2.0
            tc = 2.0 * p - bc
            top = max(tc, bc)
            bot = min(tc, bc)
            positions = np.where(days == d)[0]
            pos = 0
            for i in positions:
                t = times[i]
                if not (self.trade_from <= t < self.flatten_at):
                    pos = 0
                    continue
                if pos == 0:
                    if close[i] > top * (1.0 + self.buffer_pct):
                        pos = 1  # above the bullish value area
                    elif self.allow_short and close[i] < bot * (1.0 - self.buffer_pct):
                        pos = -1  # below the bearish value area
                elif pos == 1:
                    if close[i] < p:
                        pos = 0  # slipped back to value
                else:  # pos == -1
                    if close[i] > p:
                        pos = 0
                sig[i] = pos
        return pd.Series(sig, index=df.index)
