"""Tests for ai-router MCP server — all tools, retry logic, and agent swarm modes."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("KIMI_API_KEY", "sk-kimi-test")

import server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resp(content: str = "", reasoning: str = "", status_code: int = 200) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = {
        "choices": [{"message": {"content": content, "reasoning_content": reasoning}}]
    }
    if status_code >= 400:
        mock.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=mock
        )
    else:
        mock.raise_for_status.return_value = None
    return mock


def _make_client(*responses: MagicMock) -> MagicMock:
    """Build a mock shared client returning responses sequentially (or single if only one)."""
    client = MagicMock()
    client.post = AsyncMock(side_effect=list(responses) if len(responses) > 1 else None,
                            return_value=responses[0] if len(responses) == 1 else None)
    client.get = AsyncMock(return_value=_resp())
    return client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_key(monkeypatch):
    monkeypatch.setattr(server, "_API_KEY", "sk-kimi-test")


@pytest.fixture(autouse=True)
def _zero_backoff(monkeypatch):
    monkeypatch.setattr(server, "_RETRY_BACKOFF", 0.0)


@pytest.fixture
def mock_client(monkeypatch):
    """Single mock for both endpoints — sufficient for most tests."""
    client = _make_client(_resp("default"))
    monkeypatch.setattr(server, "_shared_client", client)
    monkeypatch.setattr(server, "_general_client", client)
    return client


@pytest.fixture
def routing_clients(monkeypatch):
    """Two separate mocks to verify which endpoint each tool routes to."""
    coding = MagicMock()
    coding.post = AsyncMock(return_value=_resp("from-coding"))
    general = MagicMock()
    general.post = AsyncMock(return_value=_resp("from-general"))
    monkeypatch.setattr(server, "_shared_client", coding)
    monkeypatch.setattr(server, "_general_client", general)
    return coding, general


# ---------------------------------------------------------------------------
# kimi_ask
# ---------------------------------------------------------------------------

async def test_kimi_ask_basic(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("the answer")))
    result = await server.kimi_ask("what is 2+2?")
    assert result == "the answer"
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["model"] == server._GENERAL_MODEL  # kimi_ask uses general endpoint
    assert payload["messages"] == [{"role": "user", "content": "what is 2+2?"}]


async def test_kimi_ask_with_system(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("ok")))
    await server.kimi_ask("question", system="be concise")
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["messages"][0] == {"role": "system", "content": "be concise"}
    assert payload["messages"][1] == {"role": "user", "content": "question"}


async def test_kimi_ask_include_reasoning(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("answer", reasoning="step 1, step 2")))
    result = await server.kimi_ask("q", include_reasoning=True)
    assert "<reasoning>" in result
    assert "step 1, step 2" in result
    assert "answer" in result


async def test_kimi_ask_no_reasoning_when_empty(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("answer", reasoning="")))
    result = await server.kimi_ask("q", include_reasoning=True)
    assert "<reasoning>" not in result
    assert result == "answer"


async def test_kimi_ask_no_api_key(monkeypatch):
    monkeypatch.setattr(server, "_API_KEY", "")
    result = await server.kimi_ask("hi")
    assert "Error" in result


async def test_kimi_ask_http_error_returns_string(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(side_effect=[_resp(status_code=503), _resp(status_code=503), _resp(status_code=503)]))
    result = await server.kimi_ask("hi")
    assert "API error" in result or "Error" in result


async def test_kimi_ask_unexpected_error_includes_type_name(mock_client, monkeypatch):
    # httpx.ReadTimeout has empty str() — without the type name, the user
    # sees a bare "Error: " with no actionable info. Regression for the
    # timeout that produced empty errors on >25K-token kimi_ask outputs.
    monkeypatch.setattr(mock_client, "post", AsyncMock(side_effect=httpx.ReadTimeout("")))
    result = await server.kimi_ask("hi")
    assert "ReadTimeout" in result


# ---------------------------------------------------------------------------
# Inline-vs-file overflow — fixed 8000-char cutoff
# ---------------------------------------------------------------------------

def test_output_or_file_inline_when_small():
    out = server._output_or_file("hello world", "kimi_ask")
    assert out == "hello world"


def test_output_or_file_inline_at_boundary():
    # Exactly at the cap should still be inline.
    out = server._output_or_file("X" * server._INLINE_MAX_CHARS, "kimi_ask")
    assert out == "X" * server._INLINE_MAX_CHARS


def test_output_or_file_writes_file_when_over_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_FALLBACK_DIR", str(tmp_path))
    big = "X" * (server._INLINE_MAX_CHARS + 1)
    out = server._output_or_file(big, "kimi_ask")
    assert "Output too large to return inline" in out
    assert "ai-router-kimi_ask-" in out
    written = list(tmp_path.glob("ai-router-kimi_ask-*.md"))
    assert len(written) == 1
    assert written[0].read_text() == big


def test_output_or_file_catches_dense_content(tmp_path, monkeypatch):
    # Regression: a 50,361-char SQL-reference kimi_swarm response tokenized to
    # >25K host tokens (Claude's tokenizer is ~2.0 chars/token for SQL) and
    # slipped past the prior chars-per-token heuristic at ratio 3.5, forcing
    # the host's emergency truncation. The new fixed 8K cutoff makes this
    # case (and all denser-than-prose content) flow through the filesystem.
    monkeypatch.setattr(server, "_FALLBACK_DIR", str(tmp_path))
    dense = "X" * 50_361
    out = server._output_or_file(dense, "kimi_swarm")
    assert "Output too large to return inline" in out, (
        f"dense {len(dense)} chars should overflow at {server._INLINE_MAX_CHARS}-char cap"
    )


def test_output_or_file_truncates_with_notice_when_filewrite_fails(monkeypatch):
    # If the disk is full / permission denied, fall back to in-place truncation
    # so the caller still gets something usable instead of an OSError.
    monkeypatch.setattr(server, "_FALLBACK_DIR", "/nonexistent/definitely-not-a-dir")
    big = "X" * (server._INLINE_MAX_CHARS + 100)
    out = server._output_or_file(big, "kimi_ask")
    assert "file fallback failed" in out
    assert out.startswith("X" * 100)  # first chars of the original content


# ---------------------------------------------------------------------------
# kimi_analyze
# ---------------------------------------------------------------------------

async def test_kimi_analyze_with_content(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("summary")))
    result = await server.kimi_analyze("summarize this", content="raw text here")
    assert result == "summary"
    payload = mock_client.post.call_args.kwargs["json"]
    assert "raw text here" in payload["messages"][1]["content"]


async def test_kimi_analyze_no_input():
    result = await server.kimi_analyze("question")
    assert result.startswith("Error")


async def test_kimi_analyze_detail_summary(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("ok")))
    await server.kimi_analyze("q", content="x", detail_level="summary")
    system_msg = mock_client.post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "concise" in system_msg.lower() or "bullet" in system_msg.lower()


async def test_kimi_analyze_detail_detailed(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("ok")))
    await server.kimi_analyze("q", content="x", detail_level="detailed")
    system_msg = mock_client.post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "code" in system_msg.lower() or "snippet" in system_msg.lower()


async def test_kimi_analyze_with_work_dir(mock_client, monkeypatch, tmp_path):
    (tmp_path / "app.py").write_text("def hello(): return 'world'")
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("dir analysis")))
    result = await server.kimi_analyze("what does this do?", work_dir=str(tmp_path))
    assert result == "dir analysis"
    user_msg = mock_client.post.call_args.kwargs["json"]["messages"][1]["content"]
    assert "app.py" in user_msg
    assert "hello" in user_msg


async def test_kimi_analyze_invalid_work_dir(mock_client):
    result = await server.kimi_analyze("q", work_dir="/nonexistent/path/xyz")
    assert "Error" in result or "not a directory" in result


# ---------------------------------------------------------------------------
# kimi_batch
# ---------------------------------------------------------------------------

async def test_kimi_batch_basic(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(side_effect=[
        _resp("result A"), _resp("result B"), _resp("result C"),
    ]))
    output = await server.kimi_batch(["p A", "p B", "p C"])
    items = json.loads(output)
    assert len(items) == 3
    assert all(i["ok"] for i in items)
    by_index = {i["index"]: i["result"] for i in items}
    assert by_index[0] == "result A"
    assert by_index[1] == "result B"
    assert by_index[2] == "result C"


async def test_kimi_batch_with_system(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("ok")))
    await server.kimi_batch(["prompt"], system="you are helpful")
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["messages"][0] == {"role": "system", "content": "you are helpful"}


async def test_kimi_batch_partial_failure(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(side_effect=[
        _resp("success"),
        _resp(status_code=400),
    ]))
    output = await server.kimi_batch(["good", "bad"])
    items = {i["index"]: i for i in json.loads(output)}
    assert items[0]["ok"] is True
    assert items[1]["ok"] is False


async def test_kimi_batch_concurrency_limit(mock_client, monkeypatch):
    active = 0
    peak = 0

    async def tracked_post(path, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.005)
        active -= 1
        return _resp("ok")

    monkeypatch.setattr(mock_client, "post", tracked_post)
    await server.kimi_batch(["p"] * 20, concurrency=5)
    assert peak <= 5


async def test_kimi_batch_empty(mock_client):
    output = await server.kimi_batch([])
    assert json.loads(output) == []


# ---------------------------------------------------------------------------
# kimi_research_compile
# ---------------------------------------------------------------------------

async def test_kimi_research_compile_two_phases(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(side_effect=[
        _resp("extract A"), _resp("extract B"), _resp("final synthesis"),
    ]))
    result = await server.kimi_research_compile(["src A", "src B"], "find key insights")
    assert result == "final synthesis"
    assert mock_client.post.call_count == 3


async def test_kimi_research_compile_synthesis_includes_extracts(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(side_effect=[
        _resp("extract A"), _resp("extract B"), _resp("synthesis"),
    ]))
    await server.kimi_research_compile(["src A", "src B"], "goal")
    synthesis_call = mock_client.post.call_args_list[-1]
    user_msg = synthesis_call.kwargs["json"]["messages"][1]["content"]
    assert "extract A" in user_msg
    assert "extract B" in user_msg


async def test_kimi_research_compile_output_formats(mock_client, monkeypatch):
    for fmt in ("structured", "narrative", "table"):
        monkeypatch.setattr(mock_client, "post", AsyncMock(side_effect=[
            _resp("e1"), _resp("e2"), _resp("out"),
        ]))
        result = await server.kimi_research_compile(["s1", "s2"], "q", output_format=fmt)
        assert result == "out"


# ---------------------------------------------------------------------------
# kimi_sentiment_batch
# ---------------------------------------------------------------------------

async def test_kimi_sentiment_basic(mock_client, monkeypatch):
    body = '{"positive": 0.9, "negative": 0.05, "neutral": 0.05, "confidence": 0.95, "summary": "positive"}'
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp(body)))
    output = await server.kimi_sentiment_batch(["great product!"])
    items = json.loads(output)
    assert items[0]["ok"] is True
    assert items[0]["positive"] == 0.9
    assert items[0]["summary"] == "positive"


async def test_kimi_sentiment_strips_markdown_fences(mock_client, monkeypatch):
    fenced = '```json\n{"positive": 0.8, "negative": 0.2, "neutral": 0.0, "confidence": 0.9, "summary": "mixed"}\n```'
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp(fenced)))
    output = await server.kimi_sentiment_batch(["text"])
    items = json.loads(output)
    assert items[0]["ok"] is True
    assert items[0]["positive"] == 0.8


async def test_kimi_sentiment_fallback_on_invalid_json(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("not valid json")))
    output = await server.kimi_sentiment_batch(["text"])
    items = json.loads(output)
    assert items[0]["ok"] is True
    assert "raw" in items[0]


async def test_kimi_sentiment_custom_dimensions(mock_client, monkeypatch):
    body = '{"joy": 0.8, "anger": 0.1, "summary": "joyful"}'
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp(body)))
    output = await server.kimi_sentiment_batch(["happy text"], dimensions="joy,anger")
    items = json.loads(output)
    assert items[0]["joy"] == 0.8


async def test_kimi_sentiment_multiple_texts(mock_client, monkeypatch):
    def make_body(val):
        return f'{{"positive": {val}, "negative": 0.0, "neutral": 0.0, "confidence": 1.0, "summary": "ok"}}'
    monkeypatch.setattr(mock_client, "post", AsyncMock(side_effect=[
        _resp(make_body(0.9)),
        _resp(make_body(0.1)),
    ]))
    output = await server.kimi_sentiment_batch(["positive text", "negative text"])
    items = {i["index"]: i for i in json.loads(output)}
    assert items[0]["positive"] == 0.9
    assert items[1]["positive"] == 0.1


# ---------------------------------------------------------------------------
# kimi_status
# ---------------------------------------------------------------------------

async def test_kimi_status_no_api_key(monkeypatch):
    monkeypatch.setattr(server, "_API_KEY", "")
    result = await server.kimi_status()
    assert "NOT SET" in result
    assert "KIMI_API_KEY" in result


async def test_kimi_status_success(mock_client, monkeypatch):
    # kimi_status probes via POST /chat/completions (1 token), not GET /models
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("ok")))
    result = await server.kimi_status()
    assert "OK" in result


async def test_kimi_status_connect_error(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(side_effect=httpx.ConnectError("refused")))
    result = await server.kimi_status()
    assert "ERROR" in result


async def test_kimi_status_non_200(mock_client, monkeypatch):
    bad = MagicMock()
    bad.status_code = 503
    bad.raise_for_status.side_effect = httpx.HTTPStatusError("HTTP 503", request=MagicMock(), response=bad)
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=bad))
    result = await server.kimi_status()
    assert "503" in result


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

async def test_retry_on_429(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(side_effect=[
        _resp(status_code=429),
        _resp("recovered"),
    ]))
    result = await server.kimi_ask("hi")
    assert result == "recovered"
    assert mock_client.post.call_count == 2


async def test_retry_on_503(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(side_effect=[
        _resp(status_code=503),
        _resp("ok after retry"),
    ]))
    result = await server.kimi_ask("hi")
    assert result == "ok after retry"


async def test_retry_on_transport_error(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(side_effect=[
        httpx.ConnectError("drop"),
        _resp("reconnected"),
    ]))
    result = await server.kimi_ask("hi")
    assert result == "reconnected"


async def test_retry_exhausted_transport_error(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(side_effect=httpx.ConnectError("always fails")))
    result = await server.kimi_ask("hi")
    assert "Error" in result
    # 1 initial attempt + _MAX_RETRIES retries
    assert mock_client.post.call_count == server._MAX_RETRIES + 1


async def test_retry_exhausted_http_error(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(side_effect=[
        _resp(status_code=429),
        _resp(status_code=429),
        _resp(status_code=429),
    ]))
    result = await server.kimi_ask("hi")
    assert "API error" in result or "Error" in result


async def test_no_retry_on_400(mock_client, monkeypatch):
    """400 Bad Request is not in retry set — should not retry."""
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp(status_code=400)))
    result = await server.kimi_ask("hi")
    assert "API error" in result or "Error" in result
    assert mock_client.post.call_count == 1


# ---------------------------------------------------------------------------
# kimi_swarm — native Agent Swarm (internal model orchestration)
# ---------------------------------------------------------------------------

async def test_kimi_swarm_sends_thinking_payload(mock_client, monkeypatch):
    """kimi_swarm must pass thinking: {"type": "enabled"} to activate internal Agent Swarm."""
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("swarm result")))
    await server.kimi_swarm("refactor this codebase end-to-end")
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload.get("thinking") == {"type": "enabled"}, (
        "thinking param missing — Kimi's Agent Swarm won't activate without it"
    )


async def test_kimi_swarm_forces_temperature_one(mock_client, monkeypatch):
    """Kimi's thinking/swarm mode requires temperature=1.0."""
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("ok")))
    await server.kimi_swarm("complex task")
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["temperature"] == 1.0, "temperature must be 1.0 for thinking mode"


async def test_kimi_swarm_returns_reasoning_by_default(mock_client, monkeypatch):
    """Swarm reasoning trace should be exposed by default (include_reasoning=True)."""
    monkeypatch.setattr(mock_client, "post", AsyncMock(
        return_value=_resp("final answer", reasoning="sub-agent planning steps")
    ))
    result = await server.kimi_swarm("design a distributed system")
    assert "<reasoning>" in result
    assert "sub-agent planning steps" in result
    assert "final answer" in result


async def test_kimi_swarm_no_reasoning_when_disabled(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(
        return_value=_resp("answer", reasoning="internal trace")
    ))
    result = await server.kimi_swarm("task", include_reasoning=False)
    assert "<reasoning>" not in result
    assert "answer" in result


async def test_kimi_swarm_with_context(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("done")))
    await server.kimi_swarm("migrate auth module", context="you are a senior backend engineer")
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["messages"][0] == {"role": "system", "content": "you are a senior backend engineer"}
    assert payload["messages"][1]["role"] == "user"
    assert "migrate auth module" in payload["messages"][1]["content"]


async def test_kimi_swarm_uses_high_max_tokens(mock_client, monkeypatch):
    """Swarm tasks need large output budgets — default should be >> kimi_ask's default of 16384."""
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("ok")))
    await server.kimi_swarm("big task")
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["max_tokens"] >= 16384, "swarm default max_tokens should be generous for long-horizon tasks"


async def test_kimi_swarm_custom_max_tokens(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("ok")))
    await server.kimi_swarm("task", max_tokens=65536)
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["max_tokens"] == 65536


async def test_kimi_swarm_error_returns_string(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(side_effect=[
        _resp(status_code=503),
        _resp(status_code=503),
        _resp(status_code=503),
    ]))
    result = await server.kimi_swarm("task")
    assert "API error" in result or "Error" in result


# ---------------------------------------------------------------------------
# External swarm pattern: kimi_batch as fan-out orchestrator
# ---------------------------------------------------------------------------

async def test_batch_fan_out_swarm_pattern(mock_client, monkeypatch):
    """kimi_batch can act as an external swarm: you decompose, N Kimi agents run in parallel."""
    subtasks = [
        "analyze security in auth.py",
        "analyze performance in db.py",
        "analyze test coverage gaps",
    ]
    monkeypatch.setattr(mock_client, "post", AsyncMock(side_effect=[
        _resp("auth: no critical issues"),
        _resp("db: N+1 query on line 42"),
        _resp("tests: missing edge cases in payment flow"),
    ]))
    output = await server.kimi_batch(
        subtasks,
        system="you are a senior code reviewer, be specific",
    )
    items = {i["index"]: i for i in json.loads(output)}
    assert len(items) == 3
    assert all(items[i]["ok"] for i in range(3))
    assert "auth" in items[0]["result"]
    assert "N+1" in items[1]["result"]
    assert "payment" in items[2]["result"]


async def test_batch_vs_swarm_different_payloads(mock_client, monkeypatch):
    """kimi_batch does NOT send thinking param — only kimi_swarm activates internal Agent Swarm."""
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("ok")))
    await server.kimi_batch(["task"])
    batch_payload = mock_client.post.call_args.kwargs["json"]
    assert "thinking" not in batch_payload, "kimi_batch must not trigger internal swarm"

    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("ok")))
    await server.kimi_swarm("task")
    swarm_payload = mock_client.post.call_args.kwargs["json"]
    assert swarm_payload.get("thinking") == {"type": "enabled"}, "kimi_swarm must trigger internal swarm"


# ---------------------------------------------------------------------------
# Model routing — coding vs general endpoint
# ---------------------------------------------------------------------------

async def test_routing_analyze_uses_coding_endpoint(routing_clients):
    """kimi_analyze must hit the coding endpoint (kimi-for-coding)."""
    coding, general = routing_clients
    await server.kimi_analyze("what does this do?", content="def foo(): pass")
    assert coding.post.called, "kimi_analyze should use the coding client"
    assert not general.post.called, "kimi_analyze should NOT use the general client"


async def test_routing_analyze_coding_model_in_payload(routing_clients):
    coding, _ = routing_clients
    await server.kimi_analyze("q", content="code")
    payload = coding.post.call_args.kwargs["json"]
    assert payload["model"] == server._MODEL  # kimi-for-coding


async def test_routing_ask_uses_general_endpoint(routing_clients):
    """kimi_ask must hit the general endpoint (kimi-k2.6) — fixes empty responses on non-code prompts."""
    coding, general = routing_clients
    await server.kimi_ask("explain goroutines")
    assert general.post.called, "kimi_ask should use the general client"
    assert not coding.post.called, "kimi_ask should NOT use the coding client"


async def test_routing_ask_general_model_in_payload(routing_clients):
    _, general = routing_clients
    await server.kimi_ask("q")
    payload = general.post.call_args.kwargs["json"]
    assert payload["model"] == server._GENERAL_MODEL  # kimi-k2.6


async def test_routing_batch_uses_general_endpoint(routing_clients):
    coding, general = routing_clients
    await server.kimi_batch(["p1", "p2"])
    assert general.post.called
    assert not coding.post.called


async def test_routing_swarm_uses_general_endpoint(routing_clients):
    """kimi_swarm uses kimi-k2.6 — the Agent Swarm feature lives on the general model."""
    coding, general = routing_clients
    await server.kimi_swarm("big task")
    assert general.post.called
    assert not coding.post.called


async def test_routing_research_compile_uses_general_endpoint(routing_clients):
    coding, general = routing_clients
    general.post = AsyncMock(side_effect=[_resp("e1"), _resp("e2"), _resp("synthesis")])
    await server.kimi_research_compile(["s1", "s2"], "goal")
    assert general.post.called
    assert not coding.post.called


async def test_routing_sentiment_uses_general_endpoint(routing_clients):
    coding, general = routing_clients
    body = '{"positive": 0.9, "negative": 0.1, "neutral": 0.0, "confidence": 1.0, "summary": "ok"}'
    general.post = AsyncMock(return_value=_resp(body))
    await server.kimi_sentiment_batch(["great!"])
    assert general.post.called
    assert not coding.post.called


# ---------------------------------------------------------------------------
# Kimi model selection — default K2.7 + validated per-call override
# ---------------------------------------------------------------------------

def test_general_default_model_is_k27():
    assert server._GENERAL_MODEL == "kimi-k2.7"


def test_resolve_kimi_model_defaults_to_configured():
    assert server._resolve_kimi_model("", use_general=True) == server._GENERAL_MODEL
    assert server._resolve_kimi_model(None, use_general=True) == server._GENERAL_MODEL
    assert server._resolve_kimi_model("", use_general=False) == server._MODEL


def test_resolve_kimi_model_valid_override():
    assert server._resolve_kimi_model("kimi-k2.7", use_general=True) == "kimi-k2.7"
    assert server._resolve_kimi_model("kimi-k2.6", use_general=True) == "kimi-k2.6"
    assert server._resolve_kimi_model("kimi-for-coding", use_general=False) == "kimi-for-coding"


def test_resolve_kimi_model_strips_moonshotai_prefix():
    assert server._resolve_kimi_model("moonshotai/kimi-k2.7", use_general=True) == "kimi-k2.7"


@pytest.mark.parametrize("bad", [
    "deepseek/deepseek-v4-pro", "gpt-4", "glm-5.1",
    "openai/gpt-5.5-pro", "anthropic/claude-opus-4.7", "google/gemini-3.1-pro-preview",
])
def test_resolve_kimi_model_rejects_non_kimi(bad):
    with pytest.raises(ValueError):
        server._resolve_kimi_model(bad, use_general=True)


async def test_kimi_ask_model_override_reaches_payload(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("ok")))
    await server.kimi_ask("hi", model="kimi-k2.6")
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["model"] == "kimi-k2.6"


async def test_kimi_ask_no_override_uses_k27_default(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("ok")))
    await server.kimi_ask("hi")
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["model"] == "kimi-k2.7"


async def test_kimi_ask_rejects_non_kimi_model(mock_client, monkeypatch):
    monkeypatch.setattr(mock_client, "post", AsyncMock(return_value=_resp("ok")))
    out = await server.kimi_ask("hi", model="deepseek/deepseek-v4-pro")
    assert "not a Kimi-family id" in out
    assert not mock_client.post.called
