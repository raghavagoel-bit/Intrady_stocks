"""Vibe-Intraday paper runtime (M1) — rule-driven NSE intraday MIS loop.

This package is the project-specific layer built ON TOP of the vendored
HKUDS/Vibe-Trading base repo (it never edits the protected ``src/agent`` /
``src/session`` internals). It implements the M1 paper intraday loop from
``docs/IMPLEMENTATION_PLAN.md`` §3D:

  * :mod:`~src.intraday.config`      — placeholder-first config (creds set later).
  * :mod:`~src.intraday.clock`       — IST market-hours + square-off cutoff logic.
  * :mod:`~src.intraday.bars`        — bar sources (Dhan 15m + offline replay).
  * :mod:`~src.intraday.paper_broker`— long-only MIS paper fills (MIS cost stack).
  * :mod:`~src.intraday.notifier`    — ENTRY/EXIT/SQUARE-OFF/HALT → Telegram/log.
  * :mod:`~src.intraday.gemini_jobs` — pre-market watchlist + EOD review.
  * :mod:`~src.intraday.runner`      — the per-interval market-hours session.

Everything is dependency-injected and unit-testable with no live Dhan / Gemini /
Telegram — the same design the base repo's live runtime uses. Live orders (M2)
are out of scope here: the loop is paper-only by construction.
"""

from src.intraday.config import IntradayConfig, Instrument, StrategyRef

__all__ = ["IntradayConfig", "Instrument", "StrategyRef"]

# NOTE: Portfolio / runner / scoreboard are intentionally NOT imported here — they
# pull in pandas + the backtest engine, which callers may not need just to read
# config. Import them from their modules directly (src.intraday.portfolio, etc.).
