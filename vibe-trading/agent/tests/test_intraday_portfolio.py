"""Offline tests for the parallel multi-strategy paper bake-off (portfolio layer).

Covers isolation (independent per-strategy accounts), the per-strategy ₹ setup
kill-switch (permanent retire, survivors keep trading), hourly rollups, the EOD
scoreboard + weekly persistence, and scoreboard metric math. No live services —
replay bars, frozen clock, stub engines.

Run:  cd vibe-trading/agent && set PYTHONPATH=. && \
      python -m pytest tests/test_intraday_portfolio.py -q
"""

from __future__ import annotations

import tempfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from src.intraday.bars import ReplayBarSource
from src.intraday.clock import IST
from src.intraday.config import IntradayConfig, Instrument, StrategyRef
from src.intraday.notifier import LogSink, TradeNotifier
from src.intraday.paper_broker import Fill, PaperBroker
from src.intraday.portfolio import Portfolio
from src.intraday.scoreboard import (
    ScoreboardStore,
    compute_metrics,
    format_scoreboard,
    rank,
)


def _ist(hh, mm):
    return datetime(2026, 7, 14, hh, mm, tzinfo=IST)


def _frame(base):
    idx = pd.date_range("2026-07-14 09:15", "2026-07-14 15:15", freq="15min", tz=IST)
    close = [base + i for i in range(len(idx))]
    return pd.DataFrame(
        {"open": close, "high": [c + 1 for c in close], "low": [c - 1 for c in close],
         "close": close, "volume": [1000] * len(idx)},
        index=idx,
    )


class _StubEngine:
    def __init__(self, want):
        self._want = want  # callable(sym, df) -> 0/1

    def generate(self, data_map):
        return {s: pd.Series([self._want(s, df)] * len(df), index=df.index) for s, df in data_map.items()}


class _StubDir:
    """Fixed-direction (−1/0/1) engine for the 3L hybrid-twin tests."""

    def __init__(self, val):
        self._val = val

    def generate(self, data_map):
        return {s: pd.Series([self._val] * len(df), index=df.index) for s, df in data_map.items()}


def _cfg(**kw):
    base = dict(
        universe=(Instrument("RELIANCE.NS"),),
        roster=(
            StrategyRef("A", "x"),
            StrategyRef("B", "x"),
        ),
        per_strategy_cash=25_000.0,
        per_strategy_loss_cutoff=10_000.0,
        max_positions=1,
    )
    base.update(kw)
    return IntradayConfig(**base)


def _portfolio(engines, cfg=None, store=None):
    cfg = cfg or _cfg()
    src = ReplayBarSource({"RELIANCE.NS": _frame(1000)})
    feed = TradeNotifier(LogSink(), mode="PAPER")
    if store is None:
        # BUG-007: never default to the REAL ~/.vibe-trading scoreboard.json —
        # finalize() from a test must land in a throwaway file.
        store = ScoreboardStore(
            Path(tempfile.mkdtemp(prefix="vibe-test-scoreboard-")) / "scoreboard.json"
        )
    return Portfolio(cfg, src, notifier=feed, scoreboard_store=store, signal_engines=engines)


# --------------------------------------------------------------------------- #
# isolation
# --------------------------------------------------------------------------- #


def test_each_strategy_has_independent_account():
    p = _portfolio({
        "A": _StubEngine(lambda s, df: 1),  # A goes long
        "B": _StubEngine(lambda s, df: 0),  # B stays flat
    })
    p.run_tick(_ist(10, 0))
    a = next(s for s in p.slots if s.name == "A")
    b = next(s for s in p.slots if s.name == "B")
    assert a.broker.open_symbols() == ["RELIANCE.NS"]
    assert b.broker.open_symbols() == []
    assert a.broker.starting_cash == 25_000 and b.broker.starting_cash == 25_000
    assert a.broker.cash != b.broker.cash  # only A deployed cash


def test_per_symbol_budget_uses_strategy_cash_not_config_cash():
    cfg = _cfg(initial_cash=50_000.0, per_strategy_cash=25_000.0)
    p = _portfolio({"A": _StubEngine(lambda s, df: 1), "B": _StubEngine(lambda s, df: 0)}, cfg=cfg)
    slot = next(s for s in p.slots if s.name == "A")
    assert slot.runner.per_symbol_budget == 25_000  # ₹25k / cap 1, NOT ₹50k


# --------------------------------------------------------------------------- #
# per-strategy setup kill-switch
# --------------------------------------------------------------------------- #


def test_strategy_retired_when_loss_hits_cutoff():
    # Force a big loss on A by marking price far below entry after it buys.
    idx = pd.date_range("2026-07-14 09:15", "2026-07-14 15:15", freq="15min", tz=IST)
    close = [1000] + [1000] * (len(idx) - 1)
    df = pd.DataFrame(
        {"open": close, "high": [c + 1 for c in close], "low": [c - 1 for c in close],
         "close": list(close), "volume": [1000] * len(idx)}, index=idx)
    df.iloc[3, df.columns.get_loc("close")] = 400  # crash → open long underwater
    src = ReplayBarSource({"RELIANCE.NS": df})
    cfg = _cfg(per_strategy_loss_cutoff=5_000.0)
    p = Portfolio(cfg, src, notifier=TradeNotifier(LogSink()),
                  signal_engines={"A": _StubEngine(lambda s, d: 1), "B": _StubEngine(lambda s, d: 0)})
    p.run_tick(_ist(9, 30))   # A opens ~₹25k of stock @ ~1000
    p.run_tick(_ist(10, 0))   # price crashed to 400 → loss > ₹5k → A retired
    a = next(s for s in p.slots if s.name == "A")
    b = next(s for s in p.slots if s.name == "B")
    assert a.halted and "kill-switch" in a.halt_reason
    assert a.broker.open_symbols() == []          # squared off on retire
    assert not b.halted                            # survivor keeps trading


def test_retired_strategy_stops_trading_but_others_continue():
    p = _portfolio({
        "A": _StubEngine(lambda s, df: 1),
        "B": _StubEngine(lambda s, df: 1),
    }, cfg=_cfg(per_strategy_loss_cutoff=1.0))  # trivially trips as soon as A is down a rupee
    p.run_tick(_ist(10, 0))
    p.run_tick(_ist(10, 15))
    a = next(s for s in p.slots if s.name == "A")
    # A retired; a further tick books nothing new for it.
    before = len(a.runner.state.fills)
    p.run_tick(_ist(10, 30))
    assert a.halted
    assert len(a.runner.state.fills) == before


def test_cutoff_disabled_when_zero():
    p = _portfolio({"A": _StubEngine(lambda s, df: 1), "B": _StubEngine(lambda s, df: 0)},
                   cfg=_cfg(per_strategy_loss_cutoff=0.0))
    p.run_tick(_ist(10, 0))
    assert not any(s.halted for s in p.slots)


# --------------------------------------------------------------------------- #
# hourly rollup + EOD scoreboard + persistence
# --------------------------------------------------------------------------- #


def test_hourly_summary_emitted_on_hour_change():
    sink = LogSink()
    p = _portfolio({"A": _StubEngine(lambda s, df: 0), "B": _StubEngine(lambda s, df: 0)})
    p.feed = TradeNotifier(sink, mode="PAPER")
    p.run_tick(_ist(10, 0))   # establishes baseline hour, no summary
    p.run_tick(_ist(10, 30))  # same hour → still none
    p.run_tick(_ist(11, 0))   # hour changed → one hourly summary
    assert any("📊 Hourly · 11:00 IST" in m for m in sink.messages)


def test_finalize_persists_and_posts_scoreboard(tmp_path):
    store = ScoreboardStore(tmp_path / "sb.json")
    sink = LogSink()
    p = _portfolio({"A": _StubEngine(lambda s, df: 0), "B": _StubEngine(lambda s, df: 0)}, store=store)
    p.feed = TradeNotifier(sink, mode="PAPER")
    mets = p.finalize(_ist(15, 30))
    assert len(mets) == 2
    assert any("EOD scoreboard" in m for m in sink.messages)
    # persisted + idempotent (second finalize doesn't duplicate)
    assert (tmp_path / "sb.json").exists()
    records = store.load()
    assert {r["name"] for r in records} == {"A", "B"}
    assert all(r["date"] == "2026-07-14" for r in records)
    p.finalize(_ist(15, 35))
    assert len(store.load()) == 2  # unchanged


def test_scoreboard_store_weekly_aggregation(tmp_path):
    store = ScoreboardStore(tmp_path / "sb.json")
    m1 = compute_metrics("A", 25_000, [_sell(100), _sell(-50)])
    store.save_day(date(2026, 7, 13), [m1])
    m2 = compute_metrics("A", 25_000, [_sell(200)])
    store.save_day(date(2026, 7, 14), [m2])
    weekly = store.weekly_table()
    row = next(r for r in weekly if r["name"] == "A")
    assert row["days"] == 2
    assert row["net_pnl"] == pytest.approx(250.0)
    assert row["trades"] == 3


def test_save_day_replaces_same_date(tmp_path):
    store = ScoreboardStore(tmp_path / "sb.json")
    store.save_day(date(2026, 7, 14), [compute_metrics("A", 25_000, [_sell(100)])])
    store.save_day(date(2026, 7, 14), [compute_metrics("A", 25_000, [_sell(300)])])
    recs = store.load()
    assert len(recs) == 1 and recs[0]["net_pnl"] == 300.0  # replaced, not appended


# --------------------------------------------------------------------------- #
# scoreboard metric math
# --------------------------------------------------------------------------- #


def _sell(pnl, commission=5.0):
    return Fill("X.NS", "sell", 1, 100.0, commission, datetime(2026, 7, 14, 12, 0, tzinfo=IST),
                realized_pnl=pnl)


def _cover(pnl, commission=5.0):
    return Fill("X.NS", "cover", 1, 100.0, commission, datetime(2026, 7, 14, 12, 0, tzinfo=IST),
                realized_pnl=pnl)


# --------------------------------------------------------------------------- #
# 3L hybrid twins: isolation, kill-switch covers a short, slot exception
# isolation, per-leg decomposition
# --------------------------------------------------------------------------- #


def test_twin_pair_isolated_only_hybrid_shorts():
    cfg = _cfg(roster=(StrategyRef("A", "x"), StrategyRef("A_ls", "x", allow_short=True)))
    p = _portfolio({"A": _StubDir(-1), "A_ls": _StubDir(-1)}, cfg=cfg)
    p.run_tick(_ist(10, 0))
    a = next(s for s in p.slots if s.name == "A")
    a_ls = next(s for s in p.slots if s.name == "A_ls")
    assert a.broker.open_symbols() == []                    # long-only coerces −1 → flat
    assert a_ls.broker.position("RELIANCE.NS").is_short     # hybrid twin shorts
    assert a.broker.cash != a_ls.broker.cash                # isolated accounts


def test_kill_switch_covers_a_short():
    idx = pd.date_range("2026-07-14 09:15", "2026-07-14 15:15", freq="15min", tz=IST)
    close = [1000] * len(idx)
    df = pd.DataFrame(
        {"open": close, "high": [c + 1 for c in close], "low": [c - 1 for c in close],
         "close": list(close), "volume": [1000] * len(idx)}, index=idx)
    df.iloc[3, df.columns.get_loc("close")] = 1600  # spike UP → short underwater
    src = ReplayBarSource({"RELIANCE.NS": df})
    cfg = _cfg(roster=(StrategyRef("A_ls", "x", allow_short=True), StrategyRef("B", "x")),
               per_strategy_loss_cutoff=5_000.0)
    p = Portfolio(cfg, src, notifier=TradeNotifier(LogSink()),
                  signal_engines={"A_ls": _StubDir(-1), "B": _StubDir(0)})
    p.run_tick(_ist(9, 30))   # A_ls shorts ~₹25k @ ~1000
    p.run_tick(_ist(10, 0))   # price spiked to 1600 → loss > ₹5k → retired + covered
    a = next(s for s in p.slots if s.name == "A_ls")
    assert a.halted and "kill-switch" in a.halt_reason
    assert a.broker.open_symbols() == []  # short covered on retire (invariant 2)


def test_one_slot_exception_halts_only_that_slot():
    p = _portfolio({"A": _StubDir(0), "B": _StubDir(0)})
    a = next(s for s in p.slots if s.name == "A")
    b = next(s for s in p.slots if s.name == "B")

    def _boom(now):
        raise RuntimeError("broker exploded")

    a.runner.run_tick = _boom  # a hybrid bug must not end the other arm's day
    p.run_tick(_ist(10, 0))
    assert a.halted and "internal error" in a.halt_reason
    assert not b.halted


def test_metrics_decompose_long_and_short_legs():
    m = compute_metrics("A_ls", 25_000, [_sell(100), _cover(50), _cover(-30)])
    assert m.long_pnl == pytest.approx(100.0)
    assert m.short_pnl == pytest.approx(20.0)
    assert m.net_pnl == pytest.approx(120.0)
    assert m.trades == 3                       # sells AND covers count as round-trips
    d = m.to_dict()
    assert d["long_pnl"] == pytest.approx(100.0) and d["short_pnl"] == pytest.approx(20.0)


def test_format_scoreboard_has_leg_columns():
    text = format_scoreboard([compute_metrics("A_ls", 25_000, [_cover(80)])], title="T")
    assert "long" in text and "ls" in text and "sht" in text  # pair columns (B4-2)
    assert "80" in text                                        # short-leg ₹ surfaced


def test_metrics_win_rate_and_drawdown():
    fills = [_sell(300), _sell(-100), _sell(-100), _sell(200)]
    m = compute_metrics("A", 25_000, fills)
    assert m.trades == 4
    assert m.wins == 2
    assert m.win_rate == pytest.approx(0.5)
    assert m.net_pnl == pytest.approx(300.0)
    assert m.fees == pytest.approx(20.0)
    # equity curve 300, 200, 100, 300 → peak 300, trough 100 → dd -200
    assert m.max_drawdown == pytest.approx(-200.0)
    assert m.return_pct == pytest.approx(300 / 25_000)


def test_rank_puts_halted_last_then_by_pnl():
    good = compute_metrics("good", 25_000, [_sell(500)])
    ok = compute_metrics("ok", 25_000, [_sell(100)])
    blown = compute_metrics("blown", 25_000, [_sell(1000)], halted=True, halt_reason="stop")
    order = [m.name for m in rank([ok, blown, good])]
    assert order == ["good", "ok", "blown"]  # blown last despite highest net


def test_format_scoreboard_is_telegram_html():
    text = format_scoreboard([compute_metrics("A", 25_000, [_sell(100)])], title="T")
    assert "<pre>" in text and "</pre>" in text and "A" in text


# --------------------------------------------------------------------------- #
# B4-2 — 64-slot report rework: pair-collapse, all-pairs hourly, halted always
# visible, unpaired llm handling, hard chunk cap. (Supersedes the §3P diet,
# which was sized for ~42 slots.)
# --------------------------------------------------------------------------- #


def _section(name, *, fills=(), opens=(), realized=0.0, fees=0.0, equity=25_000.0,
             cash=25_000.0, halted=False, halt_reason="", **extra):
    s = {"name": name, "fills": list(fills), "opens": list(opens),
         "realized": realized, "fees": fees, "equity": equity, "cash": cash,
         "halted": halted, "halt_reason": halt_reason}
    s.update(extra)
    return s


def test_hourly_collapses_pair_to_one_row_with_delta():
    from src.intraday.scoreboard import format_hourly_detailed

    sections = [
        _section("gap_fade", fills=[_sell(400.0)], realized=400.0),
        _section("gap_fade_ls", fills=[_cover(600.0)], realized=600.0,
                 hybrid=True, short_pnl=600.0),
    ]
    text = format_hourly_detailed(sections, hour_label="13:00")
    assert text.count("gap_fade") == 1                      # ONE row, twin collapsed in
    row = next(l for l in text.splitlines() if l.startswith("gap_fade"))
    # long 400 · ls 600 · short leg 600 · Δ = ls − long = 200
    assert "400" in row and "600" in row and "200" in row


def test_hourly_shows_all_pairs_no_idle_collapse():
    from src.intraday.scoreboard import format_hourly_detailed

    sections = [
        _section("orb"), _section("orb_ls", hybrid=True),
        _section("pullback"), _section("pullback_ls", hybrid=True),
    ]
    text = format_hourly_detailed(sections, hour_label="13:00")
    assert "orb" in text and "pullback" in text             # every pair renders
    assert "idle" not in text                               # no idle-collapse (B4-2)
    assert "2 pairs + 0 llm" in text


def test_hourly_halted_pair_always_shown_both_legs():
    from src.intraday.scoreboard import format_hourly_detailed

    sections = [
        _section("ao_stoch", realized=-10_094.0, halted=True, halt_reason="kill-switch"),
        _section("ao_stoch_ls", realized=25.0, hybrid=True, short_pnl=25.0),
        _section("orb", fills=[_sell(50.0)], realized=50.0),
        _section("orb_ls", hybrid=True),
    ]
    text = format_hourly_detailed(sections, hour_label="13:00")
    halt_line = next(l for l in text.splitlines() if l.startswith("⚠"))
    assert "ao_stoch" in halt_line and "✖" in halt_line
    assert "long" in halt_line and "ls" in halt_line       # surviving twin stays visible
    assert "25" in halt_line


def test_hourly_unpaired_llm_slot_rendered_and_flagged():
    from src.intraday.scoreboard import format_hourly_detailed

    sections = [
        _section("llm_local_a", fills=[_sell(163.0)], realized=163.0),
        _section("llm_local_b", realized=-10_050.0, halted=True, halt_reason="kill"),
        _section("orb"), _section("orb_ls", hybrid=True),
    ]
    text = format_hourly_detailed(sections, hour_label="13:00")
    llm_line = next(l for l in text.splitlines() if l.startswith("llm:"))
    assert "llm_local_a" in llm_line and "llm_local_b" in llm_line
    assert "✖" in llm_line                                  # halted llm slot flagged
    assert "1 pairs + 2 llm" in text


def test_hourly_pairs_sorted_movers_first():
    from src.intraday.scoreboard import format_hourly_detailed

    sections = [
        _section("small", fills=[_sell(10.0)], realized=10.0),
        _section("small_ls", hybrid=True),
        _section("big", fills=[_sell(-500.0)], realized=-500.0),
        _section("big_ls", hybrid=True),
    ]
    text = format_hourly_detailed(sections, hour_label="13:00")
    assert text.index("big ") < text.index("small")        # larger |net| first


def test_hourly_hard_chunk_cap_truncates_with_pointer():
    from src.intraday.scoreboard import format_hourly_detailed
    from src.intraday.notifier import split_for_telegram

    sections = []
    for i in range(400):                                    # far past a 3-chunk budget
        sections.append(_section(f"s{i}", fills=[_sell(-1.0)], realized=-9990.0 - i))
        sections.append(_section(f"s{i}_ls", hybrid=True))
    text = format_hourly_detailed(sections, hour_label="13:00")
    assert len(split_for_telegram(text)) <= 3
    assert "more pairs (log)" in text


def test_scoreboard_collapses_pairs_side_by_side():
    mets = [
        compute_metrics("orb", 25_000, [_sell(200.0)]),
        compute_metrics("orb_ls", 25_000, [_cover(90.0)]),
    ]
    text = format_scoreboard(mets, title="T")
    assert text.count("orb") == 1                           # one pair row, not two
    row = next(l for l in text.splitlines() if "orb" in l)
    assert "200" in row and "90" in row                     # long net · short leg


def test_scoreboard_halted_pair_flagged_and_ranked_last():
    mets = [
        compute_metrics("good", 25_000, [_sell(500.0)]),
        compute_metrics("good_ls", 25_000, []),
        compute_metrics("blown", 25_000, [_sell(-9000.0)], halted=True, halt_reason="kill"),
        compute_metrics("blown_ls", 25_000, []),
    ]
    text = format_scoreboard(mets, title="T")
    assert text.index("good") < text.index("blown")        # halted pair last
    blown_row = next(l for l in text.splitlines() if "blown" in l)
    assert "✖" in blown_row


def test_scoreboard_unpaired_llm_line():
    mets = [compute_metrics("llm_local_a", 25_000, [_sell(163.0)])]
    text = format_scoreboard(mets, title="T")
    assert "llm (unpaired): llm_local_a" in text


def test_scoreboard_hard_chunk_cap_truncates_with_pointer():
    from src.intraday.notifier import split_for_telegram

    mets = []
    for i in range(400):
        mets.append(compute_metrics(f"s{i}", 25_000, [_sell(-999.0 - i)]))
        mets.append(compute_metrics(f"s{i}_ls", 25_000, []))
    text = format_scoreboard(mets, title="T")
    assert len(split_for_telegram(text)) <= 3
    assert "more pairs (log)" in text


def test_scoreboard_topline_totals():
    mets = [
        compute_metrics("A", 25_000, [_sell(100.0)]),
        compute_metrics("B", 25_000, [_sell(-40.0), _sell(-10.0)]),
    ]
    text = format_scoreboard(mets, title="T")
    assert "Σ net +₹50 · fees ₹15 · trades 3 · 1 of 2 slots profitable" in text


# --------------------------------------------------------------------------- #
# 3R — per-slot roster params (local-LLM slots)
# --------------------------------------------------------------------------- #


def test_strategy_ref_params_parse_and_default():
    ref = StrategyRef.from_mapping({"name": "x", "run_dir": "y"})
    assert ref.params == {}
    ref = StrategyRef.from_mapping({
        "name": "llm_local_b", "run_dir": "builtin:llm_trader",
        "params": {"provider": "ollama", "model": "qwen3:8b"},
    })
    assert ref.params == {"provider": "ollama", "model": "qwen3:8b"}


def test_roster_params_reach_builtin_engine():
    cfg = _cfg(roster=(
        StrategyRef("llm_local_a", "builtin:llm_trader",
                    params={"provider": "ollama", "model": "qwen3:8b"}),
    ))
    p = _portfolio({}, cfg=cfg)  # nothing injected → the builtin path builds it
    eng = p.slots[0].runner._engine
    assert (eng.provider, eng.model, eng.slot_name) == ("ollama", "qwen3:8b", "llm_local_a")


# --------------------------------------------------------------------------- #
# async session loop
# --------------------------------------------------------------------------- #


def test_run_session_finalizes():
    import asyncio

    p = _portfolio({"A": _StubEngine(lambda s, df: 1), "B": _StubEngine(lambda s, df: 0)})
    times = iter([_ist(10, 0), _ist(14, 0), _ist(15, 15), _ist(15, 30)])
    mets = asyncio.run(
        p.run_session(interval_seconds=0.0, now_fn=lambda: next(times),
                      sleep_fn=_noop_sleep, max_ticks=10)
    )
    assert {m.name for m in mets} == {"A", "B"}
    assert p._finalized


async def _noop_sleep(_):
    return None


# --------------------------------------------------------------------------- #
# 3N — ride out a short Wi-Fi / data drop before a tick (up to reconnect budget)
# --------------------------------------------------------------------------- #


class _AlwaysEmpty:
    """Bar source that never returns data (simulates a sustained outage)."""

    def set_now(self, now):
        pass

    def recent_bars(self, symbol, *, lookback):
        return pd.DataFrame()


class _FlakyBars:
    """Empty for the first ``fail_n`` fetches (an outage), then a real frame."""

    def __init__(self, frame, fail_n):
        self._frame = frame
        self._fail_n = fail_n
        self.calls = 0

    def set_now(self, now):
        pass

    def recent_bars(self, symbol, *, lookback):
        self.calls += 1
        if self.calls <= self._fail_n:
            return pd.DataFrame()
        return self._frame.tail(lookback)


def test_await_data_online_does_not_wait():
    """Happy path: the canary probe succeeds → return the same now, never sleep."""
    import asyncio

    p = _portfolio({"A": _StubEngine(lambda s, df: 0), "B": _StubEngine(lambda s, df: 0)})
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    now0 = _ist(10, 0)
    result = asyncio.run(p._await_data(now0, now_fn=lambda: _ist(10, 9), sleep_fn=fake_sleep))
    assert slept == []          # online → zero waits
    assert result == now0       # now unchanged on the happy path


def test_await_data_rides_out_outage_then_resumes():
    """An outage lasting a few probes is ridden out, then the tick gets real data."""
    import asyncio

    p = _portfolio({"A": _StubEngine(lambda s, df: 0), "B": _StubEngine(lambda s, df: 0)}, cfg=_cfg(reconnect_budget_seconds=100.0))
    p._reconnect_budget_s = 100.0
    p._bars = _FlakyBars(_frame(1000), fail_n=2)  # probes 1-2 fail, probe 3 ok
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    result = asyncio.run(
        p._await_data(_ist(10, 0), now_fn=lambda: _ist(10, 5), sleep_fn=fake_sleep)
    )
    assert len(slept) == 2                 # two backoffs (5s, 10s) before recovery
    assert p._bars.calls == 3              # probe, probe, probe-ok
    assert result == _ist(10, 5)           # now refreshed to real wall-clock after the wait


def test_await_data_gives_up_after_budget_and_proceeds():
    """A drop longer than the budget stops waiting (bounded) and returns to hold."""
    import asyncio

    p = _portfolio({"A": _StubEngine(lambda s, df: 0), "B": _StubEngine(lambda s, df: 0)}, cfg=_cfg(reconnect_budget_seconds=60.0))
    p._reconnect_budget_s = 60.0
    p._bars = _AlwaysEmpty()
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    result = asyncio.run(
        p._await_data(_ist(10, 0), now_fn=lambda: _ist(10, 1), sleep_fn=fake_sleep)
    )
    assert slept                                   # it did wait
    assert sum(slept) <= 60.0 + 1e-9               # never sleeps past the budget
    assert result == _ist(10, 1)                   # proceeds with a fresh now


def test_reconnect_budget_zero_disables_wait():
    """budget 0 → fall straight through to today's empty-frame hold (no waiting)."""
    import asyncio

    p = _portfolio({"A": _StubEngine(lambda s, df: 0), "B": _StubEngine(lambda s, df: 0)}, cfg=_cfg(reconnect_budget_seconds=0.0))
    p._bars = _AlwaysEmpty()
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    now0 = _ist(10, 0)
    result = asyncio.run(p._await_data(now0, now_fn=lambda: _ist(10, 1), sleep_fn=fake_sleep))
    assert slept == []
    assert result == now0
