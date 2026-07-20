"""Offline tests for the 3L short-capable paper broker + runner (hybrid twins).

Covers the PaperBroker short/cover accounting identities (the spec is the
identities, docs/IMPLEMENTATION_PLAN.md §3L), one-direction-per-symbol, slippage
directions, the STT-on-entry / stamp-on-cover legs, and the runner's −1 → short
entry, direction flips, cap across both directions, long-only coercion, and the
15:15 force-cover with and without a last price (invariant 2). No live services.

Run:  cd vibe-trading/agent && set PYTHONPATH=. && \
      python -m pytest tests/test_intraday_shorts.py -q
"""

from __future__ import annotations

import datetime as dt
from datetime import datetime

import pandas as pd
import pytest

from backtest.engines.india_intraday import IndiaIntradayEngine
from src.intraday.bars import ReplayBarSource
from src.intraday.clock import IST
from src.intraday.config import IntradayConfig, Instrument
from src.intraday.notifier import LogSink, TradeNotifier
from src.intraday.paper_broker import PaperBroker
from src.intraday.runner import IntradayPaperRunner


def _broker(cash: float = 100_000.0, *, slippage: float = 0.0) -> PaperBroker:
    engine = IndiaIntradayEngine({"slippage": slippage, "allow_short": True})
    return PaperBroker(cash, engine=engine)


def _ist(hh, mm):
    return datetime(2026, 7, 16, hh, mm, tzinfo=IST)


# --------------------------------------------------------------------------- #
# broker — short accounting identities
# --------------------------------------------------------------------------- #


def test_short_entry_reserves_notional_plus_commission():
    b = _broker(cash=100_000, slippage=0.0)
    f = b.short("X.NS", 1000.0, cash_budget=50_000)
    assert f is not None and f.side == "short"
    reserve = f.qty * f.price + f.commission
    assert b.cash == pytest.approx(100_000 - reserve)
    assert f.cash_after == pytest.approx(b.cash)
    assert b.position("X.NS").is_short


def test_short_cover_roundtrip_at_one_price_is_minus_commissions():
    b = _broker(slippage=0.0)
    f_short = b.short("X.NS", 1000.0, cash_budget=50_000)
    f_cover = b.cover("X.NS", 1000.0)
    assert f_cover is not None and f_cover.side == "cover"
    # Zero slippage, same price → realized is exactly −(entry_comm + cover_comm).
    assert f_cover.realized_pnl == pytest.approx(-(f_short.commission + f_cover.commission))
    assert b.realized_pnl == pytest.approx(f_cover.realized_pnl)
    assert not b.position("X.NS").is_open


def test_short_pnl_positive_when_price_falls():
    b = _broker(slippage=0.0)
    b.short("X.NS", 1000.0, cash_budget=50_000)
    f = b.cover("X.NS", 900.0)
    assert f.realized_pnl > 0  # bought back cheaper


def test_short_equity_drops_by_commission_at_entry_zero_slippage():
    b = _broker(cash=100_000, slippage=0.0)
    f = b.short("X.NS", 1000.0, cash_budget=50_000)
    # mark == fill (zero slippage) → equity drops by exactly the entry commission.
    assert b.equity({"X.NS": 1000.0}) == pytest.approx(100_000 - f.commission)


def test_short_equity_continuity_includes_slippage():
    ref = 1000.0
    b = _broker(cash=100_000, slippage=0.001)
    f = b.short("X.NS", ref, cash_budget=50_000)
    slippage_cost = (ref - f.price) * f.qty  # a sell fills under ref
    assert b.equity({"X.NS": ref}) == pytest.approx(100_000 - f.commission - slippage_cost)


def test_short_equity_gains_as_price_falls():
    b = _broker(slippage=0.0)
    f = b.short("X.NS", 1000.0, cash_budget=50_000)
    flat = b.equity({"X.NS": 1000.0})
    down = b.equity({"X.NS": 900.0})
    assert down - flat == pytest.approx(100.0 * f.qty)


def test_short_and_cover_slippage_directions():
    b = _broker(slippage=0.001)
    f_short = b.short("X.NS", 1000.0, cash_budget=50_000)
    assert f_short.price < 1000.0  # a sell (short) fills under
    f_cover = b.cover("X.NS", 1000.0)
    assert f_cover.price > 1000.0  # a buy (cover) fills over


def test_short_leg_pays_stt_cover_leg_pays_stamp():
    b = _broker(slippage=0.0)
    f_short = b.short("X.NS", 1000.0, cash_budget=50_000)
    f_cover = b.cover("X.NS", 1000.0)
    # Same notional both legs (zero slippage): the only difference is the
    # sell-leg STT (0.025%) on entry vs the buy-leg stamp (0.003%) on cover.
    notional = f_short.qty * 1000.0
    assert f_short.commission - f_cover.commission == pytest.approx(
        notional * (0.00025 - 0.00003), rel=1e-6
    )


def test_reserve_never_exceeds_budget():
    b = _broker(slippage=0.0005)
    f = b.short("X.NS", 987.6, cash_budget=6_250)
    reserve = f.qty * f.price + f.commission
    assert reserve <= 6_250 + 1e-6


def test_cover_clamps_to_holding_never_flips_long():
    b = _broker(slippage=0.0)
    b.short("X.NS", 1000.0, cash_budget=20_000)
    held = b.position("X.NS").qty
    f = b.cover("X.NS", 1000.0, qty=held * 5)  # ask to over-cover
    assert f.qty == held
    assert b.position("X.NS").qty == 0  # flat, not long


def test_sell_still_never_flips_short():
    b = _broker(slippage=0.0)
    b.buy("X.NS", 1000.0, cash_budget=20_000)
    held = b.position("X.NS").qty
    f = b.sell("X.NS", 1000.0, qty=held * 5)
    assert f.qty == held
    assert b.position("X.NS").qty == 0


def test_buy_refuses_while_short_open():
    b = _broker(slippage=0.0)
    b.short("X.NS", 1000.0, cash_budget=20_000)
    assert b.buy("X.NS", 1000.0, cash_budget=20_000) is None  # invariant 6


def test_short_refuses_while_long_open():
    b = _broker(slippage=0.0)
    b.buy("X.NS", 1000.0, cash_budget=20_000)
    assert b.short("X.NS", 1000.0, cash_budget=20_000) is None  # invariant 6


def test_sell_returns_none_on_a_short_position():
    b = _broker(slippage=0.0)
    b.short("X.NS", 1000.0, cash_budget=20_000)
    assert b.sell("X.NS", 1000.0) is None  # a short is closed with cover, not sell


def test_cover_returns_none_on_a_long_position():
    b = _broker(slippage=0.0)
    b.buy("X.NS", 1000.0, cash_budget=20_000)
    assert b.cover("X.NS", 1000.0) is None


def test_close_position_covers_short_and_sells_long():
    b = _broker(slippage=0.0)
    b.short("A.NS", 1000.0, cash_budget=20_000)
    assert b.close_position("A.NS", 1000.0).side == "cover"
    b.buy("B.NS", 500.0, cash_budget=20_000)
    assert b.close_position("B.NS", 500.0).side == "sell"


def test_close_position_no_price_fallback_covers_at_reference():
    b = _broker(slippage=0.0)
    b.short("X.NS", 1000.0, cash_budget=20_000)
    ref = b.position("X.NS").avg_price
    f = b.close_position("X.NS", ref)  # runner passes avg_price when no live price
    assert f is not None and f.side == "cover"
    assert not b.position("X.NS").is_open


# --------------------------------------------------------------------------- #
# runner — signal −1 → short, flips, cap, coercion, force-cover
# --------------------------------------------------------------------------- #


class _DirEngine:
    """Signal engine returning a fixed direction (−1/0/1) per symbol."""

    def __init__(self, fn):
        self._fn = fn  # callable(sym, df) -> -1/0/1

    def generate(self, data_map):
        return {
            s: pd.Series([self._fn(s, df)] * len(df), index=df.index)
            for s, df in data_map.items()
        }


class _EmptySource:
    """Bar source that always returns no bars (simulates a missing live price)."""

    def set_now(self, now):
        pass

    def recent_bars(self, symbol, lookback=1):
        return pd.DataFrame()


def _session_frame(base):
    idx = pd.date_range("2026-07-16 09:15", "2026-07-16 15:15", freq="15min", tz=IST)
    close = [base + i for i in range(len(idx))]
    return pd.DataFrame(
        {"open": close, "high": [c + 1 for c in close], "low": [c - 1 for c in close],
         "close": close, "volume": [1000] * len(idx)},
        index=idx,
    )


def _runner(engine, *, allow_short, max_positions=2, cash=50_000):
    cfg = IntradayConfig(
        universe=(Instrument("RELIANCE.NS"), Instrument("SBIN.NS")),
        initial_cash=cash,
        max_positions=max_positions,
    )
    frames = {"RELIANCE.NS": _session_frame(1000), "SBIN.NS": _session_frame(500)}
    return IntradayPaperRunner(
        cfg, ReplayBarSource(frames), TradeNotifier(LogSink()),
        signal_engine=engine, allow_short=allow_short,
    )


def test_runner_opens_short_on_minus_one():
    r = _runner(_DirEngine(lambda s, df: -1 if s == "RELIANCE.NS" else 0), allow_short=True)
    fills = r.run_tick(_ist(10, 0))
    assert len(fills) == 1 and fills[0].side == "short"
    assert r.broker.position("RELIANCE.NS").is_short


def test_long_only_runner_coerces_minus_one_to_flat():
    r = _runner(_DirEngine(lambda s, df: -1), allow_short=False)
    assert r.run_tick(_ist(10, 0)) == []
    assert not r.broker.open_symbols()


def test_direction_flip_closes_then_opens_same_tick():
    state = {"dir": 1}
    r = _runner(_DirEngine(lambda s, df: state["dir"] if s == "RELIANCE.NS" else 0),
                allow_short=True)
    r.run_tick(_ist(10, 0))  # open long
    assert r.broker.position("RELIANCE.NS").direction == 1
    state["dir"] = -1
    fills = r.run_tick(_ist(11, 0))  # flip long → short in one tick
    sides = [f.side for f in fills]
    assert "sell" in sides and "short" in sides
    assert r.broker.position("RELIANCE.NS").is_short


def test_cap_respected_across_both_directions():
    # Want long RELIANCE and short SBIN, but only one slot.
    r = _runner(_DirEngine(lambda s, df: 1 if s == "RELIANCE.NS" else -1),
                allow_short=True, max_positions=1)
    fills = r.run_tick(_ist(10, 0))
    assert len(fills) == 1
    assert len(r.broker.open_symbols()) == 1


def test_force_cover_at_squareoff_with_price():
    r = _runner(_DirEngine(lambda s, df: -1 if s == "RELIANCE.NS" else 0), allow_short=True)
    r.run_tick(_ist(10, 0))
    assert r.broker.position("RELIANCE.NS").is_short
    fills = r.run_tick(_ist(15, 15))
    assert len(fills) == 1 and fills[0].side == "cover"
    assert not r.broker.open_symbols() and r.state.squared_off


def test_force_cover_at_squareoff_without_price():
    r = _runner(_DirEngine(lambda s, df: -1 if s == "RELIANCE.NS" else 0), allow_short=True)
    r.run_tick(_ist(10, 0))
    assert r.broker.position("RELIANCE.NS").is_short
    r._bars = _EmptySource()  # no live price at square-off → avg_price fallback
    fills = r.run_tick(_ist(15, 15))
    assert len(fills) == 1 and fills[0].side == "cover"
    assert not r.broker.open_symbols()  # covered authoritatively (invariant 2)
