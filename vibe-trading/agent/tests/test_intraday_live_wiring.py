"""Offline unit tests for the live-activation wiring (creds day, 2026-07-15).

Covers the pieces added when real creds landed — no network anywhere:

  * Dhan sdk ``get_historical_bars`` parsing both payload shapes (dhanhq 1.x
    ``data.candles`` lists and 2.x parallel arrays) and the failure envelope.
  * ``dhan_config_from_intraday`` (DC-003: creds from ``.env``, not the saved
    ``~/.vibe-trading/dhan.json``) and ``DhanBarSource`` threading it through.
  * ``gemini_generate`` REST parsing + ``make_llm_caller`` routing (BUG-001).
  * The bake-off launcher helpers (interval parsing, wait-for-open, fill merge).

Run:  cd vibe-trading/agent && set PYTHONPATH=. && \
      python -m pytest tests/test_intraday_live_wiring.py -q
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.intraday import bakeoff
from src.intraday.bars import DhanBarSource, dhan_config_from_intraday
from src.intraday.clock import IST, SessionClock, parse_hhmm
from src.intraday.config import IntradayConfig, Instrument
from src.intraday import gemini_jobs
from src.trading.connectors.dhan import sdk as dhan_sdk


# --------------------------------------------------------------------------- #
# Dhan sdk — get_historical_bars across dhanhq 1.x / 2.x payloads
# --------------------------------------------------------------------------- #


class _V2Client:
    """dhanhq >= 2.x facade: intraday_minute_data + parallel-array payload."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def intraday_minute_data(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


class _V1Client:
    """dhanhq 1.x facade: intraday_daily_candle_data + candles-list payload."""

    def __init__(self, payload):
        self.payload = payload

    def intraday_daily_candle_data(self, **kwargs):
        return self.payload


def _patch_client(monkeypatch, client):
    monkeypatch.setattr(dhan_sdk, "_dhan_client", lambda cfg: client)


def test_historical_bars_parses_v2_parallel_arrays(monkeypatch):
    client = _V2Client({
        "status": "success",
        "data": {
            "timestamp": [1783914300, 1783915200],
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.5],
            "close": [101.0, 102.5],
            "volume": [1000, 2000],
        },
    })
    _patch_client(monkeypatch, client)
    out = dhan_sdk.get_historical_bars("X", security_id="2885", period="15m", limit=10)
    assert out["status"] == "ok"
    assert len(out["bars"]) == 2
    assert out["bars"][0] == {
        "time": 1783914300, "open": 100.0, "high": 102.0,
        "low": 99.0, "close": 101.0, "volume": 1000,
    }
    # 2.x path must receive the interval in minutes and a +1-day exclusive toDate.
    call = client.calls[0]
    assert call["interval"] == 15
    assert call["from_date"] < call["to_date"]


def test_historical_bars_still_parses_v1_candles(monkeypatch):
    _patch_client(monkeypatch, _V1Client({
        "status": "success",
        "data": {"candles": [[1783914300, 100.0, 102.0, 99.0, 101.0, 1000]]},
    }))
    out = dhan_sdk.get_historical_bars("X", security_id="2885", period="15m", limit=10)
    assert out["status"] == "ok"
    assert out["bars"] == [{
        "time": 1783914300, "open": 100.0, "high": 102.0,
        "low": 99.0, "close": 101.0, "volume": 1000,
    }]


def test_historical_bars_failure_returns_error_envelope(monkeypatch):
    _patch_client(monkeypatch, _V2Client({
        "status": "failure",
        "remarks": "Invalid security id",
        "data": {},
    }))
    out = dhan_sdk.get_historical_bars("X", security_id="0", period="15m")
    assert out["status"] == "error"
    assert "Invalid security id" in out["error"]


# --------------------------------------------------------------------------- #
# DC-003 — creds threaded from .env instead of the saved dhan.json
# --------------------------------------------------------------------------- #


def test_dhan_config_from_intraday_none_until_configured():
    assert dhan_config_from_intraday(IntradayConfig()) is None


def test_dhan_config_from_intraday_carries_env_creds():
    cfg = IntradayConfig.load(
        json_path="___does_not_exist___.json",
        env={"DHAN_CLIENT_ID": "1100999", "DHAN_ACCESS_TOKEN": "jwt-real"},
    )
    dc = dhan_config_from_intraday(cfg)
    assert dc is not None
    assert (dc.client_id, dc.access_token) == ("1100999", "jwt-real")
    assert dc.is_paper and dc.readonly


class _RecordingSdk:
    """Stands in for the sdk module; records the kwargs each call received."""

    def __init__(self):
        self.calls = []

    def get_historical_bars(self, symbol, **kwargs):
        self.calls.append(kwargs)
        return {"status": "ok", "bars": []}


def test_bar_source_passes_dhan_config_through():
    sdk = _RecordingSdk()
    inst = {"R.NS": Instrument("R.NS", security_id="2885")}
    sentinel = object()
    DhanBarSource(inst, sdk=sdk, dhan_config=sentinel).recent_bars("R.NS", lookback=5)
    assert sdk.calls[0]["config"] is sentinel


def test_bar_source_omits_config_kwarg_when_unset():
    sdk = _RecordingSdk()
    inst = {"R.NS": Instrument("R.NS", security_id="2885")}
    DhanBarSource(inst, sdk=sdk).recent_bars("R.NS", lookback=5)
    assert "config" not in sdk.calls[0]


# --------------------------------------------------------------------------- #
# BUG-001 — real Gemini caller is direct REST, not the nonexistent llm factory
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_gemini_generate_parses_candidate_text(monkeypatch):
    import httpx

    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["headers"] = kwargs.get("headers", {})
        return _FakeResponse({
            "candidates": [{"content": {"parts": [{"text": "hello "}, {"text": "world"}]}}]
        })

    monkeypatch.setattr(httpx, "post", fake_post)
    out = gemini_jobs.gemini_generate("key-123", "gemini-3.5-flash", "hi")
    assert out == "hello world"
    assert "gemini-3.5-flash:generateContent" in seen["url"]
    assert seen["headers"]["x-goog-api-key"] == "key-123"


def test_make_llm_caller_routes_real_key_to_rest(monkeypatch):
    cfg = IntradayConfig.load(
        json_path="___does_not_exist___.json", env={"GEMINI_API_KEY": "AIza-real"}
    )
    monkeypatch.setattr(
        gemini_jobs, "gemini_generate", lambda key, model, prompt, **kw: f"{key}/{model}"
    )
    assert gemini_jobs.make_llm_caller(cfg)("x") == "AIza-real/gemini-3.5-flash"


# --------------------------------------------------------------------------- #
# CachedBarSource — one upstream fetch per symbol per tick (15-strategy scale)
# --------------------------------------------------------------------------- #


class _CountingSource:
    def __init__(self, frame):
        self.frame = frame
        self.calls = 0

    def recent_bars(self, symbol, *, lookback):
        self.calls += 1
        return self.frame.tail(lookback)


def _bars_frame(n=60):
    import pandas as pd

    idx = pd.date_range("2026-07-16 09:15", periods=n, freq="15min", tz="Asia/Kolkata")
    return pd.DataFrame(
        {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0}, index=idx
    )


def test_cached_source_serves_many_runners_from_one_fetch():
    from src.intraday.bars import CachedBarSource

    upstream = _CountingSource(_bars_frame())
    cached = CachedBarSource(upstream, min_lookback=60)
    for _ in range(15):  # 15 runners pulling the same symbol within a tick
        assert len(cached.recent_bars("R.NS", lookback=60)) == 60
    assert len(cached.recent_bars("R.NS", lookback=1)) == 1  # smaller ask → cache
    assert upstream.calls == 1


def test_cached_source_invalidates_only_when_cursor_moves():
    from src.intraday.bars import CachedBarSource

    upstream = _CountingSource(_bars_frame())
    cached = CachedBarSource(upstream, min_lookback=60)
    t1 = datetime(2026, 7, 16, 10, 30, tzinfo=IST)
    cached.set_now(t1)
    cached.recent_bars("R.NS", lookback=60)
    cached.set_now(t1)  # same tick — repeated set_now must NOT clear
    cached.recent_bars("R.NS", lookback=60)
    assert upstream.calls == 1
    cached.set_now(datetime(2026, 7, 16, 10, 45, tzinfo=IST))  # new tick
    cached.recent_bars("R.NS", lookback=60)
    assert upstream.calls == 2


# --------------------------------------------------------------------------- #
# Telegram chunking — 15-strategy reports exceed the 4096-char message cap
# --------------------------------------------------------------------------- #


def test_split_for_telegram_preserves_content_on_line_boundaries():
    from src.intraday.notifier import split_for_telegram

    assert split_for_telegram("short") == ["short"]
    text = "\n".join(f"line {i} " + "x" * 80 for i in range(100))  # ~8.7k chars
    chunks = split_for_telegram(text, limit=4000)
    assert len(chunks) >= 3
    assert all(len(c) <= 4000 for c in chunks)
    assert "\n".join(chunks) == text  # nothing lost, order preserved


# --------------------------------------------------------------------------- #
# detailed hourly report
# --------------------------------------------------------------------------- #


def test_format_hourly_detailed_collapses_pairs_and_shows_halts():
    """B4-2 shape: one row per long/_ls pair (long · ls · short leg · Δ),
    halted pairs always visible on their own both-legs line."""
    from src.intraday.paper_broker import Fill
    from src.intraday.scoreboard import format_hourly_detailed

    ts = datetime(2026, 7, 15, 10, 30, tzinfo=IST)
    sections = [
        {
            "name": "orb",
            "fills": [
                Fill("RELIANCE.NS", "buy", 12, 1295.0, 18.0, ts),
                Fill("RELIANCE.NS", "sell", 12, 1301.2, 19.0, ts, realized_pnl=62.0),
            ],
            "opens": [("TATASTEEL.NS", 100, 188.5, 190.1, 1)],
            "realized": 62.0, "fees": 37.0, "equity": 25062.0, "cash": 6052.0,
            "halted": False, "halt_reason": "", "short_pnl": 0.0,
        },
        {
            "name": "orb_ls",
            "fills": [Fill("SBIN.NS", "cover", 8, 780.0, 12.0, ts, realized_pnl=120.0)],
            "opens": [], "realized": 120.0, "fees": 12.0, "equity": 25120.0,
            "cash": 25120.0, "halted": False, "halt_reason": "",
            "hybrid": True, "short_pnl": 120.0,
        },
        {
            "name": "pullback",
            "fills": [], "opens": [], "realized": -10200.0, "fees": 250.0,
            "equity": 14800.0, "cash": 14800.0, "halted": True,
            "halt_reason": "setup kill-switch: loss ≥ ₹10,000", "short_pnl": 0.0,
        },
        {
            "name": "pullback_ls",
            "fills": [], "opens": [], "realized": 0.0, "fees": 0.0,
            "equity": 25000.0, "cash": 25000.0, "halted": False,
            "halt_reason": "", "hybrid": True, "short_pnl": 0.0,
        },
    ]
    text = format_hourly_detailed(sections, hour_label="11:00")
    assert "📊 Hourly · 11:00 IST" in text
    # orb pair collapsed to ONE row: long 62 · ls 120 · short 120 · Δ = 58
    assert text.count("orb") == 1
    orb_row = next(l for l in text.splitlines() if l.startswith("orb"))
    assert "62" in orb_row and "120" in orb_row and "58" in orb_row
    # halted pullback pair stays visible on its own line, both legs, flagged
    halt_line = next(l for l in text.splitlines() if l.startswith("⚠"))
    assert "pullback" in halt_line and "✖" in halt_line and "10,200" in halt_line


# --------------------------------------------------------------------------- #
# bake-off launcher helpers
# --------------------------------------------------------------------------- #


def test_interval_seconds_tokens():
    assert bakeoff.interval_seconds("15m") == 900.0
    assert bakeoff.interval_seconds("5m") == 300.0
    assert bakeoff.interval_seconds("1h") == 3600.0
    with pytest.raises(ValueError):
        bakeoff.interval_seconds("1d")


def _clock():
    return SessionClock(parse_hhmm("09:15"), parse_hhmm("15:30"), parse_hhmm("15:15"))


def test_wait_for_open_polls_until_bell():
    import asyncio

    # Wed 2026-07-15: 09:00 (pre-open) → 09:10 → 09:16 (open).
    times = iter([
        datetime(2026, 7, 15, 9, 0, tzinfo=IST),
        datetime(2026, 7, 15, 9, 10, tzinfo=IST),
        datetime(2026, 7, 15, 9, 16, tzinfo=IST),
    ])
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    assert asyncio.run(
        bakeoff.wait_for_open(_clock(), now_fn=lambda: next(times), sleep_fn=fake_sleep)
    )
    assert len(sleeps) == 2


def test_wait_for_open_bails_on_weekend_and_after_close():
    import asyncio

    sat = datetime(2026, 7, 18, 10, 0, tzinfo=IST)
    assert not asyncio.run(bakeoff.wait_for_open(_clock(), now_fn=lambda: sat))
    late = datetime(2026, 7, 15, 16, 0, tzinfo=IST)
    assert not asyncio.run(bakeoff.wait_for_open(_clock(), now_fn=lambda: late))
