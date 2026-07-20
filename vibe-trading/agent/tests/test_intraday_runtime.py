"""Offline unit tests for the intraday paper runtime (M1, docs 3C/3D).

No live Dhan / Gemini / Telegram: every external edge is a stub or a replay
source. Covers config placeholder resolution, the long-only MIS paper broker,
the trade notifier + sink selection, the IST session clock, the Dhan bar source
(security_id wiring / non-ok handling), the Gemini stub jobs, and the runner's
per-tick signal→fill→square-off behavior end-to-end.

Run:  cd vibe-trading/agent && set PYTHONPATH=. && \
      python -m pytest tests/test_intraday_runtime.py -q
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from src.intraday.bars import DhanBarSource, ReplayBarSource
from src.intraday.clock import IST, SessionClock
from src.intraday.config import IntradayConfig, Instrument, is_placeholder
from src.intraday.gemini_jobs import eod_review, make_llm_caller, premarket_watchlist
from src.intraday.notifier import LogSink, TradeNotifier, build_sink
from src.intraday.paper_broker import PaperBroker
from src.intraday.runner import IntradayPaperRunner


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #


def test_placeholder_detection():
    assert is_placeholder("")
    assert is_placeholder(None)
    assert is_placeholder("PLACEHOLDER-GEMINI-API-KEY")
    assert is_placeholder("your-token")
    assert is_placeholder("<dhan-id>")
    assert not is_placeholder("1234567:realtoken")


def test_config_defaults_are_placeholders():
    cfg = IntradayConfig()
    assert not cfg.is_telegram_configured
    assert not cfg.is_gemini_configured
    assert not cfg.is_dhan_configured
    assert cfg.position_cap == 3  # defaults to len(universe)
    # redacted() must never leak a real-looking secret and must be log-safe.
    red = cfg.redacted()
    assert red["telegram"] == "‹placeholder›"
    assert "PLACEHOLDER" not in str(red)


def test_config_env_overlay_activates_creds():
    env = {
        "TELEGRAM_BOT_TOKEN": "111:realbot",
        "TELEGRAM_CHAT_ID": "-1000123",
        "GEMINI_API_KEY": "AIza-real",
        "VIBE_INTRADAY_INITIAL_CASH": "25000",
        "VIBE_INTRADAY_MAX_POSITIONS": "2",
    }
    cfg = IntradayConfig.load(json_path="___does_not_exist___.json", env=env)
    assert cfg.is_telegram_configured
    assert cfg.is_gemini_configured
    assert cfg.initial_cash == 25000
    assert cfg.position_cap == 2


def test_instrument_segment_inferred_from_suffix():
    assert Instrument.from_mapping({"symbol": "TCS.BO"}).exchange_segment == "BSE_EQ"
    assert Instrument.from_mapping({"symbol": "TCS.NS"}).exchange_segment == "NSE_EQ"


# --------------------------------------------------------------------------- #
# paper broker — long-only MIS
# --------------------------------------------------------------------------- #


def test_buy_then_sell_books_costs_and_pnl():
    b = PaperBroker(50_000)
    buy = b.buy("RELIANCE.NS", 1000.0, cash_budget=50_000)
    assert buy is not None and buy.side == "buy"
    assert buy.qty > 0
    assert buy.commission > 0            # stamp + brokerage + gst on the buy leg
    assert b.cash < 50_000               # cash deployed
    # Sell higher → positive realized P&L, net of both legs' costs.
    sell = b.sell("RELIANCE.NS", 1100.0)
    assert sell is not None and sell.side == "sell"
    assert sell.qty == buy.qty
    assert sell.realized_pnl > 0
    assert not b.position("RELIANCE.NS").is_open
    assert b.realized_pnl == pytest.approx(sell.realized_pnl)


def test_sell_is_clamped_never_goes_short():
    b = PaperBroker(50_000)
    b.buy("SBIN.NS", 500.0, cash_budget=10_000)
    held = b.position("SBIN.NS").qty
    fill = b.sell("SBIN.NS", 505.0, qty=held * 5)  # ask to oversell
    assert fill.qty == held                        # clamped to holding
    assert b.position("SBIN.NS").qty == 0          # flat, not short


def test_sell_with_no_position_returns_none():
    assert PaperBroker(10_000).sell("X.NS", 100.0) is None


def test_buy_rejected_when_unaffordable():
    b = PaperBroker(50)  # ₹50 can't buy a ₹1000 share
    assert b.buy("RELIANCE.NS", 1000.0, cash_budget=50) is None


# --------------------------------------------------------------------------- #
# notifier + sinks
# --------------------------------------------------------------------------- #


def test_build_sink_is_log_when_not_configured():
    assert isinstance(build_sink(IntradayConfig()), LogSink)


def test_build_sink_is_telegram_when_configured():
    from src.intraday.notifier import TelegramSink

    cfg = IntradayConfig.load(
        json_path="___none___.json",
        env={"TELEGRAM_BOT_TOKEN": "1:real", "TELEGRAM_CHAT_ID": "42"},
    )
    assert isinstance(build_sink(cfg), TelegramSink)


def test_notifier_emits_events_to_log_sink():
    sink = LogSink()
    n = TradeNotifier(sink, mode="PAPER")
    b = PaperBroker(50_000)
    buy = b.buy("RELIANCE.NS", 1000.0, cash_budget=20_000)
    n.entry(buy, running_pnl=0.0)
    sell = b.sell("RELIANCE.NS", 1050.0)
    n.exit(sell, running_pnl=b.realized_pnl)
    n.halt("token expired")
    assert len(sink.messages) == 3
    assert "ENTRY" in sink.messages[0] and "PAPER" in sink.messages[0]
    assert "EXIT" in sink.messages[1]
    assert "HALT" in sink.messages[2]


def test_notifier_swallows_sink_failure():
    class Boom:
        def send(self, text):
            raise RuntimeError("network down")

    n = TradeNotifier(Boom())
    n.halt("should not raise")  # must not propagate


# --------------------------------------------------------------------------- #
# clock
# --------------------------------------------------------------------------- #


def _ist(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def test_session_clock_windows():
    clk = SessionClock.from_config(IntradayConfig())
    # 2026-07-14 is a Tuesday.
    assert clk.is_open(_ist(2026, 7, 14, 9, 30))
    assert not clk.is_open(_ist(2026, 7, 14, 8, 0))   # pre-open
    assert not clk.is_open(_ist(2026, 7, 18, 11, 0))  # Saturday
    assert not clk.is_past_squareoff(_ist(2026, 7, 14, 15, 0))
    assert clk.is_past_squareoff(_ist(2026, 7, 14, 15, 15))
    assert clk.is_after_close(_ist(2026, 7, 14, 15, 30))


# --------------------------------------------------------------------------- #
# dhan bar source (3C)
# --------------------------------------------------------------------------- #


class _FakeDhanSdk:
    def __init__(self, envelope):
        self.envelope = envelope
        self.calls = []

    def get_historical_bars(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        return self.envelope


def test_dhan_source_passes_security_id_and_parses():
    envelope = {
        "status": "ok",
        "bars": [
            {"time": 1_700_000_000, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
            {"time": 1_700_000_900, "open": 10.5, "high": 12, "low": 10, "close": 11.5, "volume": 120},
        ],
    }
    sdk = _FakeDhanSdk(envelope)
    inst = Instrument("RELIANCE.NS", security_id="2885", exchange_segment="NSE_EQ")
    src = DhanBarSource({"RELIANCE.NS": inst}, interval="15m", sdk=sdk)
    frame = src.recent_bars("RELIANCE.NS", lookback=10)
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert len(frame) == 2
    assert str(frame.index.tz) == "Asia/Kolkata"
    # security_id was threaded through, NOT the bare ticker (the 3C fix).
    _, kwargs = sdk.calls[0]
    assert kwargs["security_id"] == "2885"
    assert kwargs["period"] == "15m"


def test_dhan_source_skips_symbol_without_security_id():
    sdk = _FakeDhanSdk({"status": "ok", "bars": []})
    inst = Instrument("SBIN.NS")  # placeholder/empty security_id
    src = DhanBarSource({"SBIN.NS": inst}, sdk=sdk)
    assert src.recent_bars("SBIN.NS", lookback=5).empty
    assert sdk.calls == []  # never even called Dhan


def test_dhan_source_handles_non_ok_envelope():
    sdk = _FakeDhanSdk({"status": "error", "error": "bad token"})
    inst = Instrument("RELIANCE.NS", security_id="2885")
    src = DhanBarSource({"RELIANCE.NS": inst}, sdk=sdk)
    assert src.recent_bars("RELIANCE.NS", lookback=5).empty


# --------------------------------------------------------------------------- #
# gemini jobs (stub)
# --------------------------------------------------------------------------- #


def test_gemini_caller_is_stub_when_unconfigured():
    cfg = IntradayConfig()
    call = make_llm_caller(cfg)
    text = premarket_watchlist(cfg, call)
    assert text.startswith("[stub")
    assert "RELIANCE.NS" in text


def test_eod_review_stub_over_fills():
    cfg = IntradayConfig()
    b = PaperBroker(50_000)
    b.buy("RELIANCE.NS", 1000.0, cash_budget=20_000)
    sell = b.sell("RELIANCE.NS", 1010.0)
    text = eod_review(cfg, make_llm_caller(cfg), [sell], realized_pnl=b.realized_pnl)
    assert isinstance(text, str) and text


# --------------------------------------------------------------------------- #
# runner — end-to-end with a stub signal engine + replay bars
# --------------------------------------------------------------------------- #


class _StubEngine:
    """Signal engine driven by a per-symbol schedule keyed on the last bar's minute.

    Returns 1 (long) for the window we choose, then 0, so the runner opens then
    exits deterministically without depending on a real strategy's math.
    """

    def __init__(self, long_when):
        self.long_when = long_when  # callable(df) -> 0/1 for the LAST bar

    def generate(self, data_map):
        out = {}
        for sym, df in data_map.items():
            val = self.long_when(sym, df)
            out[sym] = pd.Series([val] * len(df), index=df.index)
        return out


def _session_frame(symbol_base_price):
    """Build a one-day 15m frame from 09:15 to 15:15 IST at a flat-ish price."""
    idx = pd.date_range("2026-07-14 09:15", "2026-07-14 15:15", freq="15min", tz=IST)
    n = len(idx)
    close = [symbol_base_price + i for i in range(n)]  # gently rising
    return pd.DataFrame(
        {
            "open": close,
            "high": [c + 1 for c in close],
            "low": [c - 1 for c in close],
            "close": close,
            "volume": [1000] * n,
        },
        index=idx,
    )


def _runner_with(engine, cash=50_000):
    cfg = IntradayConfig(
        universe=(Instrument("RELIANCE.NS"), Instrument("SBIN.NS")),
        initial_cash=cash,
        max_positions=2,
    )
    frames = {
        "RELIANCE.NS": _session_frame(1000),
        "SBIN.NS": _session_frame(500),
    }
    src = ReplayBarSource(frames)
    notifier = TradeNotifier(LogSink())
    runner = IntradayPaperRunner(cfg, src, notifier, signal_engine=engine)
    return runner


def test_runner_opens_long_on_signal():
    # Long only for RELIANCE, always flat for SBIN.
    engine = _StubEngine(lambda sym, df: 1 if sym == "RELIANCE.NS" else 0)
    runner = _runner_with(engine)
    fills = runner.run_tick(_ist(2026, 7, 14, 10, 0))
    assert len(fills) == 1
    assert fills[0].side == "buy" and fills[0].symbol == "RELIANCE.NS"
    assert runner.broker.position("RELIANCE.NS").is_open


def test_runner_exits_when_signal_drops():
    state = {"long": True}
    engine = _StubEngine(lambda sym, df: 1 if (sym == "RELIANCE.NS" and state["long"]) else 0)
    runner = _runner_with(engine)
    runner.run_tick(_ist(2026, 7, 14, 10, 0))    # opens
    assert runner.broker.position("RELIANCE.NS").is_open
    state["long"] = False
    fills = runner.run_tick(_ist(2026, 7, 14, 11, 0))  # strategy flat → exit
    assert len(fills) == 1 and fills[0].side == "sell"
    assert not runner.broker.position("RELIANCE.NS").is_open


def test_runner_force_flattens_at_squareoff():
    engine = _StubEngine(lambda sym, df: 1 if sym == "RELIANCE.NS" else 0)
    runner = _runner_with(engine)
    runner.run_tick(_ist(2026, 7, 14, 10, 0))            # open a long
    assert runner.broker.position("RELIANCE.NS").is_open
    fills = runner.run_tick(_ist(2026, 7, 14, 15, 15))   # square-off cutoff
    assert len(fills) == 1 and fills[0].side == "sell"
    assert not runner.broker.position("RELIANCE.NS").is_open
    assert runner.state.squared_off
    # Square-off is idempotent — a later tick books nothing more.
    assert runner.run_tick(_ist(2026, 7, 14, 15, 20)) == []


def test_runner_respects_position_cap():
    engine = _StubEngine(lambda sym, df: 1)  # want long on BOTH symbols
    cfg = IntradayConfig(
        universe=(Instrument("RELIANCE.NS"), Instrument("SBIN.NS")),
        initial_cash=50_000,
        max_positions=1,  # only one slot
    )
    frames = {"RELIANCE.NS": _session_frame(1000), "SBIN.NS": _session_frame(500)}
    runner = IntradayPaperRunner(cfg, ReplayBarSource(frames), TradeNotifier(LogSink()), signal_engine=engine)
    fills = runner.run_tick(_ist(2026, 7, 14, 10, 0))
    assert len(fills) == 1  # capped at one open position
    assert len(runner.broker.open_symbols()) == 1


def test_runner_noops_outside_session():
    engine = _StubEngine(lambda sym, df: 1)
    runner = _runner_with(engine)
    assert runner.run_tick(_ist(2026, 7, 14, 8, 0)) == []  # pre-open
    assert not runner.broker.open_symbols()


def test_runner_halts_on_engine_error():
    class _Boom:
        def generate(self, data_map):
            raise ValueError("bad indicator")

    runner = _runner_with(_Boom())
    runner.run_tick(_ist(2026, 7, 14, 10, 0))
    assert runner.state.halted
    assert runner.run_tick(_ist(2026, 7, 14, 10, 15)) == []  # stays halted


def test_run_session_loop_drives_to_squareoff():
    import asyncio

    engine = _StubEngine(lambda sym, df: 1 if sym == "RELIANCE.NS" else 0)
    runner = _runner_with(engine)
    times = iter(
        [
            _ist(2026, 7, 14, 10, 0),
            _ist(2026, 7, 14, 14, 0),
            _ist(2026, 7, 14, 15, 15),  # square-off
            _ist(2026, 7, 14, 15, 30),  # after close → loop ends
        ]
    )

    async def _sleep(_):
        return None

    state = asyncio.run(
        runner.run_session(
            interval_seconds=0.0,
            now_fn=lambda: next(times),
            sleep_fn=_sleep,
            max_ticks=10,
        )
    )
    assert state.squared_off
    assert any(f.side == "buy" for f in state.fills)
    assert any(f.side == "sell" for f in state.fills)
