"""MACD + long trend-MA filter — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of ChartArt's "MACD + SMA 200 Strategy": take MACD crossovers only in the
direction of the dominant trend. The daily-chart original filters with the 200-SMA;
on 15m bars a literal 200-bar SMA (~15 sessions) exceeds the live 120-bar lookback,
so the trend filter is scaled to a 100-bar SMA (~7½ sessions) — the same "only trade
with the higher-timeframe trend" idea sized for intraday (cf. macd_cross's 12/26/9).

MACD and the trend MA roll across the whole lookback (this is a multi-day trend
filter by nature — resetting it daily would defeat the purpose). Signals: 1 = hold
long while MACD > signal AND close > trend MA; 0 = flat. Flat before 09:45 and from
15:00 (DC-001). With ``allow_short=True`` (the 3L hybrid twin) the mirror is
symmetric: −1 while MACD < signal AND close < the trend MA. No-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """MACD stack gated by a slow trend MA, intraday.

    Attributes:
        fast / slow / signal_span: EMA spans (bars) of the MACD stack.
        trend_ma: Slow SMA window (the "200-SMA" trend filter, scaled to 15m).
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — emit −1 below the trend MA with MACD down.
    """

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal_span: int = 9,
        trend_ma: int = 100,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.fast = fast
        self.slow = slow
        self.signal_span = signal_span
        self.trend_ma = trend_ma
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

        macd = (
            close.ewm(span=self.fast, adjust=False).mean()
            - close.ewm(span=self.slow, adjust=False).mean()
        )
        signal = macd.ewm(span=self.signal_span, adjust=False).mean()
        sma = close.rolling(self.trend_ma, min_periods=self.trend_ma).mean().to_numpy()
        up = (macd > signal).to_numpy()
        c = close.to_numpy()

        tradeable = np.array([self.trade_from <= t < self.flatten_at for t in times])
        valid = ~np.isnan(sma)
        long_ok = up & (c > sma) & tradeable & valid
        sig = np.where(long_ok, 1, 0)
        if self.allow_short:
            short_ok = (~up) & (c < sma) & tradeable & valid
            sig = np.where(short_ok, -1, sig)
        return pd.Series(sig.astype(int), index=df.index)
