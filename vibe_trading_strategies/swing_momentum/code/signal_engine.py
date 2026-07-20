"""Trend-following swing momentum for NSE large caps (daily bars, delivery).

Long-only, designed to fit Vibe-Trading's IndiaEquityEngine exactly:
holding period is days-to-weeks so T+1 settlement never blocks an exit,
no shorting, and the delivery cost stack (0.1% STT both sides) is cheap
relative to the captured trend moves.

Entry: EMA(20) > EMA(50) crossover regime, confirmed by ADX(14) > adx_threshold
(a real trend, not chop) and close > SMA(200) (long-term uptrend filter).
Exit: EMA(20) falls below EMA(50) * (1 - exit_buffer) — the buffer avoids
whipsaw exits on a single flat week.

Signal semantics: 1 = hold long, 0 = flat.
"""

from typing import Dict

import numpy as np
import pandas as pd


def compute_adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """Compute ADX with Wilder EWM smoothing end to end.

    Args:
        high: High price series.
        low: Low price series.
        close: Close price series.
        period: ADX lookback period.

    Returns:
        ADX series (0-100).
    """
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = pd.Series(0.0, index=high.index)
    minus_dm = pd.Series(0.0, index=high.index)
    plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
    minus_dm[(down_move > up_move) & (down_move > 0)] = down_move

    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)

    alpha = 1 / period
    smoothed_tr = tr.ewm(alpha=alpha, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=alpha, min_periods=period).mean() / smoothed_tr
    minus_di = 100 * minus_dm.ewm(alpha=alpha, min_periods=period).mean() / smoothed_tr

    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    return dx.ewm(alpha=alpha, min_periods=period).mean()


class SignalEngine:
    """EMA-crossover trend follower with ADX and long-term-trend filters.

    Attributes:
        ema_fast: Fast EMA period.
        ema_slow: Slow EMA period.
        sma_regime: Long-term regime SMA period.
        adx_period: ADX lookback.
        adx_threshold: Minimum ADX for a tradeable trend.
        exit_buffer: Fractional buffer under the slow EMA before exiting.
    """

    def __init__(
        self,
        ema_fast: int = 20,
        ema_slow: int = 50,
        sma_regime: int = 200,
        adx_period: int = 14,
        adx_threshold: float = 20.0,
        exit_buffer: float = 0.005,
    ):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.sma_regime = sma_regime
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.exit_buffer = exit_buffer

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """Generate long/flat signals per symbol.

        Args:
            data_map: Symbol -> OHLCV DataFrame (open/high/low/close/volume,
                datetime index).

        Returns:
            Symbol -> signal Series (1 = long, 0 = flat).
        """
        return {code: self._generate_one(df) for code, df in data_map.items()}

    def _generate_one(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        ema_f = close.ewm(span=self.ema_fast, adjust=False).mean()
        ema_s = close.ewm(span=self.ema_slow, adjust=False).mean()
        sma_r = close.rolling(self.sma_regime).mean()
        adx = compute_adx(df["high"], df["low"], close, self.adx_period)

        entry = (ema_f > ema_s) & (adx > self.adx_threshold) & (close > sma_r)
        exit_ = ema_f < ema_s * (1 - self.exit_buffer)

        # Stateful hold: enter on `entry`, stay long until `exit_`.
        sig = np.zeros(len(df), dtype=int)
        in_pos = False
        entry_arr = entry.fillna(False).to_numpy()
        exit_arr = exit_.fillna(False).to_numpy()
        for i in range(len(df)):
            if not in_pos and entry_arr[i]:
                in_pos = True
            elif in_pos and exit_arr[i]:
                in_pos = False
            sig[i] = 1 if in_pos else 0
        return pd.Series(sig, index=df.index)
