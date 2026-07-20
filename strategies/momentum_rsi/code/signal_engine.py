"""Momentum RSI pullback — LONG-ONLY — NSE intraday, 15m bars.

Buys the dip inside an intraday up-trend: while price is above its intraday SMA
(trend filter), enter long when RSI turns up out of a pullback (crosses back above
an oversold-ish threshold), and exit when RSI runs hot (overbought) or the trend
breaks (price falls back below the SMA). Structurally different from ORB
(breakout) and EMA-trend (always-in-trend): it only engages on pullbacks, so it
trades selectively and mean-reverts within a trend.

SMA + RSI are computed **per day** (reset each morning) so overnight gaps don't
leak into intraday state. Tradeable window 09:45–15:00 IST; flat outside. Runs
through `IndiaIntradayEngine` (`intraday: true`); flat at 15:00 so the square-off
lands at 15:15 same-day (see DC-001).

Signal semantics: 1 = hold long, 0 = flat. With ``allow_short=True`` (the 3L
hybrid twin) the mirror is symmetric: in a DOWN-trend (price below the SMA) short
when RSI rolls over out of a rally (a local RSI PEAK at/above ``100 −
rsi_pullback``), and cover when RSI runs cold (≤ ``100 − rsi_exit``) or the
down-trend breaks. The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """RSI-pullback entries with an SMA trend filter, long-only, reset daily.

    Attributes:
        sma: Intraday SMA window (trend filter).
        rsi_len: RSI lookback in bars.
        rsi_buy: RSI level a pullback must reclaim from below to trigger a long.
        rsi_exit: RSI level at/above which an open long is closed (overbought).
        trade_from / flatten_at: IST tradeable-window bounds.
    """

    def __init__(
        self,
        sma: int = 20,
        rsi_len: int = 14,
        rsi_pullback: float = 70.0,
        rsi_exit: float = 82.0,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.sma = sma
        self.rsi_len = rsi_len
        self.allow_short = allow_short
        # A long is taken when RSI RESUMES up out of a local dip whose trough is
        # at/below ``rsi_pullback`` (a genuine pullback, not buying a runaway top),
        # while price is above its intraday SMA (up-trend). Level-agnostic entry —
        # it fires on the pullback-and-resume, not on crossing a fixed low level.
        self.rsi_pullback = rsi_pullback
        self.rsi_exit = rsi_exit
        self.trade_from = _dt.time(trade_from_hour, trade_from_minute)
        self.flatten_at = _dt.time(flatten_hour, flatten_minute)

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """Generate long/flat signals per symbol.

        Args:
            data_map: Symbol -> 15m OHLCV DataFrame with a DatetimeIndex
                (tz-aware is converted to IST; tz-naive is treated as IST).

        Returns:
            Symbol -> signal Series (1 = long, 0 = flat).
        """
        return {code: self._generate_one(df) for code, df in data_map.items()}

    def _rsi(self, close: pd.Series) -> np.ndarray:
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.rolling(self.rsi_len, min_periods=self.rsi_len).mean()
        avg_loss = loss.rolling(self.rsi_len, min_periods=self.rsi_len).mean()
        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        # Neutral 50 before enough data / when flat (avoids spurious triggers).
        return rsi.fillna(50.0).to_numpy()

    def _generate_one(self, df: pd.DataFrame) -> pd.Series:
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("Asia/Kolkata")
        times = np.array([t.time() for t in idx])
        days = np.array([t.date() for t in idx])
        close_all = pd.Series(df["close"].to_numpy(dtype=float))

        sig = np.zeros(len(df), dtype=int)
        for day in np.unique(days):
            mask = days == day
            day_close = close_all[mask].reset_index(drop=True)
            if len(day_close) < 2:
                continue
            sma = day_close.rolling(self.sma, min_periods=1).mean().to_numpy()
            rsi = self._rsi(day_close)
            close = day_close.to_numpy()
            day_times = times[mask]

            day_sig = np.zeros(len(day_close), dtype=int)
            pos = 0
            for i in range(len(day_close)):
                t = day_times[i]
                if not (self.trade_from <= t < self.flatten_at):
                    pos = 0
                    day_sig[i] = pos
                    continue
                uptrend = close[i] > sma[i]
                downtrend = close[i] < sma[i]
                # Pullback-and-resume: bar i-1 was a local RSI trough (a dip) at
                # or below the pullback level, and RSI has now turned back up.
                resume = (
                    i >= 2
                    and rsi[i] > rsi[i - 1]
                    and rsi[i - 1] <= rsi[i - 2]
                    and rsi[i - 1] <= self.rsi_pullback
                )
                # Mirror: bar i-1 was a local RSI peak at/above the mirror level
                # (100 − rsi_pullback) and RSI has now turned back down.
                fade = (
                    i >= 2
                    and rsi[i] < rsi[i - 1]
                    and rsi[i - 1] >= rsi[i - 2]
                    and rsi[i - 1] >= (100.0 - self.rsi_pullback)
                )
                if pos == 0:
                    if uptrend and resume:
                        pos = 1
                    elif self.allow_short and downtrend and fade:
                        pos = -1
                elif pos == 1:
                    if rsi[i] >= self.rsi_exit or not uptrend:
                        pos = 0
                elif pos == -1:
                    if rsi[i] <= (100.0 - self.rsi_exit) or not downtrend:
                        pos = 0
                day_sig[i] = pos
            sig[mask] = day_sig
        return pd.Series(sig, index=df.index)
