"""RSI(2) dip-buying mean reversion for NSE large caps (daily bars, delivery).

Connors-style: buy sharp 1-3 day pullbacks inside a long-term uptrend, exit
on the snap-back. Long-only and multi-day, so it fits IndiaEquityEngine's
T+1 delivery rules natively (the exit is never on the entry day).

Entry: close > SMA(200) (uptrend only) AND RSI(2) < rsi_entry (deep short-term
oversold) AND close < SMA(5) (still stretched below the short mean).
Exit: RSI(2) > rsi_exit OR close > SMA(5) (mean reached), OR max_hold_days
elapsed (time stop — a dip that doesn't bounce is a broken thesis).

Signal semantics: 1 = hold long, 0 = flat.
"""

from typing import Dict

import numpy as np
import pandas as pd


def compute_rsi(close: pd.Series, period: int = 2) -> pd.Series:
    """Compute RSI with Wilder EWM smoothing.

    Args:
        close: Close price series.
        period: RSI lookback (2 for this strategy).

    Returns:
        RSI series (0-100).
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


class SignalEngine:
    """Short-term oversold dip buyer with a long-term trend filter.

    Attributes:
        rsi_period: RSI lookback.
        rsi_entry: Entry threshold (deep oversold).
        rsi_exit: Exit threshold (bounce complete).
        sma_regime: Long-term regime SMA period.
        sma_mean: Short mean SMA period (stretch/exit reference).
        max_hold_days: Time stop in bars.
    """

    def __init__(
        self,
        rsi_period: int = 2,
        rsi_entry: float = 10.0,
        rsi_exit: float = 60.0,
        sma_regime: int = 200,
        sma_mean: int = 5,
        max_hold_days: int = 7,
    ):
        self.rsi_period = rsi_period
        self.rsi_entry = rsi_entry
        self.rsi_exit = rsi_exit
        self.sma_regime = sma_regime
        self.sma_mean = sma_mean
        self.max_hold_days = max_hold_days

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
        rsi = compute_rsi(close, self.rsi_period)
        sma_r = close.rolling(self.sma_regime).mean()
        sma_m = close.rolling(self.sma_mean).mean()

        entry = (close > sma_r) & (rsi < self.rsi_entry) & (close < sma_m)
        exit_ = (rsi > self.rsi_exit) | (close > sma_m)

        sig = np.zeros(len(df), dtype=int)
        in_pos = False
        held = 0
        entry_arr = entry.fillna(False).to_numpy()
        exit_arr = exit_.fillna(False).to_numpy()
        for i in range(len(df)):
            if not in_pos and entry_arr[i]:
                in_pos = True
                held = 0
            elif in_pos:
                held += 1
                if exit_arr[i] or held >= self.max_hold_days:
                    in_pos = False
            sig[i] = 1 if in_pos else 0
        return pd.Series(sig, index=df.index)
