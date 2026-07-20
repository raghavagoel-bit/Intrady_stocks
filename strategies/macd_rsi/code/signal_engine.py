"""MACD bull crossover + RSI oversold — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of Trebor_Namor's "MACD Bull Crossover and RSI Oversold" strategy: enter long
only when a fresh MACD bullish crossover coincides with RSI having been recently
oversold — momentum turning up out of a genuine dip, not chasing a MACD cross at the
top of an extended run. Exit on the MACD bearish crossover or when RSI runs overbought.

MACD and RSI reset each day (like macd_cross / momentum_rsi) so overnight gaps never
leak into the oscillator state. Signals: 1 = hold long, 0 = flat. Flat before 09:45
and from 15:00 (DC-001). With ``allow_short=True`` (the 3L hybrid twin) the mirror is
symmetric: short on a MACD bearish crossover while RSI has been recently overbought,
cover on the bullish crossover or RSI oversold. The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """MACD-crossover entries confirmed by a recent RSI extreme, reset daily.

    Attributes:
        fast / slow / signal_span: EMA spans (bars) of the MACD stack.
        rsi_len: RSI lookback in bars.
        rsi_os: RSI must have dipped to/below this within ``recent`` bars to arm a long.
        rsi_ob: RSI at/above this closes an open long (overbought).
        recent: How many bars back the RSI extreme still counts.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror short a bearish cross out of overbought.
    """

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal_span: int = 9,
        rsi_len: int = 14,
        rsi_os: float = 40.0,
        rsi_ob: float = 70.0,
        recent: int = 6,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.fast = fast
        self.slow = slow
        self.signal_span = signal_span
        self.rsi_len = rsi_len
        self.rsi_os = rsi_os
        self.rsi_ob = rsi_ob
        self.recent = recent
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
        return rsi.fillna(50.0).to_numpy()

    def _generate_one(self, df: pd.DataFrame) -> pd.Series:
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("Asia/Kolkata")
        times = np.array([t.time() for t in idx])
        days = np.array([t.date() for t in idx])
        close_all = pd.Series(df["close"].to_numpy(dtype=float))
        rsi_ob_mirror = 100.0 - self.rsi_ob
        rsi_os_mirror = 100.0 - self.rsi_os

        sig = np.zeros(len(df), dtype=int)
        for day in np.unique(days):
            mask = days == day
            day_close = close_all[mask].reset_index(drop=True)
            if len(day_close) < 3:
                continue
            macd = (
                day_close.ewm(span=self.fast, adjust=False).mean()
                - day_close.ewm(span=self.slow, adjust=False).mean()
            ).to_numpy()
            signal = pd.Series(macd).ewm(span=self.signal_span, adjust=False).mean().to_numpy()
            rsi = self._rsi(day_close)
            day_times = times[mask]

            day_sig = np.zeros(len(day_close), dtype=int)
            pos = 0
            for i in range(len(day_close)):
                t = day_times[i]
                if not (self.trade_from <= t < self.flatten_at):
                    pos = 0
                    day_sig[i] = pos
                    continue
                lo = max(0, i - self.recent)
                bull_cross = i >= 1 and macd[i] > signal[i] and macd[i - 1] <= signal[i - 1]
                bear_cross = i >= 1 and macd[i] < signal[i] and macd[i - 1] >= signal[i - 1]
                was_os = rsi[lo : i + 1].min() <= self.rsi_os
                was_ob = rsi[lo : i + 1].max() >= rsi_os_mirror
                if pos == 0:
                    if bull_cross and was_os:
                        pos = 1
                    elif self.allow_short and bear_cross and was_ob:
                        pos = -1
                elif pos == 1:
                    if bear_cross or rsi[i] >= self.rsi_ob:
                        pos = 0
                elif pos == -1:
                    if bull_cross or rsi[i] <= rsi_ob_mirror:
                        pos = 0
                day_sig[i] = pos
            sig[mask] = day_sig
        return pd.Series(sig, index=df.index)
