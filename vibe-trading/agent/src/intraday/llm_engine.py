"""LLM-driven signal engine — the experimental 5th bake-off slot (user, 2026-07-15).

This consciously amends the original "Gemini is research/oversight only" rule:
Gemini gets exactly ONE paper slot to prove (or disprove) it can trade, head-to-
head against the four rule engines, under identical constraints — long-only,
₹25k cash, no leverage, the ₹10k kill-switch, and the 15:15 force-flatten. The
rule engines stay LLM-free; live (M2) promotion of this slot would need its own
explicit decision.

Why this lives in ``src/intraday/`` and not ``strategies/``: the repo's
signal-engine validator (VT-001) forbids network access and env reads inside
run-dir strategy code — a sandbox we must not weaken. This engine is trusted
overlay code, wired by roster ``run_dir: "builtin:llm_trader"`` instead of a
file path (see :func:`build_builtin_engine`).

Safety posture (the LLM is fenced by deterministic code, not trust):
  * Output is parsed as strict JSON — per symbol either a bare ``"long"|"flat"``
    or an object ``{"decision", "reason", "stop", "target"}``; anything
    unparseable means **keep the previous decision** — a flaky call can never
    churn or invent a position.
  * The no-entry windows are enforced HERE: before 09:45 (warm-up) and from
    15:00 (DC-001 flatten) the signal is 0 no matter what the LLM says.
  * ``generate`` never raises (the runner halts a strategy on engine errors —
    an API outage must degrade to "hold current state", not kill the slot).
  * With no Gemini key configured the engine is permanently flat.
  * Backtesting this engine is intentionally unsupported — an LLM has no
    reproducible history; only live-paper forward results count.

Decision tracking (user, 2026-07-15): every tick's decision per symbol —
including the LLM's stated **reason, stop, and target** — is appended to a
daily JSONL journal (``~/.vibe-trading/intraday/llm_journal-YYYYMMDD.jsonl``),
and when the LLM exits a long, an ``exit_eval`` record grades the round trip
against its own stated levels (did price touch the stop/target in between?).
The stop/target are *tracked intentions*, not executed orders — intra-bar SL/TP
execution is the separate backlogged M1 feature.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import time
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.intraday.config import IntradayConfig
from src.intraday.gemini_jobs import gemini_generate

logger = logging.getLogger(__name__)

#: Reply values (lowercased) that mean "be long"; everything else means flat.
_LONG_WORDS = frozenset({"long", "buy", "hold", "1"})
#: Reply values (lowercased) that mean "be short" (honored only on a hybrid twin).
_SHORT_WORDS = frozenset({"short", "sell", "-1"})


def _decision_word(signal: int) -> str:
    """Journal label for a signal (1 long / −1 short / 0 flat)."""
    return "long" if signal == 1 else ("short" if signal == -1 else "flat")


class DecisionJournal:
    """Append-only daily JSONL sink for LLM decisions (never raises).

    One file per IST date under ``<runtime root>/intraday/``; each line is one
    JSON record (``kind: "decision" | "exit_eval"``). A write failure is logged
    and swallowed — journaling must never break the trading loop.
    """

    def __init__(self, directory: str | Path | None = None) -> None:
        if directory is None:
            try:
                from src.config.paths import get_runtime_root

                directory = get_runtime_root() / "intraday"
            except Exception:  # pragma: no cover - fall back to CWD
                directory = Path("intraday_journal")
        self.directory = Path(directory)

    def write(self, record: dict[str, Any]) -> None:
        try:
            day = str(record.get("ts", ""))[:10] or "undated"
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"llm_journal-{day.replace('-', '')}.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 — journaling is best-effort
            logger.warning("llm_trader journal write failed", exc_info=True)


class LLMSignalEngine:
    """Per-tick Gemini decisions wrapped in deterministic guard rails.

    Implements the same ``generate(data_map) -> {symbol: Series}`` contract as
    the run-dir strategies; the runner acts on the last bar of each series.

    Attributes:
        state: Symbol → last decision (0/1) — carried across ticks and used as
            the fallback whenever a call fails or a symbol is missing from the
            reply.
    """

    #: No entries before this (opening range still forming — matches the rule
    #: engines' warm-up) and none at/after 15:00 (DC-001).
    entry_from = time(9, 45)
    flat_from = time(15, 0)

    #: Consecutive LLM failures after which the engine goes DEGRADED (3R,
    #: BUG-005 lesson): decisions turn flat instead of freezing on stale state.
    degrade_after = 3

    def __init__(
        self,
        config: IntradayConfig | None = None,
        llm_call: Callable[[str], str] | None = None,
        journal: Any | None = None,
        *,
        allow_short: bool = False,
        provider: str = "gemini",
        model: str | None = None,
        slot_name: str = "llm_trader",
    ) -> None:
        """Build the engine.

        Args:
            config: Intraday config (LLM creds/urls). ``None`` → flat engine.
            llm_call: Injectable ``prompt -> reply`` for tests; defaults to a
                real call built from ``provider``.
            journal: Anything with ``write(record: dict)`` — decision tracking
                sink. ``None`` disables journaling (unit tests); the builtin
                factory wires a :class:`DecisionJournal`.
            allow_short: 3L hybrid twin — offer ``"short"`` in the prompt and map
                it to −1. The long-only slot keeps coercing ``"short"`` to flat.
            provider: ``"gemini"`` (needs a real key) or ``"ollama"`` (3R —
                local server, no key; always constructible, fails soft per tick).
            model: Model override for the provider (else the config default:
                ``gemini_model`` / ``ollama_model``).
            slot_name: Roster slot label — tags every journal record and log
                line so parallel LLM slots are attributable (BUG-005 lesson).
        """
        self._config = config
        self._llm = llm_call
        self._journal = journal
        self.allow_short = allow_short
        self.provider = provider
        self.model = model
        self.slot_name = slot_name
        self.state: dict[str, int] = {}
        #: Symbol → the LLM's latest stated rationale {"reason", "stop", "target"}.
        self.meta: dict[str, dict[str, Any]] = {}
        #: Symbol → info captured when the current long was opened.
        self.open_info: dict[str, dict[str, Any]] = {}
        #: Consecutive failed LLM round-trips; ``degrade_after`` of them → degraded.
        self._fail_count = 0
        #: Degraded = the LLM is unreachable/unusable — decisions are FLAT (not
        #: kept-last) until a call succeeds again.
        self.degraded = False

    # -- SignalEngine contract -------------------------------------------------

    def generate(self, data_map: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        """Return 0/1 series per symbol; only the last bar carries the decision."""
        decisions = self._decide(data_map)
        out: dict[str, pd.Series] = {}
        for symbol, frame in data_map.items():
            signal = pd.Series(0, index=frame.index, dtype="int64")
            if len(frame) == 0:
                out[symbol] = signal
                continue
            decision = decisions.get(symbol, self.state.get(symbol, 0))
            bar_time = self._ist_time(frame.index[-1])
            forced_flat = bar_time is not None and (
                bar_time < self.entry_from or bar_time >= self.flat_from
            )
            if forced_flat:
                decision = 0  # guard rails outrank the LLM
            self._track(symbol, frame, decision, forced_flat=forced_flat)
            self.state[symbol] = decision
            signal.iloc[-1] = decision
            out[symbol] = signal
        return out

    # -- decision tracking -------------------------------------------------------

    def _track(
        self, symbol: str, frame: pd.DataFrame, decision: int, *, forced_flat: bool
    ) -> None:
        """Journal this tick's decision; grade a round trip on any close/flip.

        Direction transitions (decision ∈ {−1, 0, 1}): a change away from a
        non-flat ``prev`` closes that position (an ``exit_eval`` graded in the
        prev direction); a change into a non-flat ``decision`` opens a new one.
        A flip (e.g. 1→−1) does both — the exit_eval captures the closed leg
        BEFORE the new ``open_info`` overwrites it.
        """
        prev = self.state.get(symbol, 0)
        meta = self.meta.get(symbol, {})
        ts = frame.index[-1]
        last_price = float(frame["close"].iloc[-1])

        closing = prev != 0 and decision != prev
        opening = decision != 0 and decision != prev

        # Capture the exit_eval of the leg being closed before we overwrite it.
        exit_record = (
            self._build_exit_eval(symbol, frame, last_price, ts, forced_flat, meta)
            if closing else None
        )

        if opening:
            self.open_info[symbol] = {
                "entry_ts": ts,
                "entry_price": last_price,
                "direction": decision,
                "reason": meta.get("reason", ""),
                "stop": meta.get("stop"),
                "target": meta.get("target"),
            }

        self._write_journal({
            "kind": "decision",
            "slot": self.slot_name,
            "ts": self._iso(ts),
            "symbol": symbol,
            "decision": _decision_word(decision),
            "changed": decision != prev,
            "forced_flat": forced_flat,
            "degraded": self.degraded,
            "last_price": last_price,
            "reason": meta.get("reason", ""),
            "stop": meta.get("stop"),
            "target": meta.get("target"),
        })

        if exit_record is not None:
            self._write_journal(exit_record)

    def _build_exit_eval(
        self, symbol: str, frame: pd.DataFrame, last_price: float, ts, forced_flat: bool,
        meta: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Grade the just-closed round trip against its own stated stop/target.

        Long: stop below entry, target above (``low ≤ stop`` / ``high ≥ target``).
        Short: the levels flip — stop ABOVE entry, target BELOW
        (``high ≥ stop`` / ``low ≤ target``).
        """
        info = self.open_info.pop(symbol, None)
        if not info:
            return None
        window = frame[frame.index >= info["entry_ts"]]
        stop, target = info.get("stop"), info.get("target")
        direction = info.get("direction", 1)
        entry_price = info["entry_price"]
        have = bool(len(window))
        if direction == -1:
            stop_hit = bool(have and stop is not None and float(window["high"].max()) >= float(stop))
            target_hit = bool(have and target is not None and float(window["low"].min()) <= float(target))
        else:
            stop_hit = bool(have and stop is not None and float(window["low"].min()) <= float(stop))
            target_hit = bool(have and target is not None and float(window["high"].max()) >= float(target))
        return {
            "kind": "exit_eval",
            "slot": self.slot_name,
            "ts": self._iso(ts),
            "symbol": symbol,
            "direction": _decision_word(direction),
            "entry_ts": self._iso(info["entry_ts"]),
            "entry_price": entry_price,
            "exit_price": last_price,
            # Raw price move; for a short a NEGATIVE move_pct is the profitable one.
            "move_pct": round((last_price / entry_price - 1) * 100, 3) if entry_price else None,
            "stop": stop,
            "target": target,
            "stop_hit": stop_hit,
            "target_hit": target_hit,
            "entry_reason": info.get("reason", ""),
            "exit_reason": "forced flat window" if forced_flat else meta.get("reason", ""),
        }

    def _write_journal(self, record: dict[str, Any]) -> None:
        if self._journal is None:
            return
        try:
            self._journal.write(record)
        except Exception:  # noqa: BLE001 — journaling is best-effort
            logger.warning("%s: journal sink failed", self.slot_name, exc_info=True)

    @staticmethod
    def _iso(stamp) -> str:
        try:
            return pd.Timestamp(stamp).isoformat()
        except Exception:  # noqa: BLE001
            return str(stamp)

    # -- LLM round trip ----------------------------------------------------------

    def _decide(self, data_map: dict[str, pd.DataFrame]) -> dict[str, int]:
        """One LLM call for the whole universe.

        Success resets the failure counter. A failed round trip (call raised OR
        the reply parsed to nothing) keeps the last decisions ({}) — but only
        ``degrade_after`` times in a row: past that the engine is **degraded**
        and decides FLAT for everything (BUG-005 lesson — a dead LLM must not
        freeze a stale position as the baseline; going flat closes it).
        """
        caller = self._caller()
        if caller is None or not data_map:
            return {}
        try:
            reply = caller(self._build_prompt(data_map))
            decisions = self._parse(reply, set(data_map))
        except Exception:  # noqa: BLE001 — API failure must never halt the slot
            return self._register_failure(data_map, "LLM call failed", exc=True)
        if not decisions:
            # A reply with no usable decision map is as dead as no reply —
            # chatty local models (3R) fail this way, so it counts too.
            return self._register_failure(data_map, "reply had no usable decisions")
        self._fail_count = 0
        self.degraded = False
        return decisions

    def _register_failure(
        self, data_map: dict[str, pd.DataFrame], why: str, *, exc: bool = False
    ) -> dict[str, int]:
        """Count one failed round trip; flat when degraded, else keep-last."""
        self._fail_count += 1
        if self._fail_count >= self.degrade_after:
            if not self.degraded:
                logger.warning(
                    "%s: %d consecutive LLM failures (%s) — DEGRADED, decisions go flat",
                    self.slot_name, self._fail_count, why, exc_info=exc,
                )
            self.degraded = True
            return {symbol: 0 for symbol in data_map}
        logger.warning(
            "%s: %s (failure %d/%d) — keeping last decisions",
            self.slot_name, why, self._fail_count, self.degrade_after, exc_info=exc,
        )
        return {}

    def _caller(self) -> Callable[[str], str] | None:
        if self._llm is not None:
            return self._llm
        cfg = self._config
        if cfg is None:
            return None
        if self.provider == "ollama":
            # No key needed — a local server either answers or fails soft per
            # tick (and degrades to flat after degrade_after misses).
            from src.intraday.local_llm import ollama_generate

            model = self.model or cfg.ollama_model
            return lambda prompt: ollama_generate(cfg.ollama_url, model, prompt)
        if not cfg.is_gemini_configured:
            return None
        return lambda prompt: gemini_generate(
            cfg.gemini_api_key, self.model or cfg.gemini_model, prompt
        )

    def _held_label(self, symbol: str) -> str:
        state = self.state.get(symbol, 0)
        return "HOLDING a long" if state == 1 else ("HOLDING a short" if state == -1 else "flat")

    def _build_prompt(self, data_map: dict[str, pd.DataFrame]) -> str:
        """Compact per-symbol tape + holdings + hard rules + strict JSON ask."""
        blocks: list[str] = []
        for symbol, frame in data_map.items():
            tail = frame.tail(8)
            day_open = float(frame["open"].iloc[0])
            last = float(frame["close"].iloc[-1])
            change = (last / day_open - 1) * 100 if day_open else 0.0
            held = self._held_label(symbol)
            bars = "; ".join(
                f"{ts.strftime('%H:%M')} O{row.open:.1f} H{row.high:.1f} "
                f"L{row.low:.1f} C{row.close:.1f} V{int(row.volume)}"
                for ts, row in tail.iterrows()
            )
            blocks.append(
                f"{symbol} ({held}, {change:+.2f}% vs day open, last {last:.2f}):\n  {bars}"
            )
        universe = ", ".join(data_map)
        if self.allow_short:
            intro = (
                "You are managing a HYBRID intraday NSE paper account (cash only, "
                "1x — no leverage). Every 15 minutes you choose, per symbol, "
                "'long' (be/stay long), 'short' (be/stay short — profit if price "
                "falls), or 'flat' (no/close position). A short reserves cash like "
                "a long. Positions force-close at 15:15 IST."
            )
            decision_values = "\"long\"|\"short\"|\"flat\""
            levels = (
                "Give stop and target only when decision is long or short (your "
                "intended exit levels; for a short the stop sits ABOVE and the "
                "target BELOW the entry). "
            )
        else:
            intro = (
                "You are managing a LONG-ONLY intraday NSE paper account (cash "
                "only, no leverage, no shorting). Every 15 minutes you choose, per "
                "symbol, 'long' (be/stay in a long position) or 'flat' (no/close "
                "position). Positions force-close at 15:15 IST."
            )
            decision_values = "\"long\"|\"flat\""
            levels = (
                "Give stop and target only when decision is long (your intended "
                "exit levels). "
            )
        return (
            intro + " Each round trip costs roughly 0.05% in fees — avoid "
            "churning; switch only on conviction.\n\n"
            "Recent 15m bars (IST):\n" + "\n".join(blocks) + "\n\n"
            f"Reply with ONLY a JSON object mapping each of [{universe}] to an "
            "object of the form {\"decision\": " + decision_values + ", \"reason\": "
            "\"<max 20 words>\", \"stop\": <price number or null>, \"target\": "
            "<price number or null>}. " + levels + "No explanation outside the "
            "JSON, no markdown."
        )

    def _parse(self, reply: str, symbols: set[str]) -> dict[str, int]:
        """Extract the JSON decision map; unknown symbols/values are ignored.

        Accepts both the rich per-symbol object form (``{"decision", "reason",
        "stop", "target"}`` — rationale captured into :attr:`meta`) and the
        legacy bare-string form (``"long"|"flat"``).
        """
        match = re.search(r"\{.*\}", reply, flags=re.DOTALL)
        if match is None:
            logger.warning("%s: no JSON in reply %r", self.slot_name, reply[:120])
            return {}
        try:
            raw = json.loads(match.group(0))
        except ValueError:
            logger.warning("%s: bad JSON in reply %r", self.slot_name, reply[:120])
            return {}
        if not isinstance(raw, dict):
            return {}
        decisions: dict[str, int] = {}
        for symbol, value in raw.items():
            if symbol not in symbols:
                continue
            if isinstance(value, dict):
                decisions[symbol] = self._word_to_signal(str(value.get("decision", "")))
                self.meta[symbol] = {
                    "reason": str(value.get("reason", ""))[:300],
                    "stop": _as_price(value.get("stop")),
                    "target": _as_price(value.get("target")),
                }
            else:
                decisions[symbol] = self._word_to_signal(str(value))
                self.meta[symbol] = {"reason": "", "stop": None, "target": None}
        return decisions

    def _word_to_signal(self, word: str) -> int:
        """Map an LLM decision word to 1/−1/0. ``short`` only on a hybrid twin;
        the long-only slot coerces it (and anything unknown) to flat."""
        w = word.strip().lower()
        if w in _LONG_WORDS:
            return 1
        if self.allow_short and w in _SHORT_WORDS:
            return -1
        return 0

    @staticmethod
    def _ist_time(stamp) -> time | None:
        """IST time-of-day of a bar stamp (naive stamps assumed IST already)."""
        try:
            ts = pd.Timestamp(stamp)
            if ts.tzinfo is not None:
                ts = ts.tz_convert("Asia/Kolkata")
            return ts.time()
        except Exception:  # noqa: BLE001 — a weird index must not halt the slot
            return None


def _as_price(value) -> float | None:
    """Coerce an LLM-supplied level to a positive float, else ``None``."""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


#: Registry of overlay-provided engines addressable from the roster.
_BUILTINS = {"llm_trader": LLMSignalEngine}


def build_builtin_engine(
    name: str,
    config: IntradayConfig,
    *,
    allow_short: bool = False,
    slot_name: str | None = None,
    **params: Any,
):
    """Resolve a roster ``run_dir: "builtin:<name>"`` to an overlay engine.

    Args:
        name: The part after ``builtin:`` (e.g. ``llm_trader``).
        config: The intraday config handed to the engine.
        allow_short: Build the hybrid (short-capable) variant of the builtin.
        slot_name: Roster slot label for journal/log attribution (defaults to
            the builtin name).
        params: Per-slot engine kwargs from ``StrategyRef.params`` (3R) — e.g.
            ``provider="ollama", model="qwen3:8b"``. An unknown kwarg fails
            fast here (TypeError), which the preflight turns into a launch-gate
            stop.

    Raises:
        ValueError: For an unknown builtin name.
    """
    cls = _BUILTINS.get(name)
    if cls is None:
        raise ValueError(f"unknown builtin strategy: {name!r} (have {sorted(_BUILTINS)})")
    if cls is LLMSignalEngine:
        return cls(
            config,
            journal=DecisionJournal(),
            allow_short=allow_short,
            slot_name=slot_name or name,
            **params,
        )
    return cls(config)  # pragma: no cover - future builtins
