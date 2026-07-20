"""Connors RSI(2) mean reversion — LONG-ONLY — NSE intraday, 15m bars. (TV port)

Port of Larry Connors' short-lookback reversion. Trade only WITH the higher
trend (close above a long moving average), and buy a sharp pullback when the
2-period RSI is deeply oversold; exit when RSI(2) snaps back up. The 2-bar RSI is
extremely sensitive — it spikes to its extremes on a single strong bar — so it
picks the fast counter-trend dips a slow oscillator misses. This is the
short-lookback reversion archetype not covered by our (14-period) RSI engines.

Port note: Connors filters on the 200-SMA, but a literal 200-bar 15m SMA can
never be valid inside the live 120-bar lookback, so the trend filter is
adapted to ``trend_ma=100`` (same adaptation as ``golden_cross`` / ``macd_sma200``).

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001). With
``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 when RSI(2)
is deeply overbought AND price is below the trend MA, covered when RSI(2) falls
back. The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Buy a deep RSI(2) dip in an up-trend; exit on the RSI(2) snap-back.

    Attributes:
        rsi_len: RSI lookback (Connors' 2).
        trend_ma: Trend filter SMA length (200 adapted to 100 for the live lookback).
        rsi_entry: RSI(2) at/below which a long is armed (oversold).
        rsi_exit: RSI(2) at/above which the long is closed.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror short a deep RSI(2) overbought below the MA.
    """

    def __init__(
        self,
        rsi_len: int = 2,
        trend_ma: int = 100,
        rsi_entry: float = 5.0,
        rsi_exit: float = 70.0,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.rsi_len = rsi_len
        self.trend_ma = trend_ma
        self.rsi_entry = rsi_entry
        self.rsi_exit = rsi_exit
        self.trade_from = _dt.time(trade_from_hour, trade_from_minute)
        self.flatten_at = _dt.time(flatten_hour, flatten_minute)
        self.allow_short = allow_short

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """Generate long/flat signals per symbol (see module docstring)."""
        return {code: self._generate_one(df) for code, df in data_map.items()}

    def _rsi(self, close: pd.Series) -> np.ndarray:
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.rolling(self.rsi_len, min_periods=self.rsi_len).mean()
        avg_loss = loss.rolling(self.rsi_len, min_periods=self.rsi_len).mean()
        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        # RSI(2) hits the degenerate ends constantly: an all-up 2-bar window has
        # zero average loss (rs = NaN) and is fully overbought (100), not neutral.
        rsi = rsi.where(~((avg_loss == 0.0) & (avg_gain > 0.0)), 100.0)
        return rsi.fillna(50.0).to_numpy()

    def _generate_one(self, df: pd.DataFrame) -> pd.Series:
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("Asia/Kolkata")
        times = np.array([t.time() for t in idx])
        close = pd.Series(df["close"].to_numpy(dtype=float))

        rsi = self._rsi(close)
        sma = close.rolling(self.trend_ma, min_periods=self.trend_ma).mean().to_numpy()
        c = close.to_numpy()
        entry_hi = 100.0 - self.rsi_entry   # overbought mirror threshold
        exit_lo = 100.0 - self.rsi_exit     # short cover threshold

        sig = np.zeros(len(df), dtype=int)
        pos = 0
        for i in range(len(c)):
            t = times[i]
            if not (self.trade_from <= t < self.flatten_at):
                pos = 0
                continue
            if np.isnan(sma[i]):
                continue
            if pos == 0:
                if rsi[i] < self.rsi_entry and c[i] > sma[i]:
                    pos = 1
                elif self.allow_short and rsi[i] > entry_hi and c[i] < sma[i]:
                    pos = -1
            elif pos == 1:
                if rsi[i] > self.rsi_exit:
                    pos = 0
            else:  # pos == -1
                if rsi[i] < exit_lo:
                    pos = 0
            sig[i] = pos
        return pd.Series(sig, index=df.index)
