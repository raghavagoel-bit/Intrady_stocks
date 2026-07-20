"""Flawless Victory (15m) — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of Trebor_Namor's "Flawless Victory Strategy - 15min" (a Machine-D derived
BB + RSI + MFI system, built and tuned specifically for 15-minute bars). Entry: the
close RECLAIMS the lower Bollinger band (was below it last bar, closes back inside) —
the moment selling exhausts — while RSI has turned back above a floor and money-flow
(MFI) is not overheated. Requiring the reclaim (rather than buying while still under
the band) is the "buy strength returning, not the falling knife" idea; the RSI floor
is tuned down to 30 for 15m bars (on intraday, a 2σ reclaim bar sits well below the
daily-chart's 42). Exit: a close back above the upper band with RSI overbought, a
failed reclaim (back under the band), else the 15:00 flatten.

Bands / RSI / MFI roll across the whole lookback. Signals: 1 = hold long, 0 = flat.
Flat before 09:45 and from 15:00 (DC-001). With ``allow_short=True`` (the 3L hybrid
twin) the mirror is symmetric: short a close that fades back below the upper band with
RSI capped and MFI cool, cover on the lower-band reclaim / upper-band pop / flatten.
No-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """15m Bollinger + RSI + MFI reversion (Flawless Victory), intraday.

    Attributes:
        window: Bollinger window (bars); band_k: band width in std devs.
        rsi_len: RSI lookback; rsi_floor: a long needs RSI at/above this (v1: 42).
        rsi_exit: an open long exits at/above this RSI on an upper-band close.
        mfi_len: Money-Flow-Index lookback; mfi_gate: a long needs MFI below this.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror the upper-band short.
    """

    def __init__(
        self,
        window: int = 20,
        band_k: float = 2.0,
        rsi_len: int = 14,
        rsi_floor: float = 30.0,
        rsi_exit: float = 70.0,
        mfi_len: int = 14,
        mfi_gate: float = 60.0,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.window = window
        self.band_k = band_k
        self.rsi_len = rsi_len
        self.rsi_floor = rsi_floor
        self.rsi_exit = rsi_exit
        self.mfi_len = mfi_len
        self.mfi_gate = mfi_gate
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
        return (100.0 - (100.0 / (1.0 + rs))).fillna(50.0).to_numpy()

    def _mfi(self, high, low, close, volume) -> np.ndarray:
        tp = (high + low + close) / 3.0
        flow = tp * volume
        up = flow.where(tp > tp.shift(1), 0.0)
        dn = flow.where(tp < tp.shift(1), 0.0)
        pos = up.rolling(self.mfi_len, min_periods=self.mfi_len).sum()
        neg = dn.rolling(self.mfi_len, min_periods=self.mfi_len).sum()
        ratio = pos / neg.replace(0.0, np.nan)
        return (100.0 - (100.0 / (1.0 + ratio))).fillna(50.0).to_numpy()

    def _generate_one(self, df: pd.DataFrame) -> pd.Series:
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("Asia/Kolkata")
        times = np.array([t.time() for t in idx])
        high = pd.Series(df["high"].to_numpy(dtype=float))
        low = pd.Series(df["low"].to_numpy(dtype=float))
        close = pd.Series(df["close"].to_numpy(dtype=float))
        volume = pd.Series(df["volume"].to_numpy(dtype=float))

        mean = close.rolling(self.window, min_periods=self.window).mean()
        std = close.rolling(self.window, min_periods=self.window).std()
        lower = (mean - self.band_k * std).to_numpy()
        upper = (mean + self.band_k * std).to_numpy()
        rsi = self._rsi(close)
        mfi = self._mfi(high, low, close, volume)
        c = close.to_numpy()
        rsi_floor_mirror = 100.0 - self.rsi_floor
        rsi_exit_mirror = 100.0 - self.rsi_exit
        mfi_gate_mirror = 100.0 - self.mfi_gate

        sig = np.zeros(len(df), dtype=int)
        pos = 0
        for i in range(len(c)):
            t = times[i]
            if not (self.trade_from <= t < self.flatten_at):
                pos = 0
                continue
            if i == 0 or np.isnan(lower[i]) or np.isnan(lower[i - 1]):
                continue
            dipped = c[i - 1] < lower[i - 1]
            poked = c[i - 1] > upper[i - 1]
            if pos == 0:
                long_ok = (
                    dipped and c[i] >= lower[i]
                    and rsi[i] >= self.rsi_floor and mfi[i] < self.mfi_gate
                )
                short_ok = (
                    poked and c[i] <= upper[i]
                    and rsi[i] <= rsi_floor_mirror and mfi[i] > mfi_gate_mirror
                )
                if long_ok:
                    pos = 1
                elif self.allow_short and short_ok:
                    pos = -1
            elif pos == 1:
                if (c[i] > upper[i] and rsi[i] >= self.rsi_exit) or c[i] < lower[i]:
                    pos = 0
            else:  # pos == -1
                if (c[i] < lower[i] and rsi[i] <= rsi_exit_mirror) or c[i] > upper[i]:
                    pos = 0
            sig[i] = pos
        return pd.Series(sig, index=df.index)
