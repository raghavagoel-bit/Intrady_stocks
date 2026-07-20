"""The intraday paper session runner — per-interval signal → paper fill → notify.

This is the M1 core deliverable (root plan §4.1 "market-hours runner"): a loop
that, each interval during the IST session, pulls recent bars, runs the SAME
rule-based ``SignalEngine`` the backtest uses, simulates MIS fills through the
:class:`PaperBroker`, and posts every event to the trade feed — then FORCE-
flattens any still-open long at the square-off cutoff (15:15 IST), authoritatively
and independent of the strategy.

The design mirrors the base repo's live runtime: the per-tick decision is a pure,
injectable method (:meth:`run_tick`) that takes ``now`` and returns the fills it
booked, so a whole session is unit-testable with a replay bar source and a frozen
clock — no live Dhan / Telegram / Gemini. The thin async wrapper
(:meth:`run_session`) only adds the wall-clock sleep loop.

Fill convention: the runner acts on a bar the moment it observes it and fills at
that bar's **close** (paper). The backtest fills next-bar-open; the small
difference is a known paper-vs-backtest basis, documented in docs/QA.md. The
strategy's own "flat by 15:00" rule still applies; 15:15 is the hard backstop.
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.intraday.bars import BarSource
from src.intraday.clock import SessionClock, to_ist
from src.intraday.config import IntradayConfig
from src.intraday.notifier import TradeNotifier
from src.intraday.paper_broker import Fill, PaperBroker

logger = logging.getLogger(__name__)


def load_signal_engine(run_dir: str | Path, *, allow_short: bool = False):
    """Import and instantiate ``SignalEngine`` from a strategy run dir.

    Expects ``<run_dir>/code/signal_engine.py`` exposing a ``SignalEngine`` with
    a no-arg ctor (the repo's backtest run-dir contract). Imported under a unique
    module name so multiple strategies can coexist.

    For a 3L hybrid twin (``allow_short=True``) the engine is built as
    ``SignalEngine(allow_short=True)`` so the SAME source drives both arms (never
    a copied run dir). If a strategy's ctor does not accept the flag, the
    resulting :class:`TypeError` is **re-raised** — a misconfigured twin silently
    running long-only would poison the A/B, so it must fail fast at startup.

    Args:
        run_dir: Path to the strategy run directory.
        allow_short: Build a short-capable (hybrid) engine.

    Returns:
        A fresh ``SignalEngine`` instance.

    Raises:
        FileNotFoundError: If ``code/signal_engine.py`` is missing.
        AttributeError: If the module has no ``SignalEngine`` class.
        TypeError: If ``allow_short`` is requested but the ctor rejects it.
    """
    path = Path(run_dir) / "code" / "signal_engine.py"
    if not path.exists():
        raise FileNotFoundError(f"strategy signal engine not found: {path}")
    mod_name = f"intraday_strategy_{path.parent.parent.name}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load strategy module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if allow_short:
        try:
            return module.SignalEngine(allow_short=True)
        except TypeError as exc:  # fail fast — never fall back to long-only
            raise TypeError(
                f"strategy at {path} does not accept allow_short=True "
                f"(hybrid twin cannot be built): {exc}"
            ) from exc
    return module.SignalEngine()


@dataclass
class SessionState:
    """Mutable per-session accounting the runner accumulates.

    Attributes:
        fills: Every fill booked this session, in order.
        halted: Set once a HALT is raised — the loop stops trading.
        squared_off: Set once the 15:15 force-flatten has run (idempotent guard).
    """

    fills: list[Fill] = field(default_factory=list)
    halted: bool = False
    squared_off: bool = False


class IntradayPaperRunner:
    """Drives one paper trading day for the configured universe.

    Attributes:
        config: The resolved intraday config.
        broker: The paper broker booking fills.
        notifier: The trade-event notifier.
        clock: IST session-boundary tests.
        state: Live :class:`SessionState`.
    """

    def __init__(
        self,
        config: IntradayConfig,
        bar_source: BarSource,
        notifier: TradeNotifier,
        *,
        broker: PaperBroker | None = None,
        signal_engine: Any | None = None,
        allow_short: bool = False,
    ) -> None:
        """Initialize the runner.

        Args:
            config: Resolved intraday config.
            bar_source: Recent-bar provider (Dhan or replay).
            notifier: Trade-event notifier.
            broker: Paper broker (defaults to one seeded with ``initial_cash``).
            signal_engine: Pre-built ``SignalEngine``. When ``None``, it is
                loaded from ``config.strategy_run_dir``.
            allow_short: Hybrid twin — honor −1 signals as short entries. When
                ``False`` (default, the long-only arm) a −1 is coerced to flat.
        """
        self.config = config
        self._bars = bar_source
        self.notifier = notifier
        self.allow_short = allow_short
        self.broker = broker or PaperBroker(config.initial_cash)
        self.clock = SessionClock.from_config(config)
        self._engine = signal_engine or load_signal_engine(
            config.strategy_run_dir, allow_short=allow_short
        )
        self.state = SessionState()

    @property
    def per_symbol_budget(self) -> float:
        """Cash allocated per entry (equal split of THIS account across the cap).

        Uses the broker's own starting capital, so a per-strategy account in the
        multi-strategy portfolio sizes off its ₹25k (not the shared config cash).
        """
        cap = max(self.config.position_cap, 1)
        return self.broker.starting_cash / cap

    # -- the per-tick decision (pure, testable) ------------------------------

    def run_tick(self, now: datetime) -> list[Fill]:
        """Evaluate one interval and book any resulting fills.

        Ordering per tick:
          1. If halted, do nothing.
          2. If at/after square-off cutoff, force-flatten all open longs (once).
          3. Otherwise, within the session window, run the signal engine and
             apply entries/exits versus current positions.

        Args:
            now: Current time (any tz; interpreted in IST).

        Returns:
            The fills booked on this tick (possibly empty).
        """
        if self.state.halted:
            return []

        if self.clock.is_past_squareoff(now):
            return self._force_flatten(now)

        if not self.clock.is_open(now):
            return []

        return self._apply_signals(now)

    def _apply_signals(self, now: datetime) -> list[Fill]:
        """Run the engine over recent bars and reconcile positions to signals.

        Desired direction per symbol is −1 (short), 0 (flat), or 1 (long); the
        long-only arm never sees −1 (coerced away in :meth:`_desired_positions`).
        Exits run first: any open position whose direction differs from the
        desired one is closed via :meth:`~PaperBroker.close_position` — this both
        flattens (desired 0) and executes a direction flip (close, then open the
        other side later this tick, cap permitting → invariant 6). Entries then
        open the desired side, respecting the position cap across BOTH directions.
        """
        desired = self._desired_positions(now)
        fills: list[Fill] = []
        ist_now = to_ist(now)

        # Exits first (frees cash + a position slot before entries this tick).
        for symbol, want in desired.items():
            pos = self.broker.position(symbol)
            if pos.is_open and pos.direction != want:
                price = self._last_price(symbol, now)
                if price is None:
                    continue
                fill = self.broker.close_position(symbol, price, timestamp=ist_now)
                if fill is not None:
                    self._record(fill)
                    self.notifier.exit(fill, running_pnl=self.broker.realized_pnl)
                    fills.append(fill)

        # Entries, respecting the simultaneous-position cap over both directions.
        for symbol, want in desired.items():
            if want == 0 or self.broker.position(symbol).is_open:
                continue
            if len(self.broker.open_symbols()) >= self.config.position_cap:
                break
            price = self._last_price(symbol, now)
            if price is None:
                continue
            if want == 1:
                fill = self.broker.buy(
                    symbol, price, cash_budget=self.per_symbol_budget, timestamp=ist_now
                )
            else:  # want == -1 (hybrid twins only)
                fill = self.broker.short(
                    symbol, price, cash_budget=self.per_symbol_budget, timestamp=ist_now
                )
            if fill is not None:
                self._record(fill)
                self.notifier.entry(fill, running_pnl=self.broker.realized_pnl)
                fills.append(fill)

        return fills

    def _force_flatten(self, now: datetime) -> list[Fill]:
        """Close every open position at market — the 15:15 authoritative
        square-off. Sells longs AND buys-to-cover shorts (an uncovered short at
        square-off would be a settlement failure — invariant 2), including the
        no-price fallback to the position's entry reference price."""
        if self.state.squared_off:
            return []
        self.state.squared_off = True
        fills: list[Fill] = []
        ist_now = to_ist(now)
        for symbol in list(self.broker.open_symbols()):
            price = self._last_price(symbol, now)
            if price is None:
                price = self.broker.position(symbol).avg_price
            fill = self.broker.close_position(symbol, price, timestamp=ist_now)
            if fill is not None:
                self._record(fill)
                self.notifier.squareoff(fill, running_pnl=self.broker.realized_pnl)
                fills.append(fill)
        return fills

    # -- helpers -------------------------------------------------------------

    def _desired_positions(self, now: datetime) -> dict[str, int]:
        """Return symbol → desired direction (−1/0/1) from the engine's last bar.

        A −1 (short) is coerced to 0 for the long-only arm (``allow_short`` off) —
        a defensive belt-and-braces on top of the engine's own long-only ctor, so
        a stray −1 can never open a short in the long-only slots.
        """
        data_map = self._build_data_map(now)
        if not data_map:
            return {}
        try:
            signals = self._engine.generate(data_map)
        except Exception:  # noqa: BLE001 — a strategy error halts trading safely
            logger.exception("signal engine raised — halting session")
            self.halt("signal engine error")
            return {}
        desired: dict[str, int] = {}
        for symbol, series in signals.items():
            if series is None or len(series) == 0:
                continue
            want = int(series.iloc[-1])
            if want not in (-1, 0, 1):
                want = 0
            if want == -1 and not self.allow_short:
                want = 0  # long-only arm never shorts
            desired[symbol] = want
        return desired

    def _build_data_map(self, now: datetime) -> dict[str, pd.DataFrame]:
        """Assemble the per-symbol recent-bar frames for the signal engine."""
        data_map: dict[str, pd.DataFrame] = {}
        for inst in self.config.universe:
            if hasattr(self._bars, "set_now"):
                self._bars.set_now(now)  # replay source honors the cursor
            frame = self._bars.recent_bars(inst.symbol, lookback=self.config.lookback_bars)
            if frame is not None and not frame.empty:
                data_map[inst.symbol] = frame
        return data_map

    def _last_price(self, symbol: str, now: datetime) -> float | None:
        """Return the latest observed close for ``symbol`` at/before ``now``."""
        if hasattr(self._bars, "set_now"):
            self._bars.set_now(now)
        frame = self._bars.recent_bars(symbol, lookback=1)
        if frame is None or frame.empty:
            return None
        return float(frame["close"].iloc[-1])

    def _record(self, fill: Fill) -> None:
        self.state.fills.append(fill)

    def halt(self, reason: str) -> None:
        """Trip the session halt and notify (no further trading this session)."""
        if self.state.halted:
            return
        self.state.halted = True
        logger.warning("intraday session halted: %s", reason)
        self.notifier.halt(reason)

    # -- async session loop (thin wrapper over run_tick) ---------------------

    async def run_session(
        self,
        *,
        interval_seconds: float = 900.0,
        now_fn: Callable[[], datetime] | None = None,
        sleep_fn: Callable[[float], Any] | None = None,
        max_ticks: int | None = None,
    ) -> SessionState:
        """Run the wall-clock loop until market close (or ``max_ticks``).

        Args:
            interval_seconds: Seconds between ticks (900 = 15m to match bars).
            now_fn: Clock (defaults to IST ``now``). Injectable for tests.
            sleep_fn: Async sleep (defaults to ``asyncio.sleep``). Injectable.
            max_ticks: Optional hard cap on ticks (test safety / dry runs).

        Returns:
            The final :class:`SessionState`.
        """
        import asyncio

        from src.intraday.clock import IST

        now_fn = now_fn or (lambda: datetime.now(IST))
        sleep_fn = sleep_fn or asyncio.sleep

        self.notifier.info(f"session start · {self.config.redacted()['universe']}")
        ticks = 0
        while True:
            now = now_fn()
            self.run_tick(now)
            ticks += 1
            done = self.state.halted or (
                self.state.squared_off and self.clock.is_after_close(now)
            )
            if done or (max_ticks is not None and ticks >= max_ticks):
                break
            await sleep_fn(interval_seconds)
        self.notifier.info(
            f"session end · fills={len(self.state.fills)} · "
            f"realized={self.broker.realized_pnl:+,.2f}"
        )
        return self.state
