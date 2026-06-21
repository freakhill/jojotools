"""
Unit tests for OpenRouter routing layer.

Covers:
  - ZDR enforcement (every OR call must include provider.data_collection = deny)
  - Banned provider guard (openai/*, x-ai/*)
  - Subscription blocked-from-OR guard (anthropic/*, moonshotai/*)
  - Profile routing (_resolve_profile_model — pure sync, no HTTP)

No live API calls. All HTTP traffic is intercepted by mock_or_client fixture.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))

# Set dummy keys before importing server so env-guarded branches are reachable
os.environ.setdefault("KIMI_API_KEY", "sk-kimi-test")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-or-test")

import server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _or_resp(content: str = "test response") -> MagicMock:
    """Mock a successful OR /chat/completions response."""
    mock = MagicMock()
    mock.status_code = 200
    mock.raise_for_status.return_value = None
    mock.json.return_value = {
        "choices": [{"message": {"content": content, "reasoning_content": ""}}]
    }
    return mock


def _or_resp_image(url: str = "https://example.com/image.png") -> MagicMock:
    """Mock a successful OR /images/generations response."""
    mock = MagicMock()
    mock.status_code = 200
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"data": [{"url": url}]}
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _zero_backoff(monkeypatch):
    """Disable retry sleep so tests run instantly."""
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


# ---------------------------------------------------------------------------
# Section 1 — ZDR enforcement
#
# Every OR call MUST include "provider": {"data_collection": "deny"}.
# Removing this field silently breaks the no-training guarantee.
# We test or_ask, or_swarm, or_image, and or_compare individually because
# or_image uses /images/generations (different path + payload shape) and
# or_compare fans out multiple _or_chat calls.
# ---------------------------------------------------------------------------

async def test_or_ask_zdr_enforced(mock_or_client, monkeypatch):
    """ZDR must be in every or_ask payload."""
    monkeypatch.setattr(server, "_API_KEY", "")  # no Kimi, force OR path
    await server.or_ask("what is 2+2?", model="deepseek/deepseek-v4-pro")
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload.get("provider", {}).get("data_collection") == "deny", (
        "ZDR not enforced — 'provider.data_collection: deny' missing from or_ask payload"
    )


async def test_or_ask_zdr_enforced_with_task_hint(mock_or_client, monkeypatch):
    """ZDR must be enforced even when task_hint triggers routing."""
    monkeypatch.setattr(server, "_API_KEY", "")
    monkeypatch.setattr(server, "_OR_API_KEY", "sk-or-test-key")
    await server.or_ask("write a story", task_hint="creative", model="minimax/minimax-m2.7")
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload.get("provider", {}).get("data_collection") == "deny", (
        "ZDR missing on or_ask with task_hint routing"
    )


async def test_or_swarm_zdr_enforced(mock_or_client, monkeypatch):
    """ZDR must be in every or_swarm payload."""
    monkeypatch.setattr(server, "_API_KEY", "")
    await server.or_swarm("design a system", model="deepseek/deepseek-v4-pro")
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload.get("provider", {}).get("data_collection") == "deny", (
        "ZDR not enforced in or_swarm payload"
    )


async def test_or_swarm_zdr_enforced_auto_model(mock_or_client, monkeypatch):
    """ZDR must be enforced when or_swarm auto-selects a model."""
    monkeypatch.setattr(server, "_API_KEY", "")
    # Provide a task_hint that routes to a non-Kimi model to ensure OR is called
    await server.or_swarm(
        "write a story",
        model="auto",
        task_hint="creative",
        host_token_pressure=True,  # skip host-redirect
    )
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload.get("provider", {}).get("data_collection") == "deny", (
        "ZDR missing on or_swarm auto-routed payload"
    )


async def test_or_image_zdr_enforced(mock_or_client, monkeypatch):
    """ZDR must be in every or_image payload — images endpoint is separate from _or_chat."""
    mock_or_client.post = AsyncMock(return_value=_or_resp_image())
    await server.or_image("a sunset over mountains", use_case="thumbnail_cinematic")
    payload = mock_or_client.post.call_args.kwargs["json"]
    assert payload.get("provider", {}).get("data_collection") == "deny", (
        "ZDR not enforced in or_image payload — images endpoint has its own payload builder"
    )


async def test_or_compare_zdr_enforced_on_all_calls(mock_or_client, monkeypatch):
    """ZDR must be enforced on ALL parallel model calls in or_compare."""
    monkeypatch.setattr(server, "_API_KEY", "")
    models = ["deepseek/deepseek-v4-pro", "minimax/minimax-m2.7"]
    await server.or_compare("compare these models", models=models)
    # or_compare fans out — assert every individual call had ZDR
    assert mock_or_client.post.call_count == len(models), (
        f"Expected {len(models)} OR calls, got {mock_or_client.post.call_count}"
    )
    for i, call in enumerate(mock_or_client.post.call_args_list):
        payload = call.kwargs["json"]
        assert payload.get("provider", {}).get("data_collection") == "deny", (
            f"ZDR missing on or_compare call {i} (model: {payload.get('model', '?')})"
        )


async def test_or_chat_directly_zdr_enforced(monkeypatch):
    """_or_chat internal function always injects ZDR into payload before sending."""
    monkeypatch.setattr(server, "_OR_API_KEY", "sk-or-test-key")
    captured_payload: dict = {}

    async def fake_post(path: str, **kwargs):
        captured_payload.update(kwargs.get("json", {}))
        return _or_resp("ok")

    fake_client = MagicMock()
    fake_client.post = fake_post
    monkeypatch.setattr(server, "_or_client", fake_client)

    await server._or_chat(
        [{"role": "user", "content": "hello"}],
        model="deepseek/deepseek-v4-pro",
    )
    assert captured_payload.get("provider", {}).get("data_collection") == "deny", (
        "_or_chat did not inject ZDR into payload"
    )


# ---------------------------------------------------------------------------
# Section 2 — Banned provider guard (openai/*, x-ai/*)
#
# These providers are refused entirely by user choice.
# The guard must fire BEFORE any HTTP call is made.
# ---------------------------------------------------------------------------

def test_is_banned_openai_prefix():
    assert server._is_banned("openai/gpt-5.5") is True


def test_is_banned_openai_dall_e():
    assert server._is_banned("openai/dall-e-3") is True


def test_is_banned_xai_grok():
    assert server._is_banned("x-ai/grok-4.20") is True


def test_is_banned_xai_anything():
    assert server._is_banned("x-ai/anything") is True


def test_is_banned_deepseek_not_banned():
    assert server._is_banned("deepseek/deepseek-v4-pro") is False


def test_is_banned_minimax_not_banned():
    assert server._is_banned("minimax/minimax-m2.7") is False


def test_is_banned_baidu_not_banned():
    assert server._is_banned("baidu/ernie-4.5-300b-a47b") is False


def test_is_banned_xiaomi_not_banned():
    assert server._is_banned("xiaomi/mimo-v2.5-pro") is False


# ---------------------------------------------------------------------------
# Section 2a — OpenRouter key sourced from 1Password (op), NOT the environment
#
# The key is fetched JIT from op://claude/openrouter-api-key and cached per
# process. There is no OPENROUTER_API_KEY env read. The conftest autouse fixture
# makes `op` look absent by default; these tests re-enable it with a mocked
# subprocess. ZDR and the ban guards are unaffected.
# ---------------------------------------------------------------------------

def test_read_or_key_from_op_picks_sk_or_field(monkeypatch):
    monkeypatch.setattr(server.shutil, "which", lambda _name: "/usr/bin/op")
    stdout = (
        '{"fields": [{"id": "username", "value": "jojo"}, '
        '{"id": "credential", "value": "sk-or-v1-abc123"}]}'
    )
    monkeypatch.setattr(
        server.subprocess, "run",
        lambda *a, **k: MagicMock(returncode=0, stdout=stdout),
    )
    assert server._read_or_key_from_op() == "sk-or-v1-abc123"


def test_read_or_key_from_op_no_op_binary(monkeypatch):
    """`op` not on PATH → empty, no subprocess attempted."""
    monkeypatch.setattr(server.shutil, "which", lambda _name: None)
    assert server._read_or_key_from_op() == ""


def test_read_or_key_from_op_signed_out(monkeypatch):
    """`op` present but signed out (returncode != 0) → empty."""
    monkeypatch.setattr(server.shutil, "which", lambda _name: "/usr/bin/op")
    monkeypatch.setattr(
        server.subprocess, "run",
        lambda *a, **k: MagicMock(returncode=1, stdout=""),
    )
    assert server._read_or_key_from_op() == ""


def test_get_or_api_key_caches_op_read(monkeypatch):
    """op is read once, then cached for the process lifetime."""
    monkeypatch.setattr(server, "_OR_API_KEY", "")
    calls = {"n": 0}

    def fake_read():
        calls["n"] += 1
        return "sk-or-cached"

    monkeypatch.setattr(server, "_read_or_key_from_op", fake_read)
    assert server._get_or_api_key() == "sk-or-cached"
    assert server._get_or_api_key() == "sk-or-cached"
    assert calls["n"] == 1


def test_or_key_never_read_from_env(monkeypatch):
    """OPENROUTER_API_KEY in the environment must be ignored — op is the only source."""
    monkeypatch.setattr(server, "_OR_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env-should-be-ignored")
    monkeypatch.setattr(server, "_read_or_key_from_op", lambda: "")
    assert server._get_or_api_key() == ""


def test_read_kimi_key_from_op_picks_sk_field(monkeypatch):
    """Kimi key stored as a Secure Note (notesPlain) starting with sk- is picked up."""
    monkeypatch.setattr(server.shutil, "which", lambda _name: "/usr/bin/op")
    stdout = '{"fields": [{"id": "notesPlain", "value": "sk-kimi-v1-xyz789"}]}'
    monkeypatch.setattr(
        server.subprocess, "run",
        lambda *a, **k: MagicMock(returncode=0, stdout=stdout),
    )
    assert server._read_kimi_key_from_op() == "sk-kimi-v1-xyz789"


def test_read_kimi_key_from_op_no_op_binary(monkeypatch):
    """`op` not on PATH → empty, no subprocess attempted."""
    monkeypatch.setattr(server.shutil, "which", lambda _name: None)
    assert server._read_kimi_key_from_op() == ""


def test_get_kimi_api_key_caches_op_read(monkeypatch):
    """op is read once, then cached for the process lifetime."""
    monkeypatch.setattr(server, "_API_KEY", "")
    calls = {"n": 0}

    def fake_read():
        calls["n"] += 1
        return "sk-kimi-cached"

    monkeypatch.setattr(server, "_read_kimi_key_from_op", fake_read)
    assert server._get_kimi_api_key() == "sk-kimi-cached"
    assert server._get_kimi_api_key() == "sk-kimi-cached"
    assert calls["n"] == 1


def test_kimi_key_falls_back_to_env_when_op_empty(monkeypatch):
    """Unlike the OR key, KIMI_API_KEY env IS a deliberate fallback when op yields nothing
    (transition / standalone / CI)."""
    monkeypatch.setattr(server, "_API_KEY", "")
    monkeypatch.setattr(server, "_read_kimi_key_from_op", lambda: "")
    monkeypatch.setenv("KIMI_API_KEY", "sk-kimi-env-fallback")
    assert server._get_kimi_api_key() == "sk-kimi-env-fallback"


def test_read_glm_key_from_op_picks_notes_field(monkeypatch):
    """GLM key stored as a Secure Note (notesPlain), no fixed prefix, is picked up."""
    monkeypatch.setattr(server.shutil, "which", lambda _name: "/usr/bin/op")
    stdout = '{"fields": [{"id": "notesPlain", "value": "glm-secret-xyz789"}]}'
    monkeypatch.setattr(
        server.subprocess, "run",
        lambda *a, **k: MagicMock(returncode=0, stdout=stdout),
    )
    assert server._read_glm_key_from_op() == "glm-secret-xyz789"


def test_read_glm_key_from_op_no_op_binary(monkeypatch):
    """`op` not on PATH → empty, no subprocess attempted."""
    monkeypatch.setattr(server.shutil, "which", lambda _name: None)
    assert server._read_glm_key_from_op() == ""


def test_get_glm_api_key_caches_op_read(monkeypatch):
    """op is read once, then cached for the process lifetime."""
    monkeypatch.setattr(server, "_GLM_API_KEY", "")
    calls = {"n": 0}

    def fake_read():
        calls["n"] += 1
        return "glm-cached"

    monkeypatch.setattr(server, "_read_glm_key_from_op", fake_read)
    assert server._get_glm_api_key() == "glm-cached"
    assert server._get_glm_api_key() == "glm-cached"
    assert calls["n"] == 1


def test_glm_key_falls_back_to_env_when_op_empty(monkeypatch):
    """GLM_API_KEY env is a deliberate fallback when op yields nothing."""
    monkeypatch.setattr(server, "_GLM_API_KEY", "")
    monkeypatch.setattr(server, "_read_glm_key_from_op", lambda: "")
    monkeypatch.setenv("GLM_API_KEY", "glm-env-fallback")
    assert server._get_glm_api_key() == "glm-env-fallback"


# ---------------------------------------------------------------------------
# Section 2b — Narrow GPT-5.5 exception allowlist to the openai/ ban
#
# OFF by default. Only the EXACT ids in _GPT_AUDIT_MODEL_IDS
# (openai/gpt-5.5-pro only — the originally-specced gpt-5.5-thinking does not exist), and only when
# AI_ROUTER_ALLOW_GPT55_AUDIT is truthy, are permitted past the ban. The general
# openai/ ban (and all x-ai/*) stays intact. ZDR is still enforced downstream.
# ---------------------------------------------------------------------------

def test_gpt_audit_exception_exact_id_only(monkeypatch):
    """Env set, but any other openai/* or x-ai/* id gets no exception."""
    monkeypatch.setenv(server._GPT_AUDIT_ENV, "1")
    assert server._gpt_audit_exception_allowed("openai/gpt-5.5") is False
    assert server._gpt_audit_exception_allowed("openai/gpt-4o") is False
    assert server._gpt_audit_exception_allowed("x-ai/grok-4.20") is False


def test_gpt_audit_exception_env_falsey(monkeypatch):
    monkeypatch.setenv(server._GPT_AUDIT_ENV, "0")
    assert server._gpt_audit_exception_allowed("openai/gpt-5.5-pro") is False


def test_gpt_audit_gate_file_enables_without_env(monkeypatch, tmp_path):
    """The chat-acceptance gate file enables the exception with no env var set."""
    monkeypatch.delenv(server._GPT_AUDIT_ENV, raising=False)
    gate = tmp_path / "gpt55-accepted"
    monkeypatch.setattr(server, "_GPT_AUDIT_GATE_FILE", gate)
    assert server._gpt_audit_exception_allowed("openai/gpt-5.5-pro") is False
    gate.write_text("ENABLE GPT-5.5 — I ACCEPT THE OPENAI-BAN EXCEPTION\n")
    assert server._gpt_audit_exception_allowed("openai/gpt-5.5-pro") is True
    # still narrow: a non-allowlisted id stays banned even with the gate file present
    assert server._gpt_audit_exception_allowed("openai/gpt-4o") is False


def test_gpt_audit_gate_file_empty_is_off(monkeypatch, tmp_path):
    """An empty / whitespace-only gate file must NOT enable the exception."""
    monkeypatch.delenv(server._GPT_AUDIT_ENV, raising=False)
    gate = tmp_path / "gpt55-accepted"
    gate.write_text("   \n")
    monkeypatch.setattr(server, "_GPT_AUDIT_GATE_FILE", gate)
    assert server._gpt_audit_exception_allowed("openai/gpt-5.5-pro") is False


def test_gpt_audit_exception_pro_off_by_default(monkeypatch):
    monkeypatch.delenv(server._GPT_AUDIT_ENV, raising=False)
    assert server._gpt_audit_exception_allowed("openai/gpt-5.5-pro") is False


def test_gpt_audit_exception_pro_on_with_env(monkeypatch):
    """openai/gpt-5.5-pro (added 2026-06-14 on request) passes only with the env opt-in."""
    monkeypatch.setenv(server._GPT_AUDIT_ENV, "1")
    assert server._gpt_audit_exception_allowed("openai/gpt-5.5-pro") is True


def test_gpt_audit_allowlist_is_exactly_one_id(monkeypatch):
    """The hole is exactly 1 id wide — only gpt-5.5-pro passes with env; every neighbour
    (incl. base gpt-5.5 and the non-existent gpt-5.5-thinking) stays banned."""
    monkeypatch.setenv(server._GPT_AUDIT_ENV, "1")
    assert server._GPT_AUDIT_MODEL_IDS == frozenset({"openai/gpt-5.5-pro"})
    assert server._gpt_audit_exception_allowed("openai/gpt-5.5-pro") is True
    # near-miss ids that must NOT slip through the hole
    for neighbour in (
        "openai/gpt-5.5",
        "openai/gpt-5.5-thinking",
        "openai/gpt-5.5-pro-thinking",
        "openai/gpt-5.5-mini",
        "openai/gpt-4o",
        "x-ai/grok-4.20",
    ):
        assert server._gpt_audit_exception_allowed(neighbour) is False


def test_gpt_audit_pro_base_ban_unchanged(monkeypatch):
    """Pro id is still reported banned by _is_banned; only the (banned AND NOT exception) gate opens."""
    monkeypatch.setenv(server._GPT_AUDIT_ENV, "1")
    assert server._is_banned("openai/gpt-5.5-pro") is True
    effective = server._is_banned("openai/gpt-5.5-pro") and not server._gpt_audit_exception_allowed(
        "openai/gpt-5.5-pro"
    )
    assert effective is False


async def test_gpt_audit_exception_allows_or_chat_pro_with_env(monkeypatch):
    """With env set, _or_chat reaches HTTP for openai/gpt-5.5-pro and still injects ZDR."""
    monkeypatch.setenv(server._GPT_AUDIT_ENV, "1")
    monkeypatch.setattr(server, "_OR_API_KEY", "sk-or-test-key")
    captured: dict = {}

    async def fake_post(path: str, **kwargs):
        captured.update(kwargs.get("json", {}))
        return _or_resp("pro ok")

    fake_client = MagicMock()
    fake_client.post = fake_post
    monkeypatch.setattr(server, "_or_client", fake_client)

    out = await server._or_chat(
        [{"role": "user", "content": "reason about this"}],
        model="openai/gpt-5.5-pro",
    )
    assert "pro ok" in out
    assert captured.get("model") == "openai/gpt-5.5-pro"
    assert captured.get("provider", {}).get("data_collection") == "deny", (
        "ZDR must still be enforced for the GPT-5.5-pro exception"
    )


async def test_gpt_audit_pro_blocked_without_env(monkeypatch):
    """Without the env opt-in, openai/gpt-5.5-pro raises before any HTTP call (ban intact)."""
    monkeypatch.delenv(server._GPT_AUDIT_ENV, raising=False)
    monkeypatch.setattr(server, "_OR_API_KEY", "sk-or-test-key")
    called = False

    async def should_not_be_called(*args, **kwargs):
        nonlocal called
        called = True
        return _or_resp("nope")

    fake_client = MagicMock()
    fake_client.post = should_not_be_called
    monkeypatch.setattr(server, "_or_client", fake_client)

    with pytest.raises(Exception, match="banned"):
        await server._or_chat([{"role": "user", "content": "hi"}], model="openai/gpt-5.5-pro")
    assert not called


async def test_gpt_audit_other_openai_still_blocked_with_env(monkeypatch):
    """Even with env set, a non-exact openai/* id raises before any HTTP call."""
    monkeypatch.setenv(server._GPT_AUDIT_ENV, "1")
    monkeypatch.setattr(server, "_OR_API_KEY", "sk-or-test-key")
    called = False

    async def should_not_be_called(*args, **kwargs):
        nonlocal called
        called = True
        return _or_resp("nope")

    fake_client = MagicMock()
    fake_client.post = should_not_be_called
    monkeypatch.setattr(server, "_or_client", fake_client)

    with pytest.raises(Exception, match="banned"):
        await server._or_chat([{"role": "user", "content": "hi"}], model="openai/gpt-4o")
    assert not called


async def test_banned_openai_raises_before_http(monkeypatch):
    """openai/* is banned — must raise before any HTTP call."""
    monkeypatch.setattr(server, "_OR_API_KEY", "sk-or-test-key")
    called = False

    async def should_not_be_called(*args, **kwargs):
        nonlocal called
        called = True
        return _or_resp("should not reach here")

    fake_client = MagicMock()
    fake_client.post = should_not_be_called
    monkeypatch.setattr(server, "_or_client", fake_client)

    with pytest.raises(Exception, match="banned"):
        await server._or_chat(
            [{"role": "user", "content": "hi"}],
            model="openai/gpt-5.5",
        )
    assert not called, "HTTP call was made despite banned provider — guard must fire first"


async def test_banned_xai_raises_before_http(monkeypatch):
    """x-ai/* is banned — must raise before any HTTP call."""
    monkeypatch.setattr(server, "_OR_API_KEY", "sk-or-test-key")
    called = False

    async def should_not_be_called(*args, **kwargs):
        nonlocal called
        called = True
        return _or_resp("should not reach here")

    fake_client = MagicMock()
    fake_client.post = should_not_be_called
    monkeypatch.setattr(server, "_or_client", fake_client)

    with pytest.raises(Exception, match="banned"):
        await server._or_chat(
            [{"role": "user", "content": "hi"}],
            model="x-ai/grok-4.20",
        )
    assert not called, "HTTP call was made despite banned provider — guard must fire first"


async def test_banned_openai_model_via_or_ask_returns_error_string(mock_or_client, monkeypatch):
    """or_ask wraps _or_chat errors into a string — verify banned models surface correctly."""
    monkeypatch.setattr(server, "_API_KEY", "")
    result = await server.or_ask("hi", model="openai/gpt-5.5")
    assert "banned" in result.lower() or "Error" in result, (
        "or_ask with a banned model should return an error string containing 'banned'"
    )


# ---------------------------------------------------------------------------
# Section 3 — Subscription blocked-from-OR guard (anthropic/*, moonshotai/*)
#
# These are tier-1 (host native) and tier-2 (subscription API) models.
# They must never be paid for via OpenRouter.
# ---------------------------------------------------------------------------

def test_is_blocked_from_or_anthropic_prefix():
    assert server._is_blocked_from_or("anthropic/claude-opus-4.7") is True


def test_is_blocked_from_or_anthropic_anything():
    assert server._is_blocked_from_or("anthropic/anything") is True


def test_is_blocked_from_or_moonshotai_prefix():
    assert server._is_blocked_from_or("moonshotai/kimi-k2.6") is True


def test_is_blocked_from_or_moonshotai_anything():
    assert server._is_blocked_from_or("moonshotai/anything") is True


def test_is_blocked_from_or_deepseek_not_blocked():
    assert server._is_blocked_from_or("deepseek/deepseek-v4-pro") is False


def test_is_blocked_from_or_minimax_not_blocked():
    assert server._is_blocked_from_or("minimax/minimax-m2.7") is False


def test_is_blocked_from_or_xiaomi_not_blocked():
    assert server._is_blocked_from_or("xiaomi/mimo-v2.5-pro") is False


async def test_blocked_anthropic_raises(monkeypatch):
    """anthropic/* must raise before any HTTP call — we have it free via host subscription."""
    monkeypatch.setattr(server, "_OR_API_KEY", "sk-or-test-key")
    called = False

    async def should_not_be_called(*args, **kwargs):
        nonlocal called
        called = True
        return _or_resp("should not reach here")

    fake_client = MagicMock()
    fake_client.post = should_not_be_called
    monkeypatch.setattr(server, "_or_client", fake_client)

    with pytest.raises(Exception):
        await server._or_chat(
            [{"role": "user", "content": "hi"}],
            model="anthropic/claude-opus-4.7",
        )
    assert not called, "HTTP call was made despite blocked model — tier-1 guard must fire first"


async def test_blocked_moonshotai_raises(monkeypatch):
    """moonshotai/* must raise before any HTTP call — we have it free via KIMI_API_KEY."""
    monkeypatch.setattr(server, "_OR_API_KEY", "sk-or-test-key")
    called = False

    async def should_not_be_called(*args, **kwargs):
        nonlocal called
        called = True
        return _or_resp("should not reach here")

    fake_client = MagicMock()
    fake_client.post = should_not_be_called
    monkeypatch.setattr(server, "_or_client", fake_client)

    with pytest.raises(Exception):
        await server._or_chat(
            [{"role": "user", "content": "hi"}],
            model="moonshotai/kimi-k2.6",
        )
    assert not called, "HTTP call was made despite blocked model — tier-2 guard must fire first"


async def test_blocked_anthropic_via_or_ask_returns_error_string(mock_or_client, monkeypatch):
    """or_ask with a tier-1 blocked model should surface an error string, not hang."""
    monkeypatch.setattr(server, "_API_KEY", "")
    result = await server.or_ask("hi", model="anthropic/claude-opus-4.7")
    assert "blocked" in result.lower() or "Error" in result, (
        "or_ask with a blocked model should return an error string"
    )


async def test_or_compare_auto_removes_blocked_models(mock_or_client, monkeypatch):
    """or_compare must silently filter out blocked/banned models rather than crashing."""
    monkeypatch.setattr(server, "_API_KEY", "")
    result = await server.or_compare(
        "test prompt",
        models=["anthropic/claude-opus-4.7", "deepseek/deepseek-v4-pro"],
    )
    # Should complete without error — blocked model removed, deepseek proceeds
    assert "deepseek" in result.lower() or "deepseek/deepseek-v4-pro" in result
    # anthropic should be flagged as removed
    assert "anthropic" in result or "Removed" in result or "blocked" in result.lower()


async def test_or_compare_all_blocked_returns_message(mock_or_client, monkeypatch):
    """or_compare with only blocked/banned models returns a clear failure message."""
    result = await server.or_compare(
        "test",
        models=["anthropic/claude-opus-4.7", "openai/gpt-5.5"],
    )
    assert "blocked" in result.lower() or "banned" in result.lower() or "All" in result


# ---------------------------------------------------------------------------
# Section 4 — Profile routing (_resolve_profile_model)
#
# _resolve_profile_model is a plain sync function — tested directly, no HTTP.
# Resolution precedence: subscription > specialist > max+reasoning > profile default.
# ---------------------------------------------------------------------------

def test_profile_eco_routes_to_deepseek_flash():
    model, note = server._resolve_profile_model("eco", "", has_kimi=True)
    assert model == "deepseek/deepseek-v4-flash", (
        f"eco profile should use deepseek-v4-flash (cheapest capable), got: {model}"
    )


def test_profile_mid_routes_to_qwen():
    model, note = server._resolve_profile_model("mid", "", has_kimi=True)
    assert model == "qwen/qwen3.5-plus-20260420", (
        f"mid profile should use qwen3.5-plus-20260420 (balanced), got: {model}"
    )


def test_profile_intel_routes_to_deepseek_v4_pro():
    model, note = server._resolve_profile_model("intel", "", has_kimi=True)
    assert model == "deepseek/deepseek-v4-pro", (
        f"intel profile should use deepseek-v4-pro (best reasoning, 80.6% SWE-bench), got: {model}"
    )


def test_profile_max_routes_to_mimo():
    model, note = server._resolve_profile_model("max", "", has_kimi=True)
    assert model == "xiaomi/mimo-v2.5-pro", (
        f"max profile (general task) should use mimo-v2.5-pro (#1 OR usage), got: {model}"
    )


def test_profile_research_routes_to_deepseek_v4_pro():
    # Use a hint that's not in _SUBSCRIPTION_HINTS — "synthesis" triggers research profile,
    # not the subscription guard. "analysis" would trigger Kimi subscription (it's a sub hint).
    model, note = server._resolve_profile_model("research", "long document synthesis", has_kimi=True)
    assert model == "deepseek/deepseek-v4-pro", (
        f"research profile should use deepseek-v4-pro (1.05M ctx), got: {model}"
    )


def test_profile_research_non_research_hint_still_routes():
    """research profile with a generic hint still resolves (with a mismatch note)."""
    model, note = server._resolve_profile_model("research", "general question", has_kimi=False)
    assert model == "deepseek/deepseek-v4-pro"
    # The note should warn about research profile on short tasks
    assert "research" in note.lower() or "intel" in note.lower() or "cost" in note.lower()


def test_profile_unknown_returns_empty():
    """Unknown profile should return empty string — caller falls through to normal routing."""
    model, note = server._resolve_profile_model("nonexistent", "", has_kimi=True)
    assert model == ""


def test_profile_empty_returns_empty():
    """Empty profile string should return empty — no profile selected."""
    model, note = server._resolve_profile_model("", "coding", has_kimi=True)
    assert model == ""


# Subscription wins over profile

def test_subscription_wins_over_eco_profile():
    """Kimi subscription always beats eco profile for coding tasks (free)."""
    model, note = server._resolve_profile_model("eco", "coding", has_kimi=True)
    assert model == server._PROFILE_USE_KIMI, (
        "coding task with eco profile should route to Kimi subscription (free), not deepseek-v4-flash"
    )
    assert "free" in note.lower() or "subscription" in note.lower() or "kimi" in note.lower()


def test_subscription_wins_over_max_profile():
    """Kimi subscription beats even max profile for coding tasks."""
    model, note = server._resolve_profile_model("max", "coding", has_kimi=True)
    assert model == server._PROFILE_USE_KIMI


def test_subscription_wins_for_debug_hint():
    model, note = server._resolve_profile_model("intel", "debug", has_kimi=True)
    assert model == server._PROFILE_USE_KIMI


def test_subscription_wins_for_refactor_hint():
    model, note = server._resolve_profile_model("eco", "refactor", has_kimi=True)
    assert model == server._PROFILE_USE_KIMI


def test_no_subscription_bypasses_kimi():
    """When has_kimi=False, subscription-preferred hints fall through to profile default."""
    model, note = server._resolve_profile_model("eco", "coding", has_kimi=False)
    # Should NOT be Kimi sentinel — no key means no free route
    assert model != server._PROFILE_USE_KIMI
    assert model == "deepseek/deepseek-v4-flash"


# Specialist wins over profile

def test_specialist_creative_wins_over_eco():
    model, note = server._resolve_profile_model("eco", "creative", has_kimi=True)
    assert model == "minimax/minimax-m2.7"


def test_specialist_creative_wins_over_intel():
    model, note = server._resolve_profile_model("intel", "story", has_kimi=True)
    assert model == "minimax/minimax-m2.7"


def test_max_reasoning_routes_to_deepseek_not_mimo():
    """max+reasoning uses deepseek-v4-pro (80.6% SWE-bench), not mimo default."""
    model, note = server._resolve_profile_model("max", "reasoning", has_kimi=False)
    assert model == "deepseek/deepseek-v4-pro", (
        f"max+reasoning should use deepseek-v4-pro (better SWE-bench), got: {model}"
    )


def test_max_math_routes_to_deepseek_not_mimo():
    model, note = server._resolve_profile_model("max", "math", has_kimi=False)
    assert model == "deepseek/deepseek-v4-pro"


def test_max_proof_routes_to_deepseek_not_mimo():
    model, note = server._resolve_profile_model("max", "proof", has_kimi=False)
    assert model == "deepseek/deepseek-v4-pro"


def test_max_logic_routes_to_deepseek_not_mimo():
    model, note = server._resolve_profile_model("max", "logic", has_kimi=False)
    assert model == "deepseek/deepseek-v4-pro"


def test_max_general_still_uses_mimo():
    """max profile with a general (non-reasoning) hint should still use mimo."""
    model, note = server._resolve_profile_model("max", "general", has_kimi=False)
    assert model == "xiaomi/mimo-v2.5-pro", (
        "max profile with general hint should use mimo-v2.5-pro (not deepseek)"
    )


def test_intel_general_uses_deepseek_v4_pro():
    """intel profile always uses deepseek-v4-pro, regardless of reasoning hint."""
    model, note = server._resolve_profile_model("intel", "general question", has_kimi=False)
    assert model == "deepseek/deepseek-v4-pro"


# Note contents

def test_profile_note_includes_profile_name():
    """Profile note should identify which profile was used."""
    model, note = server._resolve_profile_model("eco", "", has_kimi=True)
    assert "eco" in note


def test_specialist_note_includes_keyword():
    """Specialist override note should mention the triggering keyword."""
    model, note = server._resolve_profile_model("eco", "creative", has_kimi=True)
    assert "creative" in note.lower() or "specialist" in note.lower()


# ---------------------------------------------------------------------------
# Section 5 — _route_or_model routing table (no HTTP)
# ---------------------------------------------------------------------------

def test_route_or_model_creative_routes_to_minimax():
    model = server._route_or_model("creative", has_kimi=False)
    assert model == "minimax/minimax-m2.7"


def test_route_or_model_reasoning_routes_to_deepseek():
    model = server._route_or_model("reasoning", has_kimi=False)
    assert model == "deepseek/deepseek-v4-pro"


def test_route_or_model_coding_with_kimi_returns_empty():
    """Coding hint + has_kimi=True → empty string (Kimi subscription preferred)."""
    model = server._route_or_model("coding", has_kimi=True)
    assert model == "", "coding with Kimi available should return '' to signal subscription use"


def test_route_or_model_coding_without_kimi_routes_to_deepseek():
    model = server._route_or_model("coding", has_kimi=False)
    assert model == "deepseek/deepseek-v4-pro"


def test_route_or_model_image_hint_returns_none():
    """Image tasks return None — caller should redirect to or_image."""
    model = server._route_or_model("image generation", has_kimi=False)
    assert model is None


def test_route_or_model_unknown_hint_returns_none():
    model = server._route_or_model("something totally unknown", has_kimi=False)
    assert model is None


def test_route_or_model_fast_routes_to_flash():
    model = server._route_or_model("fast", has_kimi=False)
    assert model == "deepseek/deepseek-v4-flash"


def test_route_or_model_ultra_long_routes_to_deepseek():
    """Ultra-long-context tasks route to deepseek-v4-pro (1.05M ctx) — xAI/Grok is banned."""
    model = server._route_or_model("ultra long context", has_kimi=False)
    assert model == "deepseek/deepseek-v4-pro", \
        "ultra-long-context must route to deepseek-v4-pro (1.05M ctx, best remaining after Grok ban)"


def test_route_or_model_very_long_document_routes_to_deepseek():
    model = server._route_or_model("very long document", has_kimi=False)
    assert model == "deepseek/deepseek-v4-pro"


# ---------------------------------------------------------------------------
# Section 6 — Host redirect logic (_should_redirect_to_host)
# ---------------------------------------------------------------------------

def test_host_redirect_reasoning_no_pressure():
    """reasoning hint + no pressure → redirect to host."""
    assert server._should_redirect_to_host("reasoning", False) is True


def test_host_no_redirect_when_pressured():
    """Any hint with pressure → do NOT redirect."""
    assert server._should_redirect_to_host("reasoning", True) is False


def test_host_no_redirect_image():
    """Image generation is OR-required — must NOT redirect."""
    assert server._should_redirect_to_host("image generation", False) is False


def test_host_no_redirect_unknown_hint():
    """Unknown hint — ambiguous, do not redirect."""
    assert server._should_redirect_to_host("random task xyz", False) is False
