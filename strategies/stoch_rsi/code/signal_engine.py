"""Stochastic RSI cross — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of the standard Stochastic RSI momentum oscillator: a Stochastic applied to
RSI (double-smoothed), which turns faster than either alone. We compute RSI, run
a ``stoch_len`` Stochastic over it, then smooth to ``%K`` and ``%D``. Long when
``%K`` crosses UP through ``%D`` while coming out of the oversold zone (the fresh
momentum turn); exit when ``%K`` crosses back below ``%D`` or reaches overbought.
Distinct from ``ao_stoch`` (an AO-gated raw Stochastic) — this is the
RSI-of-Stochastic double-smoothed cross.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001). With
``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 on a ``%K``
cross DOWN through ``%D`` out of the overbought zone, covered on the up-cross or a
drop into oversold. The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Double-smoothed StochRSI %K/%D cross out of the extreme zones.

    Attributes:
        rsi_len: RSI lookback (bars).
        stoch_len: Stochastic lookback applied to the RSI.
        smooth_k / smooth_d: SMA smoothing for %K and %D.
        oversold / overbought: extreme-zone bounds that gate entries.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror short on the down-cross out of overbought.
    """

    def __init__(
        self,
        rsi_len: int = 14,
        stoch_len: int = 14,
        smooth_k: int = 3,
        smooth_d: int = 3,
        oversold: float = 20.0,
        overbought: float = 80.0,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.rsi_len = rsi_len
        self.stoch_len = stoch_len
        self.smooth_k = smooth_k
        self.smooth_d = smooth_d
        self.oversold = oversold
        self.overbought = overbought
        self.trade_from = _dt.time(trade_from_hour, trade_from_minute)
        self.flatten_at = _dt.time(flatten_hour, flatten_minute)
        self.allow_short = allow_short

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """Generate long/flat signals per symbol (see module docstring)."""
        return {code: self._generate_one(df) for code, df in data_map.items()}

    def _rsi(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.rolling(self.rsi_len, min_periods=self.rsi_len).mean()
        avg_loss = loss.rolling(self.rsi_len, min_periods=self.rsi_len).mean()
        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        return (100.0 - (100.0 / (1.0 + rs)))

    def _generate_one(self, df: pd.DataFrame) -> pd.Series:
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("Asia/Kolkata")
        times = np.array([t.time() for t in idx])
        close = pd.Series(df["close"].to_numpy(dtype=float))

        rsi = self._rsi(close)
        low_r = rsi.rolling(self.stoch_len, min_periods=self.stoch_len).min()
        high_r = rsi.rolling(self.stoch_len, min_periods=self.stoch_len).max()
        stoch = (rsi - low_r) / (high_r - low_r).replace(0.0, np.nan) * 100.0
        k = stoch.rolling(self.smooth_k, min_periods=self.smooth_k).mean().to_numpy()
        d = pd.Series(k).rolling(self.smooth_d, min_periods=self.smooth_d).mean().to_numpy()

        sig = np.zeros(len(df), dtype=int)
        pos = 0
        for i in range(len(k)):
            t = times[i]
            if not (self.trade_from <= t < self.flatten_at):
                pos = 0
                continue
            if i == 0 or np.isnan(k[i]) or np.isnan(d[i]) or np.isnan(k[i - 1]) or np.isnan(d[i - 1]):
                continue
            cross_up = k[i] > d[i] and k[i - 1] <= d[i - 1]
            cross_dn = k[i] < d[i] and k[i - 1] >= d[i - 1]
            if pos == 0:
                if cross_up and k[i - 1] < self.oversold:
                    pos = 1
                elif self.allow_short and cross_dn and k[i - 1] > self.overbought:
                    pos = -1
            elif pos == 1:
                if cross_dn or k[i] > self.overbought:
                    pos = 0
            else:  # pos == -1
                if cross_up or k[i] < self.oversold:
                    pos = 0
            sig[i] = pos
        return pd.Series(sig, index=df.index)
