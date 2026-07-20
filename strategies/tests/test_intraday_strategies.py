"""Regression tests for the long-only intraday strategies (offline, synthetic).

Checks each strategy is (1) accepted by the repo's own signal-engine validators,
(2) long-only and flat in the no-trade windows, and (3) produces only long,
same-day trades through the real IndiaIntradayEngine. No network required.

Run: cd vibe_intraday/strategies && set PYTHONPATH=../vibe-trading/agent && pytest -q
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_AGENT = Path(__file__).resolve().parents[2] / "vibe-trading" / "agent"
sys.path.insert(0, str(_AGENT))

from backtest.engines.base import _align  # noqa: E402
from backtest.engines.india_intraday import IndiaIntradayEngine  # noqa: E402
from backtest.runner import (  # noqa: E402
    _validate_signal_engine_class,
    _validate_signal_engine_source,
)

_STRAT = Path(__file__).resolve().parents[1]
STRATEGIES = [
    "orb_intraday",
    "pullback_buy",
    "ema_trend",
    "momentum_rsi",
    "gap_go",
    "gap_fade",
    "vwap_hold",
    "range_break",
    "macd_cross",
    "boll_bounce",
    "boll_break",
    "atr_trail",
    "rel_strength",
    "three_thrust",
    "supertrend",
    "ut_bot",
    "squeeze_momentum",
    "wavetrend",
    "qqe_mode",
    "oi_dma_adx",
    # TradingView ports added 2026-07-18 (B3 batch).
    "bb_rsi",
    "macd_sma200",
    "macd_rsi",
    "pmax",
    "hull_suite",
    "ao_stoch",
    "golden_cross",
    "flawless_victory",
    "ema_cross",
    "ichimoku",
    "rsi_div",
    # Tier-1 shortlist batch added 2026-07-19 (B7).
    "cpr_pivot",
    "psar_flip",
    "supertrend_vwap",
    "donchian",
    "keltner",
    "stoch_rsi",
    "connors_rsi2",
]


def _load(name: str):
    path = _STRAT / name / "code" / "signal_engine.py"
    spec = importlib.util.spec_from_file_location(f"se_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return path, mod.SignalEngine


def _day_index(day: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.date_range(
        day + pd.Timedelta(hours=9, minutes=15), periods=25, freq="15min",
        tz="Asia/Kolkata",
    )


def _next_weekday(day: pd.Timestamp) -> pd.Timestamp:
    while day.dayofweek >= 5:
        day += pd.Timedelta(days=1)
    return day


def _synthetic_15m(days: int = 4, seed: int = 1) -> pd.DataFrame:
    """Steady uptrend with periodic dips + volume spikes (the default fixture)."""
    rng = np.random.default_rng(seed)
    frames = []
    day = pd.Timestamp("2026-06-01")
    price = 100.0
    for _ in range(days):
        day = _next_weekday(day)
        idx = _day_index(day)
        rows = []
        for k in range(25):
            price += 0.25 + (-0.6 if k % 6 == 5 else 0.0) + rng.normal(0, 0.1)
            vol = 10_000.0 * (1.9 if (k > 3 and k % 5 == 0) else 1.0)
            rows.append([price - 0.25, price + 0.4, price - 0.5, price, vol])
        frames.append(pd.DataFrame(
            rows, columns=["open", "high", "low", "close", "volume"], index=idx
        ))
        day += pd.Timedelta(days=1)
    return pd.concat(frames)


def _gap_15m(direction: int, seed: int = 2) -> pd.DataFrame:
    """Two days: a normal day, then a day gapping ±0.6% and trending up."""
    rng = np.random.default_rng(seed)
    frames = []
    day = _next_weekday(pd.Timestamp("2026-06-01"))
    price = 100.0
    for day_no in range(2):
        idx = _day_index(day)
        if day_no == 1:
            price += direction * price * 0.006  # the overnight gap
        rows = []
        for _ in range(25):
            price += 0.25 + rng.normal(0, 0.05)
            rows.append([price - 0.25, price + 0.4, price - 0.5, price, 10_000.0])
        frames.append(pd.DataFrame(
            rows, columns=["open", "high", "low", "close", "volume"], index=idx
        ))
        day = _next_weekday(day + pd.Timedelta(days=1))
    return pd.concat(frames)


def _oscillating_15m(days: int = 2, seed: int = 3) -> pd.DataFrame:
    """Trendless sine-wave days (amplitude ~2.5, period 10 bars) — reversion food."""
    rng = np.random.default_rng(seed)
    frames = []
    day = _next_weekday(pd.Timestamp("2026-06-01"))
    k = 0
    for _ in range(days):
        idx = _day_index(day)
        rows = []
        for _ in range(25):
            price = 100.0 + 2.5 * np.sin(2 * np.pi * k / 10) + rng.normal(0, 0.05)
            rows.append([price, price + 0.2, price - 0.2, price, 10_000.0])
            k += 1
        frames.append(pd.DataFrame(
            rows, columns=["open", "high", "low", "close", "volume"], index=idx
        ))
        day = _next_weekday(day + pd.Timedelta(days=1))
    return pd.concat(frames)


def _surge_15m(seed: int = 4) -> pd.DataFrame:
    """One flat, quiet morning that resolves into a strong volume-backed ramp."""
    rng = np.random.default_rng(seed)
    day = _next_weekday(pd.Timestamp("2026-06-01"))
    idx = _day_index(day)
    rows = []
    price = 100.0
    for k in range(25):
        if k < 15:
            price = 100.0 + rng.normal(0, 0.03)
            vol = 10_000.0
        else:
            price += 0.8
            vol = 22_000.0
        rows.append([price - 0.1, price + 0.2, price - 0.2, price, vol])
    return pd.DataFrame(
        rows, columns=["open", "high", "low", "close", "volume"], index=idx
    )


def _vshape_15m(seed: int = 6) -> pd.DataFrame:
    """Two days: quiet warm-up, then a sharp midday plunge that V-recovers.

    A pure sine can never close ``2σ`` outside its own Bollinger band (max
    deviation ≈ 1.41σ), so the 2σ bounce buyer needs a fat-tail day: flat
    tape, a 3-bar dump, then a steady recovery through the middle band.
    """
    rng = np.random.default_rng(seed)
    frames = []
    day = _next_weekday(pd.Timestamp("2026-06-01"))
    price = 100.0
    for day_no in range(2):
        idx = _day_index(day)
        rows = []
        for k in range(25):
            if day_no == 1 and 10 <= k <= 12:
                price -= 0.65                       # the dump
            elif day_no == 1 and k > 12:
                price += 0.35                       # the V-recovery
            else:
                price = 100.0 + rng.normal(0, 0.05)
            rows.append([price + 0.05, price + 0.15, price - 0.15, price, 10_000.0])
        frames.append(pd.DataFrame(
            rows, columns=["open", "high", "low", "close", "volume"], index=idx
        ))
        day = _next_weekday(day + pd.Timedelta(days=1))
    return pd.concat(frames)


def _squeeze_15m(seed: int = 5) -> pd.DataFrame:
    """Two days: a dead-quiet compression day, then a midday volatility release.

    Day 1 (and day 2's morning) keeps ranges tiny so the Bollinger Bands sit
    inside the Keltner Channel (squeeze ON); from day 2 bar 10 the price ramps
    with wide ranges so the bands expand past the channel (the squeeze FIRES)
    with strongly positive momentum.
    """
    rng = np.random.default_rng(seed)
    frames = []
    day = _next_weekday(pd.Timestamp("2026-06-01"))
    for day_no in range(2):
        idx = _day_index(day)
        rows = []
        price = 100.0
        for k in range(25):
            if day_no == 1 and k >= 10:
                price += 0.8
                rows.append([price - 0.4, price + 0.3, price - 0.5, price, 22_000.0])
            else:
                price = 100.0 + rng.normal(0, 0.03)
                rows.append([price - 0.05, price + 0.05, price - 0.05, price, 10_000.0])
        frames.append(pd.DataFrame(
            rows, columns=["open", "high", "low", "close", "volume"], index=idx
        ))
        day = _next_weekday(day + pd.Timedelta(days=1))
    return pd.concat(frames)


def _long_uptrend_15m(days: int = 8, seed: int = 8) -> pd.DataFrame:
    """A long, smooth multi-day up-trend — enough bars for slow filters.

    The 50/200-style trend strategies (golden_cross, macd_sma200) and Ichimoku
    need ~100+ bars before their slow averages/cloud become valid, so their
    trade fixture spans many sessions of a clean rising drift.
    """
    rng = np.random.default_rng(seed)
    frames = []
    day = pd.Timestamp("2026-05-01")
    price = 100.0
    for _ in range(days):
        day = _next_weekday(day)
        idx = _day_index(day)
        rows = []
        for _ in range(25):
            price += 0.18 + rng.normal(0, 0.06)
            rows.append([price - 0.1, price + 0.2, price - 0.2, price, 10_000.0])
        frames.append(pd.DataFrame(
            rows, columns=["open", "high", "low", "close", "volume"], index=idx
        ))
        day += pd.Timedelta(days=1)
    return pd.concat(frames)


def _divergence_15m(seed: int = 9) -> pd.DataFrame:
    """Bullish regular RSI divergence: a deep first low, then a lower second low.

    Dip 1 is a deep monotonic crash (RSI ≈ 0). A *modest* recovery follows, so when
    dip 2 falls to a marginally LOWER price its 14-bar RSI window still holds those
    recovery up-bars → RSI at dip 2 (≈33) is clearly higher than at dip 1 (≈4). Price
    makes a lower low while RSI makes a higher low → bullish divergence, then the tape
    rallies to confirm. Mirrored, it is a textbook bearish divergence for the twin.
    """
    seg = [100.0]

    def _ramp(n: int, step: float) -> None:
        for _ in range(n):
            seg.append(seg[-1] + step)

    _ramp(12, +0.05)   # gentle monotonic warm-up (no spurious pivot lows)
    _ramp(8, -1.0)     # dip 1: deep crash → ~92.6 (RSI ≈ 0)
    _ramp(2, +0.25)    # confirm the dip-1 pivot low
    _ramp(10, +0.5)    # modest recovery (seeds up-bars into dip 2's RSI window)
    _ramp(7, -1.0)     # dip 2: → ~91.6, a lower low than dip 1
    _ramp(2, +0.25)    # confirm the dip-2 pivot low
    _ramp(12, +0.6)    # rally — confirms the divergence

    frames = []
    day = _next_weekday(pd.Timestamp("2026-06-01"))
    k = 0
    n_days = (len(seg) + 24) // 25
    for _ in range(n_days):
        idx = _day_index(day)
        rows = []
        for _ in range(25):
            price = seg[k] if k < len(seg) else seg[-1]
            rows.append([price + 0.02, price + 0.12, price - 0.12, price, 10_000.0])
            k += 1
        frames.append(pd.DataFrame(
            rows, columns=["open", "high", "low", "close", "volume"], index=idx
        ))
        day = _next_weekday(day + pd.Timedelta(days=1))
    return pd.concat(frames)


def _dip_uptrend_15m(days: int = 10, seed: int = 11) -> pd.DataFrame:
    """A steady multi-day up-trend with a sharp 2-bar afternoon dip each day.

    Connors RSI(2) needs both conditions to coincide: price well ABOVE a slow
    100-bar SMA (so the trend filter passes) AND a violent short pullback that
    drives the 2-period RSI to its extreme. A smooth drift never dents RSI(2), so
    each session climbs (23 up-bars) but takes a hard two-bar dump around 13:15 —
    enough sessions (~250 bars) that the 100-SMA is valid and price stays above it.
    Mirrored, it is the same setup for the short twin (a spike above the MA).
    """
    rng = np.random.default_rng(seed)
    frames = []
    day = pd.Timestamp("2026-05-01")
    price = 100.0
    for _ in range(days):
        day = _next_weekday(day)
        idx = _day_index(day)
        rows = []
        for k in range(25):
            if k in (16, 17):
                price -= 1.2                         # the sharp afternoon dip
            else:
                price += 0.30 + rng.normal(0, 0.03)  # steady climb dominates
            rows.append([price - 0.1, price + 0.2, price - 0.2, price, 10_000.0])
        frames.append(pd.DataFrame(
            rows, columns=["open", "high", "low", "close", "volume"], index=idx
        ))
        day += pd.Timedelta(days=1)
    return pd.concat(frames)


#: Fixture used by the "produces trades" test — specialists get the pattern
#: they exist to trade (a gap strategy can't trade a gapless drift, etc.).
TRADE_FIXTURES = {
    "gap_go": lambda: _gap_15m(+1),
    "gap_fade": lambda: _gap_15m(-1),
    "boll_bounce": _vshape_15m,
    "boll_break": _surge_15m,
    "squeeze_momentum": _squeeze_15m,
    "wavetrend": lambda: _oscillating_15m(days=4),
    # TradingView ports (2026-07-18).
    "bb_rsi": _vshape_15m,
    "flawless_victory": _vshape_15m,
    "macd_rsi": lambda: _oscillating_15m(days=4),
    "macd_sma200": lambda: _long_uptrend_15m(8),
    "golden_cross": lambda: _long_uptrend_15m(8),
    "ichimoku": lambda: _long_uptrend_15m(8),
    "rsi_div": _divergence_15m,
    # Tier-1 shortlist batch (2026-07-19).
    "stoch_rsi": lambda: _oscillating_15m(days=4),
    "connors_rsi2": _dip_uptrend_15m,
}


@pytest.mark.parametrize("name", STRATEGIES)
def test_repo_validators_accept(name: str) -> None:
    path, cls = _load(name)
    _validate_signal_engine_source(path)   # AST purity (no decorators/top-level stmts)
    _validate_signal_engine_class(cls)     # no-arg ctor + generate()


@pytest.mark.parametrize("name", STRATEGIES)
def test_long_only_and_flat_windows(name: str) -> None:
    _, cls = _load(name)
    df = _synthetic_15m()
    sig = cls().generate({"RELIANCE.NS": df})["RELIANCE.NS"]

    assert set(pd.unique(sig)) <= {0, 1}, "signals must be long-only (0/1)"
    ist = sig.index.tz_convert("Asia/Kolkata")
    tt = np.array([t.time() for t in ist])
    assert (sig.to_numpy()[tt < dt.time(9, 45)] == 0).all(), "traded before 09:45"
    assert (sig.to_numpy()[tt >= dt.time(15, 0)] == 0).all(), "held at/after 15:00 flatten"


def _mirror(df: pd.DataFrame) -> pd.DataFrame:
    """Reflect an OHLC frame around 2× its first open → a price-mirrored tape.

    An up-trend becomes a down-trend, a gap-up becomes a gap-down, a lower-band
    dip becomes an upper-band poke, etc. — so a strategy's short mirror fires
    exactly where its long fires on the original (highs/lows swap; volume kept).
    """
    base = 2.0 * float(df["open"].iloc[0])
    out = df.copy()
    out["open"] = base - df["open"]
    out["close"] = base - df["close"]
    out["high"] = base - df["low"]   # old low reflects to the new high
    out["low"] = base - df["high"]
    return out


def _rally_then_plunge_15m(seed: int = 7) -> pd.DataFrame:
    """Two rally days, then a day-3 hard plunge from 09:45.

    A price mirror of a smooth up-trend keeps QQE's smoothed RSI gliding down
    *below* its trailing line, which only flips to the short side on a sharp
    cross — so the QQE mirror needs a rally that establishes the long-side trail,
    then a plunge that crosses it downward.
    """
    rng = np.random.default_rng(seed)
    frames = []
    day = _next_weekday(pd.Timestamp("2026-06-01"))
    price = 100.0
    for d in range(3):
        idx = _day_index(day)
        rows = []
        for k in range(25):
            if d < 2:
                price += 0.35 + rng.normal(0, 0.05)          # two rally days
            else:
                price += (-1.4 if k >= 2 else 0.0) + rng.normal(0, 0.05)  # day-3 plunge
            rows.append([price - 0.1, price + 0.2, price - 0.3, price, 10_000.0])
        frames.append(pd.DataFrame(
            rows, columns=["open", "high", "low", "close", "volume"], index=idx))
        day = _next_weekday(day + pd.Timedelta(days=1))
    return pd.concat(frames)


#: Short-side fixture overrides. Most strategies short a straight price mirror of
#: their long fixture; a few asymmetric ones (QQE's trailing-line flip) need a
#: bespoke tape.
SHORT_FIXTURES = {
    "qqe_mode": _rally_then_plunge_15m,
}


def _short_fixture(name: str) -> pd.DataFrame:
    if name in SHORT_FIXTURES:
        return SHORT_FIXTURES[name]()
    return _mirror(TRADE_FIXTURES.get(name, _synthetic_15m)())


@pytest.mark.parametrize("name", STRATEGIES)
def test_hybrid_emits_short_on_mirrored_fixture(name: str) -> None:
    _, cls = _load(name)
    code = "RELIANCE.NS"
    df = _short_fixture(name)
    sig = cls(allow_short=True).generate({code: df})[code]

    vals = set(pd.unique(sig))
    assert vals <= {-1, 0, 1}, "hybrid signals must be in {-1,0,1}"
    assert -1 in vals, f"{name} hybrid should emit at least one short on the mirror"
    # A short is never held outside the tradeable window.
    ist = sig.index.tz_convert("Asia/Kolkata")
    tt = np.array([t.time() for t in ist])
    arr = sig.to_numpy()
    assert (arr[tt < dt.time(9, 45)] != -1).all(), "shorted before 09:45"
    assert (arr[tt >= dt.time(15, 0)] != -1).all(), "held a short at/after 15:00 flatten"


@pytest.mark.parametrize("name", STRATEGIES)
def test_no_arg_ctor_never_shorts(name: str) -> None:
    _, cls = _load(name)
    code = "RELIANCE.NS"
    fixtures = [
        _synthetic_15m(),
        _mirror(_synthetic_15m()),
        _short_fixture(name),
    ]
    for df in fixtures:
        sig = cls().generate({code: df})[code]  # long-only no-arg ctor
        assert (sig.to_numpy() != -1).all(), f"{name} no-arg ctor emitted a short"


@pytest.mark.parametrize("name", STRATEGIES)
def test_hybrid_short_same_day_trades(name: str) -> None:
    """The mirrored short runs through the engine as short, same-day, MIS."""
    _, cls = _load(name)
    code = "RELIANCE.NS"
    df = _short_fixture(name)
    sig = cls(allow_short=True).generate({code: df})[code]
    dates, close_df, target_pos, _ = _align({code: df}, {code: sig}, [code])
    eng = IndiaIntradayEngine({"initial_cash": 50_000, "intraday": True, "allow_short": True})
    eng._execute_bars(dates, {code: df}, close_df, target_pos, [code])

    assert eng.trades, "expected trades on the mirrored fixture"
    assert any(t.direction == -1 for t in eng.trades), "expected at least one short trade"
    for t in eng.trades:
        assert t.entry_time.date() == t.exit_time.date(), "no overnight carry (MIS)"


@pytest.mark.parametrize("name", STRATEGIES)
def test_only_long_same_day_trades(name: str) -> None:
    _, cls = _load(name)
    code = "RELIANCE.NS"
    df = TRADE_FIXTURES.get(name, _synthetic_15m)()
    sig = cls().generate({code: df})[code]
    dates, close_df, target_pos, _ = _align({code: df}, {code: sig}, [code])
    eng = IndiaIntradayEngine({"initial_cash": 50_000, "intraday": True})
    eng._execute_bars(dates, {code: df}, close_df, target_pos, [code])

    assert eng.trades, "expected trades on the synthetic uptrend"
    for t in eng.trades:
        assert t.direction == 1, "long-only"
        assert t.entry_time.date() == t.exit_time.date(), "no overnight carry (MIS)"
