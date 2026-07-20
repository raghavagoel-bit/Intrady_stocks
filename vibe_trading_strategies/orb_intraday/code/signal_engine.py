"""Opening Range Breakout (ORB) for NSE intraday — 15-minute bars.

The classic Indian intraday setup: the first 30 minutes (9:15-9:45 IST) define
the opening range; a close above the range high with expanded volume goes long,
a close below the range low goes short (MIS). One entry per direction per day,
exit when price closes back through the range midpoint (failed breakout), and
a hard flatten at/after 15:00 IST — before the broker's MIS auto-square-off.

IMPORTANT — how to backtest this one:
Vibe-Trading's IndiaEquityEngine hard-codes T+1 delivery rules (a position
opened today cannot be closed the same day), which structurally blocks
intraday round-trips. So this strategy ships with its own standalone simulator
(`python ../run_standalone.py`) that models Dhan MIS economics: Rs.20/0.03%
brokerage per executed order, STT 0.025% on the sell leg only, exchange txn
charges, SEBI fee, buy-side intraday stamp duty (0.003%), 18% GST on charges,
and configurable slippage. The SignalEngine class itself stays runner-
compatible for when/if the repo grows an intraday India engine.

Signal semantics: 1 = hold long, -1 = hold short, 0 = flat.
"""

import datetime as _dt
from typing import Dict

import numpy as np
import pandas as pd


class SignalEngine:
    """15m opening-range breakout with volume confirmation and EOD flatten.

    Attributes:
        or_end: Time (IST) when the opening range is fixed.
        flatten_at: Time (IST) at/after which all positions are flat.
        vol_window: Rolling bars for the volume baseline.
        vol_mult: Entry-bar volume must exceed vol_mult x rolling mean.
        allow_short: Enable the short side (MIS intraday shorting).
    """

    def __init__(
        self,
        or_end_hour: int = 9,
        or_end_minute: int = 45,
        flatten_hour: int = 15,
        flatten_minute: int = 0,
        vol_window: int = 20,
        vol_mult: float = 1.3,
        allow_short: bool = True,
    ):
        self.or_end = _dt.time(or_end_hour, or_end_minute)
        self.flatten_at = _dt.time(flatten_hour, flatten_minute)
        self.vol_window = vol_window
        self.vol_mult = vol_mult
        self.allow_short = allow_short

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """Generate intraday long/short/flat signals per symbol.

        Args:
            data_map: Symbol -> 15m OHLCV DataFrame with a DatetimeIndex
                (tz-aware IST from broker/Yahoo loaders, or tz-naive treated
                as exchange-local time).

        Returns:
            Symbol -> signal Series (1 = long, -1 = short, 0 = flat).
        """
        return {code: self._generate_one(df) for code, df in data_map.items()}

    def _generate_one(self, df: pd.DataFrame) -> pd.Series:
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("Asia/Kolkata")
        times = np.array([t.time() for t in idx])
        days = np.array([t.date() for t in idx])

        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)
        vol_ma = (
            pd.Series(volume).rolling(self.vol_window, min_periods=5).mean().to_numpy()
        )

        sig = np.zeros(len(df), dtype=int)
        pos = 0
        traded_long = traded_short = False
        cur_day = None
        or_high = or_low = or_mid = np.nan

        for i in range(len(df)):
            if days[i] != cur_day:
                cur_day = days[i]
                pos = 0
                traded_long = traded_short = False
                day_mask = (days == cur_day) & (times < self.or_end)
                if day_mask.any():
                    or_high = high[day_mask].max()
                    or_low = low[day_mask].min()
                    or_mid = (or_high + or_low) / 2
                else:
                    or_high = or_low = or_mid = np.nan

            t = times[i]
            if t >= self.flatten_at or t < self.or_end or np.isnan(or_high):
                pos = 0
                sig[i] = pos
                continue

            vol_ok = vol_ma[i] > 0 and volume[i] > self.vol_mult * vol_ma[i]

            if pos == 0:
                if not traded_long and close[i] > or_high and vol_ok:
                    pos, traded_long = 1, True
                elif (
                    self.allow_short
                    and not traded_short
                    and close[i] < or_low
                    and vol_ok
                ):
                    pos, traded_short = -1, True
            elif pos == 1 and close[i] < or_mid:
                pos = 0  # failed breakout
            elif pos == -1 and close[i] > or_mid:
                pos = 0

            sig[i] = pos
        return pd.Series(sig, index=df.index)


# ---------------------------------------------------------------------------
# MIS cost model + simulator helpers (driven by ../run_standalone.py; the
# Vibe-Trading runner ignores them).
# ---------------------------------------------------------------------------


def _mis_costs(buy_notional: float, sell_notional: float) -> float:
    """Dhan MIS round-trip charges for one buy leg + one sell leg."""
    brokerage = min(20.0, 0.0003 * buy_notional) + min(20.0, 0.0003 * sell_notional)
    exchange = 0.0000297 * (buy_notional + sell_notional)
    sebi = 0.000001 * (buy_notional + sell_notional)
    stt = 0.00025 * sell_notional          # intraday STT: sell side only
    stamp = 0.00003 * buy_notional         # intraday stamp duty: buy side only
    gst = 0.18 * (brokerage + exchange + sebi)
    return brokerage + exchange + sebi + stt + stamp + gst


def _simulate(df: pd.DataFrame, sig: pd.Series, capital: float, slippage: float):
    """Next-bar-open execution of held-position signals with MIS costs."""
    opens = df["open"].to_numpy(dtype=float)
    trades = []
    pos = 0
    entry_px = qty = 0.0
    sig_arr = sig.to_numpy()
    for i in range(1, len(df)):
        want = sig_arr[i - 1]  # act on the previous bar's signal at this open
        if want == pos:
            continue
        px = opens[i]
        if pos != 0:  # close existing
            exit_px = px * (1 - slippage) if pos == 1 else px * (1 + slippage)
            gross = (exit_px - entry_px) * qty * pos
            buy_n = entry_px * qty if pos == 1 else exit_px * qty
            sell_n = exit_px * qty if pos == 1 else entry_px * qty
            trades.append(gross - _mis_costs(buy_n, sell_n))
            pos = 0
        if want != 0:  # open new
            entry_px = px * (1 + slippage) if want == 1 else px * (1 - slippage)
            qty = max(int(capital / entry_px), 0)
            if qty > 0:
                pos = want
    return trades
