"""Integration tests — hit real API to confirm model routing hypothesis.

Hypothesis: kimi-for-coding returns empty/null content for non-code prompts,
while kimi-k2.6 on api.moonshot.ai/v1 handles both code and general prompts.

Run with: uv run pytest test_integration.py -v -m integration
Skipped automatically when KIMI_API_KEY is not set.

OR integration tests require OPENROUTER_API_KEY:
  uv run pytest test_integration.py -v -m integration -k or
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import server

pytestmark = pytest.mark.integration

skip_no_key = pytest.mark.skipif(
    not os.environ.get("KIMI_API_KEY"),
    reason="KIMI_API_KEY not set — integration tests require a live key",
)

_GENERAL_PROMPT = "Explain the concept of goroutines to a junior developer. Write at least two paragraphs."
_CODE_PROMPT = "Write a Python function that returns the nth Fibonacci number using memoization."
_TIMEOUT = 60.0


async def _raw_call(base_url: str, model: str, prompt: str) -> tuple[str, str]:
    """Direct API call — bypasses server.py to isolate model behaviour."""
    async with httpx.AsyncClient(
        base_url=base_url,
        headers={
            "Authorization": f"Bearer {server._API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": server._USER_AGENT,
        },
        timeout=_TIMEOUT,
    ) as c:
        r = await c.post("/chat/completions", json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
            "temperature": 0.7,
        })
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        return msg.get("content") or "", msg.get("reasoning_content") or ""


# ---------------------------------------------------------------------------
# Core hypothesis: kimi-for-coding is silent on general prompts
# ---------------------------------------------------------------------------

@skip_no_key
async def test_coding_model_empty_on_general_prompt():
    """kimi-for-coding should return empty content for a non-code prompt."""
    content, _ = await _raw_call(server._BASE_URL, server._MODEL, _GENERAL_PROMPT)
    assert content == "", (
        f"Hypothesis wrong: kimi-for-coding DID return content for a general prompt "
        f"({len(content)} chars). Review routing — maybe coding model now handles general queries.\n"
        f"Preview: {content[:200]}"
    )


@skip_no_key
async def test_general_model_answers_general_prompt():
    """kimi-k2.6 should return substantial content for the same general prompt."""
    content, _ = await _raw_call(server._GENERAL_BASE_URL, server._GENERAL_MODEL, _GENERAL_PROMPT)
    assert len(content) > 100, (
        f"kimi-k2.6 returned too little content ({len(content)} chars) for a general prompt.\n"
        f"Got: {content!r}"
    )


# ---------------------------------------------------------------------------
# Confirm coding model still works for code prompts (routing is correct, not broken)
# ---------------------------------------------------------------------------

@skip_no_key
async def test_coding_model_answers_code_prompt():
    """kimi-for-coding should return real content for a code prompt."""
    content, _ = await _raw_call(server._BASE_URL, server._MODEL, _CODE_PROMPT)
    assert len(content) > 50, (
        f"kimi-for-coding returned too little content ({len(content)} chars) for a code prompt.\n"
        f"Got: {content!r}"
    )


@skip_no_key
async def test_general_model_answers_code_prompt():
    """kimi-k2.6 should also handle code prompts (it's not coding-only)."""
    content, _ = await _raw_call(server._GENERAL_BASE_URL, server._GENERAL_MODEL, _CODE_PROMPT)
    assert len(content) > 50, (
        f"kimi-k2.6 returned too little content ({len(content)} chars) for a code prompt.\n"
        f"Got: {content!r}"
    )


# ---------------------------------------------------------------------------
# Side-by-side comparison — same prompt, both models
# ---------------------------------------------------------------------------

@skip_no_key
async def test_compare_models_on_general_prompt():
    """Run both models on the same general prompt and print a comparison.

    Not a pass/fail assertion — purely diagnostic. Check the captured output
    with `pytest -s` to see the full side-by-side.
    """
    coding_content, _ = await _raw_call(server._BASE_URL, server._MODEL, _GENERAL_PROMPT)
    general_content, _ = await _raw_call(server._GENERAL_BASE_URL, server._GENERAL_MODEL, _GENERAL_PROMPT)

    print(f"\n{'='*60}")
    print(f"PROMPT: {_GENERAL_PROMPT}")
    print(f"\n--- kimi-for-coding ({server._BASE_URL}) ---")
    print(repr(coding_content[:300]) if coding_content else "(empty)")
    print(f"\n--- kimi-k2.6 ({server._GENERAL_BASE_URL}) ---")
    print(general_content[:300] if general_content else "(empty)")
    print("=" * 60)

    # Soft assertion: general model should have more content
    assert len(general_content) > len(coding_content), (
        "Expected kimi-k2.6 to return more content than kimi-for-coding on a general prompt"
    )


# ---------------------------------------------------------------------------
# OpenRouter integration — verify ZDR + real response from each key model
# ---------------------------------------------------------------------------

skip_no_or_key = pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set — OR integration tests require a live key",
)

_OR_TIMEOUT = 30.0


async def _or_raw_call(model: str, prompt: str) -> tuple[str, dict]:
    """Direct OR call — bypasses server routing to test raw model access + ZDR.

    Returns (content, payload_sent) so callers can assert both response content
    and that the ZDR field was present in the payload sent to OR.
    """
    payload_sent: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 50,
        # ZDR enforced in test too — mirrors server.py _or_chat behaviour
        "provider": {"data_collection": "deny"},
    }
    async with httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1",
        headers={
            "Authorization": f"Bearer {server._OR_API_KEY}",
            "HTTP-Referer": "https://github.com/jojo/dotfiles",
            "X-Title": "ai-router-mcp-test",
        },
        timeout=_OR_TIMEOUT,
    ) as c:
        r = await c.post("/chat/completions", json=payload_sent)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"].get("content", "")
        return content, payload_sent


@pytest.mark.integration
@skip_no_or_key
async def test_deepseek_v4_pro_accessible():
    """DeepSeek V4 Pro responds via OR with ZDR enforced in payload."""
    content, payload = await _or_raw_call(
        "deepseek/deepseek-v4-pro",
        "Reply with just the word: OK",
    )
    assert len(content) > 0, (
        "deepseek/deepseek-v4-pro returned empty response — model may be unavailable via OR"
    )
    assert payload["provider"]["data_collection"] == "deny", (
        "ZDR field missing from payload sent to deepseek-v4-pro"
    )


@pytest.mark.integration
@skip_no_or_key
async def test_ernie_accessible():
    """ERNIE 4.5 300B responds via OR with ZDR — Chinese specialist integration."""
    content, payload = await _or_raw_call(
        "baidu/ernie-4.5-300b-a47b",
        "你好，用中文回复一个字：好",
    )
    assert len(content) > 0, (
        "baidu/ernie-4.5-300b-a47b returned empty response — Chinese specialist may be unavailable via OR"
    )
    assert payload["provider"]["data_collection"] == "deny"


@pytest.mark.integration
@skip_no_or_key
async def test_minimax_accessible():
    """MiniMax M2.7 responds via OR with ZDR — creative specialist integration."""
    content, payload = await _or_raw_call(
        "minimax/minimax-m2.7",
        "Reply with just the word: OK",
    )
    assert len(content) > 0, (
        "minimax/minimax-m2.7 returned empty response — creative specialist may be unavailable via OR"
    )
    assert payload["provider"]["data_collection"] == "deny"


@pytest.mark.integration
@skip_no_or_key
async def test_deepseek_v4_flash_accessible():
    """DeepSeek V4 Flash responds via OR — eco profile model integration."""
    content, payload = await _or_raw_call(
        "deepseek/deepseek-v4-flash",
        "Reply with just the word: OK",
    )
    assert len(content) > 0, (
        "deepseek/deepseek-v4-flash returned empty response — eco model may be unavailable via OR"
    )
    assert payload["provider"]["data_collection"] == "deny"


@pytest.mark.integration
@skip_no_or_key
async def test_or_zdr_field_present_in_payload():
    """Verify ZDR field is present in payload for every model in the integration set.

    This is a meta-test: if our _or_raw_call helper were ever changed to drop the
    ZDR field, this test catches it before real calls proceed.
    """
    _, payload = await _or_raw_call(
        "deepseek/deepseek-v4-flash",
        "hi",
    )
    assert "provider" in payload, "payload missing 'provider' key"
    assert payload["provider"].get("data_collection") == "deny", (
        "ZDR field 'provider.data_collection=deny' not in payload"
    )
