"""Opening Range Breakout (ORB) — LONG-ONLY — for NSE intraday, 15m bars.

The classic Indian intraday setup, upside only: the first 30 minutes (09:15–09:45
IST) define the opening range; a 15m bar that CLOSES above the range high with
expanded volume goes long (MIS). One long entry per day. Exit when a bar closes
back below the range midpoint (failed breakout), or at the 15:00 flatten.

Runs through `IndiaIntradayEngine` (set ``intraday: true`` in config). Fills are
next-bar-open, so the strategy goes flat at **15:00** (one bar before the 15:15
close) — the square-off then executes at 15:15 the same day (see DC-001).

Signal semantics: 1 = hold long, 0 = flat. With ``allow_short=True`` (the 3L
hybrid twin) the mirror is symmetric: −1 on a volume-backed 15m close BELOW the
opening-range LOW, exited when a bar closes back above the range midpoint. One
short entry per day. The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """15m opening-range breakout, long-only, with volume confirmation.

    Attributes:
        or_end: Time (IST) when the opening range is fixed (default 09:45).
        flatten_at: Time (IST) from which the strategy is flat (default 15:00).
        vol_window: Rolling bars for the volume baseline.
        vol_mult: Entry-bar volume must exceed vol_mult x rolling mean.
            (Defaults 12/1.5 set by the 2026-07-15 grid tune — stricter volume
            confirmation, fewer/better breakouts; validated out-of-sample in
            docs/BACKTEST_REPORT.md.)
    """

    def __init__(
        self,
        or_end_hour: int = 9,
        or_end_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        vol_window: int = 12,
        vol_mult: float = 1.5,
        allow_short: bool = False,
    ):
        self.or_end = _dt.time(or_end_hour, or_end_minute)
        self.flatten_at = _dt.time(flatten_hour, flatten_minute)
        self.vol_window = vol_window
        self.vol_mult = vol_mult
        self.allow_short = allow_short

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """Generate long/flat signals per symbol.

        Args:
            data_map: Symbol -> 15m OHLCV DataFrame with a DatetimeIndex
                (tz-aware is converted to IST; tz-naive is treated as
                exchange-local time).

        Returns:
            Symbol -> signal Series (1 = long, 0 = flat).
        """
        return {code: self._generate_one(df) for code, df in data_map.items()}

    def _generate_one(self, df: pd.DataFrame) -> pd.Series:
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("Asia/Kolkata")
        times = np.array([t.time() for t in idx])
        days = np.array([t.date() for t in idx])

        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)
        vol_ma = (
            pd.Series(volume).rolling(self.vol_window, min_periods=5).mean().to_numpy()
        )

        low = df["low"].to_numpy(dtype=float)

        sig = np.zeros(len(df), dtype=int)
        pos = 0
        traded_long = False
        traded_short = False
        cur_day = None
        or_high = or_low = or_mid = np.nan

        for i in range(len(df)):
            if days[i] != cur_day:
                cur_day = days[i]
                pos = 0
                traded_long = False
                traded_short = False
                day_or = (days == cur_day) & (times < self.or_end)
                if day_or.any():
                    or_high = high[day_or].max()
                    or_low = low[day_or].min()
                    or_mid = (or_high + or_low) / 2
                else:
                    or_high = or_low = or_mid = np.nan

            t = times[i]
            # Flat outside the tradeable window (before OR set, or at/after flatten).
            if t < self.or_end or t >= self.flatten_at or np.isnan(or_high):
                pos = 0
                sig[i] = pos
                continue

            vol_ok = vol_ma[i] > 0 and volume[i] > self.vol_mult * vol_ma[i]

            if pos == 0:
                if not traded_long and close[i] > or_high and vol_ok:
                    pos, traded_long = 1, True
                elif self.allow_short and not traded_short and close[i] < or_low and vol_ok:
                    pos, traded_short = -1, True
            elif pos == 1 and close[i] < or_mid:
                pos = 0  # failed breakout: back below midpoint
            elif pos == -1 and close[i] > or_mid:
                pos = 0  # failed breakdown: back above midpoint

            sig[i] = pos
        return pd.Series(sig, index=df.index)
