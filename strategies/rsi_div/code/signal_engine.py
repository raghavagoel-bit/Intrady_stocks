"""RSI Divergence — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of eemani123's "RSI Divergence Indicator strategy": buy confirmed *bullish
regular divergence* — price prints a lower swing low while RSI prints a higher swing
low (selling pressure fading under a falling price). Swing lows are pivots confirmed
``pivot`` bars after the fact (causal — no look-ahead), and only the last two are
compared. Exit when RSI reaches overbought or the 15:00 flatten.

RSI rolls across the whole lookback; pivots are detected within it. Signals:
1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001). With
``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: short confirmed
*bearish* divergence — a higher price swing high with a lower RSI swing high — and
cover on RSI oversold. The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


class SignalEngine:
    """Regular RSI divergence on confirmed pivots, intraday.

    Attributes:
        rsi_len: RSI lookback in bars.
        pivot: bars on each side that define a confirmed swing pivot.
        rsi_ob / rsi_os: overbought / oversold exit levels.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror bearish divergence to a short.
    """

    def __init__(
        self,
        rsi_len: int = 14,
        pivot: int = 2,
        arm: int = 3,
        rsi_ob: float = 70.0,
        rsi_os: float = 30.0,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.rsi_len = rsi_len
        self.pivot = pivot
        self.arm = arm
        self.rsi_ob = rsi_ob
        self.rsi_os = rsi_os
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

    def _is_pivot_low(self, x: np.ndarray, i: int) -> bool:
        p = self.pivot
        if i - p < 0 or i + p >= len(x):
            return False
        seg = x[i - p : i + p + 1]
        return x[i] == seg.min() and float(x[i]) < float(seg.max())

    def _is_pivot_high(self, x: np.ndarray, i: int) -> bool:
        p = self.pivot
        if i - p < 0 or i + p >= len(x):
            return False
        seg = x[i - p : i + p + 1]
        return x[i] == seg.max() and float(x[i]) > float(seg.min())

    def _generate_one(self, df: pd.DataFrame) -> pd.Series:
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("Asia/Kolkata")
        times = np.array([t.time() for t in idx])
        close = pd.Series(df["close"].to_numpy(dtype=float))
        c = close.to_numpy()
        rsi = self._rsi(close)
        p = self.pivot

        sig = np.zeros(len(df), dtype=int)
        pos = 0
        lows: List[Tuple[float, float]] = []   # (price, rsi) at confirmed pivot lows
        highs: List[Tuple[float, float]] = []
        bull_at = -1                            # confirmation bar of the latest signal
        bear_at = -1
        for i in range(len(c)):
            # A pivot centred at bar (i - p) becomes confirmed at bar i.
            j = i - p
            if j >= 0:
                if self._is_pivot_low(c, j):
                    lows.append((c[j], rsi[j]))
                    if len(lows) >= 2 and lows[-1][0] < lows[-2][0] and lows[-1][1] > lows[-2][1]:
                        bull_at = i     # lower price low, higher RSI low → bullish
                if self._is_pivot_high(c, j):
                    highs.append((c[j], rsi[j]))
                    if len(highs) >= 2 and highs[-1][0] > highs[-2][0] and highs[-1][1] < highs[-2][1]:
                        bear_at = i     # higher price high, lower RSI high → bearish

            t = times[i]
            if not (self.trade_from <= t < self.flatten_at):
                pos = 0
                continue
            # A confirmed divergence stays "armed" for ``arm`` bars so the entry
            # is not lost when confirmation lands just before the window opens.
            bull_live = 0 <= (i - bull_at) <= self.arm
            bear_live = 0 <= (i - bear_at) <= self.arm
            if pos == 0:
                if bull_live:
                    pos = 1
                elif self.allow_short and bear_live:
                    pos = -1
            elif pos == 1:
                if rsi[i] >= self.rsi_ob or bear_at == i:
                    pos = 0
            else:  # pos == -1
                if rsi[i] <= self.rsi_os or bull_at == i:
                    pos = 0
            sig[i] = pos
        return pd.Series(sig, index=df.index)
