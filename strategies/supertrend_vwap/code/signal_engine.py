"""Supertrend + VWAP confluence — LONG-ONLY — NSE intraday, 15m bars. (TV port)

A popular Indian-intraday confluence filter: take the trend from Supertrend but
only act when price also agrees with the session's institutional fair value
(VWAP). Long only when the Supertrend is in an UP-trend AND the close is above
the day's VWAP; the moment either condition drops out, step to flat. Requiring
both gates cuts the whipsaws each piece throws alone (Supertrend chops in a
range; a bare VWAP cross fires on noise). Both pieces are already used by sibling
engines (``supertrend`` and ``vwap_hold``) — this run-dir just ANDs them.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 while
the Supertrend is DOWN and the close is below VWAP. The no-arg ctor stays
long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Long when Supertrend-up and price>VWAP; mirror short when both flip.

    Attributes:
        atr_window: ATR lookback (bars) for the Supertrend bands.
        mult: Band distance in ATRs from hl2.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — short when Supertrend-down and price<VWAP.
    """

    def __init__(
        self,
        atr_window: int = 10,
        mult: float = 2.0,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
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
        days = np.array([t.date() for t in idx])
        high = pd.Series(df["high"].to_numpy(dtype=float))
        low = pd.Series(df["low"].to_numpy(dtype=float))
        close = pd.Series(df["close"].to_numpy(dtype=float))
        volume = df["volume"].to_numpy(dtype=float)

        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        atr = tr.rolling(self.atr_window, min_periods=self.atr_window).mean().to_numpy()
        hl2 = ((high + low) / 2.0).to_numpy()
        c = close.to_numpy()
        hi = high.to_numpy()
        lo = low.to_numpy()

        # Ratcheted Supertrend trend state (sequential, as in the Pine source).
        up_trend_arr = np.zeros(len(df), dtype=bool)
        up_trend = False
        final_upper = np.nan
        final_lower = np.nan
        for i in range(len(c)):
            if np.isnan(atr[i]):
                up_trend_arr[i] = up_trend
                continue
            basic_upper = hl2[i] + self.mult * atr[i]
            basic_lower = hl2[i] - self.mult * atr[i]
            if np.isnan(final_upper):
                final_upper, final_lower = basic_upper, basic_lower
            else:
                if basic_upper < final_upper or c[i - 1] > final_upper:
                    final_upper = basic_upper
                if basic_lower > final_lower or c[i - 1] < final_lower:
                    final_lower = basic_lower
            if up_trend:
                if c[i] < final_lower:
                    up_trend = False
            else:
                if c[i] > final_upper:
                    up_trend = True
            up_trend_arr[i] = up_trend

        # Session VWAP + confluence gate.
        sig = np.zeros(len(df), dtype=int)
        for day in sorted(set(days)):
            positions = np.where(days == day)[0]
            typical = (hi[positions] + lo[positions] + c[positions]) / 3.0
            vol = np.maximum(volume[positions], 1.0)
            vwap = np.cumsum(typical * vol) / np.cumsum(vol)
            for j, i in enumerate(positions):
                t = times[i]
                if not (self.trade_from <= t < self.flatten_at):
                    continue
                if up_trend_arr[i] and c[i] > vwap[j]:
                    sig[i] = 1
                elif self.allow_short and (not up_trend_arr[i]) and c[i] < vwap[j]:
                    sig[i] = -1
        return pd.Series(sig, index=df.index)
