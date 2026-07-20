"""Local-LLM caller (Ollama) — zero-cost, quota-free fallback + trader brain.

Two consumers (both 3O/3R, 2026-07-17):

  * :func:`~src.intraday.gemini_jobs._call` runs the bookend prompt through
    local Ollama when Gemini's retries are exhausted (BUG-006: a quota-429
    cannot be retried away — the review should still get written).
  * The ``llm_local_a`` / ``llm_local_b`` roster slots (§3R) use it as their
    per-tick decision caller via ``LLMSignalEngine(provider="ollama")``.

Same contract as :func:`~src.intraday.gemini_jobs.gemini_generate`: prompt in,
completion text out, raise on HTTP/shape errors (callers convert failures to
their own fallbacks). Lives in the trusted overlay — localhost is still network,
so this must never move into ``strategies/`` run-dir code (VT-001).
"""

from __future__ import annotations


def ollama_generate(
    url: str, model: str, prompt: str, *, timeout: float = 120.0
) -> str:
    """One non-streaming ``/api/generate`` call against a local Ollama server.

    Args:
        url: Ollama base URL (default config: ``http://localhost:11434``).
        model: Model tag, e.g. ``llama3.1:8b`` / ``qwen3:8b``.
        prompt: The prompt text.
        timeout: Generous by default — a cold model load on the local GPU can
            take tens of seconds before the first token.

    Returns:
        The completion text.

    Raises:
        httpx.HTTPError / KeyError: on transport, non-2xx, or shape errors.
    """
    import httpx  # declared dep; imported lazily so tests need no network

    resp = httpx.post(
        f"{url.rstrip('/')}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            # num_ctx 16384: the 38-symbol tick prompt measures 9.6k–13.7k
            # tokens depending on tokenizer — 8192 silently truncates it and
            # the model stops after ~1 token (done_reason=length, measured
            # 2026-07-17). think=false: qwen3 answers 17s instead of 47s and
            # non-thinking models (llama3.1) ignore the flag.
            "think": False,
            "options": {"temperature": 0.2, "num_ctx": 16384},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["response"]
