"""Bar sources that feed the intraday runner's per-tick signal evaluation.

A :class:`BarSource` returns the most recent ``lookback`` OHLCV bars for one
symbol as a tz-aware (IST) DataFrame — exactly the shape the strategy
``SignalEngine.generate`` consumes. Two implementations ship:

  * :class:`ReplayBarSource` — replays a pre-loaded per-symbol frame up to a
    simulated "now". This is the offline / test / dry-run source and needs no
    credentials; point it at a yfinance 15m pull to rehearse a full session.
  * :class:`DhanBarSource` — live 15m bars via the Dhan connector's read path.

3C note (why DhanBarSource passes ``security_id`` explicitly): Dhan's
``get_historical_bars`` keys on the **numeric security id**, not the ticker, and
the generic ``india_broker`` backtest loader passes the bare symbol — which Dhan
rejects. This source resolves the id from the configured :class:`Instrument` and
passes it through, closing that gap. Dhan intraday candles are also capped at
~5 trading days, so DhanBarSource is for the *live session*, not deep backtests
(those keep using Yahoo — documented in docs/QA.md).
"""

from __future__ import annotations

import logging
from typing import Protocol

import pandas as pd

from src.intraday.config import Instrument

logger = logging.getLogger(__name__)


class BarSource(Protocol):
    """Returns recent OHLCV bars for a symbol as an IST-indexed DataFrame."""

    def recent_bars(self, symbol: str, *, lookback: int) -> pd.DataFrame:  # pragma: no cover
        ...


class ReplayBarSource:
    """Offline source: serves a pre-loaded frame up to a moving cursor.

    Feed it a ``{symbol: full_session_frame}`` map and advance :meth:`set_now`
    each tick; ``recent_bars`` returns the last ``lookback`` bars at/before the
    cursor. Perfect for deterministic tests and for replaying a historical
    session with zero credentials.

    Attributes:
        frames: Symbol → full OHLCV frame (DatetimeIndex).
    """

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = {s: _ensure_ist(df) for s, df in frames.items()}
        self._now: pd.Timestamp | None = None

    def set_now(self, now) -> None:
        """Set the replay cursor; later bars are hidden from ``recent_bars``."""
        ts = pd.Timestamp(now)
        if ts.tzinfo is None:
            from src.intraday.clock import IST

            ts = ts.tz_localize(IST)
        self._now = ts.tz_convert("Asia/Kolkata")

    def recent_bars(self, symbol: str, *, lookback: int) -> pd.DataFrame:
        df = self.frames.get(symbol)
        if df is None or df.empty:
            return pd.DataFrame()
        visible = df if self._now is None else df[df.index <= self._now]
        return visible.tail(lookback)


class DhanBarSource:
    """Live 15m (or configured interval) bars via the Dhan read path.

    Passes the instrument's numeric ``security_id`` + ``exchange_segment``
    explicitly (see the module 3C note). Any per-symbol failure yields an empty
    frame rather than aborting the tick — one bad symbol never stops the session.

    Creds note (DC-003): the Dhan sdk's default ``load_config()`` reads a saved
    ``~/.vibe-trading/dhan.json`` — NOT the environment — so an ``.env``-only
    setup would silently call Dhan with empty creds. Pass ``dhan_config`` (or
    build one with :func:`dhan_config_from_intraday`) to keep secrets in
    ``agent/.env`` only.

    Attributes:
        interval: Dhan period token (``"15m"`` etc.).
    """

    def __init__(
        self,
        instruments: dict[str, Instrument],
        *,
        interval: str = "15m",
        sdk=None,
        dhan_config=None,
    ) -> None:
        """Initialize the Dhan source.

        Args:
            instruments: Symbol → :class:`Instrument` (carries the security id).
            interval: Bar interval token.
            sdk: Dhan sdk module (injectable for tests). Defaults to the real
                ``src.trading.connectors.dhan.sdk``.
            dhan_config: Optional ``DhanConfig`` with real creds (see the DC-003
                creds note). ``None`` falls back to the sdk's saved-file config.
        """
        self._instruments = instruments
        self.interval = interval
        if sdk is None:
            from src.trading.connectors.dhan import sdk as dhan_sdk

            sdk = dhan_sdk
        self._sdk = sdk
        self._dhan_config = dhan_config

    def recent_bars(self, symbol: str, *, lookback: int) -> pd.DataFrame:
        inst = self._instruments.get(symbol)
        if inst is None or not inst.has_security_id:
            logger.warning("Dhan bars: no security_id for %s — skipping", symbol)
            return pd.DataFrame()
        try:
            kwargs = {}
            if self._dhan_config is not None:
                kwargs["config"] = self._dhan_config
            envelope = self._sdk.get_historical_bars(
                inst.symbol,
                security_id=inst.security_id,
                exchange_segment=inst.exchange_segment,
                period=self.interval,
                limit=lookback,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001 — one bad symbol never aborts a tick
            logger.warning("Dhan bars failed for %s: %s", symbol, exc)
            return pd.DataFrame()
        if not isinstance(envelope, dict) or str(envelope.get("status")) != "ok":
            logger.warning("Dhan bars non-ok for %s: %s", symbol, envelope)
            return pd.DataFrame()
        return _bars_to_frame(envelope.get("bars", []))


class CachedBarSource:
    """Share one upstream fetch per symbol across many parallel runners.

    With 15 strategies each pulling 4 symbols per tick, an uncached Dhan source
    would take ~60 API hits per 15m tick for identical data. This wrapper
    fetches each symbol once (at the largest lookback it may need) and serves
    every runner from that frame until the TTL lapses or the replay cursor
    moves.

    Attributes:
        ttl_seconds: Cache lifetime — keep it well under the tick interval so
            each tick fetches fresh bars exactly once per symbol.
    """

    def __init__(self, source, *, ttl_seconds: float = 300.0, min_lookback: int = 60) -> None:
        """Wrap ``source``.

        Args:
            source: Any :class:`BarSource` (Dhan or replay).
            ttl_seconds: Seconds a fetched frame stays valid.
            min_lookback: Fetch at least this many bars so a later, larger
                request within the TTL is still served from cache.
        """
        self._source = source
        self._ttl = ttl_seconds
        self._min_lookback = min_lookback
        self._cache: dict[str, tuple[float, pd.DataFrame]] = {}
        self._now = None

    def set_now(self, now) -> None:
        """Advance the replay cursor and invalidate — only when it moves.

        Runners call ``set_now`` before every fetch with the same tick time, so
        clearing unconditionally would defeat the cache within a tick; a new
        tick (different ``now``) clears it.
        """
        if now == self._now:
            return
        self._now = now
        if hasattr(self._source, "set_now"):
            self._source.set_now(now)
        self._cache.clear()

    def recent_bars(self, symbol: str, *, lookback: int) -> pd.DataFrame:
        import time as _time

        entry = self._cache.get(symbol)
        now = _time.monotonic()
        if entry is not None and now - entry[0] < self._ttl and len(entry[1]) >= lookback:
            return entry[1].tail(lookback)
        frame = self._source.recent_bars(
            symbol, lookback=max(lookback, self._min_lookback)
        )
        if frame is not None and not frame.empty:
            self._cache[symbol] = (now, frame)
            return frame.tail(lookback)
        return frame if frame is not None else pd.DataFrame()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def dhan_config_from_intraday(config):
    """Build a paper-profile ``DhanConfig`` from ``IntradayConfig`` creds.

    Keeps secrets in ``agent/.env`` (via :class:`~src.intraday.config.IntradayConfig`)
    instead of requiring a saved ``~/.vibe-trading/dhan.json`` (DC-003). Read-only:
    the M1 runtime only ever pulls bars — orders stay in the paper broker.

    Args:
        config: An :class:`~src.intraday.config.IntradayConfig` with real Dhan creds.

    Returns:
        A ``DhanConfig`` (profile ``paper``, readonly) carrying those creds, or
        ``None`` when Dhan creds are still placeholders.
    """
    if not config.is_dhan_configured:
        return None
    from src.trading.connectors.dhan.sdk import DhanConfig

    return DhanConfig(
        client_id=config.dhan_client_id,
        access_token=config.dhan_access_token,
        profile="paper",
        readonly=True,
    )


_OHLCV = ["open", "high", "low", "close", "volume"]


def _bars_to_frame(bars: list[dict]) -> pd.DataFrame:
    """Convert Dhan ``bars`` (epoch-second ``time`` + OHLCV) to an IST frame."""
    if not bars:
        return pd.DataFrame()
    frame = pd.DataFrame(bars)
    if "time" not in frame.columns:
        return pd.DataFrame()
    ts = pd.to_numeric(frame["time"], errors="coerce")
    if ts.notna().any():
        index = pd.to_datetime(ts, unit="s", utc=True)
    else:
        index = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    frame = frame.drop(columns=["time"])
    frame.index = pd.DatetimeIndex(index).tz_convert("Asia/Kolkata")
    for col in _OHLCV:
        if col not in frame.columns:
            frame[col] = 0.0
    frame = frame[_OHLCV].apply(pd.to_numeric, errors="coerce")
    return frame.dropna(subset=["open", "high", "low", "close"]).sort_index()


def _ensure_ist(df: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` with a tz-aware IST DatetimeIndex (naive → assumed IST)."""
    if df.empty:
        return df
    idx = df.index
    if getattr(idx, "tz", None) is None:
        df = df.copy()
        df.index = pd.DatetimeIndex(idx).tz_localize("Asia/Kolkata")
    else:
        df = df.copy()
        df.index = idx.tz_convert("Asia/Kolkata")
    return df
