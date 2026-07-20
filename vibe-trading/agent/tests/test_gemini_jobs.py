"""Offline tests for the 3O bookend reliability work (BUG-006).

Covers the bounded transient retry in ``gemini_jobs._call``, the local-Ollama
fallback path (``[local]`` prefix), the aggregated large-session EOD prompt,
``ollama_generate`` parsing, and the new ollama config fields. No live network
anywhere — httpx is only used to construct exception/response objects.

Run:  cd vibe-trading/agent && set PYTHONPATH=. && \
      python -m pytest tests/test_gemini_jobs.py -q
"""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from src.intraday import gemini_jobs
from src.intraday.clock import IST
from src.intraday.config import IntradayConfig
from src.intraday.gemini_jobs import _call, eod_review
from src.intraday.local_llm import ollama_generate
from src.intraday.paper_broker import Fill
from src.intraday.scoreboard import compute_metrics


def _timeout():
    return httpx.ReadTimeout("read timed out")


def _status_error(code):
    req = httpx.Request("POST", "http://api.test/generate")
    return httpx.HTTPStatusError(
        f"HTTP {code}", request=req, response=httpx.Response(code, request=req)
    )


# --------------------------------------------------------------------------- #
# _call — bounded transient retry
# --------------------------------------------------------------------------- #


def test_call_retries_transient_then_succeeds():
    outcomes = iter([_timeout(), _status_error(429), "recovered text"])
    calls = []

    def flaky(prompt):
        calls.append(prompt)
        out = next(outcomes)
        if isinstance(out, Exception):
            raise out
        return out

    sleeps = []
    text = _call(flaky, "p", fallback="(none)", sleep_fn=sleeps.append)
    assert text == "recovered text"
    assert len(calls) == 3
    assert sleeps == [2.0, 8.0]  # 2s then 8s between the three attempts


def test_call_does_not_retry_non_transient():
    calls = []

    def broken(prompt):
        calls.append(prompt)
        raise ValueError("bad prompt")  # not a network condition

    sleeps = []
    assert _call(broken, "p", fallback="(none)", sleep_fn=sleeps.append) == "(none)"
    assert len(calls) == 1 and sleeps == []


def test_call_4xx_other_than_429_is_not_retried():
    calls = []

    def unauthorized(prompt):
        calls.append(prompt)
        raise _status_error(401)

    assert _call(unauthorized, "p", fallback="(none)", sleep_fn=lambda s: None) == "(none)"
    assert len(calls) == 1


def test_call_exhausted_retries_use_local_fallback_with_prefix():
    def dead(prompt):
        raise _status_error(429)  # quota-429: retries can't fix it (BUG-006)

    dead.fallback = lambda prompt: "local model wrote this"
    text = _call(dead, "p", fallback="(none)", sleep_fn=lambda s: None)
    assert text == "[local] local model wrote this"


def test_call_exhausted_without_fallback_returns_static_string():
    def dead(prompt):
        raise _timeout()

    assert _call(dead, "p", fallback="(no review)", sleep_fn=lambda s: None) == "(no review)"


def test_call_fallback_failure_still_returns_static_string():
    def dead(prompt):
        raise _timeout()

    def dead_local(prompt):
        raise ConnectionError("ollama not running")

    dead.fallback = dead_local
    assert _call(dead, "p", fallback="(no review)", sleep_fn=lambda s: None) == "(no review)"


def test_make_llm_caller_attaches_ollama_fallback(monkeypatch):
    cfg = IntradayConfig.load(
        json_path="___does_not_exist___.json", env={"GEMINI_API_KEY": "AIza-real"}
    )
    import src.intraday.local_llm as local_llm

    monkeypatch.setattr(
        local_llm, "ollama_generate", lambda url, model, prompt, **kw: f"{url}|{model}"
    )
    caller = gemini_jobs.make_llm_caller(cfg)
    assert caller.fallback("x") == "http://localhost:11434|llama3.1:8b"


def test_stub_caller_has_no_fallback():
    caller = gemini_jobs.make_llm_caller(IntradayConfig())  # placeholder key
    assert getattr(caller, "fallback", None) is None


# --------------------------------------------------------------------------- #
# eod_review — aggregate past 40 fills
# --------------------------------------------------------------------------- #


def _fill(sym, side, pnl=0.0, fee=2.0):
    return Fill(sym, side, 5, 100.0, fee, datetime(2026, 7, 17, 12, 0, tzinfo=IST),
                realized_pnl=pnl)


def test_eod_review_aggregates_per_pair_when_fills_exceed_limit():
    fills = [_fill("R.NS", "buy") for _ in range(50)]  # > 40 → aggregate branch
    orb_fills = [_fill("R.NS", "sell", pnl=120.0), _fill("T.NS", "sell", pnl=-80.0)]
    orb_ls_fills = [_fill("R.NS", "cover", pnl=45.0)]  # short leg on the twin
    metrics = [
        compute_metrics("orb", 25_000, orb_fills),
        compute_metrics("orb_ls", 25_000, orb_ls_fills),
        compute_metrics("pullback", 25_000, [], halted=True, halt_reason="kill-switch"),
        compute_metrics("pullback_ls", 25_000, []),
    ]
    seen = {}

    def capture(prompt):
        seen["prompt"] = prompt
        return "review"

    out = eod_review(
        IntradayConfig(), capture, fills, realized_pnl=85.0, metrics=metrics,
        fills_by_strategy={"orb": orb_fills, "orb_ls": orb_ls_fills},
    )
    assert out == "review"
    p = seen["prompt"]
    # B4-2: one pair-collapsed line, long leg vs its short-capable twin
    assert "orb: long ₹+40 / ls ₹+45 (short leg ₹+45)" in p
    assert "best R.NS ₹+165" in p and "worst T.NS ₹-80" in p  # combined across legs
    assert "pullback: long ₹+0 / ls ₹+0" in p and "[RETIRED]" in p
    assert "top-2 and bottom-2 pairs" in p
    assert "12:00 BUY" not in p  # raw fill lines are gone from the big prompt


def test_eod_review_small_session_keeps_raw_fill_lines():
    fills = [_fill("R.NS", "buy"), _fill("R.NS", "sell", pnl=50.0)]
    seen = {}

    def capture(prompt):
        seen["prompt"] = prompt
        return "review"

    eod_review(IntradayConfig(), capture, fills, realized_pnl=50.0,
               metrics=[compute_metrics("orb", 25_000, fills)])
    assert "12:00 BUY 5 R.NS" in seen["prompt"]  # small day → unchanged raw journal


# --------------------------------------------------------------------------- #
# ollama_generate — parse + error envelope
# --------------------------------------------------------------------------- #


def test_ollama_generate_parses_response(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["json"] = kwargs.get("json")
        return httpx.Response(
            200, json={"response": "hello from llama"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    out = ollama_generate("http://localhost:11434/", "llama3.1:8b", "hi")
    assert out == "hello from llama"
    assert seen["url"] == "http://localhost:11434/api/generate"  # trailing / stripped
    assert seen["json"]["model"] == "llama3.1:8b"
    assert seen["json"]["stream"] is False
    assert seen["json"]["think"] is False  # qwen3 latency; ignored by llama3.1
    assert seen["json"]["options"]["num_ctx"] == 16384  # 38-sym prompt > 8k tokens


def test_ollama_generate_raises_on_http_error(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(httpx.HTTPStatusError):
        ollama_generate("http://localhost:11434", "llama3.1:8b", "hi")


# --------------------------------------------------------------------------- #
# config — ollama fields
# --------------------------------------------------------------------------- #


def test_config_ollama_defaults_and_env_override():
    cfg = IntradayConfig()
    assert cfg.ollama_url == "http://localhost:11434"
    assert cfg.ollama_model == "llama3.1:8b"
    cfg = IntradayConfig.load(
        json_path="___does_not_exist___.json",
        env={"VIBE_INTRADAY_OLLAMA_URL": "http://gpu-box:11434",
             "VIBE_INTRADAY_OLLAMA_MODEL": "qwen3:8b"},
    )
    assert (cfg.ollama_url, cfg.ollama_model) == ("http://gpu-box:11434", "qwen3:8b")
