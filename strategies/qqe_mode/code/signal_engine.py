"""QQE Mode — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of the QQE (Quantitative Qualitative Estimation) signal popular on
TradingView: Wilder RSI smoothed with a short ema, trailed by a stop line
that sits a QQE-factor multiple of the RSI's own smoothed volatility away
and only ratchets toward the RSI. We are long while the smoothed RSI is
above its trailing line AND above 50 (bull side only), inside the window.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 while
the smoothed RSI is BELOW its trailing line AND below 50 (bear side). The no-arg
ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


def _wilder_rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0).ewm(alpha=1.0 / window, adjust=False).mean()
    loss = (-delta.clip(upper=0.0)).ewm(alpha=1.0 / window, adjust=False).mean()
    rs = gain / loss.replace(0.0, np.nan)
    return (100.0 - 100.0 / (1.0 + rs)).fillna(50.0)


class SignalEngine:
    """Smoothed-RSI vs QQE trailing line, bull side only, intraday.

    Attributes:
        rsi_window: Wilder RSI lookback (TV default 14).
        smooth: ema applied to the RSI (TV "RSI smoothing", default 5).
        qqe_factor: Trail distance multiple (TV fast QQE default 4.238).
        wilders: Smoothing length for the RSI's volatility (2*rsi_window-1).
        trade_from / flatten_at: IST tradeable window bounds.
    """

    def __init__(
        self,
        rsi_window: int = 14,
        smooth: int = 5,
        qqe_factor: float = 4.238,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.rsi_window = rsi_window
        self.smooth = smooth
        self.qqe_factor = qqe_factor
        self.wilders = 2 * rsi_window - 1
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
        close = pd.Series(df["close"].to_numpy(dtype=float))

        rsi_ma = _wilder_rsi(close, self.rsi_window).ewm(
            span=self.smooth, adjust=False
        ).mean()
        atr_rsi = rsi_ma.diff().abs()
        dar = (
            atr_rsi.ewm(alpha=1.0 / self.wilders, adjust=False).mean()
            .ewm(alpha=1.0 / self.wilders, adjust=False).mean()
            * self.qqe_factor
        )
        r = rsi_ma.to_numpy()
        band = dar.to_numpy()
        # Soft ema warm-up: skip the RSI window plus one Wilder length as burn-in.
        burn_in = self.rsi_window + self.wilders

        sig = np.zeros(len(df), dtype=int)
        trail = np.nan
        for i in range(len(sig)):
            if i < burn_in or np.isnan(band[i]):
                continue
            if np.isnan(trail):
                trail = r[i] - band[i]
            elif r[i] > trail and r[i - 1] > trail:
                trail = max(trail, r[i] - band[i])   # ratchet up under the RSI
            elif r[i] < trail and r[i - 1] < trail:
                trail = min(trail, r[i] + band[i])   # ratchet down above the RSI
            elif r[i] > trail:
                trail = r[i] - band[i]               # flip below
            else:
                trail = r[i] + band[i]               # flip above
            t = times[i]
            in_window = self.trade_from <= t < self.flatten_at
            long_ok = r[i] > trail and r[i] > 50.0
            short_ok = r[i] < trail and r[i] < 50.0
            if long_ok and in_window:
                sig[i] = 1
            elif self.allow_short and short_ok and in_window:
                sig[i] = -1
        return pd.Series(sig, index=df.index)
