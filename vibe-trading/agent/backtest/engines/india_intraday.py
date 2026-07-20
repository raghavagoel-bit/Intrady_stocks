"""India equity **intraday (MIS)** backtest engine — long-only.

Subclasses :class:`IndiaEquityEngine` but flips the rules that make the delivery
engine unusable for intraday:

  - **Same-day exits allowed** — the delivery engine's T+1 block (can't sell a
    position on its entry bar-date) is removed, so a stock bought at 09:30 can be
    sold at 14:00.
  - **Long-only by default** — short entries are rejected unless the config sets
    ``allow_short: true`` (the 3L hybrid A/B, paper broker only). With the flag
    off the behavior is byte-for-byte identical to before; with it on the parent
    engine's fully-general short machinery (``_close_position`` / next-bar-open
    covers / direction-aware ``calc_commission``) is used, and a short entry (a
    sell) is blocked at the **lower** circuit — the mirror of a long being
    blocked at the upper.
  - **MIS cost stack** replaces the delivery stack:
      * Brokerage: ``min(₹20, 0.03% × notional)`` per executed order   [in_brokerage / in_brokerage_cap]
      * STT: 0.025% on the **sell** leg only                            [in_stt]
      * Stamp duty: 0.003% on the **buy** leg only                      [in_stamp_duty]
      * Exchange txn: NSE ~0.00297% (both legs)                         [in_exchange_txn]
      * SEBI turnover fee: 0.0001% (both legs)                          [in_sebi_fee]
      * GST: 18% on (brokerage + exchange txn + SEBI fee)              [in_gst]
      * No DP charge (delivery-only).
  - Circuit bands are kept (upper blocks buys, lower blocks sells/closes).

**Square-off contract:** this engine does NOT force an end-of-day flatten. For a
backtest the 15:15 square-off must be produced by the SignalEngine (emit 0 after
the cutoff; the next-bar-open fill closes the long). The live runtime enforces
square-off authoritatively. An intraday SignalEngine that never flattens will
carry a position across the day gap — which is a strategy bug, not an engine one.

NOTE: SEBI/exchange tariffs change periodically — verify the ``in_*`` rates
against a current Dhan MIS schedule before relying on absolute cost figures.
"""

from __future__ import annotations

import pandas as pd

from backtest.engines.china_a import _calc_pct_change
from backtest.engines.india_equity import IndiaEquityEngine


class IndiaIntradayEngine(IndiaEquityEngine):
    """NSE / BSE intraday (MIS) engine — long-only, same-day exits, MIS costs.

    Config keys (all optional; MIS defaults shown):
      - price_limit: circuit band fraction or None (default 0.20)
      - slippage: default 0.0005
      - in_brokerage: per-order brokerage rate (default 0.0003)
      - in_brokerage_cap: per-order brokerage cap in ₹ (default 20.0)
      - in_stt: sell-side STT (default 0.00025)
      - in_stamp_duty: buy-side stamp (default 0.00003)
      - in_exchange_txn / in_sebi_fee / in_gst
    """

    def __init__(self, config: dict):
        super().__init__(config)  # delivery defaults + leverage 1.0
        # Long-only unless explicitly opted in (3L hybrid twins, paper only). The
        # parent already read this key; keep the read here so the default and the
        # intent are visible at the intraday layer.
        self.allow_short = bool(config.get("allow_short", False))
        self.slippage_rate = float(config.get("slippage", 0.0005))
        # MIS cost stack (override the delivery defaults from the parent).
        self.in_brokerage = float(config.get("in_brokerage", 0.0003))
        self.in_brokerage_cap = float(config.get("in_brokerage_cap", 20.0))
        self.in_stt = float(config.get("in_stt", 0.00025))          # sell only
        self.in_exchange_txn = float(config.get("in_exchange_txn", 0.0000297))
        self.in_sebi_fee = float(config.get("in_sebi_fee", 0.000001))
        self.in_stamp_duty = float(config.get("in_stamp_duty", 0.00003))  # buy only
        self.in_gst = float(config.get("in_gst", 0.18))
        # Informational: the intended flatten cutoff. Enforced by the signal
        # engine (backtest) and the live runtime — not by this engine.
        self.squareoff_time = str(config.get("squareoff_time", "15:15"))

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """India intraday (MIS) execution rules.

        Args:
            symbol: NSE/BSE symbol (e.g. ``RELIANCE.NS``).
            direction: 1 (buy/open long), -1 (open short — rejected unless
                ``allow_short``), 0 (sell/close a long).
            bar: Current bar (needs ``close`` + ``pre_close``/``pct_chg`` for
                circuit checks).

        Returns:
            True if the trade is allowed.
        """
        # 1. Short entries only when opted in (3L hybrid twins, paper only).
        if direction == -1 and not self.allow_short:
            return False

        # 2. No T+1 block — intraday round-trips are the whole point.

        # 3. Circuit bands (single configurable band; disabled when falsy).
        if self.price_limit:
            pct_chg = _calc_pct_change(bar)
            if pct_chg is not None:
                limit = float(self.price_limit)
                if direction == 1 and pct_chg >= limit - 0.001:
                    return False  # upper circuit: can't buy
                # A close (0) and a short entry (-1) are both sells → both are
                # blocked at the lower circuit (can't hit the bid limit-down).
                if direction in (0, -1) and pct_chg <= -limit + 0.001:
                    return False  # lower circuit: can't sell / short

        return True

    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        """India intraday (MIS) cost stack (see module docstring).

        Buy leg pays stamp duty; sell leg pays STT; both legs pay capped
        brokerage + exchange txn + SEBI fee + 18% GST on those charges.
        """
        notional = size * price
        # For a long (direction 1): open = buy, close = sell. General form covers
        # the (rejected) short case too, keeping the leg logic unambiguous.
        is_buy = (direction == 1 and is_open) or (direction == -1 and not is_open)

        brokerage = min(self.in_brokerage_cap, notional * self.in_brokerage)  # per order
        exchange_txn = notional * self.in_exchange_txn
        sebi_fee = notional * self.in_sebi_fee
        gst = (brokerage + exchange_txn + sebi_fee) * self.in_gst

        comm = brokerage + exchange_txn + sebi_fee + gst
        if is_buy:
            comm += notional * self.in_stamp_duty   # stamp duty: buy leg only
        else:
            comm += notional * self.in_stt          # STT: sell leg only
        return comm
