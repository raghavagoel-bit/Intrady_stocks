"""Offline unit tests for the LLM bake-off slot (src/intraday/llm_engine.py).

The LLM itself is a fake in every test — what's under test is the deterministic
fence around it: long-only 0/1 output, the no-entry windows outranking the LLM,
keep-last-decision on any API/parse failure, strict JSON parsing, flat-forever
without a key, and the ``builtin:`` roster wiring in Portfolio.

Run:  cd vibe-trading/agent && set PYTHONPATH=. && \
      python -m pytest tests/test_llm_engine.py -q
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.intraday.config import IntradayConfig
from src.intraday.llm_engine import LLMSignalEngine, build_builtin_engine


def _frame(last_hhmm: str, bars: int = 6) -> pd.DataFrame:
    """A tiny IST 15m frame whose final bar closes at ``last_hhmm``."""
    end = pd.Timestamp(f"2026-07-16 {last_hhmm}", tz="Asia/Kolkata")
    idx = pd.date_range(end=end, periods=bars, freq="15min")
    base = 100.0
    return pd.DataFrame(
        {
            "open": [base + i for i in range(bars)],
            "high": [base + i + 0.5 for i in range(bars)],
            "low": [base + i - 0.5 for i in range(bars)],
            "close": [base + i + 0.2 for i in range(bars)],
            "volume": [10_000] * bars,
        },
        index=idx,
    )


def test_long_decision_lands_on_last_bar_only():
    eng = LLMSignalEngine(llm_call=lambda p: '{"R.NS": "long", "S.NS": "flat"}')
    out = eng.generate({"R.NS": _frame("10:30"), "S.NS": _frame("10:30")})
    assert out["R.NS"].iloc[-1] == 1
    assert out["S.NS"].iloc[-1] == 0
    assert set(pd.unique(out["R.NS"])) <= {0, 1}
    assert out["R.NS"].iloc[:-1].sum() == 0  # only the live bar carries a signal
    assert eng.state == {"R.NS": 1, "S.NS": 0}


def test_guard_rails_outrank_the_llm():
    eng = LLMSignalEngine(llm_call=lambda p: '{"R.NS": "long"}')
    assert eng.generate({"R.NS": _frame("09:30")})["R.NS"].iloc[-1] == 0  # pre-09:45
    assert eng.generate({"R.NS": _frame("15:00")})["R.NS"].iloc[-1] == 0  # DC-001 flatten
    assert eng.generate({"R.NS": _frame("15:15")})["R.NS"].iloc[-1] == 0


def test_failure_keeps_last_decision_instead_of_churning():
    replies = iter(['{"R.NS": "long"}', "boom"])

    def flaky(prompt: str) -> str:
        text = next(replies)
        if text == "boom":
            raise RuntimeError("API down")
        return text

    eng = LLMSignalEngine(llm_call=flaky)
    assert eng.generate({"R.NS": _frame("10:30")})["R.NS"].iloc[-1] == 1
    # Next call blows up → the long is held, not dumped.
    assert eng.generate({"R.NS": _frame("10:45")})["R.NS"].iloc[-1] == 1


def test_unparseable_and_fenced_replies():
    eng = LLMSignalEngine(llm_call=lambda p: "no json here")
    assert eng.generate({"R.NS": _frame("11:00")})["R.NS"].iloc[-1] == 0

    fenced = LLMSignalEngine(llm_call=lambda p: '```json\n{"R.NS": "buy"}\n```')
    assert fenced.generate({"R.NS": _frame("11:00")})["R.NS"].iloc[-1] == 1

    # Symbols the LLM invents are ignored; unknown values mean flat.
    weird = LLMSignalEngine(llm_call=lambda p: '{"HACK.NS": "long", "R.NS": "short"}')
    out = weird.generate({"R.NS": _frame("11:00")})
    assert out["R.NS"].iloc[-1] == 0
    assert "HACK.NS" not in out


def test_no_key_means_permanently_flat():
    eng = LLMSignalEngine(config=IntradayConfig())  # placeholder creds, no injection
    assert eng.generate({"R.NS": _frame("10:30")})["R.NS"].iloc[-1] == 0


def test_prompt_carries_tape_holdings_and_rules():
    seen = {}

    def capture(prompt: str) -> str:
        seen["prompt"] = prompt
        return '{"R.NS": "long"}'

    eng = LLMSignalEngine(llm_call=capture)
    eng.state["R.NS"] = 1
    eng.generate({"R.NS": _frame("10:30")})
    p = seen["prompt"]
    assert "LONG-ONLY" in p and "no leverage" in p
    assert "HOLDING a long" in p
    assert "10:30" in p  # the live bar is in the tape
    assert "JSON" in p


class _ListJournal:
    def __init__(self):
        self.records = []

    def write(self, record):
        self.records.append(record)


def test_rich_reply_captures_reason_stop_target_and_journals():
    reply = (
        '{"R.NS": {"decision": "long", "reason": "breakout above VWAP", '
        '"stop": 104.0, "target": 109.5}}'
    )
    journal = _ListJournal()
    eng = LLMSignalEngine(llm_call=lambda p: reply, journal=journal)
    out = eng.generate({"R.NS": _frame("10:30")})
    assert out["R.NS"].iloc[-1] == 1
    assert eng.meta["R.NS"] == {"reason": "breakout above VWAP", "stop": 104.0, "target": 109.5}

    (rec,) = journal.records
    assert rec["kind"] == "decision" and rec["decision"] == "long" and rec["changed"]
    assert rec["reason"] == "breakout above VWAP"
    assert rec["stop"] == 104.0 and rec["target"] == 109.5
    assert rec["symbol"] == "R.NS" and rec["last_price"] > 0
    # Entry info captured for the eventual exit_eval.
    assert eng.open_info["R.NS"]["stop"] == 104.0


def test_exit_eval_grades_the_round_trip_against_stated_levels():
    replies = iter([
        '{"R.NS": {"decision": "long", "reason": "up", "stop": 104.0, "target": 200.0}}',
        '{"R.NS": {"decision": "flat", "reason": "momentum gone", "stop": null, "target": null}}',
    ])
    journal = _ListJournal()
    eng = LLMSignalEngine(llm_call=lambda p: next(replies), journal=journal)

    eng.generate({"R.NS": _frame("10:30")})            # open (lows dip to ~104.5+)
    frame2 = _frame("10:45", bars=7)                   # superset window incl. entry bar
    frame2.loc[frame2.index[-1], "low"] = 103.0        # price touched the stated stop
    eng.generate({"R.NS": frame2})                     # close

    evals = [r for r in journal.records if r["kind"] == "exit_eval"]
    assert len(evals) == 1
    ev = evals[0]
    assert ev["stop_hit"] is True          # low 103.0 <= stop 104.0
    assert ev["target_hit"] is False       # highs never reached 200
    assert ev["entry_reason"] == "up" and ev["exit_reason"] == "momentum gone"
    assert ev["entry_price"] > 0 and ev["exit_price"] > 0 and ev["move_pct"] is not None


def test_legacy_bare_string_reply_still_works():
    eng = LLMSignalEngine(llm_call=lambda p: '{"R.NS": "long"}')
    assert eng.generate({"R.NS": _frame("10:30")})["R.NS"].iloc[-1] == 1
    assert eng.meta["R.NS"] == {"reason": "", "stop": None, "target": None}


def test_decision_journal_writes_daily_jsonl(tmp_path):
    import json as _json

    from src.intraday.llm_engine import DecisionJournal

    j = DecisionJournal(tmp_path)
    j.write({"kind": "decision", "ts": "2026-07-16T10:30:00+05:30", "symbol": "R.NS"})
    j.write({"kind": "decision", "ts": "2026-07-16T10:45:00+05:30", "symbol": "R.NS"})
    path = tmp_path / "llm_journal-20260716.jsonl"
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert _json.loads(lines[0])["symbol"] == "R.NS"


def test_prompt_asks_for_reason_stop_target():
    seen = {}

    def capture(prompt: str) -> str:
        seen["prompt"] = prompt
        return '{"R.NS": {"decision": "flat", "reason": "", "stop": null, "target": null}}'

    LLMSignalEngine(llm_call=capture).generate({"R.NS": _frame("10:30")})
    p = seen["prompt"]
    assert '"decision"' in p and '"reason"' in p and '"stop"' in p and '"target"' in p


# --------------------------------------------------------------------------- #
# 3L hybrid twin (allow_short)
# --------------------------------------------------------------------------- #


def test_hybrid_parses_short_to_minus_one():
    eng = LLMSignalEngine(llm_call=lambda p: '{"R.NS": "short"}', allow_short=True)
    out = eng.generate({"R.NS": _frame("10:30")})
    assert out["R.NS"].iloc[-1] == -1
    assert set(pd.unique(out["R.NS"])) <= {-1, 0, 1}


def test_long_only_slot_coerces_short_to_flat():
    eng = LLMSignalEngine(llm_call=lambda p: '{"R.NS": "short"}')  # allow_short=False
    assert eng.generate({"R.NS": _frame("10:30")})["R.NS"].iloc[-1] == 0


def test_hybrid_prompt_offers_short():
    seen = {}

    def capture(prompt: str) -> str:
        seen["prompt"] = prompt
        return '{"R.NS": "flat"}'

    eng = LLMSignalEngine(llm_call=capture, allow_short=True)
    eng.state["R.NS"] = -1
    eng.generate({"R.NS": _frame("10:30")})
    p = seen["prompt"]
    assert "HYBRID" in p and "short" in p.lower()
    assert "HOLDING a short" in p


def test_short_exit_eval_flips_stop_and_target():
    replies = iter([
        '{"R.NS": {"decision": "short", "reason": "down", "stop": 108.0, "target": 90.0}}',
        '{"R.NS": {"decision": "flat", "reason": "cover", "stop": null, "target": null}}',
    ])
    journal = _ListJournal()
    eng = LLMSignalEngine(llm_call=lambda p: next(replies), journal=journal, allow_short=True)

    eng.generate({"R.NS": _frame("10:30")})            # open short
    frame2 = _frame("10:45", bars=7)
    frame2.loc[frame2.index[-1], "high"] = 109.0       # price spiked to the stated stop
    eng.generate({"R.NS": frame2})                     # cover

    ev = [r for r in journal.records if r["kind"] == "exit_eval"][0]
    assert ev["direction"] == "short"
    assert ev["stop_hit"] is True          # high 109 >= stop 108 (flipped: stop ABOVE)
    assert ev["target_hit"] is False       # low never fell to the 90 target
    assert ev["entry_reason"] == "down" and ev["exit_reason"] == "cover"


def test_builtin_roster_wiring():
    assert isinstance(build_builtin_engine("llm_trader", IntradayConfig()), LLMSignalEngine)
    with pytest.raises(ValueError):
        build_builtin_engine("nope", IntradayConfig())


def test_builtin_hybrid_wiring_sets_allow_short():
    eng = build_builtin_engine("llm_trader", IntradayConfig(), allow_short=True)
    assert isinstance(eng, LLMSignalEngine) and eng.allow_short is True


# --------------------------------------------------------------------------- #
# 3R — local-LLM slots: provider routing, per-slot params, slot tagging,
# bounded keep-last (degraded mode)
# --------------------------------------------------------------------------- #


def test_ollama_provider_routes_to_local_caller(monkeypatch):
    import src.intraday.local_llm as local_llm

    seen = {}

    def fake_ollama(url, model, prompt, **kw):
        seen["url"], seen["model"] = url, model
        return '{"R.NS": "long"}'

    monkeypatch.setattr(local_llm, "ollama_generate", fake_ollama)
    # Placeholder Gemini creds on purpose: ollama needs no key to be live.
    eng = LLMSignalEngine(IntradayConfig(), provider="ollama", model="qwen3:8b")
    out = eng.generate({"R.NS": _frame("10:30")})
    assert out["R.NS"].iloc[-1] == 1
    assert seen == {"url": "http://localhost:11434", "model": "qwen3:8b"}

    # No model override → the config default model.
    seen.clear()
    LLMSignalEngine(IntradayConfig(), provider="ollama").generate({"R.NS": _frame("10:45")})
    assert seen["model"] == "llama3.1:8b"


def test_builtin_params_build_two_engines_with_different_models():
    a = build_builtin_engine("llm_trader", IntradayConfig(), slot_name="llm_local_a",
                             provider="ollama", model="llama3.1:8b")
    b = build_builtin_engine("llm_trader", IntradayConfig(), slot_name="llm_local_b",
                             provider="ollama", model="qwen3:8b")
    assert (a.provider, a.model, a.slot_name) == ("ollama", "llama3.1:8b", "llm_local_a")
    assert (b.provider, b.model, b.slot_name) == ("ollama", "qwen3:8b", "llm_local_b")
    assert a.allow_short is False and b.allow_short is False  # long-only slots (3R scope)


def test_unknown_param_fails_fast_in_builtin_factory():
    with pytest.raises(TypeError):
        build_builtin_engine("llm_trader", IntradayConfig(), providr="ollama")  # typo'd key


def test_slot_name_tags_journal_and_failure_log(caplog):
    import logging

    journal = _ListJournal()
    eng = LLMSignalEngine(llm_call=lambda p: '{"R.NS": "long"}', journal=journal,
                          slot_name="llm_local_a")
    eng.generate({"R.NS": _frame("10:30")})
    assert journal.records[0]["slot"] == "llm_local_a"

    def boom(p):
        raise RuntimeError("down")

    failing = LLMSignalEngine(llm_call=boom, slot_name="llm_local_b")
    with caplog.at_level(logging.WARNING, logger="src.intraday.llm_engine"):
        failing.generate({"R.NS": _frame("10:45")})
    assert any("llm_local_b" in r.getMessage() for r in caplog.records)


def test_degraded_after_three_failures_goes_flat_not_frozen():
    calls = {"n": 0}

    def flaky(p):
        calls["n"] += 1
        if calls["n"] == 1:
            return '{"R.NS": "long"}'
        raise RuntimeError("down")

    journal = _ListJournal()
    eng = LLMSignalEngine(llm_call=flaky, journal=journal)
    assert eng.generate({"R.NS": _frame("10:30")})["R.NS"].iloc[-1] == 1
    # Failures 1 and 2: keep-last still holds the long.
    assert eng.generate({"R.NS": _frame("10:45")})["R.NS"].iloc[-1] == 1
    assert eng.generate({"R.NS": _frame("11:00")})["R.NS"].iloc[-1] == 1
    assert not eng.degraded
    # 3rd consecutive failure → DEGRADED: flat, which closes the stale long.
    assert eng.generate({"R.NS": _frame("11:15")})["R.NS"].iloc[-1] == 0
    assert eng.degraded
    decisions = [r for r in journal.records if r["kind"] == "decision"]
    assert decisions[-1]["degraded"] is True and decisions[-1]["decision"] == "flat"
    assert decisions[-2]["degraded"] is False


def test_success_resets_failure_counter():
    # Unparseable replies count as failures too; a good reply resets the run.
    replies = iter(["garbage", "garbage", '{"R.NS": "flat"}', "garbage", "garbage"])
    eng = LLMSignalEngine(llm_call=lambda p: next(replies))
    for hhmm in ("10:30", "10:45", "11:00", "11:15", "11:30"):
        eng.generate({"R.NS": _frame(hhmm)})
    assert not eng.degraded          # never hit 3 consecutive (2, reset, 2)
    assert eng._fail_count == 2


def test_no_params_ctor_regression_stays_long_only_gemini():
    eng = LLMSignalEngine()
    assert (eng.provider, eng.model, eng.slot_name) == ("gemini", None, "llm_trader")
    assert eng.allow_short is False and eng.degraded is False
    # No config → no caller → permanently flat, exactly as before 3R.
    assert eng.generate({"R.NS": _frame("10:30")})["R.NS"].iloc[-1] == 0


def test_portfolio_builds_builtin_slot():
    from src.intraday.bars import ReplayBarSource
    from src.intraday.config import StrategyRef
    from src.intraday.notifier import LogSink, TradeNotifier
    from src.intraday.portfolio import Portfolio
    from dataclasses import replace

    cfg = replace(IntradayConfig(), roster=(StrategyRef("llm_trader", "builtin:llm_trader"),))
    p = Portfolio(
        cfg,
        ReplayBarSource({}),
        notifier=TradeNotifier(LogSink(), mode="PAPER"),
    )
    assert len(p.slots) == 1
    assert isinstance(p.slots[0].runner._engine, LLMSignalEngine)
