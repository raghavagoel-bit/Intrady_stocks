"""MIS **paper** broker — simulated fills on live/replayed bars.

This is the fill engine for the M1 paper loop. It deliberately reuses the exact
cost + slippage math from the backtest's :class:`IndiaIntradayEngine`, so a paper
session and a backtest price a round-trip identically (the plan's whole reason for
paper-first: catch the MIS cost drag before risking cash). It holds no live
broker surface — Dhan stays paper-only (P2) until M2.

Direction (3L). By default the broker is **long-only**: :meth:`buy` opens/adds a
long, :meth:`sell` only ever reduces or closes it (clamped — never flips short).
The hybrid A/B twins additionally use :meth:`short` / :meth:`cover`; a position is
long XOR short XOR flat in a symbol (invariant 6 — buy refuses while a short is
open, short refuses while a long is open). Shorting exists in this **paper**
broker only; live/M2 stays long-only.

Accounting model (the identities are the spec, docs/IMPLEMENTATION_PLAN.md §3L):

  * **Long.** Entry (buy) pays stamp duty; exit (sell) pays STT; both legs pay
    capped brokerage + exchange + SEBI + 18% GST — via
    ``IndiaIntradayEngine.calc_commission``. Cash −= (qty·fill + comm) at entry;
    equity marks the holding at ``qty·mark``.
  * **Short.** Entry (short) is a sell → pays STT; cover is a buy → pays stamp
    duty. **1x capital, no leverage:** a short reserves the full notional +
    entry commission from cash exactly like a long's outlay, so an account can
    never deploy more than its cash across both directions. Cash −=
    (qty·entry_fill + entry_comm) at entry; on cover cash += that reserve +
    realized, where
    ``realized = (qty·entry_fill − entry_comm) − (qty·cover_fill + cover_comm)``.
  * **Equity is continuous through every fill** — it jumps only by that fill's
    commission + slippage. A short's contribution above cash is
    ``entry_notional + (entry_fill − mark)·qty`` (it gains as price falls); the
    entry commission is a sunk cost already out of cash, so it is not carried in
    equity. A round-trip at one price with zero slippage realizes exactly
    ``−(entry_comm + cover_comm)``.
  * **Slippage.** Buys/covers fill slightly through (pay up), sells/shorts
    slightly under — via ``IndiaIntradayEngine.apply_slippage``.

Cash and realized P&L are tracked in ₹. Every fill returns an immutable
:class:`Fill` the runner hands to the notifier and the journal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from backtest.engines.india_intraday import IndiaIntradayEngine

#: A long round-trip is buy→sell; a short round-trip is short→cover.
Side = Literal["buy", "sell", "short", "cover"]


@dataclass(frozen=True)
class Fill:
    """One simulated paper fill.

    Attributes:
        symbol: The instrument filled.
        side: ``"buy"`` / ``"sell"`` (open/close a long) or ``"short"`` /
            ``"cover"`` (open/close a short).
        qty: Filled quantity (shares, always positive).
        price: Slippage-adjusted fill price (₹).
        commission: MIS charges for this leg (₹).
        timestamp: Fill time (as passed by the runner; IST by convention).
        realized_pnl: Net realized P&L booked by THIS fill (``sell`` and
            ``cover`` only; ₹, net of both legs' commissions). ``0.0`` for the
            opening ``buy`` / ``short``.
        cash_after: Account cash after the fill (₹).
    """

    symbol: str
    side: Side
    qty: float
    price: float
    commission: float
    timestamp: datetime
    realized_pnl: float = 0.0
    cash_after: float = 0.0


@dataclass
class Position:
    """An open position (long or short) with the data needed to book exit P&L.

    Long: ``entry_cost`` is the total ₹ paid to acquire ``qty`` (fills × price +
    buy commissions), so realized P&L on a sell is
    ``sell_proceeds − sell_commission − entry_cost_of_qty_sold``.

    Short: ``entry_notional`` is ``Σ qty·entry_fill`` (the sell proceeds, ex
    commission) and ``entry_comm`` is the entry (STT) commission; the cash
    reserved at entry is ``entry_notional + entry_comm`` (1x, no leverage).
    """

    symbol: str
    qty: float = 0.0
    direction: int = 1            # 1 = long, -1 = short
    entry_cost: float = 0.0       # long: total ₹ laid out (incl buy commissions)
    entry_notional: float = 0.0   # short: Σ qty·entry_fill (ex commission)
    entry_comm: float = 0.0       # short: Σ entry (STT) commission

    @property
    def is_open(self) -> bool:
        return self.qty > 0

    @property
    def is_short(self) -> bool:
        return self.direction == -1

    @property
    def reserve(self) -> float:
        """Short only: cash reserved at entry (notional + entry commission)."""
        return self.entry_notional + self.entry_comm

    @property
    def avg_price(self) -> float:
        """Reference entry price: for a short the mean entry fill, for a long
        the commission-inclusive average (the existing long convention)."""
        if self.qty <= 0:
            return 0.0
        if self.is_short:
            return self.entry_notional / self.qty
        return self.entry_cost / self.qty


class PaperBroker:
    """Simulates MIS fills (long, and — for the hybrid twins — short) against a
    shared cost/slippage engine.

    Attributes:
        cash: Current uninvested cash (₹).
        realized_pnl: Cumulative realized P&L across the session (₹).
    """

    def __init__(self, initial_cash: float, *, engine: IndiaIntradayEngine | None = None) -> None:
        """Initialize the paper account.

        Args:
            initial_cash: Starting cash (₹).
            engine: Cost/slippage engine. Defaults to a stock
                :class:`IndiaIntradayEngine` with MIS defaults; inject a
                pre-configured one to match a specific strategy's cost config.
        """
        self.cash = float(initial_cash)
        self.starting_cash = float(initial_cash)
        self.realized_pnl = 0.0
        self._engine = engine or IndiaIntradayEngine({})
        self._positions: dict[str, Position] = {}

    # -- inspection ----------------------------------------------------------

    def position(self, symbol: str) -> Position:
        """Return the (possibly flat) position for ``symbol``."""
        return self._positions.get(symbol, Position(symbol))

    def open_symbols(self) -> list[str]:
        """Return the symbols with a currently open position (long or short)."""
        return [s for s, p in self._positions.items() if p.is_open]

    def equity(self, marks: dict[str, float]) -> float:
        """Return cash + marked-to-market value of open positions.

        Longs mark at ``qty·mark``; shorts contribute
        ``entry_notional + (entry_fill − mark)·qty`` (they gain as price falls).
        Missing marks fall back to the position's entry reference price, so a
        symbol with no current price contributes exactly what it cost.

        Args:
            marks: Symbol → current price (₹) for open positions.
        """
        total = self.cash
        for s, p in self._positions.items():
            if not p.is_open:
                continue
            mark = marks.get(s, p.avg_price)
            if p.is_short:
                total += p.entry_notional + (p.avg_price - mark) * p.qty
            else:
                total += p.qty * mark
        return total

    # -- fills: long ---------------------------------------------------------

    def buy(
        self,
        symbol: str,
        price: float,
        *,
        cash_budget: float,
        timestamp: datetime | None = None,
    ) -> Fill | None:
        """Open/add a long by deploying up to ``cash_budget`` at ``price``.

        Sizes the largest whole-share quantity whose (slippage-adjusted cost +
        commission) fits within ``cash_budget`` and available cash. Returns
        ``None`` when nothing can be afforded, or when a short is already open on
        this symbol (invariant 6 — direction flips must close first).
        """
        pos = self._positions.get(symbol)
        if pos is not None and pos.is_open and pos.is_short:
            return None  # can't add a long over an open short
        fill_price = self._engine.apply_slippage(float(price), 1)
        if fill_price <= 0:
            return None
        budget = min(float(cash_budget), self.cash)
        qty = self._size_within(budget, fill_price, direction=1)
        if qty <= 0:
            return None
        commission = self._engine.calc_commission(qty, fill_price, 1, True)
        total = qty * fill_price + commission

        pos = self._positions.setdefault(symbol, Position(symbol, direction=1))
        pos.direction = 1
        pos.qty += qty
        pos.entry_cost += total
        self.cash -= total
        return Fill(
            symbol=symbol,
            side="buy",
            qty=qty,
            price=fill_price,
            commission=commission,
            timestamp=timestamp or _ts(price),
            realized_pnl=0.0,
            cash_after=self.cash,
        )

    def sell(self, symbol: str, price: float, *, qty: float | None = None, timestamp: datetime | None = None) -> Fill | None:
        """Reduce/close a long. Clamped to the holding (never flips short).

        Only acts on a long position; a short is closed with :meth:`cover`.

        Args:
            symbol: Instrument to sell.
            price: Reference price; sell slippage is applied on top.
            qty: Quantity to sell. ``None`` (default) closes the whole position.
                Any value above the holding is clamped down.
            timestamp: Fill time (IST by convention). Defaults to ``now`` in IST.

        Returns:
            The :class:`Fill` (with realized P&L), or ``None`` if no long held.
        """
        pos = self._positions.get(symbol)
        if pos is None or not pos.is_open or pos.is_short:
            return None
        sell_qty = pos.qty if qty is None else min(float(qty), pos.qty)
        if sell_qty <= 0:
            return None

        fill_price = self._engine.apply_slippage(float(price), -1)
        commission = self._engine.calc_commission(sell_qty, fill_price, 1, False)
        proceeds = sell_qty * fill_price - commission

        # Portion of entry cost attributable to the shares being sold.
        cost_fraction = pos.entry_cost * (sell_qty / pos.qty)
        realized = proceeds - cost_fraction

        pos.qty -= sell_qty
        pos.entry_cost -= cost_fraction
        if pos.qty <= 1e-9:
            pos.qty = 0.0
            pos.entry_cost = 0.0
        self.cash += proceeds
        self.realized_pnl += realized
        return Fill(
            symbol=symbol,
            side="sell",
            qty=sell_qty,
            price=fill_price,
            commission=commission,
            timestamp=timestamp or _ts(price),
            realized_pnl=realized,
            cash_after=self.cash,
        )

    # -- fills: short --------------------------------------------------------

    def short(
        self,
        symbol: str,
        price: float,
        *,
        cash_budget: float,
        timestamp: datetime | None = None,
    ) -> Fill | None:
        """Open/add a short, reserving up to ``cash_budget`` of notional + comm.

        1x capital: the reserve (qty·fill + entry commission) is deducted from
        cash exactly like a long's outlay, so shorts and longs compete for the
        same rupees. Returns ``None`` when nothing can be afforded, or when a
        long is already open on this symbol (invariant 6).
        """
        pos = self._positions.get(symbol)
        if pos is not None and pos.is_open and not pos.is_short:
            return None  # can't add a short over an open long
        fill_price = self._engine.apply_slippage(float(price), -1)
        if fill_price <= 0:
            return None
        budget = min(float(cash_budget), self.cash)
        qty = self._size_within(budget, fill_price, direction=-1)
        if qty <= 0:
            return None
        commission = self._engine.calc_commission(qty, fill_price, -1, True)
        reserve = qty * fill_price + commission

        pos = self._positions.setdefault(symbol, Position(symbol, direction=-1))
        pos.direction = -1
        pos.qty += qty
        pos.entry_notional += qty * fill_price
        pos.entry_comm += commission
        self.cash -= reserve
        return Fill(
            symbol=symbol,
            side="short",
            qty=qty,
            price=fill_price,
            commission=commission,
            timestamp=timestamp or _ts(price),
            realized_pnl=0.0,
            cash_after=self.cash,
        )

    def cover(self, symbol: str, price: float, *, qty: float | None = None, timestamp: datetime | None = None) -> Fill | None:
        """Buy-to-cover a short. Clamped to the holding (never flips long).

        Returns the :class:`Fill` with realized P&L, or ``None`` if no short
        held. Releases the covered fraction of the entry reserve back to cash
        along with the realized P&L.
        """
        pos = self._positions.get(symbol)
        if pos is None or not pos.is_open or not pos.is_short:
            return None
        cover_qty = pos.qty if qty is None else min(float(qty), pos.qty)
        if cover_qty <= 0:
            return None
        frac = cover_qty / pos.qty

        fill_price = self._engine.apply_slippage(float(price), 1)
        commission = self._engine.calc_commission(cover_qty, fill_price, -1, False)

        entry_notional_part = pos.entry_notional * frac
        entry_comm_part = pos.entry_comm * frac
        reserve_part = entry_notional_part + entry_comm_part
        realized = (entry_notional_part - entry_comm_part) - (cover_qty * fill_price + commission)

        pos.qty -= cover_qty
        pos.entry_notional -= entry_notional_part
        pos.entry_comm -= entry_comm_part
        if pos.qty <= 1e-9:
            pos.qty = 0.0
            pos.entry_notional = 0.0
            pos.entry_comm = 0.0
        self.cash += reserve_part + realized
        self.realized_pnl += realized
        return Fill(
            symbol=symbol,
            side="cover",
            qty=cover_qty,
            price=fill_price,
            commission=commission,
            timestamp=timestamp or _ts(price),
            realized_pnl=realized,
            cash_after=self.cash,
        )

    def close_position(self, symbol: str, price: float, *, timestamp: datetime | None = None) -> Fill | None:
        """Flatten a symbol: sell a long or cover a short (whichever is open).

        The single choke point the runner's 15:15 force-flatten and the
        portfolio kill-switch call, so shorts are closed (buy-to-cover) exactly
        as authoritatively as longs are sold (invariant 2).
        """
        pos = self._positions.get(symbol)
        if pos is None or not pos.is_open:
            return None
        if pos.is_short:
            return self.cover(symbol, price, timestamp=timestamp)
        return self.sell(symbol, price, timestamp=timestamp)

    # -- sizing --------------------------------------------------------------

    def _size_within(self, budget: float, fill_price: float, *, direction: int) -> float:
        """Largest whole-share qty whose (qty·fill + entry commission) fits
        ``budget`` for an entry in ``direction`` (1 buy = stamp, −1 short = STT).
        """
        qty = self._engine.round_size(budget / fill_price, fill_price) if fill_price > 0 else 0
        while qty > 0:
            commission = self._engine.calc_commission(qty, fill_price, direction, True)
            if qty * fill_price + commission <= budget + 1e-9:
                break
            qty -= 1
        return qty


def _ts(_price: float) -> datetime:
    """Return the current IST time (fill default when the caller gives none)."""
    from src.intraday.clock import IST

    return datetime.now(IST)
