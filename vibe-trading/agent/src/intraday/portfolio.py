"""Parallel multi-strategy paper bake-off (week-1 M1 plan).

Runs the whole roster of strategies **side by side** on one shared live bar feed,
each in its own isolated ₹25k paper account, so a week of paper trading produces a
clean per-strategy ranking to decide which setup graduates to a live test.

Three behaviours this layer adds over the single-strategy runner:

  * **Isolation.** One :class:`IntradayPaperRunner` + :class:`PaperBroker` per
    strategy; they share bars but never share cash or positions. Per-trade events
    go to each runner's log tape (not Telegram) to keep the feed quiet.
  * **Per-strategy setup kill-switch.** After every tick, a strategy whose
    cumulative loss (realized + open) reaches ``per_strategy_loss_cutoff`` (₹10k)
    is squared off and **retired for the rest of the run** — permanently, not a
    daily reset — while the survivors keep trading. A disqualified setup is not a
    candidate.
  * **Reporting.** An **hourly** rollup (trades + running P&L per strategy) and an
    end-of-day **scoreboard** go to Telegram; the daily result is persisted so the
    week accumulates (see :mod:`~src.intraday.scoreboard`).

Everything is injectable (bar source, notifier, clock, store), so a full multi-day
bake-off is unit-testable with replay bars and a frozen clock — no live services.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.intraday.bars import BarSource
from src.intraday.clock import IST, SessionClock, to_ist
from src.intraday.config import IntradayConfig
from src.intraday.notifier import LogSink, TradeNotifier, build_sink
from src.intraday.runner import IntradayPaperRunner, load_signal_engine
from src.intraday.paper_broker import PaperBroker
from src.intraday.scoreboard import (
    ScoreboardStore,
    StrategyMetrics,
    compute_metrics,
    format_hourly_detailed,
    format_scoreboard,
)

logger = logging.getLogger(__name__)


def _default_store_path() -> Path:
    """Default weekly scoreboard location under the runtime root."""
    try:
        from src.config.paths import get_runtime_root

        return get_runtime_root() / "intraday" / "scoreboard.json"
    except Exception:  # pragma: no cover - fall back to CWD if paths unavailable
        return Path("intraday_scoreboard.json")


def _resolve_run_dir(run_dir: str) -> Path:
    """Resolve a roster ``run_dir`` (absolute, or relative to the agent root)."""
    path = Path(run_dir)
    if path.is_absolute() or path.exists():
        return path
    agent_root = Path(__file__).resolve().parents[2]  # src/intraday → src → agent
    return agent_root / run_dir


@dataclass
class Slot:
    """One strategy's isolated paper account within the portfolio.

    Attributes:
        name: Strategy label.
        runner: The strategy's own :class:`IntradayPaperRunner`.
        starting_cash: Independent starting capital (₹).
        halted: Set once the setup kill-switch retired it.
        halt_reason: Why it was retired.
        hour_trade_baseline: Sell-count snapshot at the last hourly summary (to
            compute trades-this-hour).
        hour_fill_baseline: Fill-count snapshot at the last hourly summary (the
            detailed report lists every fill since this index).
    """

    name: str
    runner: IntradayPaperRunner
    starting_cash: float
    halted: bool = False
    halt_reason: str = ""
    hour_trade_baseline: int = 0
    hour_fill_baseline: int = 0

    @property
    def broker(self) -> PaperBroker:
        return self.runner.broker

    def sell_count(self) -> int:
        """Count of round-trips closed (sells + short covers)."""
        return sum(1 for f in self.runner.state.fills if f.side in ("sell", "cover"))


class Portfolio:
    """Drives the whole roster in parallel for one (or many) paper day(s)."""

    def __init__(
        self,
        config: IntradayConfig,
        bar_source: BarSource,
        *,
        notifier: TradeNotifier | None = None,
        scoreboard_store: ScoreboardStore | None = None,
        signal_engines: dict[str, Any] | None = None,
    ) -> None:
        """Build one isolated runner per roster strategy.

        Args:
            config: Resolved config (its ``roster`` + ``per_strategy_cash`` +
                ``per_strategy_loss_cutoff`` drive the bake-off).
            bar_source: Shared recent-bar provider (all strategies see identical bars).
            notifier: Telegram/log feed for hourly + EOD + halt (defaults from config).
            scoreboard_store: Weekly persistence (defaults under the runtime root).
            signal_engines: Optional ``{name: SignalEngine}`` to inject pre-built
                engines (tests); otherwise each is loaded from its ``run_dir``.
        """
        self.config = config
        self._bars = bar_source
        self.clock = SessionClock.from_config(config)
        self.feed = notifier or TradeNotifier(build_sink(config), mode="PAPER")
        self.store = scoreboard_store or ScoreboardStore(_default_store_path())
        self._last_summary_hour: int | None = None
        self._finalized = False
        self._reconnect_budget_s = max(0.0, float(config.reconnect_budget_seconds))

        engines = signal_engines or {}
        self.slots: list[Slot] = []
        for ref in config.roster:
            engine = engines.get(ref.name)
            if engine is None and ref.run_dir.startswith("builtin:"):
                # Overlay-provided engine (e.g. the LLM trader) — trusted code,
                # so it may use network/creds the run-dir sandbox forbids.
                from src.intraday.llm_engine import build_builtin_engine

                engine = build_builtin_engine(
                    ref.run_dir.split(":", 1)[1], config,
                    allow_short=ref.allow_short, slot_name=ref.name, **ref.params,
                )
            if engine is None:
                if ref.params:
                    # Run-dir engines take no roster params (3R is builtin-only).
                    logger.warning(
                        "portfolio: slot %s carries roster params %s but is a "
                        "run-dir strategy — params ignored", ref.name, sorted(ref.params),
                    )
                # Hybrid twins load the SAME source with allow_short=True; a ctor
                # that rejects the flag raises here (fail fast — see load_signal_engine).
                engine = load_signal_engine(_resolve_run_dir(ref.run_dir), allow_short=ref.allow_short)
            runner = IntradayPaperRunner(
                config,
                bar_source,
                # Per-trade → log, not Telegram; the mode tag carries the strategy
                # name so log lines are attributable across parallel slots.
                TradeNotifier(LogSink(), mode=f"PAPER·{ref.name}"),
                broker=PaperBroker(config.per_strategy_cash),
                signal_engine=engine,
                allow_short=ref.allow_short,
            )
            self.slots.append(Slot(ref.name, runner, config.per_strategy_cash))

    # -- per-tick ------------------------------------------------------------

    def run_tick(self, now: datetime) -> None:
        """Tick every live strategy, enforce the kill-switch, emit hourly rollups.

        Each slot's tick is isolated in try/except: one process now hosts BOTH
        the 21 long-only slots and the 21 hybrid twins (3L), and an unexpected
        broker/engine exception in one slot must never end the other 41 slots'
        day. A raising slot is squared off (best-effort) and halted alone.
        """
        for slot in self.slots:
            if slot.halted:
                continue
            try:
                slot.runner.run_tick(now)
                self._check_cutoff(slot, now)
            except Exception:  # noqa: BLE001 — isolate one slot's failure
                logger.exception(
                    "portfolio: slot %s raised in run_tick — halting only that slot", slot.name
                )
                self._halt_slot(slot, now, "internal error in run_tick (see log)")
        self._maybe_hourly(now)

    def _halt_slot(self, slot: Slot, now: datetime, reason: str) -> None:
        """Square off (best-effort) and permanently halt a single slot."""
        try:
            ist_now = to_ist(now)
            for symbol in list(slot.broker.open_symbols()):
                price = self._last_price(symbol, now) or slot.broker.position(symbol).avg_price
                slot.broker.close_position(symbol, price, timestamp=ist_now)
        except Exception:  # noqa: BLE001 — never let cleanup re-raise into the loop
            logger.exception("portfolio: best-effort square-off failed for %s", slot.name)
        slot.halted = True
        slot.halt_reason = reason
        try:
            slot.runner.halt(reason)
        except Exception:  # noqa: BLE001
            logger.exception("portfolio: child halt failed for %s", slot.name)
        self.feed.halt(f"{slot.name} HALTED — {reason}. Not trading further this run.")

    def _check_cutoff(self, slot: Slot, now: datetime) -> None:
        """Retire ``slot`` if its cumulative loss hit the setup kill-switch."""
        cutoff = self.config.per_strategy_loss_cutoff
        if cutoff <= 0 or slot.halted:
            return
        marks = self._marks(now)
        loss = slot.starting_cash - slot.broker.equity(marks)
        if loss < cutoff:
            return
        # Retire: square off everything at last price (longs sold, shorts
        # covered — invariant 2), then halt (permanent).
        ist_now = to_ist(now)
        for symbol in list(slot.broker.open_symbols()):
            price = self._last_price(symbol, now) or slot.broker.position(symbol).avg_price
            slot.broker.close_position(symbol, price, timestamp=ist_now)
        slot.halted = True
        slot.halt_reason = f"setup kill-switch: loss ≥ ₹{cutoff:,.0f}"
        slot.runner.halt(slot.halt_reason)  # stops the child runner trading
        self.feed.halt(
            f"{slot.name} RETIRED — cumulative loss ₹{loss:,.0f} ≥ ₹{cutoff:,.0f} "
            f"(net {slot.broker.realized_pnl:+,.0f}). Not trading further this run."
        )
        logger.warning("portfolio: %s retired on setup kill-switch (loss ₹%.0f)", slot.name, loss)

    def _maybe_hourly(self, now: datetime) -> None:
        """Emit the hourly rollup once per IST clock-hour during the session."""
        if not self.clock.is_open(now):
            return
        hour = to_ist(now).hour
        if self._last_summary_hour is None:
            self._last_summary_hour = hour
            self._snapshot_hour_baselines()
            return
        if hour == self._last_summary_hour:
            return
        marks = self._marks(now)
        sections = []
        for s in self.slots:
            opens = []
            for symbol in s.broker.open_symbols():
                pos = s.broker.position(symbol)
                opens.append((symbol, pos.qty, pos.avg_price, marks.get(symbol), pos.direction))
            all_fills = s.runner.state.fills
            sections.append({
                "name": s.name,
                "fills": list(all_fills[s.hour_fill_baseline:]),
                "opens": opens,
                "realized": s.broker.realized_pnl,
                "fees": sum(f.commission for f in all_fills),
                "equity": s.broker.equity(marks),
                "cash": s.broker.cash,
                "halted": s.halted,
                "halt_reason": s.halt_reason,
                "hybrid": s.runner.allow_short,
                "long_pnl": sum(f.realized_pnl for f in all_fills if f.side == "sell"),
                "short_pnl": sum(f.realized_pnl for f in all_fills if f.side == "cover"),
            })
        self.feed.summary(format_hourly_detailed(sections, hour_label=f"{hour:02d}:00"))
        self._last_summary_hour = hour
        self._snapshot_hour_baselines()

    def _snapshot_hour_baselines(self) -> None:
        for s in self.slots:
            s.hour_trade_baseline = s.sell_count()
            s.hour_fill_baseline = len(s.runner.state.fills)

    # -- reporting -----------------------------------------------------------

    def metrics(self) -> list[StrategyMetrics]:
        """Compute per-strategy metrics from the current fills."""
        return [
            compute_metrics(
                s.name,
                s.starting_cash,
                s.runner.state.fills,
                open_positions=len(s.broker.open_symbols()),
                halted=s.halted,
                halt_reason=s.halt_reason,
            )
            for s in self.slots
        ]

    def finalize(self, now: datetime) -> list[StrategyMetrics]:
        """Persist the day's scoreboard and post it to the feed (idempotent)."""
        if self._finalized:
            return self.metrics()
        self._finalized = True
        mets = self.metrics()
        day = to_ist(now).date()
        try:
            self.store.save_day(day, mets)
        except Exception:  # noqa: BLE001 — a persistence hiccup must not crash the run
            logger.warning("scoreboard persistence failed", exc_info=True)
        self.feed.summary(format_scoreboard(mets, title=f"📊 EOD scoreboard · {day.isoformat()}"))
        return mets

    # -- helpers -------------------------------------------------------------

    def _marks(self, now: datetime) -> dict[str, float]:
        marks: dict[str, float] = {}
        for inst in self.config.universe:
            price = self._last_price(inst.symbol, now)
            if price is not None:
                marks[inst.symbol] = price
        return marks

    def _last_price(self, symbol: str, now: datetime) -> float | None:
        if hasattr(self._bars, "set_now"):
            self._bars.set_now(now)
        frame = self._bars.recent_bars(symbol, lookback=1)
        if frame is None or frame.empty:
            return None
        return float(frame["close"].iloc[-1])

    @property
    def all_halted(self) -> bool:
        return bool(self.slots) and all(s.halted for s in self.slots)

    async def _await_data(self, now: datetime, now_fn, sleep_fn) -> datetime:
        """Ride out a short data/Wi-Fi drop before a tick; return the current ``now``.

        A blip up to ``reconnect_budget_seconds`` (default 5 min, < the 15m tick)
        must not cost a bar. Probe one canary symbol through the shared cache:

        * **Online** (probe returns a price): return immediately. The probe warms
          that symbol's cache entry, so ``run_tick`` reuses it — zero extra live
          fetches on the happy path.
        * **Outage** (probe empty/raises): back off 5s→30s and re-probe until data
          returns or the budget lapses, refreshing ``now`` each retry so the tick
          is stamped with real wall-clock time after the wait. If the budget lapses
          the tick still proceeds and degrades to today's empty-frame *hold* — only
          that one bar is lost, exactly as before this guard existed.

        Injectable ``now_fn``/``sleep_fn`` keep it deterministic under test.
        """
        universe = self.config.universe
        if not universe or self._reconnect_budget_s <= 0:
            return now
        canary = universe[0].symbol
        if self._probe(canary, now):
            return now
        self.feed.info(
            f"⚠ data feed down — retrying up to {int(self._reconnect_budget_s)}s before the tick"
        )
        waited = 0.0
        backoff = 5.0
        while waited < self._reconnect_budget_s:
            await sleep_fn(min(backoff, self._reconnect_budget_s - waited))
            waited += backoff
            now = now_fn()
            if self._probe(canary, now):
                self.feed.info(f"✓ data feed restored after ~{int(waited)}s — resuming")
                return now
            backoff = min(backoff * 2, 30.0)
        logger.warning(
            "data feed still down after %ss — proceeding; slots hold this tick", int(waited)
        )
        return now

    def _probe(self, symbol: str, now: datetime) -> bool:
        """True if the canary symbol currently returns a bar (connectivity check)."""
        try:
            return self._last_price(symbol, now) is not None
        except Exception:  # noqa: BLE001 — a raising fetch means 'still down', not a crash
            return False

    # -- async loop ----------------------------------------------------------

    async def run_session(
        self,
        *,
        interval_seconds: float = 900.0,
        now_fn: Callable[[], datetime] | None = None,
        sleep_fn: Callable[[float], Any] | None = None,
        max_ticks: int | None = None,
    ) -> list[StrategyMetrics]:
        """Run the wall-clock loop to close, then finalize the day's scoreboard."""
        import asyncio

        now_fn = now_fn or (lambda: datetime.now(IST))
        sleep_fn = sleep_fn or asyncio.sleep

        self.feed.info(f"bake-off start · {[s.name for s in self.slots]} · ₹{self.config.per_strategy_cash:,.0f} each")
        ticks = 0
        now = now_fn()
        while True:
            now = await self._await_data(now, now_fn, sleep_fn)
            self.run_tick(now)
            ticks += 1
            squared = all(s.runner.state.squared_off or s.halted for s in self.slots)
            done = self.all_halted or (squared and self.clock.is_after_close(now))
            if done or (max_ticks is not None and ticks >= max_ticks):
                break
            await sleep_fn(interval_seconds)
            now = now_fn()
        return self.finalize(now)
