"""Bake-off launcher CLI — the thin entry point that runs one paper trading day.

Wires the tested pieces together for a real session (the "start the bake-off"
script from the week-1 plan):

  1. :class:`~src.intraday.config.IntradayConfig` from ``config/intraday.json``
     + ``agent/.env`` (creds must be real — this launcher is for live paper days;
     offline rehearsal stays in the unit tests with replay bars).
  2. :class:`~src.intraday.bars.DhanBarSource` fed by the ``.env`` Dhan creds
     (via :func:`~src.intraday.bars.dhan_config_from_intraday`, DC-003).
  3. :class:`~src.intraday.portfolio.Portfolio` over the configured roster.
  4. The two Gemini bookends: pre-market watchlist before open, EOD review after
     the scoreboard (research/oversight only — never in the per-bar path).

Run from ``agent/`` (one invocation = one trading day; Dhan tokens expire every
24h anyway, so a fresh morning start is the natural unit):

    PYTHONPATH=. python -m src.intraday.bakeoff            # wait for open, run to close
    PYTHONPATH=. python -m src.intraday.bakeoff --max-ticks 3   # bounded probe run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime

from src.intraday.bars import CachedBarSource, DhanBarSource, dhan_config_from_intraday
from src.intraday.clock import IST, SessionClock, to_ist
from src.intraday.config import IntradayConfig
from src.intraday.gemini_jobs import eod_review, make_llm_caller, premarket_watchlist
from src.intraday.portfolio import Portfolio, _resolve_run_dir
from src.intraday.runner import load_signal_engine

logger = logging.getLogger(__name__)


def validate_roster(config: IntradayConfig) -> None:
    """Preflight every roster slot BEFORE any live tick (3L launch gate).

    Loads each strategy exactly as the portfolio will — long-only slots plain,
    hybrid ``_ls`` twins with ``allow_short=True`` — so a misconfigured twin
    (one whose ctor rejects the flag, or an unknown builtin) fails fast at
    startup rather than silently running the wrong arm mid-session.

    Raises:
        Exception: propagated from the first slot that fails to build.
    """
    from src.intraday.llm_engine import build_builtin_engine

    long_n = sum(1 for r in config.roster if not r.allow_short)
    hybrid_n = sum(1 for r in config.roster if r.allow_short)
    logger.info(
        "roster preflight: %d long-only + %d hybrid (_ls) = %d slots",
        long_n, hybrid_n, len(config.roster),
    )
    for ref in config.roster:
        if ref.run_dir.startswith("builtin:"):
            # Mirror the portfolio exactly (slot params included, 3R) so a bad
            # provider/model kwarg fails here, before any live tick.
            build_builtin_engine(
                ref.run_dir.split(":", 1)[1], config,
                allow_short=ref.allow_short, slot_name=ref.name, **ref.params,
            )
        else:
            load_signal_engine(_resolve_run_dir(ref.run_dir), allow_short=ref.allow_short)

#: Pre-open poll cadence (seconds) while waiting for the 09:15 bell.
_WAIT_POLL_SECONDS = 30.0


def interval_seconds(interval: str) -> float:
    """Convert a bar-interval token (``"15m"``, ``"5m"``) to loop seconds."""
    text = interval.strip().lower()
    if text.endswith("m"):
        return float(text[:-1]) * 60.0
    if text.endswith("h"):
        return float(text[:-1]) * 3600.0
    raise ValueError(f"unsupported interval token: {interval!r}")


async def wait_for_open(
    clock: SessionClock,
    *,
    now_fn=None,
    sleep_fn=None,
    poll_seconds: float = _WAIT_POLL_SECONDS,
) -> bool:
    """Sleep until the session opens; return False when today can't trade.

    Returns:
        ``True`` once ``clock.is_open`` (start ticking now); ``False`` when the
        session is already past close or it's a weekend — nothing to run today.
    """
    now_fn = now_fn or (lambda: datetime.now(IST))
    sleep_fn = sleep_fn or asyncio.sleep
    while True:
        now = now_fn()
        if clock.is_open(now):
            return True
        ist = to_ist(now)
        if ist.weekday() >= 5:
            logger.info("weekend (%s IST) — no session today", ist.date())
            return False
        if clock.is_after_close(now):
            logger.info("already past close (%s IST) — no session today", ist.time())
            return False
        await sleep_fn(poll_seconds)


def combined_fills(portfolio: Portfolio):
    """All slots' fills merged in time order (for the portfolio-level EOD review)."""
    fills = [f for slot in portfolio.slots for f in slot.runner.state.fills]
    return sorted(fills, key=lambda f: f.timestamp)


async def run_day(config: IntradayConfig, *, max_ticks: int | None = None) -> int:
    """Run one full paper trading day; return a process exit code."""
    if not config.is_dhan_configured:
        logger.error("Dhan creds are still placeholders — fill agent/.env first.")
        return 2
    missing_ids = [i.symbol for i in config.universe if not i.has_security_id]
    if missing_ids:
        logger.error("missing Dhan security_id for %s — fill config/intraday.json.", missing_ids)
        return 2
    if not config.roster:
        logger.error("empty roster in config/intraday.json — nothing to bake off.")
        return 2

    # 3L launch gate: build every slot (both arms) before the first live tick.
    try:
        validate_roster(config)
    except Exception:  # noqa: BLE001 — a broken twin must not start a live day
        logger.exception(
            "roster preflight FAILED — a strategy could not be built. Launch gate: "
            "fix the twin or run config/intraday.long21.json (20 long-only) instead."
        )
        return 2

    # Cached so all roster runners share ONE Dhan fetch per symbol per tick
    # (15 strategies × 4 symbols would otherwise be ~60 API hits per tick).
    bars = CachedBarSource(
        DhanBarSource(
            {i.symbol: i for i in config.universe},
            interval=config.interval,
            dhan_config=dhan_config_from_intraday(config),
        ),
        min_lookback=config.lookback_bars,
    )
    portfolio = Portfolio(config, bars)
    llm = make_llm_caller(config)
    clock = portfolio.clock

    logger.info("bake-off config: %s", config.redacted())

    # Bookend 1: pre-market watchlist (only if we're actually before the bell).
    now = datetime.now(IST)
    if not clock.is_open(now) and not clock.is_after_close(now) and to_ist(now).weekday() < 5:
        portfolio.feed.watchlist(premarket_watchlist(config, llm))

    if not await wait_for_open(clock):
        return 0

    metrics = await portfolio.run_session(
        interval_seconds=interval_seconds(config.interval),
        max_ticks=max_ticks,
    )

    # Bookend 2: EOD journal review over the whole roster's fills. Metrics +
    # the per-slot split let a 40-slot day aggregate to per-strategy lines (3O)
    # instead of dumping hundreds of raw fills into the prompt.
    fills = combined_fills(portfolio)
    realized = sum(m.net_pnl for m in metrics)
    portfolio.feed.eod(eod_review(
        config, llm, fills,
        realized_pnl=realized,
        metrics=metrics,
        fills_by_strategy={s.name: list(s.runner.state.fills) for s in portfolio.slots},
    ))
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="python -m src.intraday.bakeoff",
        description="Run one paper trading day of the multi-strategy bake-off.",
    )
    parser.add_argument(
        "--config", default=None, help="path to intraday.json (default: config/intraday.json)"
    )
    parser.add_argument(
        "--max-ticks", type=int, default=None,
        help="stop after N ticks (bounded probe run; default: run to close)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument(
        "--log-dir", default="logs",
        help="also write a per-day utf-8 log file here (empty string disables)",
    )
    args = parser.parse_args(argv)

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log_dir:
        from pathlib import Path

        log_dir = Path(args.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        day = datetime.now(IST).strftime("%Y%m%d")
        handlers.append(
            logging.FileHandler(log_dir / f"bakeoff-{day}.log", encoding="utf-8")
        )
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    config = IntradayConfig.load(args.config)
    return asyncio.run(run_day(config, max_ticks=args.max_ticks))


if __name__ == "__main__":
    sys.exit(main())
