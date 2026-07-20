"""Squeeze Momentum (LazyBear) — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of LazyBear's Squeeze Momentum Indicator: a "squeeze" is on while the
Bollinger Bands sit inside the Keltner Channel (volatility compressed). We
enter long on the bar the squeeze releases ("fires") with positive momentum
(within a short grace window after the release, since momentum's nested
rolling windows warm up a few bars late), and stay in while momentum remains
positive. Momentum is the linear-regression endpoint of the close's deviation
from the Donchian/SMA midline, as in Pine.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 on a
squeeze release with NEGATIVE momentum, held while momentum stays negative.
Long-only by default.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


def _linreg_endpoint(values: pd.Series, window: int) -> np.ndarray:
    """Rolling linear-regression value at the last bar of each window (Pine linreg)."""
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()

    def _fit(y: np.ndarray) -> float:
        slope = ((x - x_mean) * (y - y.mean())).sum() / denom
        return y.mean() + slope * (window - 1 - x_mean)

    return values.rolling(window, min_periods=window).apply(_fit, raw=True).to_numpy()


class SignalEngine:
    """BB-inside-KC squeeze fire with rising momentum, long-only intraday.

    Attributes:
        length: Lookback for BB, KC, and the momentum linreg (TV default 20).
        bb_mult: Bollinger band width in standard deviations (TV default 2.0).
        kc_mult: Keltner channel width in mean true ranges (TV default 1.5).
        fire_grace: Bars after a squeeze release during which a positive
            momentum reading still counts as an entry.
        trade_from / flatten_at: IST tradeable window bounds.
    """

    def __init__(
        self,
        length: int = 20,
        bb_mult: float = 2.0,
        kc_mult: float = 1.0,
        fire_grace: int = 5,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.length = length
        self.bb_mult = bb_mult
        self.kc_mult = kc_mult
        self.fire_grace = fire_grace
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
        n = self.length

        std = close.rolling(n, min_periods=n).std(ddof=0)
        sma = close.rolling(n, min_periods=n).mean()
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        range_ma = tr.rolling(n, min_periods=n).mean()
        # Squeeze on: BB (sma ± bb_mult*std) entirely inside KC (sma ± kc_mult*rangeMA).
        squeeze_on = (self.bb_mult * std < self.kc_mult * range_ma).to_numpy()

        hh = high.rolling(n, min_periods=n).max()
        ll = low.rolling(n, min_periods=n).min()
        midline = ((hh + ll) / 2.0 + sma) / 2.0
        mom = _linreg_endpoint(close - midline, n)
        sq_valid = ~(std.isna() | range_ma.isna()).to_numpy()
        mom_valid = ~np.isnan(mom)

        sig = np.zeros(len(df), dtype=int)
        pos = 0
        since_fire = len(sig) + 1  # "no fire seen yet"
        for i in range(len(sig)):
            # Fire tracking runs on every bar (a release just before the
            # window opens is still tradeable within the grace period).
            if i > 0 and sq_valid[i] and sq_valid[i - 1]:
                if squeeze_on[i - 1] and not squeeze_on[i]:
                    since_fire = 0
                else:
                    since_fire += 1
            t = times[i]
            if not (self.trade_from <= t < self.flatten_at):
                pos = 0
                continue
            if not mom_valid[i]:
                continue
            if pos == 0:
                if since_fire <= self.fire_grace and mom[i] > 0:
                    pos = 1
                elif self.allow_short and since_fire <= self.fire_grace and mom[i] < 0:
                    pos = -1
            elif pos == 1 and mom[i] <= 0:
                pos = 0  # upside momentum rolled over — the move is spent
            elif pos == -1 and mom[i] >= 0:
                pos = 0  # downside momentum rolled over
            sig[i] = pos
        return pd.Series(sig, index=df.index)
