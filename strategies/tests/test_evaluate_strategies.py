"""Regression tests for the robustness evaluator (`evaluate_strategies.py`).

Fast + offline: exercises the fold splitter, the score formula, symbol-name
recovery from cache filenames, and one real `evaluate()` pass over a tiny
synthetic 2-symbol dataset — no full 31×38 sweep, no network.

Run: cd vibe_intraday/strategies && set PYTHONPATH=. && pytest tests/test_evaluate_strategies.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_STRAT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_STRAT))

import evaluate_strategies as ev  # noqa: E402


def _uptrend(days: int = 8, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = []
    day = pd.Timestamp("2026-05-04")  # a Monday
    price = 100.0
    for _ in range(days):
        while day.dayofweek >= 5:
            day += pd.Timedelta(days=1)
        idx = pd.date_range(day + pd.Timedelta(hours=9, minutes=15), periods=25,
                            freq="15min", tz="Asia/Kolkata")
        rows = []
        for _ in range(25):
            price += 0.2 + rng.normal(0, 0.05)
            rows.append([price - 0.1, price + 0.2, price - 0.2, price, 10_000.0])
        frames.append(pd.DataFrame(
            rows, columns=["open", "high", "low", "close", "volume"], index=idx))
        day += pd.Timedelta(days=1)
    return pd.concat(frames)


def test_folds_partition_all_days() -> None:
    df = _uptrend(days=8)
    folds = ev._folds(df, 4)
    assert len(folds) == 4
    # Folds are disjoint and together cover every original bar.
    total = sum(len(f) for f in folds)
    assert total == len(df)
    day_sets = [set(f.index.date) for f in folds]
    for a in range(len(day_sets)):
        for b in range(a + 1, len(day_sets)):
            assert day_sets[a].isdisjoint(day_sets[b]), "folds overlap in days"


def test_folds_degenerate_when_too_few_days() -> None:
    df = _uptrend(days=2)
    assert ev._folds(df, 4) == [df] or len(ev._folds(df, 4)) == 1


def test_score_consistency_dominates_and_churn_penalised() -> None:
    # Higher pos_rate always scores higher at equal churn/median.
    assert ev._score(0.6, 0.0, 2.0) > ev._score(0.4, 0.0, 2.0)
    # Churn above 4 trades/symbol drags the score down.
    assert ev._score(0.5, 0.0, 12.0) < ev._score(0.5, 0.0, 3.0)
    # A better median net nudges the score up.
    assert ev._score(0.5, 500.0, 3.0) > ev._score(0.5, 0.0, 3.0)


def test_cached_symbol_name_recovery(tmp_path, monkeypatch) -> None:
    for fn in ["ADANIENT_NS_15m.csv", "BAJAJ-AUTO_NS_15m.csv", "M&M_NS_15m.csv"]:
        (tmp_path / fn).write_text("x")
    monkeypatch.setattr(ev.bt, "CACHE_DIR", tmp_path)
    assert ev.cached_symbols() == ["ADANIENT.NS", "BAJAJ-AUTO.NS", "M&M.NS"]


def test_evaluate_one_strategy_two_symbols() -> None:
    data = {"AAA.NS": _uptrend(seed=1), "BBB.NS": _uptrend(seed=2)}
    result = ev.evaluate("ema_cross", data, folds=4)
    assert result.name == "ema_cross"
    assert 0.0 <= result.pos_rate <= 1.0
    assert 0.0 <= result.sym_pos <= 1.0
    assert set(result.per_symbol) == {"AAA.NS", "BBB.NS"}
    assert result.trades_avg >= 0.0
    assert np.isfinite(result.score)
