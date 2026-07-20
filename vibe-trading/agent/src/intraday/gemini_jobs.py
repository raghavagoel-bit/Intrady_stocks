"""Gemini research jobs: pre-market watchlist + end-of-day journal review.

Per the locked architecture decision, Gemini does **research + oversight only** —
it never makes per-bar trade decisions (the rule engine does). Its two jobs
bookend the trading day (root plan §4.5 "DAY BOOKENDS"):

  * :func:`premarket_watchlist` — before 09:15, summarize the day's setup for the
    fixed universe and post it to the trade feed as the morning watchlist.
  * :func:`eod_review` — after 15:30, review the session's fills and post a
    short trade-journal note.

Both take an injected ``llm_call: (prompt) -> str``. :func:`make_llm_caller`
returns a **stub caller** whenever the Gemini key is still a placeholder, so the
jobs run end-to-end today and light up for real the moment a key is dropped in.
The real caller hits the Gemini REST ``generateContent`` endpoint directly over
httpx (same minimal one-way style as the Telegram sink) — no LangChain stack
needed for these two bookend calls (BUG-001: the earlier ``src.llm.factory``
import never existed in the repo).

Reliability (3O, BUG-006): the 07-17 watchlist died on a quota-429 on the FIRST
call of the day (free-tier quota resets ~12:30 IST = midnight Pacific, so an
08:37 IST call still sits in yesterday's Pacific quota day). :func:`_call` now
retries transient failures (timeout / 5xx / 429) up to 3 attempts, and when the
real caller carries a local-Ollama ``fallback`` (attached by
:func:`make_llm_caller`), the prompt runs through the local model before the
static fallback string — output prefixed ``[local]`` so the feed shows which
brain wrote it.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Sequence

from src.intraday.config import IntradayConfig
from src.intraday.paper_broker import Fill

logger = logging.getLogger(__name__)

#: An LLM caller: prompt in, completion text out.
LLMCaller = Callable[[str], str]

_STUB_PREFIX = "[stub — Gemini key not set] "

#: Gemini REST base — one-way generateContent only (research/oversight bookends).
_GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models"


def gemini_generate(api_key: str, model: str, prompt: str, *, timeout: float = 30.0) -> str:
    """One ``generateContent`` call against the Gemini REST API.

    Deliberately dependency-light (httpx only, like the Telegram sink) — the two
    bookend research jobs do not justify the LangChain stack. Raises on HTTP or
    shape errors; :func:`_call` in the jobs layer converts those to fallbacks.

    Args:
        api_key: Real Gemini API key.
        model: Model id, e.g. ``gemini-3.5-flash``.
        prompt: The prompt text.

    Returns:
        The first candidate's concatenated text parts.
    """
    import httpx  # declared dep; imported lazily so tests need no network

    resp = httpx.post(
        f"{_GEMINI_API}/{model}:generateContent",
        headers={"x-goog-api-key": api_key},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


def make_llm_caller(config: IntradayConfig) -> LLMCaller:
    """Return a real Gemini caller if configured, else a deterministic stub.

    The stub echoes a short deterministic summary so the pipeline (prompt build →
    call → notify) is fully exercised offline. When a real key is present, the
    caller posts straight to the Gemini REST API (see :func:`gemini_generate`).

    Args:
        config: The intraday config (carries the Gemini key/model/provider).

    Returns:
        An :data:`LLMCaller`.
    """
    if not config.is_gemini_configured:
        def _stub(prompt: str) -> str:
            first_line = prompt.strip().splitlines()[0] if prompt.strip() else ""
            return _STUB_PREFIX + first_line
        return _stub

    def _real(prompt: str) -> str:
        return gemini_generate(config.gemini_api_key, config.gemini_model, prompt)

    # 3O: the primary caller carries its local-Ollama fallback; _call runs it
    # only after Gemini's retries are exhausted (e.g. a quota-429, BUG-006).
    def _local(prompt: str) -> str:
        from src.intraday.local_llm import ollama_generate

        return ollama_generate(config.ollama_url, config.ollama_model, prompt)

    _real.fallback = _local  # type: ignore[attr-defined]
    return _real


def premarket_watchlist(
    config: IntradayConfig,
    llm_call: LLMCaller,
    *,
    notes: str = "",
) -> str:
    """Build + run the pre-market watchlist prompt; return the LLM text.

    Args:
        config: Intraday config (universe + capital frame the prompt).
        llm_call: The injected LLM caller (real or stub).
        notes: Optional operator context to fold into the prompt.

    Returns:
        The watchlist text (to hand to :meth:`TradeNotifier.watchlist`).
    """
    symbols = ", ".join(i.symbol for i in config.universe)
    if config.roster:
        capital = (
            f"₹{config.per_strategy_cash:,.0f} per strategy × {len(config.roster)} "
            f"parallel strategies"
        )
    else:
        capital = f"₹{config.initial_cash:,.0f}"
    prompt = (
        f"Pre-market intraday watchlist for {symbols}.\n"
        f"Capital {capital}, long-only, cash-only paper trading (NO leverage or "
        f"margin — do not mention leverage or buying power), square-off by "
        f"{config.squareoff} IST. For each symbol give a one-line bias (up/"
        f"neutral) and any level to watch. Be terse; plain text only (no "
        f"markdown, no asterisks); this is research only, not a trade "
        f"instruction. Do not restate capital or position sizing.\n{notes}".strip()
    )
    return _call(llm_call, prompt, fallback="(no watchlist)")


#: Above this many combined fills the EOD prompt aggregates per strategy (3O) —
#: 40 slots × raw fill lines was hundreds of lines: cost, timeout risk, and
#: feedback diluted into a fill dump.
_EOD_RAW_FILL_LIMIT = 40


def eod_review(
    config: IntradayConfig,
    llm_call: LLMCaller,
    fills: Sequence[Fill],
    *,
    realized_pnl: float,
    metrics: Sequence[Any] | None = None,
    fills_by_strategy: dict[str, Sequence[Fill]] | None = None,
) -> str:
    """Build + run the end-of-day review prompt over the session's fills.

    With a small session the prompt lists raw fills as before. Past
    :data:`_EOD_RAW_FILL_LIMIT` fills (the 40-slot roster) it aggregates to one
    line per strategy — name, trades, net ₹, fees ₹, best/worst symbol by
    realized — and asks for ranked feedback instead of a fill-dump commentary.

    Args:
        config: Intraday config.
        llm_call: The injected LLM caller (real or stub).
        fills: The session's fills, in order.
        realized_pnl: Net realized P&L for the day (₹).
        metrics: Optional per-strategy :class:`~src.intraday.scoreboard.
            StrategyMetrics` (the bake-off has them at EOD) — preferred source
            for the aggregate lines.
        fills_by_strategy: Optional ``{strategy: fills}`` split, used to name
            each strategy's best/worst symbol by realized ₹.

    Returns:
        The review text (to hand to :meth:`TradeNotifier.eod`).
    """
    if len(fills) > _EOD_RAW_FILL_LIMIT and metrics:
        lines = _strategy_lines(metrics, fills_by_strategy or {})
        journal = "\n".join(lines)
        prompt = (
            f"End-of-day intraday paper bake-off review. Net realized P&L "
            f"₹{realized_pnl:,.2f} across {len(fills)} fills, "
            f"{len(metrics)} slots collapsed to {len(lines)} long/_ls pair lines "
            f"below (long leg vs its short-capable twin).\n"
            f"{journal}\n"
            f"Give: a 2-3 line market read; the top-2 and bottom-2 pairs "
            f"with a one-line why each; whether allowing shorts (the ls leg) "
            f"helped or hurt; one observation on cost drag; one thing to change "
            f"tomorrow. Plain text only (no markdown, no asterisks). "
            f"Research/oversight only."
        )
        return _call(llm_call, prompt, fallback="(no review)")

    lines = [
        f"{f.timestamp:%H:%M} {f.side.upper()} {int(f.qty)} {f.symbol} "
        f"@ ₹{f.price:,.2f} (fee ₹{f.commission:,.2f})"
        + (f" realized {f.realized_pnl:+,.2f}" if f.side == "sell" else "")
        for f in fills
    ]
    journal = "\n".join(lines) if lines else "(no trades today)"
    prompt = (
        f"End-of-day intraday journal review. Net realized P&L "
        f"₹{realized_pnl:,.2f} across {len(fills)} fills.\nTrades:\n{journal}\n"
        f"Give a 2–3 line review: what worked, cost drag, one thing to watch "
        f"tomorrow. Plain text only (no markdown, no asterisks). "
        f"Research/oversight only."
    )
    return _call(llm_call, prompt, fallback="(no review)")


def _strategy_lines(
    metrics: Sequence[Any], fills_by_strategy: dict[str, Sequence[Fill]]
) -> list[str]:
    """One aggregate line per long/``_ls`` pair for the large-session EOD prompt.

    B4-2 (64-slot roster): the prompt is pair-collapsed to match the Telegram
    report — each base strategy is one line comparing its pure-long leg to its
    short-capable twin (so the LLM can judge whether shorts helped), with the
    combined best/worst symbol across both legs. Pairs rank best-first (halted
    last); unpaired long slots (``llm_local_a/b``) get their own trailing lines.
    """
    from src.intraday.scoreboard import _pair_items  # same-package internal reuse

    pairs, unpaired = _pair_items(list(metrics), lambda m: m.name)

    def _best(pair: tuple) -> float:
        _, lng, ls = pair
        return max(lng.net_pnl if lng else 0.0, ls.net_pnl if ls else 0.0)

    def _halted(pair: tuple) -> bool:
        _, lng, ls = pair
        return bool((lng and lng.halted) or (ls and ls.halted))

    def _best_worst(*legs: Any) -> str:
        """Best/worst symbol by combined realized ₹ across the given legs."""
        by_symbol: dict[str, float] = {}
        for leg in legs:
            if leg is None:
                continue
            for f in fills_by_strategy.get(leg.name, ()):
                if f.side in ("sell", "cover"):
                    by_symbol[f.symbol] = by_symbol.get(f.symbol, 0.0) + f.realized_pnl
        if not by_symbol:
            return ""
        best = max(by_symbol, key=by_symbol.get)
        worst = min(by_symbol, key=by_symbol.get)
        return (
            f", best {best} ₹{by_symbol[best]:+,.0f}, "
            f"worst {worst} ₹{by_symbol[worst]:+,.0f}"
        )

    lines: list[str] = []
    for base, lng, ls in sorted(pairs, key=lambda p: (_halted(p), -_best(p))):
        long_net = lng.net_pnl if lng else 0.0
        ls_net = ls.net_pnl if ls else 0.0
        ls_short = ls.short_pnl if ls else 0.0
        trades = (lng.trades if lng else 0) + (ls.trades if ls else 0)
        fees = (lng.fees if lng else 0.0) + (ls.fees if ls else 0.0)
        line = (
            f"{base}: long ₹{long_net:+,.0f} / ls ₹{ls_net:+,.0f} "
            f"(short leg ₹{ls_short:+,.0f}), {trades} trades, fees ₹{fees:,.0f}"
        )
        line += _best_worst(lng, ls)
        if _halted((base, lng, ls)):
            line += " [RETIRED]"
        lines.append(line)

    for m in unpaired:
        line = f"{m.name}: net ₹{m.net_pnl:+,.0f}, {m.trades} trades, fees ₹{m.fees:,.0f}"
        line += _best_worst(m)
        if getattr(m, "halted", False):
            line += " [RETIRED]"
        lines.append(line)
    return lines


#: Sleeps between transient-failure retries (attempt 1 → 2s, attempt 2 → 8s).
_RETRY_SLEEPS = (2.0, 8.0)


def _is_transient(exc: Exception) -> bool:
    """A failure worth retrying: timeout, transport error, HTTP 5xx or 429."""
    try:
        import httpx
    except Exception:  # pragma: no cover — httpx is a declared dep
        return False
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return False


def _call(
    llm_call: LLMCaller,
    prompt: str,
    *,
    fallback: str,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> str:
    """Invoke the LLM caller defensively; never raise into the runner.

    3O: transient failures (timeout / 5xx / 429) are retried up to 3 attempts
    (sleeping 2s then 8s); anything else fails immediately. After the last
    failure, a ``fallback`` attribute on ``llm_call`` (the local-Ollama caller
    attached by :func:`make_llm_caller`) gets one shot — its output is prefixed
    ``[local]``. Only then does the static fallback string come back.
    """
    last_exc: Exception | None = None
    for attempt in range(1 + len(_RETRY_SLEEPS)):
        try:
            text = llm_call(prompt)
            return (text or fallback).strip()
        except Exception as exc:  # noqa: BLE001 — research failure must not break the loop
            last_exc = exc
            if attempt >= len(_RETRY_SLEEPS) or not _is_transient(exc):
                break
            logger.warning(
                "Gemini job failed (transient, attempt %d/%d) — retrying",
                attempt + 1, 1 + len(_RETRY_SLEEPS), exc_info=True,
            )
            sleep_fn(_RETRY_SLEEPS[attempt])
    logger.warning("Gemini job failed", exc_info=last_exc)

    local = getattr(llm_call, "fallback", None)
    if local is not None:
        try:
            text = local(prompt)
        except Exception:  # noqa: BLE001 — the fallback failing is not an error path up
            logger.warning("local LLM fallback failed too", exc_info=True)
        else:
            if text and text.strip():
                return "[local] " + text.strip()
    return fallback
