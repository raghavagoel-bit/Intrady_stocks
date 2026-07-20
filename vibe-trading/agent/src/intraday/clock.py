"""IST market-hours + square-off cutoff logic for the intraday session.

Pure, side-effect-free helpers so scheduling decisions are unit-testable without
sleeping or freezing a real clock. Everything is anchored to **Asia/Kolkata**
(IST, UTC+5:30, no DST) regardless of the host timezone — the runtime always
reasons in exchange-local time.

The three boundaries that matter (all configurable via :class:`IntradayConfig`):

  * ``market_open`` (09:15) / ``market_close`` (15:30) — the tradeable window.
  * ``strategy_flat`` (15:00) — the strategy must emit 0 by here so a
    next-bar-open exit lands at the square-off (see DC-001 in the plan).
  * ``squareoff`` (15:15) — at/after this the runtime FORCE-flattens any
    still-open long; this is authoritative and independent of the strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone, timedelta

#: IST is a fixed UTC+5:30 offset (India observes no daylight saving).
IST = timezone(timedelta(hours=5, minutes=30))


def to_ist(moment: datetime) -> datetime:
    """Return ``moment`` in IST.

    A tz-aware datetime is converted; a naive datetime is *assumed already IST*
    (the runtime's canonical zone) rather than guessed as UTC.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=IST)
    return moment.astimezone(IST)


def parse_hhmm(text: str) -> time:
    """Parse an ``"HH:MM"`` string into a :class:`datetime.time`.

    Raises:
        ValueError: If the string is not ``HH:MM``.
    """
    hh, mm = text.strip().split(":")
    return time(int(hh), int(mm))


@dataclass(frozen=True)
class SessionClock:
    """Market-session boundary tests, all in IST.

    Attributes:
        open_at: Session open (IST time-of-day).
        close_at: Session close (IST time-of-day).
        squareoff_at: Force-flatten cutoff (IST time-of-day).
    """

    open_at: time
    close_at: time
    squareoff_at: time

    @classmethod
    def from_config(cls, config) -> "SessionClock":
        """Build a clock from an :class:`~src.intraday.config.IntradayConfig`."""
        return cls(
            open_at=parse_hhmm(config.market_open),
            close_at=parse_hhmm(config.market_close),
            squareoff_at=parse_hhmm(config.squareoff),
        )

    def is_open(self, moment: datetime) -> bool:
        """True when ``moment`` (any tz) falls within [open, close] IST, weekday.

        Note: this does not consult an NSE holiday calendar — holidays simply
        produce no bars, so the runner no-ops. Weekend guard is included because
        it is cheap and unambiguous.
        """
        ist = to_ist(moment)
        if ist.weekday() >= 5:  # Sat/Sun
            return False
        return self.open_at <= ist.time() <= self.close_at

    def is_past_squareoff(self, moment: datetime) -> bool:
        """True when ``moment`` is at/after the square-off cutoff (IST).

        This is the authoritative force-flatten trigger: once true, the runtime
        closes every open long regardless of what the strategy signals.
        """
        return to_ist(moment).time() >= self.squareoff_at

    def is_after_close(self, moment: datetime) -> bool:
        """True when ``moment`` is at/after the market close (IST)."""
        return to_ist(moment).time() >= self.close_at
