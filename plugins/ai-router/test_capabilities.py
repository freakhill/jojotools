"""
Capability routing tests — verify that our model selection matches company-advertised strengths.

These are routing tests: we assert that the correct model ID is selected for each
task category. We don't test model output quality (that would require live API calls).

Each test documents WHY a model is best for its category (benchmark source or
company-advertised claim). The assertion message is the living documentation —
if a test fails after a model swap, read the message to understand what was broken.

Test structure:
  Section 1 — Specialist routing via task_hint (or_ask auto-routing)
  Section 2 — Profile routing (or_ask with profile= set)
  Section 3 — Adversarial: verify wrong models are NOT selected
  Section 4 — _route_or_model direct routing table coverage

No live API calls. All HTTP is mocked via mock_or_client fixture.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent))

os.environ.setdefault("KIMI_API_KEY", "sk-kimi-test")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-test")

import server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _or_resp(content: str = "test response") -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.raise_for_status.return_value = None
    mock.json.return_value = {
        "choices": [{"message": {"content": content, "reasoning_content": ""}}]
    }
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _zero_backoff(monkeypatch):
    monkeypatch.setattr(server, "_RETRY_BACKOFF", 0.0)


@pytest.fixture
def mock_or_client(monkeypatch):
    """Mock the OR httpx client — prevents real API calls in unit tests."""
    client = MagicMock()
    client.post = AsyncMock(return_value=_or_resp("test response"))
    client.get = AsyncMock(return_value=_or_resp())
    monkeypatch.setattr(server, "_or_client", client)
    monkeypatch.setattr(server, "_OR_API_KEY", "sk-or-test-key")
    return client


@pytest.fixture
def no_kimi(monkeypatch):
    """Disable Kimi subscription so OR routing is always exercised."""
    monkeypatch.setattr(server, "_API_KEY", "")


# ---------------------------------------------------------------------------
# Section 1 — Specialist routing via task_hint
#
# Pattern: call or_ask with a specific task_hint and model="auto",
# capture the model in the outbound payload, assert the correct specialist.
# host_token_pressure=True skips the host-redirect check so we always reach OR.
# ---------------------------------------------------------------------------

async def test_deepseek_v4_pro_used_for_reasoning(mock_or_client, no_kimi):
    """DeepSeek V4 Pro: 80.6% SWE-bench Verified, 95.2% HMMT math (company advertised)."""
    await server.or_ask(
        "prove that sqrt(2) is irrational",
        task_hint="reasoning",
        model="auto",
        host_token_pressure=True,
    )
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "deepseek/deepseek-v4-pro", (
        "reasoning tasks should use DeepSeek V4 Pro "
        "(80.6% SWE-bench, 95.2% HMMT math — company-advertised reasoning leader)"
    )


async def test_deepseek_v4_pro_used_for_math(mock_or_client, no_kimi):
    """DeepSeek V4 Pro: best math performance (95.2% HMMT)."""
    await server.or_ask(
        "solve this integral",
        task_hint="math",
        model="auto",
        host_token_pressure=True,
    )
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "deepseek/deepseek-v4-pro", (
        "math tasks should use DeepSeek V4 Pro (95.2% HMMT — company-advertised math champion)"
    )


async def test_minimax_used_for_creative(mock_or_client, monkeypatch):
    """MiniMax M2.7: advertised as creative writing specialist with narrative depth."""
    monkeypatch.setattr(server, "_API_KEY", "")
    await server.or_ask(
        "write a short story about a lost robot",
        task_hint="creative",
        model="auto",
        host_token_pressure=True,
    )
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "minimax/minimax-m2.7", (
        "creative tasks must use MiniMax M2.7 (advertised creative + narrative specialist)"
    )


async def test_minimax_used_for_story(mock_or_client, monkeypatch):
    """MiniMax M2.7: also routes on 'story' keyword."""
    monkeypatch.setattr(server, "_API_KEY", "")
    await server.or_ask("tell me a story", task_hint="story", model="auto", host_token_pressure=True)
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "minimax/minimax-m2.7"


async def test_minimax_used_for_fiction(mock_or_client, monkeypatch):
    """MiniMax M2.7: routes on 'fiction' keyword."""
    monkeypatch.setattr(server, "_API_KEY", "")
    await server.or_ask("write fiction", task_hint="fiction", model="auto", host_token_pressure=True)
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "minimax/minimax-m2.7"


async def test_deepseek_flash_for_fast_task(mock_or_client, no_kimi):
    """DeepSeek V4 Flash: advertised as fastest/cheapest capable model ($0.112/M)."""
    await server.or_ask(
        "summarize this text quickly",
        task_hint="fast",
        model="auto",
        host_token_pressure=True,
    )
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "deepseek/deepseek-v4-flash", (
        "fast tasks should use deepseek-v4-flash ($0.112/M — company-advertised fastest cheap model)"
    )


async def test_deepseek_flash_for_batch_task(mock_or_client, no_kimi):
    """DeepSeek V4 Flash: also routes on 'batch' and 'cheap' keywords."""
    await server.or_ask(
        "process these items in batch",
        task_hint="batch",
        model="auto",
        host_token_pressure=True,
    )
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "deepseek/deepseek-v4-flash"


async def test_deepseek_v4_pro_for_ultra_long(mock_or_client, no_kimi):
    """DeepSeek V4 Pro: 1.05M context fallback for ultra-long tasks (xAI/Grok banned)."""
    await server.or_ask(
        "analyze this 800K token document",
        task_hint="ultra long context",
        model="auto",
        host_token_pressure=True,
    )
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "deepseek/deepseek-v4-pro", (
        "ultra-long-context tasks should use deepseek-v4-pro (1.05M ctx — xAI/Grok is banned)"
    )


async def test_deepseek_v4_pro_for_coding_no_kimi(mock_or_client, no_kimi):
    """DeepSeek V4 Pro: fallback for coding when Kimi subscription is unavailable."""
    await server.or_ask(
        "refactor this function",
        task_hint="coding",
        model="auto",
        host_token_pressure=True,
    )
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "deepseek/deepseek-v4-pro", (
        "coding tasks without Kimi subscription should fall back to deepseek-v4-pro"
    )


# ---------------------------------------------------------------------------
# Section 2 — Profile routing (or_ask with profile=)
#
# Profiles control the default model when no specialist override applies.
# We verify each profile's primary model is selected for a neutral task
# (one that triggers no specialist override and no subscription route).
# host_token_pressure=True is NOT set here — profiles already opt out of host-redirect.
# ---------------------------------------------------------------------------

async def test_deepseek_flash_eco_profile(mock_or_client, no_kimi):
    """DeepSeek V4 Flash: eco profile primary model — cheapest capable ($0.112/M)."""
    await server.or_ask("summarize this text", profile="eco", model="auto")
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "deepseek/deepseek-v4-flash", (
        "eco profile must use deepseek-v4-flash (company-advertised cheapest + fast)"
    )


async def test_qwen_mid_profile(mock_or_client, no_kimi):
    """Qwen3.5-Plus: mid profile primary model — balanced quality/cost at $0.30/M."""
    await server.or_ask("answer this question", profile="mid", model="auto")
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "qwen/qwen3.5-plus-20260420", (
        "mid profile must use qwen3.5-plus-20260420 (balanced quality/cost)"
    )


async def test_deepseek_intel_profile(mock_or_client, no_kimi):
    """DeepSeek V4 Pro: intel profile — best reasoning at moderate cost ($0.44/M)."""
    await server.or_ask("analyze this", profile="intel", model="auto")
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "deepseek/deepseek-v4-pro", (
        "intel profile must use deepseek-v4-pro (80.6% SWE-bench, reasoning leader)"
    )


async def test_mimo_max_profile_general(mock_or_client, no_kimi):
    """MiMo V2.5 Pro: max profile primary model — #1 OpenRouter usage, general quality peak."""
    await server.or_ask("explain quantum entanglement", profile="max", model="auto")
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "xiaomi/mimo-v2.5-pro", (
        "max profile general tasks must use MiMo V2.5 Pro (#1 OpenRouter usage, general quality)"
    )


async def test_deepseek_research_profile(mock_or_client, no_kimi):
    """DeepSeek V4 Pro: research profile — 1.05M context for long-doc synthesis."""
    await server.or_ask(
        "synthesize this long document",
        profile="research",
        task_hint="long document analysis",
        model="auto",
    )
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "deepseek/deepseek-v4-pro", (
        "research profile must use deepseek-v4-pro (1.05M ctx window for synthesis)"
    )


async def test_deepseek_max_profile_reasoning(mock_or_client, no_kimi):
    """max+reasoning uses deepseek-v4-pro (80.6% SWE-bench), overriding mimo default."""
    await server.or_ask(
        "prove this theorem formally",
        profile="max",
        task_hint="reasoning",
        model="auto",
    )
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "deepseek/deepseek-v4-pro", (
        "max profile + reasoning hint must route to deepseek-v4-pro (not mimo), "
        "because deepseek wins SWE-bench at lower cost"
    )


async def test_mimo_max_profile_narrative(mock_or_client, no_kimi):
    """MiMo V2.5 Pro: max profile + narrative/general uses mimo (not deepseek)."""
    # 'narrative' is a specialist hint that routes to minimax, so use a neutral hint
    await server.or_ask(
        "explain this complex concept",
        profile="max",
        model="auto",
    )
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "xiaomi/mimo-v2.5-pro", (
        "max profile general task must still use mimo-v2.5-pro (not deepseek)"
    )


# ---------------------------------------------------------------------------
# Section 3 — Specialist overrides profile (priority: specialist > profile default)
# ---------------------------------------------------------------------------

async def test_specialist_minimax_overrides_eco_profile(mock_or_client, no_kimi):
    """Specialist always overrides profile: creative → MiniMax even with eco profile."""
    await server.or_ask(
        "write a poem",
        profile="eco",
        task_hint="creative",
        model="auto",
        host_token_pressure=True,
    )
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "minimax/minimax-m2.7", (
        "Creative specialist must override eco profile (use MiniMax, not deepseek-flash)"
    )


async def test_flash_not_used_for_max_profile(mock_or_client, no_kimi):
    """max profile must NOT use deepseek-v4-flash (eco model)."""
    await server.or_ask("complex task", profile="max", model="auto")
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert "flash" not in payload["model"], (
        "max profile must not degrade to flash (eco model)"
    )


async def test_mimo_not_used_for_max_reasoning(mock_or_client, no_kimi):
    """max+reasoning must NOT use mimo — deepseek-v4-pro wins on reasoning benchmarks."""
    await server.or_ask(
        "formal proof task",
        profile="max",
        task_hint="reasoning",
        model="auto",
    )
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert "mimo" not in payload["model"], (
        "max+reasoning must NOT use mimo — deepseek-v4-pro wins SWE-bench for this task"
    )


async def test_openai_never_routed(mock_or_client, no_kimi):
    """openai/* must never appear in a routed payload — it's on the banlist."""
    # Try to force it via explicit model= — should error, not silently call openai
    result = await server.or_ask("hi", model="openai/gpt-5.5")
    # The result is an error string — the important thing is no HTTP was made with openai
    # Verify no call with openai was made
    for call in mock_or_client.post.call_args_list:
        payload = call.kwargs.get("json", {})
        assert "openai" not in payload.get("model", ""), (
            "openai model appeared in an OR payload — it's banned and must never be called"
        )


async def test_xai_never_routed(mock_or_client, no_kimi):
    """x-ai/* must never appear in a routed payload — it's on the banlist."""
    result = await server.or_ask("hi", model="x-ai/grok-4.20")
    for call in mock_or_client.post.call_args_list:
        payload = call.kwargs.get("json", {})
        assert "x-ai" not in payload.get("model", ""), (
            "xAI model appeared in an OR payload — it's banned and must never be called"
        )


async def test_auto_routing_no_hint_returns_alternatives_not_model(mock_or_client, no_kimi):
    """or_ask with model=auto and no task_hint must return alternatives table, not pick a random model."""
    result = await server.or_ask("do something", model="auto")
    # Should return alternatives table, not an API call
    assert mock_or_client.post.call_count == 0, (
        "or_ask with no task_hint should return alternatives table without calling OR"
    )
    assert "model" in result.lower() or "routing" in result.lower() or "alternative" in result.lower()


# ---------------------------------------------------------------------------
# Section 5 — or_swarm capability routing
# ---------------------------------------------------------------------------

async def test_or_swarm_creative_routes_to_minimax(mock_or_client, no_kimi):
    """or_swarm with creative hint routes to MiniMax (same routing table as or_ask)."""
    await server.or_swarm(
        "write a long-form story",
        task_hint="creative",
        host_token_pressure=True,
    )
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "minimax/minimax-m2.7"


async def test_or_swarm_default_uses_deepseek_v4_pro(mock_or_client, no_kimi):
    """or_swarm with no task_hint defaults to deepseek-v4-pro (best cost/quality for complex tasks)."""
    await server.or_swarm("design a distributed system architecture")
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "deepseek/deepseek-v4-pro", (
        "or_swarm with no task_hint must default to deepseek-v4-pro (best reasoning for complex tasks)"
    )


async def test_or_swarm_reasoning_routes_to_deepseek(mock_or_client, no_kimi):
    """or_swarm with reasoning hint uses deepseek-v4-pro."""
    await server.or_swarm(
        "prove this algorithm is correct",
        task_hint="reasoning",
        host_token_pressure=True,
    )
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload["model"] == "deepseek/deepseek-v4-pro"
