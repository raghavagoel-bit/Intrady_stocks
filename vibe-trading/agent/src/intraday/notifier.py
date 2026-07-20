"""Trade-event notifier → Telegram (or a log sink when creds are placeholders).

Root plan §4.5: every trade event flows to a Telegram channel in both paper and
live modes, from ONE central notifier so paper and live behave identically (only
the fill source differs). This module is that notifier plus its sinks.

Design:

  * A :class:`NotifierSink` is anything with ``send(text) -> None``. Two ship:
    :class:`LogSink` (default / offline) and :class:`TelegramSink` (a thin,
    one-way ``sendMessage`` HTTP call — no bot, no polling).
  * :func:`build_sink` picks the live Telegram sink only when the config reports
    Telegram creds are real; otherwise it returns a :class:`LogSink`, so the
    runtime is fully exercisable before a token exists.
  * :class:`TradeNotifier` formats the six event kinds (ENTRY, EXIT,
    SQUARE-OFF, HALT, WATCHLIST, EOD) and pushes them through the sink. Sends are
    best-effort: a sink failure is logged and swallowed — a Telegram outage must
    never break the trading loop.

This is a notification sink ONLY. Telegram never places or approves an order
(that stays in the mandate gate). No inbound handling lives here.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Protocol, runtime_checkable

from src.intraday.paper_broker import Fill

logger = logging.getLogger(__name__)

#: Telegram Bot API base — one-way sendMessage only.
_TELEGRAM_API = "https://api.telegram.org"


@runtime_checkable
class NotifierSink(Protocol):
    """Anything that can deliver a formatted notification line."""

    def send(self, text: str) -> None:  # pragma: no cover - protocol
        ...


class LogSink:
    """Default sink: writes each event to the logger (and an in-memory tape).

    Used whenever Telegram is not configured yet, and in tests. The
    :attr:`messages` tape makes assertions trivial and gives a paper-session
    transcript even with no Telegram.
    """

    def __init__(self, level: int = logging.INFO) -> None:
        self._level = level
        self.messages: list[str] = []

    def send(self, text: str) -> None:
        self.messages.append(text)
        logger.log(self._level, "[intraday-notify] %s", text.replace("\n", " | "))


class TelegramSink:
    """One-way Telegram sink via ``sendMessage`` POSTs.

    Intentionally minimal: no bot application, no long-polling, no inbound. Just
    pushes text to a chat id. Network/HTTP errors are raised to the notifier,
    which swallows them (best-effort delivery).

    Telegram caps a message at 4096 chars; a 15-strategy hourly report exceeds
    that, so oversized texts are split on line boundaries into sequential
    messages (see :func:`split_for_telegram`).

    Attributes:
        chat_id: Target Telegram chat/channel id.
    """

    def __init__(self, bot_token: str, chat_id: str, *, timeout: float = 10.0) -> None:
        self._token = bot_token
        self.chat_id = chat_id
        self._timeout = timeout

    def send(self, text: str) -> None:
        import httpx  # declared dep; imported lazily so tests need no network

        url = f"{_TELEGRAM_API}/bot{self._token}/sendMessage"
        for chunk in split_for_telegram(text):
            resp = httpx.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()


def split_for_telegram(text: str, limit: int = 4000) -> list[str]:
    """Split ``text`` into ≤ ``limit``-char chunks on line boundaries.

    A single line longer than the limit is hard-split. Order is preserved and
    no content is dropped; a within-limit text comes back as ``[text]``.
    """
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:  # pathological single line — hard split
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def build_sink(config) -> NotifierSink:
    """Return the live Telegram sink if configured, else a :class:`LogSink`.

    Args:
        config: An :class:`~src.intraday.config.IntradayConfig`.

    Returns:
        A :class:`TelegramSink` when Telegram creds are real, else a
        :class:`LogSink` — so the caller never has to branch on cred state.
    """
    if config.is_telegram_configured:
        logger.info("intraday notifier: Telegram sink active (chat=%s)", config.telegram_chat_id)
        return TelegramSink(config.telegram_bot_token, config.telegram_chat_id)
    logger.info("intraday notifier: Telegram not configured — using log sink")
    return LogSink()


class TradeNotifier:
    """Formats + delivers the six intraday event kinds (root plan §4.5).

    Attributes:
        sink: The delivery sink (Telegram or log).
        mode: ``"PAPER"`` or ``"LIVE"`` — stamped on every message so a reader
            can never confuse a simulated fill for a real one.
    """

    def __init__(self, sink: NotifierSink, *, mode: str = "PAPER") -> None:
        self.sink = sink
        self.mode = mode.upper()

    # -- public events -------------------------------------------------------

    def entry(self, fill: Fill, *, running_pnl: float) -> None:
        """Post an ENTRY (a new long opened)."""
        self._emit("🟢 ENTRY", fill, running_pnl)

    def exit(self, fill: Fill, *, running_pnl: float) -> None:
        """Post an EXIT (a long closed by the strategy's exit rule)."""
        self._emit("🔴 EXIT", fill, running_pnl)

    def squareoff(self, fill: Fill, *, running_pnl: float) -> None:
        """Post a SQUARE-OFF (the 15:15 forced flatten closed an open long)."""
        self._emit("⏹ SQUARE-OFF", fill, running_pnl)

    def halt(self, reason: str) -> None:
        """Post a HALT / ERROR (kill switch, mandate breach, data/token failure)."""
        self._safe_send(f"⚠️ <b>[{self.mode}] HALT</b>\n{_esc(reason)}")

    def watchlist(self, text: str) -> None:
        """Post the morning watchlist (from Gemini pre-market research)."""
        self._safe_send(f"📋 <b>[{self.mode}] Pre-market watchlist</b>\n{_esc(text)}")

    def eod(self, text: str) -> None:
        """Post the end-of-day journal summary (from Gemini EOD review)."""
        self._safe_send(f"📓 <b>[{self.mode}] EOD review</b>\n{_esc(text)}")

    def info(self, text: str) -> None:
        """Post a free-form operational line (session start/stop, etc.)."""
        self._safe_send(f"ℹ️ <b>[{self.mode}]</b> {_esc(text)}")

    def summary(self, body: str) -> None:
        """Post a pre-formatted rollup (hourly summary / EOD scoreboard).

        ``body`` is already Telegram-HTML (built by :mod:`~src.intraday.scoreboard`,
        which emits ``<b>``/``<pre>`` blocks), so it is sent as-is — not re-escaped.
        """
        self._safe_send(body)

    # -- formatting ----------------------------------------------------------

    def _emit(self, tag: str, fill: Fill, running_pnl: float) -> None:
        side = fill.side.upper()
        realized = (
            f"\nRealized: {_money(fill.realized_pnl)}" if fill.side == "sell" else ""
        )
        text = (
            f"{tag} <b>{_esc(fill.symbol)}</b> [{self.mode}]\n"
            f"{side} {int(fill.qty)} @ ₹{fill.price:,.2f}"
            f"  (fee ₹{fill.commission:,.2f})\n"
            f"{_fmt_ts(fill.timestamp)} IST"
            f"{realized}\n"
            f"Session P&amp;L: {_money(running_pnl)}  ·  Cash: ₹{fill.cash_after:,.0f}"
        )
        self._safe_send(text)

    def _safe_send(self, text: str) -> None:
        """Deliver ``text``; a sink failure is logged, never raised into the loop."""
        try:
            self.sink.send(text)
        except Exception:  # noqa: BLE001 — notifications must not break trading
            logger.warning("intraday notifier delivery failed", exc_info=True)


# ---------------------------------------------------------------------------
# formatting helpers
# ---------------------------------------------------------------------------


def _esc(text: str) -> str:
    """Escape the HTML-significant characters for Telegram HTML parse mode."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _money(value: float) -> str:
    """Format a ₹ P&L figure with an explicit sign."""
    sign = "+" if value >= 0 else "−"
    return f"{sign}₹{abs(value):,.2f}"


def _fmt_ts(ts: datetime) -> str:
    """Format a fill timestamp as ``YYYY-MM-DD HH:MM``."""
    return ts.strftime("%Y-%m-%d %H:%M")
