"""Bollinger + RSI Double — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of ChartArt's "Bollinger Bands + RSI, Double Strategy": a mean-reversion
entry that requires BOTH an extended price (a close below the lower Bollinger
band) AND a stretched RSI (below an oversold level) before buying the snap-back.
Requiring the two together filters the lone-signal whipsaws each indicator throws
on its own. Exit back at the middle band (the rolling mean) or when RSI normalises.

Bands + RSI roll across the whole lookback (a local mean spanning yesterday's
close is still a valid reversion anchor). Signals: 1 = hold long, 0 = flat. Flat
before 09:45 and from 15:00 (DC-001). With ``allow_short=True`` (the 3L hybrid
twin) the mirror is symmetric: short when the close pokes ABOVE the upper band
AND RSI is overbought, covering at the middle band. The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """Buy the lower-band + oversold-RSI stretch; exit at the middle band.

    Attributes:
        window: Rolling window (bars) for the band mean/std.
        band_k: Band width in standard deviations.
        rsi_len: RSI lookback in bars.
        rsi_low: RSI must be at/below this to confirm a long (oversold).
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror short the upper-band + overbought poke.
    """

    def __init__(
        self,
        window: int = 20,
        band_k: float = 2.0,
        rsi_len: int = 14,
        rsi_low: float = 35.0,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.window = window
        self.band_k = band_k
        self.rsi_len = rsi_len
        self.rsi_low = rsi_low
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
        close = pd.Series(df["close"].to_numpy(dtype=float))

        mean = close.rolling(self.window, min_periods=self.window).mean()
        std = close.rolling(self.window, min_periods=self.window).std()
        lower = (mean - self.band_k * std).to_numpy()
        upper = (mean + self.band_k * std).to_numpy()
        mid = mean.to_numpy()
        rsi = self._rsi(close)
        c = close.to_numpy()
        rsi_high = 100.0 - self.rsi_low

        sig = np.zeros(len(df), dtype=int)
        pos = 0
        for i in range(len(c)):
            t = times[i]
            if not (self.trade_from <= t < self.flatten_at):
                pos = 0
                continue
            if np.isnan(lower[i]):
                continue
            if pos == 0:
                if c[i] < lower[i] and rsi[i] <= self.rsi_low:
                    pos = 1  # oversold stretch below the lower band
                elif self.allow_short and c[i] > upper[i] and rsi[i] >= rsi_high:
                    pos = -1  # overbought poke above the upper band
            elif pos == 1:
                if c[i] >= mid[i] or rsi[i] >= 50.0:
                    pos = 0  # reverted to the mean
            else:  # pos == -1
                if c[i] <= mid[i] or rsi[i] <= 50.0:
                    pos = 0
            sig[i] = pos
        return pd.Series(sig, index=df.index)
