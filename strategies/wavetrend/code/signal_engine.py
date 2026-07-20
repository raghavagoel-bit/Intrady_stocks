"""WaveTrend (Cipher B core) — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of LazyBear's WaveTrend oscillator (the engine inside VuManChu Cipher B):
tci = ema21 of the channel index built from hlc3 vs its ema10, wt1 = tci,
wt2 = sma4(wt1). We buy the wt1/wt2 cross UP that starts below the zero
line (the common Cipher B "green dot below zero" entry), ride until the
cross back DOWN, and never short.

Signals: 1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001).
With ``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 on the
wt1/wt2 cross DOWN from overbought (wt2 ≥ +oversold-magnitude), held until the
cross back up. Long-only by default.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """WaveTrend cross-up from oversold, long-only intraday.

    Attributes:
        channel_len: ema length for the price channel (TV n1, default 10).
        average_len: ema length for tci smoothing (TV n2, default 21).
        oversold: wt2 must be at/below this at the cross to enter (default
            0.0 — the zero line; the repo validator only allows literal
            defaults, so deeper negative levels are set at construction).
        trade_from / flatten_at: IST tradeable window bounds.
    """

    def __init__(
        self,
        channel_len: int = 10,
        average_len: int = 21,
        oversold: float = 0.0,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.channel_len = channel_len
        self.average_len = average_len
        self.oversold = oversold
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
        high = pd.Series(df["high"].to_numpy(dtype=float))
        low = pd.Series(df["low"].to_numpy(dtype=float))
        close = pd.Series(df["close"].to_numpy(dtype=float))

        ap = (high + low + close) / 3.0
        esa = ap.ewm(span=self.channel_len, adjust=False).mean()
        d = (ap - esa).abs().ewm(span=self.channel_len, adjust=False).mean()
        ci = (ap - esa) / (0.015 * d.replace(0.0, np.nan))
        wt1 = ci.ewm(span=self.average_len, adjust=False).mean()
        wt2 = wt1.rolling(4, min_periods=4).mean()
        # emas warm up softly — discard the first channel+average bars as burn-in.
        burn_in = self.channel_len + self.average_len
        w1 = wt1.to_numpy()
        w2 = wt2.to_numpy()

        overbought = -self.oversold  # mirror level (no negative literal in ctor)
        sig = np.zeros(len(df), dtype=int)
        pos = 0
        for i in range(len(sig)):
            t = times[i]
            if not (self.trade_from <= t < self.flatten_at):
                pos = 0
                continue
            if i < burn_in or np.isnan(w1[i]) or np.isnan(w2[i]) or np.isnan(w1[i - 1]):
                continue
            crossed_up = w1[i - 1] <= w2[i - 1] and w1[i] > w2[i]
            crossed_down = w1[i - 1] >= w2[i - 1] and w1[i] < w2[i]
            if pos == 0:
                if crossed_up and w2[i] <= self.oversold:
                    pos = 1
                elif self.allow_short and crossed_down and w2[i] >= overbought:
                    pos = -1
            elif pos == 1 and crossed_down:
                pos = 0
            elif pos == -1 and crossed_up:
                pos = 0
            sig[i] = pos
        return pd.Series(sig, index=df.index)
