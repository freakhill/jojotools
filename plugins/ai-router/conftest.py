"""Shared pytest fixtures for the ai-router test suite."""
from __future__ import annotations

import pytest

import server


@pytest.fixture(autouse=True)
def _no_real_op(monkeypatch, tmp_path):
    """Keep tests hermetic around external state:
      * make `op` look absent so _read_or_key_from_op() returns "" without ever
        spawning a real subprocess (op-parse tests re-enable it via shutil.which);
      * start every test with an empty OR-key cache so a key fetched in one test
        cannot leak into the next;
      * point the GPT-5.5 acceptance gate file at a nonexistent temp path so a real
        accepted file on disk can't enable the exception during env-gate tests
        (gate-file tests set it themselves);
      * give Kimi a deterministic test key and drop any real KIMI_API_KEY env so the
        op/env JIT fetch never reaches outside the process (no_kimi tests set _API_KEY="").
    Tests that need a live key set ``server._OR_API_KEY`` directly in their body."""
    monkeypatch.setattr(server.shutil, "which", lambda _name: None)
    monkeypatch.setattr(server, "_OR_API_KEY", "")
    monkeypatch.setattr(server, "_GPT_AUDIT_GATE_FILE", tmp_path / "gpt55-absent")
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.setattr(server, "_API_KEY", "sk-kimi-test")
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.setattr(server, "_GLM_API_KEY", "")
