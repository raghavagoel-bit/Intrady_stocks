"""Tests for IndiaIntradayEngine (NSE / BSE MIS) market rules.

Validates the ways the intraday engine differs from the delivery engine:
  - Long-only by default; short entries rejected unless config opts in via
    allow_short (the 3L hybrid A/B, paper only)
  - Same-day exits allowed (no T+1 block)
  - Circuit bands still enforced (upper blocks buy, lower blocks sell/close)
  - MIS cost stack: STT sell-only, stamp buy-only, capped brokerage, no DP charge
  - Engine routing: intraday flag selects IndiaIntradayEngine, else delivery
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.engines.india_equity import IndiaEquityEngine
from backtest.engines.india_intraday import IndiaIntradayEngine
from backtest.models import Position


def _engine(**overrides) -> IndiaIntradayEngine:
    config = {"initial_cash": 1_000_000, "intraday": True}
    config.update(overrides)
    return IndiaIntradayEngine(config)


def _bar(close: float = 100.0, pre_close: float | None = None) -> pd.Series:
    data = {"close": close, "open": close}
    if pre_close is not None:
        data["pre_close"] = pre_close
    return pd.Series(data)


def _charges_block(engine: IndiaIntradayEngine, notional: float) -> float:
    """Leg-independent charges: capped brokerage + exchange + SEBI + 18% GST."""
    brokerage = min(engine.in_brokerage_cap, notional * engine.in_brokerage)
    exchange = notional * engine.in_exchange_txn
    sebi = notional * engine.in_sebi_fee
    gst = (brokerage + exchange + sebi) * engine.in_gst
    return brokerage + exchange + sebi + gst


# ---------------------------------------------------------------------------
# can_execute: long-only, same-day exit, circuit bands
# ---------------------------------------------------------------------------


class TestCanExecute:
    def test_long_allowed(self) -> None:
        assert _engine().can_execute("RELIANCE.NS", 1, _bar()) is True

    def test_short_always_blocked(self) -> None:
        assert _engine().can_execute("RELIANCE.NS", -1, _bar()) is False

    def test_short_permitted_when_allow_short_opted_in(self) -> None:
        # 3L: the hybrid A/B (paper only) opts in via config. Default stays
        # long-only (test_short_always_blocked); with the flag a short entry is
        # permitted, and — being a sell — is blocked only at the lower circuit.
        engine = _engine(allow_short=True)
        assert engine.allow_short is True
        assert engine.can_execute("RELIANCE.NS", -1, _bar()) is True
        # Lower circuit (−20% vs pre_close) blocks the short entry (a sell).
        assert engine.can_execute("RELIANCE.NS", -1, _bar(close=80.0, pre_close=100.0)) is False
        # Upper circuit does NOT block a short entry (only blocks buys).
        assert engine.can_execute("RELIANCE.NS", -1, _bar(close=120.0, pre_close=100.0)) is True

    def test_same_bar_sell_allowed(self) -> None:
        # The defining intraday behaviour: the delivery T+1 block is gone.
        engine = _engine()
        ts = pd.Timestamp("2024-04-01 10:00")
        engine.positions["RELIANCE.NS"] = Position(
            symbol="RELIANCE.NS", direction=1, size=10, entry_price=100.0, entry_time=ts,
        )
        bar = _bar()
        bar.name = ts  # same bar-date as entry -> delivery would block; MIS allows
        assert engine.can_execute("RELIANCE.NS", 0, bar) is True

    def test_upper_circuit_blocks_buy(self) -> None:
        engine = _engine(price_limit=0.20)
        bar = _bar(close=120.0, pre_close=100.0)  # +20%
        assert engine.can_execute("RELIANCE.NS", 1, bar) is False

    def test_lower_circuit_blocks_sell(self) -> None:
        engine = _engine(price_limit=0.20)
        bar = _bar(close=80.0, pre_close=100.0)  # -20%
        assert engine.can_execute("RELIANCE.NS", 0, bar) is False

    def test_circuit_disabled_allows_trade_at_limit(self) -> None:
        engine = _engine(price_limit=0)
        bar = _bar(close=120.0, pre_close=100.0)
        assert engine.can_execute("RELIANCE.NS", 1, bar) is True


# ---------------------------------------------------------------------------
# calc_commission: India MIS stack
# ---------------------------------------------------------------------------


class TestCommission:
    def test_nonzero_cost(self) -> None:
        assert _engine().calc_commission(100, 1000.0, 1, is_open=True) > 0

    def test_stt_on_sell_leg_only(self) -> None:
        engine = _engine()
        notional = 100 * 1000.0
        # Long: buy = is_open True (no STT), sell = is_open False (STT charged).
        sell = engine.calc_commission(100, 1000.0, 1, is_open=False)
        assert sell - _charges_block(engine, notional) == pytest.approx(
            notional * engine.in_stt, abs=1e-6
        )

    def test_stamp_on_buy_leg_only(self) -> None:
        engine = _engine()
        notional = 100 * 1000.0
        buy = engine.calc_commission(100, 1000.0, 1, is_open=True)
        assert buy - _charges_block(engine, notional) == pytest.approx(
            notional * engine.in_stamp_duty, abs=1e-6
        )

    def test_brokerage_capped_at_20(self) -> None:
        # 0.03% of a ₹10L order = ₹300 -> uncapped, but the ₹20 cap binds.
        engine = _engine()
        notional = 1000 * 1000.0  # ₹10,00,000
        assert notional * engine.in_brokerage > engine.in_brokerage_cap
        comm = engine.calc_commission(1000, 1000.0, 1, is_open=True)
        expected = _charges_block(engine, notional) + notional * engine.in_stamp_duty
        # _charges_block applies the cap, so matching it proves the cap is applied.
        assert comm == pytest.approx(expected, abs=1e-6)

    def test_no_dp_charge(self) -> None:
        # Delivery charges a flat DP fee on sells; MIS does not.
        engine = _engine()
        notional = 100 * 1000.0
        sell = engine.calc_commission(100, 1000.0, 1, is_open=False)
        expected = _charges_block(engine, notional) + notional * engine.in_stt
        assert sell == pytest.approx(expected, abs=1e-6)

    def test_cheaper_than_delivery_roundtrip(self) -> None:
        # MIS should be materially cheaper than delivery for the same round trip
        # (STT 0.025% sell-only vs 0.1% both sides, lower stamp, no DP).
        mis = _engine()
        delivery = IndiaEquityEngine({"initial_cash": 1_000_000})
        size, price = 100, 1000.0
        mis_rt = (
            mis.calc_commission(size, price, 1, is_open=True)
            + mis.calc_commission(size, price, 1, is_open=False)
        )
        del_rt = (
            delivery.calc_commission(size, price, 1, is_open=True)
            + delivery.calc_commission(size, price, 1, is_open=False)
        )
        assert mis_rt < del_rt


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


class TestIntradayRoundTripExecution:
    """End-to-end: the execution loop must open AND close a long the same day."""

    @staticmethod
    def _intraday_frame(days: int = 2) -> pd.DataFrame:
        frames = []
        day = pd.Timestamp("2026-06-01")
        price = 100.0
        for _ in range(days):
            while day.dayofweek >= 5:
                day += pd.Timedelta(days=1)
            idx = pd.date_range(
                day + pd.Timedelta(hours=9, minutes=15), periods=25, freq="15min"
            )
            rows = []
            for k in range(25):
                price += 0.5 if k < 18 else -0.3  # rise into midday, drift down
                rows.append([price, price + 0.4, price - 0.4, price, 10_000.0])
            frames.append(pd.DataFrame(
                rows, columns=["open", "high", "low", "close", "volume"], index=idx
            ))
            day += pd.Timedelta(days=1)
        return pd.concat(frames)

    def _signal(self, df: pd.DataFrame) -> pd.Series:
        """Long from 10:00, flat from 15:00 — the strategy-level square-off.

        The flat is emitted at 15:00 (one bar before the 15:15 close) because the
        engine fills on the NEXT bar's open: a 15:00 flat executes at 15:15, same
        day. Flattening only at 15:15 would execute at next day's 09:15 (a carry).
        """
        import datetime as dt

        sig = pd.Series(0, index=df.index)
        t = df.index.time
        hold = (t >= dt.time(10, 0)) & (t < dt.time(15, 0))
        sig[hold] = 1
        return sig

    def test_same_day_round_trip_is_recorded(self) -> None:
        from backtest.engines.base import _align

        code = "RELIANCE.NS"
        df = self._intraday_frame(days=2)
        data_map = {code: df}
        signal_map = {code: self._signal(df)}

        dates, close_df, target_pos, _ = _align(data_map, signal_map, [code])
        engine = _engine()
        engine._execute_bars(dates, data_map, close_df, target_pos, [code])

        assert engine.trades, "expected at least one intraday trade"
        for t in engine.trades:
            assert t.direction == 1, "long-only: every trade must be a long"
            # The defining property: entry and exit fall on the SAME calendar day
            # (a delivery T+1 engine could never close these).
            assert t.entry_time.date() == t.exit_time.date(), (
                f"expected same-day exit, got {t.entry_time} -> {t.exit_time}"
            )


class TestRouting:
    def test_intraday_flag_selects_intraday_engine(self) -> None:
        from backtest.runner import _create_market_engine

        engine = _create_market_engine(
            "yahoo", {"initial_cash": 100_000, "intraday": True}, ["RELIANCE.NS"]
        )
        assert isinstance(engine, IndiaIntradayEngine)

    def test_no_flag_selects_delivery_engine(self) -> None:
        from backtest.runner import _create_market_engine

        engine = _create_market_engine(
            "yahoo", {"initial_cash": 100_000}, ["RELIANCE.NS"]
        )
        assert isinstance(engine, IndiaEquityEngine)
        assert not isinstance(engine, IndiaIntradayEngine)
