"""Placeholder-first configuration for the intraday paper runtime.

The whole point of this module is that the runtime can be **stood up and
unit-tested before any real credential exists**. Every secret (Dhan token,
Gemini key, Telegram token) defaults to an obvious placeholder, and
:meth:`IntradayConfig.is_*_configured` reports whether a *real* value has been
dropped in yet. Nothing here reaches the network; wiring decisions (use the live
Telegram sink vs. the log sink, call Gemini vs. return a stub) are taken by the
callers from these predicates.

Resolution order (lowest → highest precedence):

  1. Built-in defaults (safe placeholders + the ₹50k / 3-symbol trial universe).
  2. A JSON config file (``config/intraday.json`` by default; see
     ``config/intraday.example.json``).
  3. Environment variables (optionally loaded from ``agent/.env``) — so secrets
     stay in ``.env`` / the process env and never need to live in the JSON.

Secrets are NEVER logged or serialized back out (see :meth:`redacted`).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

#: Substrings that mark a value as an un-filled placeholder (case-insensitive).
#: A value containing any of these is treated as "not configured yet".
_PLACEHOLDER_MARKERS = (
    "placeholder",
    "your-",
    "your_",
    "xxxx",
    "changeme",
    "change-me",
    "todo",
    "<",  # e.g. "<dhan-client-id>"
)

#: Default JSON config location, relative to the ``agent/`` package root.
DEFAULT_CONFIG_REL = Path("config") / "intraday.json"


def is_placeholder(value: str | None) -> bool:
    """Return whether ``value`` is empty or a recognizable placeholder.

    Args:
        value: The candidate secret / setting.

    Returns:
        ``True`` when the value is missing or still a template placeholder, so a
        caller can fall back to the safe (offline / stub) path.
    """
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    low = text.lower()
    return any(marker in low for marker in _PLACEHOLDER_MARKERS)


@dataclass(frozen=True)
class Instrument:
    """One tradeable NSE/BSE symbol in the intraday universe.

    Attributes:
        symbol: Project-convention ticker, e.g. ``RELIANCE.NS`` (``.NS`` = NSE,
            ``.BO`` = BSE). This is what the strategy ``SignalEngine`` keys on.
        security_id: Dhan numeric security id (Dhan quotes/history require the
            numeric id, NOT the ticker — see the 3C note in docs/QA.md). Empty
            until filled; only needed for the live Dhan bar source.
        exchange_segment: Dhan exchange segment (``NSE_EQ`` / ``BSE_EQ``).
    """

    symbol: str
    security_id: str = ""
    exchange_segment: str = "NSE_EQ"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Instrument":
        """Build an instrument from a JSON-like mapping."""
        symbol = str(data.get("symbol") or "").strip()
        if not symbol:
            raise ValueError("universe instrument requires a 'symbol'")
        segment = str(data.get("exchange_segment") or "").strip().upper()
        if not segment:
            segment = "BSE_EQ" if symbol.upper().endswith(".BO") else "NSE_EQ"
        return cls(
            symbol=symbol,
            security_id=str(data.get("security_id") or "").strip(),
            exchange_segment=segment,
        )

    @property
    def has_security_id(self) -> bool:
        """True once a real (non-placeholder) Dhan security id is set."""
        return not is_placeholder(self.security_id)


@dataclass(frozen=True)
class StrategyRef:
    """One strategy in the parallel paper roster.

    Attributes:
        name: Short unique label (used in the scoreboard + Telegram summaries).
        run_dir: Path to the strategy run dir (holds ``code/signal_engine.py`` +
            ``config.json``), relative to the ``agent/`` root or absolute.
        allow_short: 3L hybrid twin — build the engine short-capable
            (``SignalEngine(allow_short=True)``) and let the runner honor −1 as a
            short entry. Default ``False`` = the long-only arm. A twin shares its
            long counterpart's ``run_dir`` (same tuned source, never a copy).
        params: Per-slot engine kwargs (3R), passed through to
            ``build_builtin_engine`` — e.g. ``{"provider": "ollama", "model":
            "llama3.1:8b"}`` lets two roster slots share one builtin with
            different models. Run-dir slots must leave it empty.
    """

    name: str
    run_dir: str
    allow_short: bool = False
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "StrategyRef":
        name = str(data.get("name") or "").strip()
        run_dir = str(data.get("run_dir") or "").strip()
        if not name or not run_dir:
            raise ValueError("roster entry requires 'name' and 'run_dir'")
        return cls(
            name=name,
            run_dir=run_dir,
            allow_short=bool(data.get("allow_short", False)),
            params=dict(data.get("params") or {}),
        )


@dataclass(frozen=True)
class IntradayConfig:
    """Resolved settings for one intraday paper session.

    All time-of-day fields are IST ``"HH:MM"`` strings interpreted by
    :mod:`~src.intraday.clock`. Credentials default to placeholders.

    Attributes:
        universe: The 2–3 liquid symbols to trade (trial: ₹25–50k, long-only).
        interval: Bar interval token (``"15m"`` default) — matches the strategy.
        market_open / market_close: IST session bounds (09:15 / 15:30).
        strategy_flat: IST time the strategy must be flat by (15:00) so a
            next-bar-open fill lands the exit at the square-off (DC-001).
        squareoff: IST cutoff at/after which the runtime FORCE-flattens any
            still-open long (15:15) — authoritative, independent of the strategy.
        initial_cash: Paper starting capital (₹).
        max_positions: Cap on simultaneous open longs (defaults to len(universe)).
        strategy_run_dir: Path to the strategy run dir (holds ``code/signal_engine.py``
            + ``config.json``); the single-strategy runner imports its ``SignalEngine``.
        roster: The parallel paper-trading roster (multi-strategy bake-off). When
            non-empty, the :class:`~src.intraday.portfolio.Portfolio` runs one
            isolated ``PaperBroker`` per entry; empty falls back to
            ``strategy_run_dir`` (single strategy).
        per_strategy_cash: Independent paper capital per strategy (₹). The bake-off
            gives every strategy its own equal account for an apples-to-apples rank.
        per_strategy_loss_cutoff: Per-strategy **setup kill-switch** (₹). When a
            strategy's cumulative loss (realized + open) reaches this, that strategy
            is squared off and RETIRED for the rest of the run — permanently, not a
            daily reset — while the others keep trading. ``0`` disables it.
        lookback_bars: How many recent bars to feed the signal engine per tick.
        telegram_bot_token / telegram_chat_id: Trade-feed sink creds.
        gemini_api_key / gemini_model / gemini_provider: Research/EOD LLM creds.
        dhan_client_id / dhan_access_token: Data (+ M2 execution) creds.
    """

    universe: tuple[Instrument, ...] = (
        Instrument("RELIANCE.NS"),
        Instrument("SBIN.NS"),
        Instrument("ICICIBANK.NS"),
    )
    interval: str = "15m"
    market_open: str = "09:15"
    market_close: str = "15:30"
    strategy_flat: str = "15:00"
    squareoff: str = "15:15"
    initial_cash: float = 50_000.0
    max_positions: int = 0  # 0 → default to len(universe)
    strategy_run_dir: str = ""
    roster: tuple[StrategyRef, ...] = ()
    per_strategy_cash: float = 25_000.0
    per_strategy_loss_cutoff: float = 10_000.0
    lookback_bars: int = 60
    # Ride out a short data/Wi-Fi drop before a tick so a blip up to this many
    # seconds doesn't cost a 15m bar. 0 disables the wait (fall straight through
    # to today's empty-frame 'hold'). Default 300s = 5 min (< the 900s tick).
    reconnect_budget_seconds: float = 300.0

    telegram_bot_token: str = "PLACEHOLDER-TELEGRAM-BOT-TOKEN"
    telegram_chat_id: str = "PLACEHOLDER-TELEGRAM-CHAT-ID"
    gemini_api_key: str = "PLACEHOLDER-GEMINI-API-KEY"
    gemini_model: str = "gemini-3.5-flash"
    gemini_provider: str = "gemini"
    # Local Ollama (3O bookend fallback + 3R llm_local_* trader slots). No key
    # needed — a local server either answers or the callers fail soft.
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    dhan_client_id: str = "PLACEHOLDER-DHAN-CLIENT-ID"
    dhan_access_token: str = "PLACEHOLDER-DHAN-ACCESS-TOKEN"

    # -- configured-yet predicates (drive live-vs-stub wiring) ---------------

    @property
    def is_telegram_configured(self) -> bool:
        """True once both the Telegram bot token and chat id are real."""
        return not is_placeholder(self.telegram_bot_token) and not is_placeholder(
            self.telegram_chat_id
        )

    @property
    def is_gemini_configured(self) -> bool:
        """True once the Gemini API key is real."""
        return not is_placeholder(self.gemini_api_key)

    @property
    def is_dhan_configured(self) -> bool:
        """True once Dhan client id + access token are real."""
        return not is_placeholder(self.dhan_client_id) and not is_placeholder(
            self.dhan_access_token
        )

    @property
    def position_cap(self) -> int:
        """Effective max simultaneous open longs."""
        return self.max_positions if self.max_positions > 0 else len(self.universe)

    def instrument_for(self, symbol: str) -> Instrument | None:
        """Return the universe instrument for ``symbol``, or ``None``."""
        for inst in self.universe:
            if inst.symbol == symbol:
                return inst
        return None

    def redacted(self) -> dict[str, Any]:
        """Return a log-safe view: secrets masked, predicates surfaced.

        Never returns raw tokens — safe to print at startup so an operator can
        confirm WHICH creds are still placeholders without leaking real ones.
        """

        def mask(value: str) -> str:
            return "‹set›" if not is_placeholder(value) else "‹placeholder›"

        return {
            "universe": [i.symbol for i in self.universe],
            "interval": self.interval,
            "session": f"{self.market_open}-{self.market_close} IST",
            "strategy_flat": self.strategy_flat,
            "squareoff": self.squareoff,
            "initial_cash": self.initial_cash,
            "position_cap": self.position_cap,
            "roster": [s.name for s in self.roster],
            "per_strategy_cash": self.per_strategy_cash,
            "per_strategy_loss_cutoff": self.per_strategy_loss_cutoff,
            "telegram": mask(self.telegram_bot_token),
            "telegram_configured": self.is_telegram_configured,
            "gemini": mask(self.gemini_api_key),
            "gemini_model": self.gemini_model,
            "gemini_configured": self.is_gemini_configured,
            "dhan": mask(self.dhan_access_token),
            "dhan_configured": self.is_dhan_configured,
        }

    # -- construction --------------------------------------------------------

    @classmethod
    def load(
        cls,
        json_path: str | Path | None = None,
        *,
        env: Mapping[str, str] | None = None,
        load_env_file: bool = True,
    ) -> "IntradayConfig":
        """Resolve config from defaults ← JSON file ← environment.

        Args:
            json_path: Explicit JSON config path. ``None`` uses
                ``config/intraday.json`` beside the ``agent/`` root if present.
            env: Environment mapping (defaults to :data:`os.environ`). Injectable
                for tests.
            load_env_file: When ``True`` and ``env`` is not supplied, load
                ``agent/.env`` into the environment first (python-dotenv), so
                secrets in ``.env`` are picked up without exporting them.

        Returns:
            A fully-resolved :class:`IntradayConfig`.
        """
        if env is None:
            if load_env_file:
                _load_dotenv()
            env = os.environ

        cfg = cls()
        cfg = _apply_json(cfg, json_path)
        cfg = _apply_env(cfg, env)
        return cfg


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def _agent_root() -> Path:
    """Return the ``agent/`` package root (three parents up from this file)."""
    # src/intraday/config.py → src/intraday → src → agent
    return Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    """Best-effort load ``agent/.env`` into ``os.environ`` (never overrides set vars)."""
    try:
        from dotenv import load_dotenv  # optional, but in requirements.txt
    except Exception:  # pragma: no cover — dotenv is a declared dep
        return
    env_path = _agent_root() / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


def _apply_json(cfg: IntradayConfig, json_path: str | Path | None) -> IntradayConfig:
    """Overlay a JSON config file onto ``cfg`` (silently skipped when absent)."""
    path = Path(json_path) if json_path is not None else _agent_root() / DEFAULT_CONFIG_REL
    if not path.exists():
        return cfg
    data = json.loads(path.read_text(encoding="utf-8"))
    updates: dict[str, Any] = {}

    if "universe" in data:
        updates["universe"] = tuple(
            Instrument.from_mapping(item) for item in data["universe"]
        )
    if "roster" in data:
        updates["roster"] = tuple(
            StrategyRef.from_mapping(item) for item in data["roster"]
        )
    for key in (
        "interval",
        "market_open",
        "market_close",
        "strategy_flat",
        "squareoff",
        "strategy_run_dir",
        "gemini_model",
        "gemini_provider",
        "ollama_url",
        "ollama_model",
    ):
        if key in data and data[key] is not None:
            updates[key] = str(data[key])
    for key in ("initial_cash", "per_strategy_cash", "per_strategy_loss_cutoff", "reconnect_budget_seconds"):
        if key in data and data[key] is not None:
            updates[key] = float(data[key])
    for key in ("max_positions", "lookback_bars"):
        if key in data and data[key] is not None:
            updates[key] = int(data[key])
    # Secrets MAY live in JSON (placeholders by default) but env wins over them.
    for key in (
        "telegram_bot_token",
        "telegram_chat_id",
        "gemini_api_key",
        "dhan_client_id",
        "dhan_access_token",
    ):
        if key in data and data[key] is not None:
            updates[key] = str(data[key])

    return replace(cfg, **updates)


#: Env var → config field. Standard vibe-trading names reused where they exist.
_ENV_MAP = {
    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
    "TELEGRAM_CHAT_ID": "telegram_chat_id",
    "GEMINI_API_KEY": "gemini_api_key",
    "LANGCHAIN_MODEL_NAME": "gemini_model",
    "LANGCHAIN_PROVIDER": "gemini_provider",
    "DHAN_CLIENT_ID": "dhan_client_id",
    "DHAN_ACCESS_TOKEN": "dhan_access_token",
    "VIBE_INTRADAY_INTERVAL": "interval",
    "VIBE_INTRADAY_SQUAREOFF": "squareoff",
    "VIBE_INTRADAY_STRATEGY_FLAT": "strategy_flat",
    "VIBE_INTRADAY_STRATEGY_DIR": "strategy_run_dir",
    "VIBE_INTRADAY_OLLAMA_URL": "ollama_url",
    "VIBE_INTRADAY_OLLAMA_MODEL": "ollama_model",
}

_ENV_FLOAT = {
    "VIBE_INTRADAY_INITIAL_CASH": "initial_cash",
    "VIBE_INTRADAY_PER_STRATEGY_CASH": "per_strategy_cash",
    "VIBE_INTRADAY_LOSS_CUTOFF": "per_strategy_loss_cutoff",
}
_ENV_INT = {
    "VIBE_INTRADAY_MAX_POSITIONS": "max_positions",
    "VIBE_INTRADAY_LOOKBACK_BARS": "lookback_bars",
}


def _apply_env(cfg: IntradayConfig, env: Mapping[str, str]) -> IntradayConfig:
    """Overlay environment variables onto ``cfg`` (highest precedence)."""
    updates: dict[str, Any] = {}
    for var, field_name in _ENV_MAP.items():
        val = env.get(var)
        if val:
            updates[field_name] = val
    for var, field_name in _ENV_FLOAT.items():
        val = env.get(var)
        if val:
            updates[field_name] = float(val)
    for var, field_name in _ENV_INT.items():
        val = env.get(var)
        if val:
            updates[field_name] = int(val)
    return replace(cfg, **updates) if updates else cfg
