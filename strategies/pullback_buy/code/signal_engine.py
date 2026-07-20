"""VWAP pullback-buy — LONG-ONLY — for NSE intraday, 15m bars.

A second long-only setup so a 2–3 stock universe still produces enough trades
(ORB only fires on upside breaks, ~once/day/symbol). Intraday VWAP is the
canonical Indian day-trading reference: in an up day, price tends to pull back
toward VWAP and resume — so buy the reclaim.

Entry (when flat, after the 09:45 warmup, before the 15:00 flatten):
  - up day: current close > day VWAP, AND
  - a pullback just happened: the prior bar's low dipped to/under VWAP (within
    ``touch_band``), AND
  - reclaim: current bar closes back above VWAP and is green (close > prior close).
Exit: close falls ``exit_band`` below VWAP (trend lost), or the 15:00 flatten.

Runs through `IndiaIntradayEngine` (``intraday: true``). Next-bar-open fills, so
the flat at 15:00 squares off at 15:15 same day (DC-001).

Signal semantics: 1 = hold long, 0 = flat. With ``allow_short=True`` (the 3L
hybrid twin) the mirror is symmetric: on a DOWN day (close < VWAP) short a rally
that pokes UP to VWAP (prior high ≥ VWAP within the band) and is then rejected
(close back below VWAP and red); exit when close rises ``exit_band`` above VWAP.
The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Intraday VWAP-pullback long entries with a same-day-trend filter.

    Attributes:
        warmup_end: Skip entries before this time (opening noise; default 09:45).
        flatten_at: Time (IST) from which the strategy is flat (default 15:00).
        touch_band: How close to VWAP the pullback low must reach (fraction).
        exit_band: How far below VWAP price may fall before exiting (fraction).
        allow_short: hybrid twin — mirror short the VWAP-rejection on a down day.
    """

    def __init__(
        self,
        warmup_end_hour: int = 9,
        warmup_end_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        touch_band: float = 0.002,
        exit_band: float = 0.003,
        allow_short: bool = False,
    ):
        self.warmup_end = _dt.time(warmup_end_hour, warmup_end_minute)
        self.flatten_at = _dt.time(flatten_hour, flatten_minute)
        self.touch_band = touch_band
        self.exit_band = exit_band
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

    def _day_vwap(self, df: pd.DataFrame, days: np.ndarray) -> np.ndarray:
        """Cumulative intraday VWAP, reset each day."""
        typical = (df["high"] + df["low"] + df["close"]).to_numpy(dtype=float) / 3.0
        vol = df["volume"].to_numpy(dtype=float)
        vwap = np.full(len(df), np.nan)
        cum_pv = cum_v = 0.0
        cur = None
        for i in range(len(df)):
            if days[i] != cur:
                cur = days[i]
                cum_pv = cum_v = 0.0
            cum_pv += typical[i] * vol[i]
            cum_v += vol[i]
            vwap[i] = cum_pv / cum_v if cum_v > 0 else np.nan
        return vwap

    def _generate_one(self, df: pd.DataFrame) -> pd.Series:
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("Asia/Kolkata")
        times = np.array([t.time() for t in idx])
        days = np.array([t.date() for t in idx])

        close = df["close"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        vwap = self._day_vwap(df, days)

        sig = np.zeros(len(df), dtype=int)
        pos = 0
        cur_day = None

        for i in range(len(df)):
            if days[i] != cur_day:
                cur_day = days[i]
                pos = 0

            t = times[i]
            if t < self.warmup_end or t >= self.flatten_at or np.isnan(vwap[i]):
                pos = 0
                sig[i] = pos
                continue

            if pos == 1:
                if close[i] < vwap[i] * (1 - self.exit_band):
                    pos = 0  # lost the up-trend
            elif pos == -1:
                if close[i] > vwap[i] * (1 + self.exit_band):
                    pos = 0  # lost the down-trend
            else:
                pulled_back = (
                    i > 0 and days[i - 1] == cur_day
                    and low[i - 1] <= vwap[i - 1] * (1 + self.touch_band)
                )
                reclaim = close[i] > vwap[i] and i > 0 and close[i] > close[i - 1]
                if pulled_back and reclaim:
                    pos = 1
                elif self.allow_short:
                    pushed_up = (
                        i > 0 and days[i - 1] == cur_day
                        and high[i - 1] >= vwap[i - 1] * (1 - self.touch_band)
                    )
                    reject = close[i] < vwap[i] and i > 0 and close[i] < close[i - 1]
                    if pushed_up and reject:
                        pos = -1

            sig[i] = pos
        return pd.Series(sig, index=df.index)
