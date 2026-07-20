"""Per-strategy metrics + weekly scoreboard persistence for the paper bake-off.

Turns a strategy's fills into the numbers you rank strategies on at week's end,
and persists one record per (date, strategy) to a JSON file so results survive
the daily restarts across the week. The metrics are deliberately the ones that
decide whether a strategy graduates to a live test:

  * ``net_pnl``      — realized ₹ P&L, **net of MIS costs** (the whole point).
  * ``return_pct``   — net_pnl / starting capital.
  * ``trades``       — number of round-trips (closed longs).
  * ``win_rate``     — % of round-trips with positive realized P&L.
  * ``fees``         — total ₹ commission paid (the cost drag).
  * ``max_drawdown`` — worst peak-to-trough of the realized-equity curve (₹).
  * ``halted`` / ``halt_reason`` — set when the ₹ setup kill-switch retired it.

A strategy that blew its per-strategy loss cutoff is ranked last regardless of
anything else — a disqualified setup is not a candidate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.intraday.notifier import split_for_telegram
from src.intraday.paper_broker import Fill

logger = logging.getLogger(__name__)


#: Fill sides that close a round-trip (book realized P&L): a long sell or a
#: short buy-to-cover.
_CLOSING_SIDES = ("sell", "cover")


@dataclass(frozen=True)
class StrategyMetrics:
    """Computed performance of one strategy over a session (JSON-serializable).

    ``net_pnl`` is the total realized across both legs; ``long_pnl`` /
    ``short_pnl`` decompose it (Σ realized of ``sell`` fills vs ``cover`` fills)
    so a hybrid twin's pair delta is attributable to the short side (3L
    invariant 3). A long-only slot has ``short_pnl == 0``.
    """

    name: str
    starting_cash: float
    net_pnl: float
    return_pct: float
    trades: int
    wins: int
    win_rate: float
    fees: float
    max_drawdown: float
    open_positions: int
    halted: bool = False
    halt_reason: str = ""
    long_pnl: float = 0.0
    short_pnl: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "starting_cash": round(self.starting_cash, 2),
            "net_pnl": round(self.net_pnl, 2),
            "return_pct": round(self.return_pct, 4),
            "trades": self.trades,
            "wins": self.wins,
            "win_rate": round(self.win_rate, 4),
            "fees": round(self.fees, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "open_positions": self.open_positions,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "long_pnl": round(self.long_pnl, 2),
            "short_pnl": round(self.short_pnl, 2),
        }


def compute_metrics(
    name: str,
    starting_cash: float,
    fills: Sequence[Fill],
    *,
    open_positions: int = 0,
    halted: bool = False,
    halt_reason: str = "",
) -> StrategyMetrics:
    """Reduce a strategy's fills to a :class:`StrategyMetrics`.

    Round-trips are counted by **closing** fills — a long ``sell`` OR a short
    ``cover`` (each books realized P&L); a win is a close with positive realized
    P&L. ``long_pnl`` sums the ``sell`` legs, ``short_pnl`` the ``cover`` legs;
    ``net_pnl`` is their total. The drawdown is taken over the cumulative
    realized-P&L curve stepped by each close, in fill order.

    Args:
        name: Strategy label.
        starting_cash: The strategy's independent starting capital (₹).
        fills: The strategy's fills, in order.
        open_positions: Count of positions still open (should be 0 after the
            15:15 square-off; surfaced so a stuck position is visible).
        halted / halt_reason: Set when the setup kill-switch retired the strategy.

    Returns:
        The metrics.
    """
    closes = [f for f in fills if f.side in _CLOSING_SIDES]
    trades = len(closes)
    wins = sum(1 for f in closes if f.realized_pnl > 0)
    net_pnl = sum(f.realized_pnl for f in closes)
    long_pnl = sum(f.realized_pnl for f in fills if f.side == "sell")
    short_pnl = sum(f.realized_pnl for f in fills if f.side == "cover")
    fees = sum(f.commission for f in fills)

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for f in closes:
        equity += f.realized_pnl
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)  # most-negative drop from a peak

    return StrategyMetrics(
        name=name,
        starting_cash=starting_cash,
        net_pnl=net_pnl,
        return_pct=(net_pnl / starting_cash) if starting_cash else 0.0,
        trades=trades,
        wins=wins,
        win_rate=(wins / trades) if trades else 0.0,
        fees=fees,
        max_drawdown=max_dd,
        open_positions=open_positions,
        halted=halted,
        halt_reason=halt_reason,
        long_pnl=long_pnl,
        short_pnl=short_pnl,
    )


def rank(metrics: Iterable[StrategyMetrics]) -> list[StrategyMetrics]:
    """Rank strategies best-first: survivors by net P&L, halted ones last."""
    return sorted(metrics, key=lambda m: (m.halted, -m.net_pnl))


def format_scoreboard(metrics: Sequence[StrategyMetrics], *, title: str) -> str:
    """Render the EOD scoreboard collapsed to one row per long/``_ls`` pair.

    B4-2 (64-slot roster): a flat 64-row table spilled to 2 Telegram chunks and
    scattered each strategy's two legs across the ranking. Here each base
    strategy is one row — its pure-long net (``long``), its hybrid twin's net
    (``ls``), and the twin's short-leg ₹ (``sht``) side by side — so the A/B
    delta reads directly. Rows rank by the pair's **best** leg (halted pairs
    last, flagged ``✖``; a halt on *either* leg keeps the whole pair visible).
    Unpaired long slots (``llm_local_a/b`` — no ``_ls`` twin) get their own
    trailing line. A topline sums the whole roster; the report is held under
    :data:`_CHUNK_CAP` Telegram chunks (:func:`_cap_report`).
    """
    pairs, unpaired = _pair_items(metrics, lambda m: m.name)
    total_net = sum(m.net_pnl for m in metrics)
    total_fees = sum(m.fees for m in metrics)
    total_trades = sum(m.trades for m in metrics)
    profitable = sum(1 for m in metrics if m.net_pnl > 0)
    ordered = sorted(pairs, key=lambda p: (_pair_halted(p), -_pair_best_net(p)))

    head = [
        f"<b>{title}</b>",
        f"Σ net {_money(total_net)} · fees ₹{total_fees:,.0f} · trades "
        f"{total_trades} · {profitable} of {len(metrics)} slots profitable",
        "<b>Ranked by best leg</b> · long vs ls (hybrid) · sht = short leg",
        "<pre>",
        f"{'#':<3}{'pair':<16}{'long':>8}{'ls':>8}{'sht':>7}{'trd':>4}{'flag':>6}",
    ]
    body = []
    for i, (base, lng, ls) in enumerate(ordered, 1):
        long_txt = f"{lng.net_pnl:>8,.0f}" if lng else f"{'—':>8}"
        ls_txt = f"{ls.net_pnl:>8,.0f}" if ls else f"{'—':>8}"
        sht = (ls.short_pnl if ls else 0.0)
        trades = (lng.trades if lng else 0) + (ls.trades if ls else 0)
        flag = "✖" if _pair_halted((base, lng, ls)) else ""
        body.append(
            f"{i:<3}{base[:15]:<16}{long_txt}{ls_txt}{sht:>7,.0f}"
            f"{trades:>4}{flag:>6}"
        )
    tail = ["</pre>"]
    if unpaired:
        tail.append(
            "llm (unpaired): "
            + " · ".join(
                f"{m.name} {_money(m.net_pnl)}{' ✖' if m.halted else ''}"
                for m in unpaired
            )
        )
    return _cap_report(head, body, tail, pointer="… +{n} more pairs (log)")


def format_hourly(rows: Sequence[tuple[str, int, float]], *, hour_label: str) -> str:
    """Render the hourly rollup: (name, trades_this_hour, running_net_pnl)."""
    lines = [f"<b>Hourly summary · {hour_label} IST</b>", "<pre>"]
    lines.append(f"{'strategy':<14}{'+trd':>6}{'net ₹':>10}")
    for name, hourly_trades, running in rows:
        lines.append(f"{name[:13]:<14}{hourly_trades:>6}{running:>10,.0f}")
    lines.append("</pre>")
    return "\n".join(lines)


def _money(value: float) -> str:
    """₹ figure with an explicit sign (matches the notifier's convention)."""
    sign = "+" if value >= 0 else "−"
    return f"{sign}₹{abs(value):,.0f}"


#: Hard cap on Telegram chunks per report; content beyond it is truncated with a
#: pointer to the log tape (B4-2, 64-slot roster — the full per-fill tape lives
#: in the log regardless).
_CHUNK_CAP = 3


def _pair_items(items: Sequence[Any], name_of) -> tuple[list[tuple], list[Any]]:
    """Group each long slot with its ``_ls`` hybrid twin.

    Returns ``(pairs, unpaired)`` where each pair is ``(base, long_item,
    ls_item)`` (either item may be ``None`` if a leg is missing) and ``unpaired``
    is the long slots with no ``_ls`` twin — e.g. ``llm_local_a`` / ``llm_local_b``
    (B4-2: handle unpaired slots gracefully). ``name_of`` extracts a slot's
    name from an item (a section dict or a :class:`StrategyMetrics`).
    """
    by = {name_of(it): it for it in items}
    pairs: list[tuple] = []
    unpaired: list[Any] = []
    consumed: set[str] = set()
    for it in items:
        name = name_of(it)
        if name.endswith("_ls"):
            continue
        twin = by.get(f"{name}_ls")
        if twin is not None:
            pairs.append((name, it, twin))
            consumed.add(f"{name}_ls")
        else:
            unpaired.append(it)
    for it in items:  # defensive: an _ls with no long partner is its own pair
        name = name_of(it)
        if name.endswith("_ls") and name not in consumed:
            pairs.append((name[:-3], None, it))
    return pairs, unpaired


def _slot_net(item: Any) -> float:
    """Net ₹ of a pair leg — a section dict's ``realized`` or a metric's ``net_pnl``."""
    if item is None:
        return 0.0
    if isinstance(item, dict):
        return item.get("realized", 0.0)
    return item.net_pnl


def _slot_halted(item: Any) -> bool:
    if item is None:
        return False
    if isinstance(item, dict):
        return bool(item.get("halted"))
    return bool(item.halted)


def _pair_halted(pair: tuple) -> bool:
    """A halt on *either* leg (the surviving twin must stay visible, B4-2)."""
    _, lng, ls = pair
    return _slot_halted(lng) or _slot_halted(ls)


def _pair_best_net(pair: tuple) -> float:
    _, lng, ls = pair
    return max(_slot_net(lng), _slot_net(ls))


def _pair_mag(pair: tuple) -> float:
    """Mover magnitude — the larger absolute leg net (hourly sort key)."""
    _, lng, ls = pair
    return max(abs(_slot_net(lng)), abs(_slot_net(ls)))


def _cap_report(
    head: Sequence[str], body: Sequence[str], tail: Sequence[str], *, pointer: str
) -> str:
    """Assemble ``head`` + droppable ``body`` rows + ``tail`` under the cap.

    ``head`` runs through the ``<pre>`` header row and ``tail`` starts with
    ``</pre>`` plus any always-visible trailing lines (retired slots, unpaired
    llm) — the tail is never dropped, so a halt stays visible even under
    truncation. If the full report exceeds :data:`_CHUNK_CAP` Telegram chunks
    (measured with the real :func:`~src.intraday.notifier.split_for_telegram`),
    body rows are dropped from the end and ``pointer`` (kept inside ``<pre>``)
    records how many pairs were hidden.
    """
    def assemble(rows: Sequence[str]) -> str:
        return "\n".join([*head, *rows, *tail])

    if len(split_for_telegram(assemble(body))) <= _CHUNK_CAP:
        return assemble(body)
    rows = list(body)
    while rows:
        rows.pop()
        candidate = assemble([*rows, pointer.format(n=len(body) - len(rows))])
        if len(split_for_telegram(candidate)) <= _CHUNK_CAP:
            return candidate
    return assemble([pointer.format(n=len(body))])


def format_hourly_detailed(sections: Sequence[dict[str, Any]], *, hour_label: str) -> str:
    """Render the hourly report, one line per long/``_ls`` pair.

    Each section dict carries: ``name``, ``fills`` (list[:class:`Fill`] since
    the last report), ``opens`` (list of ``(symbol, qty, avg_price, mark,
    direction)``), ``realized`` (₹ today, net of charges), ``halted`` /
    ``halt_reason``, and for hybrid slots ``short_pnl`` (₹ today on the short
    leg) so the short side is attributable (3L invariant 3). ``equity`` /
    ``cash`` / ``fees`` / per-fill detail are no longer rendered here — the full
    tape lives in the log.

    B4-2 (64-slot roster): the prior per-slot block (header + legs + up to 8
    fills + open positions) ballooned to 4 Telegram chunks at 64 slots. This
    collapses each base strategy to one table row — pure-long net (``long``),
    hybrid-twin net (``ls``), the twin's short leg (``sht``), the A/B delta
    (``Δ`` = ls net − long net = the value of allowing shorts), and fill/hold
    counts (``f`` / ``h``) across both legs. Live pairs sort movers-first (by
    the larger absolute leg net); halted pairs are pulled out and always listed
    (both legs, so a surviving twin stays visible); unpaired llm slots get their
    own line. The report is held under :data:`_CHUNK_CAP` chunks.
    """
    pairs, unpaired = _pair_items(sections, lambda s: s["name"])
    total_net = sum(s.get("realized", 0.0) for s in sections)
    active = sum(1 for s in sections if s.get("fills"))
    holding = sum(1 for s in sections if s.get("opens"))
    retired = sum(1 for s in sections if s.get("halted"))

    live = [p for p in pairs if not _pair_halted(p)]
    halted = [p for p in pairs if _pair_halted(p)]
    live.sort(key=lambda p: -_pair_mag(p))

    head = [
        f"<b>📊 Hourly · {hour_label} IST</b>",
        f"Σ net {_money(total_net)} · {active} active · {holding} holding · "
        f"{retired} ✖retired · {len(sections)} slots "
        f"({len(pairs)} pairs + {len(unpaired)} llm)",
        "<b>All pairs</b> — Δ = short-side edge (ls net − long net)",
        "<pre>",
        f"{'pair':<16}{'long':>8}{'ls':>8}{'sht':>7}{'Δ':>7}{'f':>3}{'h':>3}",
    ]
    body = [_hourly_pair_row(p) for p in live]
    tail = ["</pre>"]
    for base, lng, ls in halted:
        tail.append("⚠ " + _hourly_halt_line(base, lng, ls))
    if unpaired:
        tail.append(
            "llm: "
            + " · ".join(
                f"{s['name']} {_money(s.get('realized', 0.0))}"
                f"{' ✖' if s.get('halted') else ''}"
                for s in unpaired
            )
        )
    return _cap_report(head, body, tail, pointer="… +{n} more pairs (log)")


def _hourly_pair_row(pair: tuple) -> str:
    """One monospace table row for a live pair (inside the ``<pre>`` block)."""
    base, lng, ls = pair
    long_net = _slot_net(lng)
    ls_net = _slot_net(ls)
    ls_sht = ls.get("short_pnl", 0.0) if ls else 0.0
    delta = ls_net - long_net
    fills = (len(lng.get("fills") or []) if lng else 0) + (
        len(ls.get("fills") or []) if ls else 0
    )
    holds = (len(lng.get("opens") or []) if lng else 0) + (
        len(ls.get("opens") or []) if ls else 0
    )
    return (
        f"{base[:15]:<16}{long_net:>8,.0f}{ls_net:>8,.0f}"
        f"{ls_sht:>7,.0f}{delta:>7,.0f}{fills:>3}{holds:>3}"
    )


def _hourly_halt_line(base: str, lng: Any, ls: Any) -> str:
    """Both legs of a halted pair, ✖ on the retired leg (never collapsed away)."""
    parts = []
    for label, item in (("long", lng), ("ls", ls)):
        if item is None:
            continue
        tag = " ✖" if _slot_halted(item) else ""
        parts.append(f"{label} {_money(_slot_net(item))}{tag}")
    return f"<b>{base}</b>: " + " / ".join(parts)


class ScoreboardStore:
    """Append-only per-(date, strategy) record store for the week.

    One JSON file holds a flat list of daily records; :meth:`save_day` replaces
    any existing records for that date (idempotent re-runs) and appends the new
    ones. :meth:`weekly_table` reduces the file to a per-strategy weekly total.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("scoreboard store unreadable at %s — starting fresh", self.path)
            return []

    def save_day(self, day: date, metrics: Sequence[StrategyMetrics]) -> None:
        """Persist ``metrics`` for ``day`` (replacing any prior records for it)."""
        records = [r for r in self.load() if r.get("date") != day.isoformat()]
        for m in metrics:
            row = m.to_dict()
            row["date"] = day.isoformat()
            records.append(row)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    def weekly_table(self) -> list[dict[str, Any]]:
        """Aggregate every persisted day into a per-strategy weekly summary."""
        agg: dict[str, dict[str, Any]] = {}
        for r in self.load():
            name = r.get("name", "?")
            a = agg.setdefault(
                name,
                {"name": name, "days": 0, "net_pnl": 0.0, "trades": 0, "wins": 0,
                 "fees": 0.0, "ever_halted": False},
            )
            a["days"] += 1
            a["net_pnl"] += float(r.get("net_pnl", 0))
            a["trades"] += int(r.get("trades", 0))
            a["wins"] += int(r.get("wins", 0))
            a["fees"] += float(r.get("fees", 0))
            a["ever_halted"] = a["ever_halted"] or bool(r.get("halted"))
        for a in agg.values():
            a["win_rate"] = (a["wins"] / a["trades"]) if a["trades"] else 0.0
        return sorted(agg.values(), key=lambda a: (a["ever_halted"], -a["net_pnl"]))
