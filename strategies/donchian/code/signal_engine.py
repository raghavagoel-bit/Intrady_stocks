"""Donchian channel breakout (Turtle) — LONG-ONLY — NSE intraday, 15m bars. (TV port)

Port of the classic Turtle/Donchian system. Long when the close breaks above the
highest high of the prior ``entry_bars`` bars; exit when the close falls below
the lowest low of the prior ``exit_bars`` bars (a shorter channel, so winners are
given room while losers are cut faster). Distinct from ``range_break`` (which
breaks the fixed opening-session box) — this is a continuously rolling channel,
the textbook breakout archetype.

Channels roll across the whole lookback (a breakout of yesterday's extreme is
still a valid signal); the entry/exit still respect the intraday window. Signals:
1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001). With
``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 on a close
below the prior ``entry_bars`` low, covered on a close above the prior
``exit_bars`` high. The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Breakout of the rolling Donchian channel, shorter channel for the exit.

    Attributes:
        entry_bars: Prior bars whose high/low the entry must break.
        exit_bars: Prior bars whose low/high triggers the exit (shorter).
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror short on a lower-channel break.
    """

    def __init__(
        self,
        entry_bars: int = 20,
        exit_bars: int = 10,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.entry_bars = entry_bars
        self.exit_bars = exit_bars
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
        close = df["close"].to_numpy(dtype=float)

        up_break = high.shift(1).rolling(
            self.entry_bars, min_periods=self.entry_bars).max().to_numpy()
        dn_break = low.shift(1).rolling(
            self.entry_bars, min_periods=self.entry_bars).min().to_numpy()
        exit_low = low.shift(1).rolling(
            self.exit_bars, min_periods=self.exit_bars).min().to_numpy()
        exit_high = high.shift(1).rolling(
            self.exit_bars, min_periods=self.exit_bars).max().to_numpy()

        sig = np.zeros(len(df), dtype=int)
        pos = 0
        for i in range(len(close)):
            t = times[i]
            if not (self.trade_from <= t < self.flatten_at):
                pos = 0
                continue
            if (np.isnan(up_break[i]) or np.isnan(dn_break[i])
                    or np.isnan(exit_low[i]) or np.isnan(exit_high[i])):
                continue
            if pos == 0:
                if close[i] > up_break[i]:
                    pos = 1
                elif self.allow_short and close[i] < dn_break[i]:
                    pos = -1
            elif pos == 1:
                if close[i] < exit_low[i]:
                    pos = 0
            else:  # pos == -1
                if close[i] > exit_high[i]:
                    pos = 0
            sig[i] = pos
        return pd.Series(sig, index=df.index)
