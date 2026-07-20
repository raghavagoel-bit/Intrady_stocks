"""OI × DMA × ADX confluence — LONG-ONLY — NSE intraday, 15m bars.

Three-factor trend confirmation:

  - **DMA**: today's price must trade above the mean of the prior
    ``dma_days`` daily closes (a true daily moving average, anchored at day
    boundaries — the classic "above the DMA" position-trader filter).
  - **ADX**: Wilder ADX(14) on the 15m bars must show a real trend
    (``adx_entry`` or better) with bullish direction (+DI above −DI).
  - **OI**: if the bar feed carries an ``oi`` (open interest) column, entries
    also require a long-buildup — OI rising over the last ``oi_bars`` bars
    alongside price. Spot NSE equities have NO open interest; OI lives on the
    stock's futures. Until a Dhan FNO feed is wired (backlog), the column is
    absent and this gate passes through — the strategy trades as DMA × ADX.

Exit when the bullish direction flips (+DI below −DI) or price loses the DMA.

Signals: 1 = hold long, 0 = flat. With ``allow_short=True`` (the 3L hybrid twin)
the mirror is symmetric: −1 while price is BELOW the DMA with a real trend
(ADX ≥ entry) and bearish direction (−DI above +DI); exit when the direction
flips (+DI above −DI) or price reclaims the DMA. The OI gate mirrors to a
short-buildup (OI falling), passing through when no OI feed is wired. The no-arg
ctor stays long-only.
NOTE: needs ~4 trading days of history (DMA + ADX warm-up) — run with
``lookback_bars`` ≥ 120 so the live loop sees enough bars (Dhan 15m history
covers ≈5 days, DC-002).
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


def _wilder(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(alpha=1.0 / window, adjust=False).mean()


class SignalEngine:
    """DMA trend + ADX strength + optional OI long-buildup, long-only.

    Attributes:
        dma_days: Prior daily closes averaged for the DMA filter.
        adx_window: Wilder smoothing window for DI/ADX.
        adx_entry: Minimum ADX to open (trend must be established).
        oi_bars: OI must have risen over this many bars (only if OI present).
        trade_from / flatten_at: IST tradeable window bounds.
    """

    def __init__(
        self,
        dma_days: int = 3,
        adx_window: int = 14,
        adx_entry: float = 20.0,
        oi_bars: int = 4,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.dma_days = dma_days
        self.adx_window = adx_window
        self.adx_entry = adx_entry
        self.oi_bars = oi_bars
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
        day_keys = np.array([t.date() for t in idx])
        high = pd.Series(df["high"].to_numpy(dtype=float))
        low = pd.Series(df["low"].to_numpy(dtype=float))
        close = pd.Series(df["close"].to_numpy(dtype=float))

        # --- DMA: mean of the prior dma_days COMPLETED days' closing prices.
        daily_last = {}
        seen_days = []
        for d in day_keys:
            if d not in daily_last:
                daily_last[d] = None
                seen_days.append(d)
        closes_np = close.to_numpy()
        for i, d in enumerate(day_keys):
            daily_last[d] = closes_np[i]  # last write per day wins = day close
        day_index = {d: k for k, d in enumerate(seen_days)}
        day_closes = [daily_last[d] for d in seen_days]
        dma_by_day = np.full(len(seen_days), np.nan)
        for k in range(len(seen_days)):
            if k >= self.dma_days:
                dma_by_day[k] = float(np.mean(day_closes[k - self.dma_days:k]))
        dma = np.array([dma_by_day[day_index[d]] for d in day_keys])

        # --- Wilder DI / ADX on the 15m stream (volatility has no day gate).
        up = high.diff()
        down = -low.diff()
        plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0))
        minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0))
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        atr = _wilder(tr, self.adx_window)
        plus_di = 100.0 * _wilder(plus_dm, self.adx_window) / atr.replace(0.0, np.nan)
        minus_di = 100.0 * _wilder(minus_dm, self.adx_window) / atr.replace(0.0, np.nan)
        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
        adx = _wilder(dx.fillna(0.0), self.adx_window).to_numpy()
        pdi = plus_di.to_numpy()
        mdi = minus_di.to_numpy()
        burn_in = 2 * self.adx_window

        # --- Optional OI build-up gate (pass-through when feed has no OI): a
        # long wants OI rising, the mirror short wants OI falling.
        if "oi" in df.columns:
            oi = pd.Series(df["oi"].to_numpy(dtype=float))
            oi_rising = (oi.diff(self.oi_bars) > 0).to_numpy()
            oi_falling = (oi.diff(self.oi_bars) < 0).to_numpy()
        else:
            oi_rising = np.ones(len(df), dtype=bool)
            oi_falling = np.ones(len(df), dtype=bool)

        c = closes_np
        sig = np.zeros(len(df), dtype=int)
        pos = 0
        for i in range(len(sig)):
            t = times[i]
            if not (self.trade_from <= t < self.flatten_at):
                pos = 0
                continue
            if i < burn_in or np.isnan(dma[i]) or np.isnan(adx[i]):
                continue
            bull = pdi[i] > mdi[i]
            bear = mdi[i] > pdi[i]
            above_dma = c[i] > dma[i]
            below_dma = c[i] < dma[i]
            strong = adx[i] >= self.adx_entry
            if pos == 0:
                if bull and above_dma and strong and oi_rising[i]:
                    pos = 1
                elif self.allow_short and bear and below_dma and strong and oi_falling[i]:
                    pos = -1
            elif pos == 1:
                if not bull or not above_dma:
                    pos = 0  # direction flipped or daily trend lost
            elif pos == -1:
                if not bear or not below_dma:
                    pos = 0  # direction flipped or daily trend reclaimed
            sig[i] = pos
        return pd.Series(sig, index=df.index)
