"""Ichimoku (+ Hull confirm) — LONG-ONLY — NSE intraday, 15m bars. (TradingView port)

Port of SeaSide420's "Ichimoku + Daily-Candle_X + HULL-MA_X": trade with the
Ichimoku cloud, confirmed by Hull-MA slope. Long when the close is above the cloud
(the leading span plotted at the current bar, i.e. computed ``displace`` bars ago),
the conversion line (Tenkan) is above the base line (Kijun), and the Hull MA is
rising. The cloud is the trend/support filter; Tenkan>Kijun times the momentum; the
Hull slope vetoes entries against the short-term drift.

Spans use the standard 9/26/52 lengths and a 26-bar forward displacement. Signals:
1 = hold long, 0 = flat. Flat before 09:45 and from 15:00 (DC-001). With
``allow_short=True`` (the 3L hybrid twin) the mirror is symmetric: −1 below the cloud
with Tenkan<Kijun and a falling Hull MA. The no-arg ctor stays long-only.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


def _hma(close: pd.Series, length: int) -> np.ndarray:
    """Hull moving average of ``close``."""
    def _wma(x: pd.Series, n: int) -> pd.Series:
        w = np.arange(1, n + 1, dtype=float)
        return x.rolling(n, min_periods=n).apply(lambda v: float(np.dot(v, w) / w.sum()), raw=True)

    half = max(1, length // 2)
    sq = max(1, int(round(np.sqrt(length))))
    raw = 2.0 * _wma(close, half) - _wma(close, length)
    return _wma(raw, sq).to_numpy()


class SignalEngine:
    """Ichimoku cloud + Tenkan/Kijun, Hull-slope confirmed, intraday.

    Attributes:
        tenkan / kijun / senkou_b: Ichimoku lengths (9 / 26 / 52).
        displace: forward displacement of the cloud (bars, standard 26).
        hull_len: Hull MA length for the slope confirm.
        trade_from / flatten_at: IST tradeable window bounds.
        allow_short: hybrid twin — mirror the below-cloud short.
    """

    def __init__(
        self,
        tenkan: int = 9,
        kijun: int = 26,
        senkou_b: int = 52,
        displace: int = 26,
        hull_len: int = 20,
        trade_from_hour: int = 9,
        trade_from_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        allow_short: bool = False,
    ):
        self.tenkan = tenkan
        self.kijun = kijun
        self.senkou_b = senkou_b
        self.displace = displace
        self.hull_len = hull_len
        self.trade_from = _dt.time(trade_from_hour, trade_from_minute)
        self.flatten_at = _dt.time(flatten_hour, flatten_minute)
        self.allow_short = allow_short

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """Generate long/flat signals per symbol (see module docstring)."""
        return {code: self._generate_one(df) for code, df in data_map.items()}

    def _mid(self, high: pd.Series, low: pd.Series, n: int) -> pd.Series:
        return (high.rolling(n, min_periods=n).max() + low.rolling(n, min_periods=n).min()) / 2.0

    def _generate_one(self, df: pd.DataFrame) -> pd.Series:
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("Asia/Kolkata")
        times = np.array([t.time() for t in idx])
        high = pd.Series(df["high"].to_numpy(dtype=float))
        low = pd.Series(df["low"].to_numpy(dtype=float))
        close = pd.Series(df["close"].to_numpy(dtype=float))

        tenkan = self._mid(high, low, self.tenkan)
        kijun = self._mid(high, low, self.kijun)
        span_a = ((tenkan + kijun) / 2.0).shift(self.displace).to_numpy()
        span_b = self._mid(high, low, self.senkou_b).shift(self.displace).to_numpy()
        tk = tenkan.to_numpy()
        kj = kijun.to_numpy()
        hma = _hma(close, self.hull_len)
        c = close.to_numpy()

        cloud_top = np.fmax(span_a, span_b)
        cloud_bot = np.fmin(span_a, span_b)

        sig = np.zeros(len(df), dtype=int)
        for i in range(len(c)):
            t = times[i]
            if not (self.trade_from <= t < self.flatten_at):
                continue
            if i < 2 or np.isnan(cloud_top[i]) or np.isnan(hma[i]) or np.isnan(hma[i - 2]):
                continue
            rising = hma[i] > hma[i - 2]
            falling = hma[i] < hma[i - 2]
            if c[i] > cloud_top[i] and tk[i] > kj[i] and rising:
                sig[i] = 1
            elif self.allow_short and c[i] < cloud_bot[i] and tk[i] < kj[i] and falling:
                sig[i] = -1
        return pd.Series(sig, index=df.index)
