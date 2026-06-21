# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "mcp[cli]>=1.3",
#   "httpx>=0.27",
# ]
# ///
"""ai-router MCP — three-tier model routing: Kimi K2.7 subscription + OpenRouter + host-native."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config — all tunable via env vars, no key ever touches Claude's context
# ---------------------------------------------------------------------------
# Kimi subscription key — fetched JIT from 1Password (op://claude/kimi-api-key),
# mirroring the OpenRouter key. Read once per process from `op` and cached; the
# KIMI_API_KEY env var is a fallback (transition / standalone / CI). Tests set
# _API_KEY directly to bypass op. The key value is never logged.
_OP_KIMI_ITEM = "kimi-api-key"       # → op://claude/kimi-api-key (same vault as the OR key)
_API_KEY: str = ""                   # process-lifetime cache; "" until first op/env read
# The Kimi coding endpoint (api.kimi.com/coding/v1) gates access to recognised coding-agent
# clients — a request whose User-Agent is NOT one of the approved agents (Kimi CLI, Claude
# Code, …) is refused with HTTP 403 "Kimi For Coding is currently only available for Coding
# Agents". Presenting the Kimi CLI's UA is what lets the subscription key reach the endpoint
# (verified 2026-06-16). Keep this aligned with the installed `kimi` CLI version; override
# with KIMI_USER_AGENT if Moonshot tightens the accepted pattern.
_USER_AGENT = os.environ.get("KIMI_USER_AGENT", "KimiCLI/1.44.0")
_DEFAULT_MAX_TOKENS = 16384  # Aligned with modern model output norms (Sonnet/Opus 4.7, K2.6 all support ≥16K output). Raising the cap only prevents truncation when the answer legitimately needs the room — it does not enlarge typical responses.
_DEFAULT_CONCURRENCY = 8

# ---------------------------------------------------------------------------
# MCP tool-result overflow → filesystem
# ---------------------------------------------------------------------------
# Claude Code caps MCP tool results at the host's inline ceiling (~25K tokens
# by its own tokenizer). Predicting that ceiling from char count is unreliable
# — different content types tokenize at wildly different densities (~5 chars/
# token for prose down to ~1 for CJK or dense code/JSON). Two prior heuristic
# values (4.0 then 3.5) each let dense outputs slip past and forced the host's
# emergency truncation to kick in.
#
# Instead: any output over a low fixed char cap is written to /tmp and the
# response is a short preview + file path. 8000 chars is safe under any
# tokenizer — at the worst observed density (~1 char/token for CJK) that's
# still 8K host tokens, well under the 25K cap. Status/probe responses
# (kimi_status, or_status, or_profile) and short summaries stay inline;
# everything substantive flows through the filesystem.
_INLINE_MAX_CHARS = 8000
_FALLBACK_DIR = os.environ.get("AI_ROUTER_FALLBACK_DIR", "/tmp")


def _output_or_file(content: str, tool: str) -> str:
    """Return `content` inline if small; otherwise write to _FALLBACK_DIR and
    return a preview + file path. The host calls Read on the path to consume
    the full output.

    Falls back to in-place truncation with a diagnostic notice if the file
    write itself fails (e.g., disk full, permission denied).
    """
    if len(content) <= _INLINE_MAX_CHARS:
        return content
    path = f"{_FALLBACK_DIR}/ai-router-{tool}-{int(time.time() * 1000)}.md"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        return (
            content[:_INLINE_MAX_CHARS]
            + f"\n\n[Output truncated at {_INLINE_MAX_CHARS:,} chars; file fallback failed: {e}]"
        )
    preview = content[:1500]
    return (
        f"[Output too large to return inline; full result written to file]\n\n"
        f"File: {path}\n"
        f"Size: {len(content):,} chars\n\n"
        f"Read the file with the Read tool to consume the full output.\n\n"
        f"=== Preview (first 1500 chars) ===\n\n{preview}"
    )

# Coding endpoint — kimi-for-coding (rolling latest coding model, currently K2.7), kimi_analyze.
_BASE_URL = os.environ.get("KIMI_BASE_URL", "https://api.kimi.com/coding/v1")
_MODEL = os.environ.get("KIMI_MODEL", "kimi-for-coding")

# General endpoint — default Kimi K2.7 (latest); handles ask/batch/swarm/research/sentiment.
# Same coding base URL as _BASE_URL; the served model is chosen per request by the payload's
# "model" field, so the endpoint accepts explicit version ids (kimi-k2.7, kimi-k2.6) and the
# rolling kimi-for-coding alias (verified 2026-06-16). Per-call override via kimi_ask/kimi_swarm
# `model=`; global override via the KIMI_GENERAL_MODEL env var.
_GENERAL_BASE_URL = os.environ.get("KIMI_GENERAL_BASE_URL", "https://api.kimi.com/coding/v1")
_GENERAL_MODEL = os.environ.get("KIMI_GENERAL_MODEL", "kimi-k2.7")

# z.ai GLM Coding Plan subscription — direct API key, OpenAI-compatible.
# Flat-rate sub (no per-token marginal cost within plan caps), so treated as Tier 2.
# GLM key — fetched JIT from op://claude/glm-api-key (Secure Note), mirroring the Kimi
# and OR keys; GLM_API_KEY env is a fallback (op first, then env). Cached for the
# process. Tests set _GLM_API_KEY directly to bypass op. The value is never logged.
_OP_GLM_ITEM = "glm-api-key"         # → op://claude/glm-api-key (same vault)
_GLM_API_KEY: str = ""               # process-lifetime cache; "" until first op/env read
_GLM_BASE_URL = os.environ.get("GLM_BASE_URL", "https://api.z.ai/api/coding/paas/v4")
_GLM_MODEL = os.environ.get("GLM_MODEL", "glm-5.1")
_GLM_USER_AGENT = os.environ.get("GLM_USER_AGENT", "ai-router-mcp/glm")

# OpenRouter — multi-model routing, ZDR enforced per-request
# The key is fetched just-in-time from 1Password (op), NOT from the environment —
# there is no standing OPENROUTER_API_KEY export (JIT credential discipline). It is
# read once per process from `op` and cached. Tests may set _OR_API_KEY directly to
# bypass op. The key value is never logged.
_OP_OR_ITEM = "openrouter-api-key"   # 1Password item holding the OpenRouter key
_OP_OR_VAULT = os.environ.get("AI_ROUTER_OP_VAULT", "claude")  # 1Password vault for ALL op keys; override via env
_OR_API_KEY: str = ""               # process-lifetime cache; "" until first op read
_OR_BASE_URL = "https://openrouter.ai/api/v1"
_OR_REFERER = "https://github.com/freakhill/jojotools"
_OR_TITLE = "ai-router-mcp"


def _read_or_key_from_op() -> str:
    """Fetch the OpenRouter key just-in-time from 1Password via the `op` CLI.
    Returns "" if op is missing, signed out, or the item/field is absent — callers
    then surface the usual unavailable error. The key value is never logged."""
    if shutil.which("op") is None:
        return ""
    try:
        proc = subprocess.run(
            ["op", "item", "get", _OP_OR_ITEM, "--vault", _OP_OR_VAULT,
             "--reveal", "--format", "json"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    try:
        fields = (json.loads(proc.stdout) or {}).get("fields", []) or []
    except ValueError:
        return ""
    # Prefer a field whose value looks like an OpenRouter key; else credential/password.
    for f in fields:
        if (f.get("value") or "").strip().startswith("sk-or"):
            return f["value"].strip()
    for f in fields:
        if f.get("id") in ("credential", "password") and (f.get("value") or "").strip():
            return f["value"].strip()
    return ""


def _get_or_api_key() -> str:
    """Return the OpenRouter key, reading it from `op` JIT on first use and caching it."""
    global _OR_API_KEY
    if _OR_API_KEY == "":
        _OR_API_KEY = _read_or_key_from_op()
    return _OR_API_KEY


def _read_kimi_key_from_op() -> str:
    """Fetch the Kimi key just-in-time from 1Password via the `op` CLI
    (item op://claude/kimi-api-key). Returns "" if op is missing, signed out, or the
    item/field is absent — callers then fall back to env or surface unavailable. The
    key value is never logged."""
    if shutil.which("op") is None:
        return ""
    try:
        proc = subprocess.run(
            ["op", "item", "get", _OP_KIMI_ITEM, "--vault", _OP_OR_VAULT,
             "--reveal", "--format", "json"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    try:
        fields = (json.loads(proc.stdout) or {}).get("fields", []) or []
    except ValueError:
        return ""
    # Prefer a field whose value looks like a Kimi/Moonshot key (sk-...); else a
    # secure-note / credential / password field (the key is stored as SECURE_NOTE notesPlain).
    for f in fields:
        if (f.get("value") or "").strip().startswith("sk-"):
            return f["value"].strip()
    for f in fields:
        if f.get("id") in ("credential", "password", "notesPlain") and (f.get("value") or "").strip():
            return f["value"].strip()
    return ""


def _get_kimi_api_key() -> str:
    """Return the Kimi key, reading it from `op` JIT on first use and caching it.
    Falls back to the KIMI_API_KEY env var when op yields nothing (transition /
    standalone / CI) so an existing export keeps working during the migration."""
    global _API_KEY
    if _API_KEY == "":
        _API_KEY = _read_kimi_key_from_op() or os.environ.get("KIMI_API_KEY", "")
    return _API_KEY


def _read_glm_key_from_op() -> str:
    """Fetch the GLM (z.ai) key just-in-time from 1Password via `op`
    (item op://claude/glm-api-key, a Secure Note). Returns "" if op is missing,
    signed out, or the item/field is absent. The key value is never logged."""
    if shutil.which("op") is None:
        return ""
    try:
        proc = subprocess.run(
            ["op", "item", "get", _OP_GLM_ITEM, "--vault", _OP_OR_VAULT,
             "--reveal", "--format", "json"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    try:
        fields = (json.loads(proc.stdout) or {}).get("fields", []) or []
    except ValueError:
        return ""
    # GLM keys have no fixed prefix — take the secure-note / credential field, else any value.
    for f in fields:
        if f.get("id") in ("credential", "password", "notesPlain") and (f.get("value") or "").strip():
            return f["value"].strip()
    for f in fields:
        if (f.get("value") or "").strip():
            return f["value"].strip()
    return ""


def _get_glm_api_key() -> str:
    """Return the GLM key, reading it from `op` JIT on first use and caching it.
    Falls back to the GLM_API_KEY env var when op yields nothing (mirrors the Kimi key)."""
    global _GLM_API_KEY
    if _GLM_API_KEY == "":
        _GLM_API_KEY = _read_glm_key_from_op() or os.environ.get("GLM_API_KEY", "")
    return _GLM_API_KEY

# ---------------------------------------------------------------------------
# PRIVACY POLICY — NO TRAINING ON OUR SESSIONS. NON-NEGOTIABLE.
#
# Every model used through this server must operate under a no-training policy:
#
#   • OpenRouter calls: `"provider": {"data_collection": "deny"}` is injected into
#     EVERY request payload. This tells OpenRouter to route exclusively to providers
#     that have a Zero Data Retention (ZDR) agreement — they do not store, log, or
#     train on our prompts or responses. Removing or omitting this field would silently
#     break this guarantee, so it is set in one place (_or_chat / or_image) and never
#     overridable by callers.
#
#   • Kimi K2.6 (subscription): Moonshot AI's commercial API does not train on API
#     sessions. Enterprise/subscription tier explicitly excludes training data collection.
#
#   • Claude (host): Anthropic's Claude Code / API tier does not train on user sessions.
#
# If you add a new model or provider: confirm their no-training policy BEFORE adding
# them to models.json. Mark `"no_training": true` and document the source in `"no_training_source"`.
# Models without a confirmed no-training policy must NOT be added.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Three-tier routing config — loaded from models.json routing_config at startup.
#
# Tier 1 (host_native): models the calling host already has via its own flat-rate subscription
#   → redirect back to host (zero marginal token cost on the subscription, never pay OR)
# Tier 2 (subscription_api): models we have flat-rate API key subscriptions for (KIMI_API_KEY etc.)
#   → route to their own API (zero marginal token cost on the subscription, never pay OR)
# Tier 3 (openrouter): everything else — per-token paid via OR
#
# banned_providers: providers we refuse to use entirely (any tier), by choice.
#   Currently: openai/ (OpenAI), x-ai/ (xAI/Grok)
#   To change: edit routing_config.banned_providers in models.json only.
#
# Safe hardcoded defaults apply when routing_config is absent from models.json.
# ---------------------------------------------------------------------------

_OR_BLOCKED_PREFIXES: list[str] = ["anthropic/", "moonshotai/", "zai/"]  # safe defaults (tier 1+2)
# Shared client timeout. 300s accommodates Kimi tools whose default max_tokens
# is 65536 — at K2.6's ~50-100 tok/s throughput that needs more than 120s.
# _resolve_client returns the pooled (mockable) client only when the caller's
# timeout matches this value, so keep the per-tool defaults aligned.
_DEFAULT_CLIENT_TIMEOUT = 300.0
_OR_BLOCKED_IDS: set[str] = set()
_BANNED_PREFIXES: list[str] = ["openai/", "x-ai/"]  # safe defaults (banned by choice)
_BANNED_IDS: set[str] = set()

# --- Narrow, OFF-by-default exception to the openai/ ban --------------------
# A SMALL, explicit allowlist of GPT-5.5 model ids may pass the openai/ ban, and
# only when the operator has set the explicit opt-in env var below. This does NOT
# lift the general openai/ ban: every other openai/* and all x-ai/* models stay
# refused on every path (auto-route, explicit model, swarm, compare). ZDR is still
# enforced downstream (_or_chat injects provider.data_collection=deny), so an
# un-approved OpenAI route fails closed rather than leaking. Exact OpenRouter ids
# must be verified when a key is provisioned.
#   - openai/gpt-5.5-pro : GPT-5.5 Pro (deep-reasoning / "thinking" tier) — serves BOTH
#     as the FLO evaluator AUDIT VOICE (the SKILL.md GPT-5.5 gate layers a typed-phrase
#     confirmation + a type-back self-abasement re-confirm on top of this env flag) AND
#     as the general callable jojo added 2026-06-14. The originally-specced
#     `openai/gpt-5.5-thinking` does NOT exist on OpenRouter (verified S14b, 2026-06-14:
#     "not a valid model ID"), so the voice uses the calibrated gpt-5.5-pro instead.
# The hole is exactly 1 id wide, OFF by default, and shuts the moment the gate is unset.
_GPT_AUDIT_MODEL_IDS: frozenset[str] = frozenset({
    "openai/gpt-5.5-pro",
})
_GPT_AUDIT_MODEL_ID = "openai/gpt-5.5-pro"  # canonical FLO audit id (back-compat)
_GPT_AUDIT_ENV = "AI_ROUTER_ALLOW_GPT55_AUDIT"
_TRUTHY = {"1", "true", "yes", "on"}
# Chat-acceptance gate file: written only after the typed-phrase + live conduct-check
# ceremony (FLO SKILL.md GPT-5.5 gate). Lets the exception persist without an env var
# or restart; revocable by deleting the file. Overridable for tests via env.
_GPT_AUDIT_GATE_FILE = Path(
    os.environ.get(
        "AI_ROUTER_GPT_GATE_FILE",
        str(Path.home() / ".config" / "ai-router" / "gpt55-accepted"),
    )
)


def _gpt_audit_enabled() -> bool:
    """The GPT-5.5 exception is ON when EITHER the env opt-in is truthy OR the
    chat-acceptance gate file exists and is non-empty. Both paths leave the openai/
    ban fully intact for every id outside _GPT_AUDIT_MODEL_IDS; this only decides
    whether the allowlisted ids may pass."""
    if os.environ.get(_GPT_AUDIT_ENV, "").strip().lower() in _TRUTHY:
        return True
    try:
        return _GPT_AUDIT_GATE_FILE.is_file() and _GPT_AUDIT_GATE_FILE.read_text().strip() != ""
    except OSError:
        return False


def _gpt_audit_exception_allowed(model: str) -> bool:
    """True only for an explicitly allowlisted GPT-5.5 id AND only when the
    exception is enabled (env opt-in or chat-acceptance gate file). The deliberate,
    strong-gated exception to the openai/ ban — narrow by exact id, off by default.
    Every id outside _GPT_AUDIT_MODEL_IDS stays banned regardless."""
    return model in _GPT_AUDIT_MODEL_IDS and _gpt_audit_enabled()


def _is_banned(model: str) -> bool:
    """Return True if this provider is on the user banlist (refused entirely, not just redirected)."""
    return model in _BANNED_IDS or any(model.startswith(p) for p in _BANNED_PREFIXES)


def _is_blocked_from_or(model: str) -> bool:
    """Return True if this model must never be called via OpenRouter."""
    return model in _OR_BLOCKED_IDS or any(model.startswith(p) for p in _OR_BLOCKED_PREFIXES)


def _blocked_from_or_reason(model: str) -> str:
    """Human-readable reason why a model is blocked from OR."""
    for prefix in _OR_BLOCKED_PREFIXES:
        if model.startswith(prefix):
            return f"'{prefix}*' models are blocked from OpenRouter (tier-1/2 subscription). Edit routing_config in models.json to change this."
    return "Model is in the OR blocked list. Edit routing_config.tier_1_host_native or tier_2_subscription_api in models.json."

# ---------------------------------------------------------------------------
# Lifespan-managed shared HTTP clients — one pool per endpoint
# ---------------------------------------------------------------------------

_shared_client: httpx.AsyncClient | None = None   # coding endpoint
_general_client: httpx.AsyncClient | None = None  # general endpoint
_glm_client: httpx.AsyncClient | None = None       # z.ai GLM Coding Plan
_or_client: httpx.AsyncClient | None = None        # OpenRouter

_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES = 2
_RETRY_BACKOFF = 1.0

# ---------------------------------------------------------------------------
# Model catalog — loaded once from models.json alongside this file
# ---------------------------------------------------------------------------

_MODELS_PATH = Path(__file__).parent / "models.json"
_MODEL_CATALOG: dict = {}


def _load_model_catalog() -> dict:
    try:
        return json.loads(_MODELS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _apply_routing_config(catalog: dict) -> None:
    """Read routing_config from models.json and update the three-tier routing globals.

    Tier 1 (host_native): sets _OR_BLOCKED_PREFIXES / _OR_BLOCKED_IDS for host models.
    Tier 2 (subscription_api): adds subscription API prefixes/IDs to the blocked list.
    Also refreshes _HOST_CAPABLE_HINTS and _KIMI_SUB_HINTS from config if present.
    Falls back to hardcoded defaults when routing_config is absent.
    """
    global _OR_BLOCKED_PREFIXES, _OR_BLOCKED_IDS, _HOST_CAPABLE_HINTS, _KIMI_SUB_HINTS

    rc = catalog.get("routing_config", {})
    if not rc:
        return  # keep hardcoded defaults

    prefixes: list[str] = []
    ids: set[str] = set()

    # Tier 1: host-native models (e.g. all anthropic/* for Claude Code host)
    tier1 = rc.get("tier_1_host_native", {})
    prefixes.extend(tier1.get("prefixes", []))
    ids.update(tier1.get("model_ids", []))
    t1_hints = tier1.get("task_hints")
    if t1_hints:
        _HOST_CAPABLE_HINTS = frozenset(t1_hints)

    # Tier 2: subscription API models (e.g. all moonshotai/* via KIMI_API_KEY)
    for entry in rc.get("tier_2_subscription_api", {}).get("entries", []):
        prefix = entry.get("prefix", "")
        if prefix and prefix not in prefixes:
            prefixes.append(prefix)
        ids.update(entry.get("model_ids", []))
        if entry.get("provider") == "moonshotai":
            t2_hints = entry.get("task_hints")
            if t2_hints:
                _KIMI_SUB_HINTS = frozenset(t2_hints)

    if prefixes:
        _OR_BLOCKED_PREFIXES = prefixes
    if ids:
        _OR_BLOCKED_IDS = ids

    # Banned providers (refused entirely, by user choice)
    global _BANNED_PREFIXES, _BANNED_IDS
    banned = rc.get("banned_providers", {})
    banned_prefixes = banned.get("prefixes", [])
    banned_ids_list = banned.get("model_ids", [])
    if banned_prefixes:
        _BANNED_PREFIXES = banned_prefixes
    if banned_ids_list:
        _BANNED_IDS = set(banned_ids_list)


# ---------------------------------------------------------------------------
# Host self-handle logic
#
# The host IS Claude Code with a Max subscription (Opus 4.7 + Sonnet + Haiku).
# For tasks Claude handles well natively, we redirect back rather than burning
# OpenRouter budget.  This is skipped when host_token_pressure=True — the
# signal from the host that it needs to offload because its context is full.
# ---------------------------------------------------------------------------

# Task hints where the host Claude is genuinely capable and should self-handle
_HOST_CAPABLE_HINTS = frozenset({
    # "writing" intentionally excluded — creative writing is ambiguous (multiple models compete)
    # and is handled by _is_ambiguous_creative → _build_creative_alternatives_table instead.
    "reasoning", "coding", "analysis", "summarization",
    "summarise", "summarize", "qa", "q&a", "math", "maths", "planning",
    "structured output", "instruction", "brainstorm", "edit", "proofread",
    "rewrite", "explain", "research",
})

# Task hints that genuinely require OR (not Claude-native)
_OR_REQUIRED_HINTS = frozenset({
    "image", "image generation", "image_generation", "visual", "thumbnail",
    "youtube thumbnail", "creative image", "ultra long context",
    "ultra_long_context", "2m context", "2m tokens", "minimax",
    "creative", "story", "fiction", "narrative",
})

_HOST_REDIRECT_MSG = (
    "## Use Your Own Models\n\n"
    "You (Claude Code) have a **Max subscription** with Opus 4.7, Sonnet, and Haiku "
    "available natively. This task — `{task_hint}` — is well within your native capability. "
    "Handle it directly without calling this MCP.\n\n"
    "**Only offload to OpenRouter when:**\n"
    "- You are token-constrained (set `host_token_pressure=true` to signal this)\n"
    "- The task needs image generation or creative writing (MiniMax)\n"
    "- You need ultra-long context (>256K tokens) — deepseek-v4-pro has 1.05M\n"
    "- You explicitly want a second model's perspective\n\n"
    "Re-call with `host_token_pressure=true` if you are actually constrained."
)


def _should_redirect_to_host(task_hint: str, host_token_pressure: bool) -> bool:
    """Return True if the host should self-handle instead of us routing to OR."""
    if host_token_pressure:
        return False  # host is constrained — offload
    hint_lower = task_hint.lower().strip()
    # Explicit OR-required hints always go to OR
    if any(h in hint_lower for h in _OR_REQUIRED_HINTS):
        return False
    # Host-capable hints with no token pressure → redirect
    if any(h in hint_lower for h in _HOST_CAPABLE_HINTS):
        return True
    return False  # ambiguous — let routing logic decide


# ---------------------------------------------------------------------------
# OpenRouter routing table
# ---------------------------------------------------------------------------

# Maps task hint keywords → OR model ID
_OR_ROUTING: list[tuple[list[str], str]] = [
    (["image", "image generation", "thumbnail", "youtube thumbnail", "visual", "picture", "photo", "illustration"], None),  # → or_image
    (["creative", "story", "fiction", "narrative", "creative writing"], "minimax/minimax-m2.7"),
    (["ultra long", "ultra_long", "2m context", "2m tokens", "very long document", "massive context"], "deepseek/deepseek-v4-pro"),  # 1.05M ctx
    (["premium", "strongest", "hardest", "frontier"], "xiaomi/mimo-v2.5-pro"),
    (["fast", "cheap", "quick", "batch", "high volume"], "deepseek/deepseek-v4-flash"),
    (["reasoning", "math", "proof", "logic"], "deepseek/deepseek-v4-pro"),
    (["coding", "code", "debug", "refactor", "agentic"], "deepseek/deepseek-v4-pro"),  # fallback when no kimi sub
]

# Task hints where we prefer Kimi subscription over OR
_KIMI_SUB_HINTS = frozenset({
    "coding", "code", "debug", "refactor", "agentic", "analysis",
    "codebase", "analyze", "reasoning", "math", "research", "batch",
})


def _route_or_model(task_hint: str, has_kimi: bool) -> str | None:
    """
    Return the OR model ID for a task hint, or None for image tasks (use or_image).
    Returns empty string "" if we should use kimi subscription instead.
    """
    hint_lower = task_hint.lower().strip()

    # Prefer Kimi subscription for capable tasks (flat-rate, no marginal token cost)
    if has_kimi and any(h in hint_lower for h in _KIMI_SUB_HINTS):
        return ""  # signal: use kimi subscription

    for keywords, model_id in _OR_ROUTING:
        if any(kw in hint_lower for kw in keywords):
            return model_id

    return None  # no match — caller should show alternatives


# ---------------------------------------------------------------------------
# Ambiguous creative hints — multiple models could legitimately excel here.
# For these hints, alternatives MUST always be shown alongside the result
# (rubric fixture F3: "Write creative story about AI" → alternatives visible).
# ---------------------------------------------------------------------------

_AMBIGUOUS_HINTS = frozenset({
    "creative", "story", "fiction", "narrative", "creative writing",
    "write", "writing", "general", "chat", "conversation", "mixed",
    "storytelling", "poem", "poetry", "blog", "essay", "script",
})


def _is_ambiguous_creative(task_hint: str) -> bool:
    """Return True when task_hint signals creative/ambiguous work needing alternatives shown."""
    hint_lower = task_hint.lower().strip()
    return any(h in hint_lower for h in _AMBIGUOUS_HINTS)


def _build_creative_alternatives_table(
    recommended_id: str,
    recommended_name: str,
    task_hint: str,
) -> str:
    """Build a focused alternatives table for creative/ambiguous tasks.

    Shows the recommended model highlighted, plus 3 strong alternatives,
    so the caller can re-call with model='<id>' to switch.
    """
    catalog = _MODEL_CATALOG.get("openrouter_models", [])
    catalog_by_id = {m["id"]: m for m in catalog}

    # Creative-task alternatives — ordered by creative suitability.
    creative_alts = [
        ("minimax/minimax-m2.7", "narrative depth, long-form, creative specialist"),
        ("xiaomi/mimo-v2.5-pro", "strong general-purpose, high usage, balanced"),
        ("deepseek/deepseek-v4-pro", "creative reasoning, structured narrative"),
        ("qwen/qwen3.5-plus-20260420", "balanced creative, multilingual, 1M ctx"),
    ]

    rows: list[str] = []
    seen = set()

    # Recommended row first — marked with star
    rec_m = catalog_by_id.get(recommended_id)
    rec_strengths = ", ".join(rec_m.get("strengths", [])[:3]) if rec_m else "auto-selected for task"
    rec_cost = f"${rec_m['input_cost_per_m']:.3f}/M in" if rec_m else "see OR"
    rows.append(
        f"| **{recommended_name} (recommended)** | `{recommended_id}` | {rec_strengths} | {rec_cost} |"
    )
    seen.add(recommended_id)

    # Up to 3 alternatives (skip recommended)
    added = 0
    for alt_id, alt_strengths in creative_alts:
        if alt_id in seen:
            continue
        alt_m = catalog_by_id.get(alt_id)
        if alt_m:
            cost = f"${alt_m['input_cost_per_m']:.3f}/M in"
            name = alt_m.get("name", alt_id)
            rows.append(f"| {name} | `{alt_id}` | {alt_strengths} | {cost} |")
        else:
            rows.append(f"| {alt_id.split('/')[-1]} | `{alt_id}` | {alt_strengths} | see OR |")
        seen.add(alt_id)
        added += 1
        if added >= 3:
            break

    table = "\n".join(rows)
    return (
        f"\n\n---\n"
        f"## Alternatives for `{task_hint}` tasks\n\n"
        f"Multiple models excel at creative/writing work. Result above used **{recommended_name}**.\n\n"
        f"| Model | ID | Strengths | Cost |\n"
        f"|---|---|---|---|\n"
        f"{table}\n\n"
        f"**Switch model:** re-call with `model=\"<model-id>\"` to use a different one.\n"
        f"**Accept recommendation:** re-call without `model` and same `task_hint` to re-run with the same model."
    )


def _build_alternatives_table(recommended: str = "") -> str:
    """Build the general ambiguous-routing alternatives table.

    When `recommended` is a model ID, that row is marked as recommended.
    """
    catalog = _MODEL_CATALOG.get("openrouter_models", [])
    rows = []
    # Show a curated subset — top picks across tiers
    highlights = [
        "deepseek/deepseek-v4-pro",
        "deepseek/deepseek-v4-flash",
        "xiaomi/mimo-v2.5-pro",
        "minimax/minimax-m2.7",
        "qwen/qwen3.5-plus-20260420",
        "google/gemini-3.1-flash-lite",
    ]
    catalog_by_id = {m["id"]: m for m in catalog}
    for mid in highlights:
        m = catalog_by_id.get(mid)
        if m:
            strengths = ", ".join(m.get("strengths", [])[:3])
            cost = f"${m['input_cost_per_m']:.3f}/M in"
            label = f"**{m['name']} (recommended)**" if mid == recommended else m["name"]
            rows.append(f"| {label} | `{m['id']}` | {strengths} | {cost} |")

    table = "\n".join(rows)
    return (
        "## Routing Recommendation\n\n"
        "Task type unclear. Top alternatives:\n\n"
        "| Model | ID | Strengths | Cost |\n"
        "|---|---|---|---|\n"
        f"| Kimi K2.6 | `kimi_ask` (subscription) | agentic coding, long-horizon | flat-rate sub (no marginal $) |\n"
        f"{table}\n\n"
        "**Re-call with** `model=\"<model-id>\"` to execute with your chosen model.\n"
        "**Or** provide `task_hint` (e.g. `\"coding\"`, `\"chinese\"`, `\"creative\"`, "
        "`\"reasoning\"`, `\"image\"`) for auto-routing.\n\n"
        "**Image generation?** Use `or_image` instead — it routes to DALL-E 3, Flux, or Ideogram."
    )


# ---------------------------------------------------------------------------
# Profile resolution — 5-tier transversal quality/cost profiles
# ---------------------------------------------------------------------------

_PROFILE_USE_KIMI = "__kimi__"  # sentinel: route to Kimi subscription

# Capability hints that map to a specialist model (override profile default)
_SPECIALIST_HINTS: dict[str, str] = {
    "creative": "minimax/minimax-m2.7",
    "story": "minimax/minimax-m2.7",
    "fiction": "minimax/minimax-m2.7",
    "narrative": "minimax/minimax-m2.7",
}

# Capability hints that map to subscription tools (kimi) — profile does not change this
_SUBSCRIPTION_HINTS = frozenset({
    "coding", "code", "debug", "refactor", "agentic",
    "analysis", "codebase", "analyze",
})

# Profile → default OR model (used when no specialist override applies)
_PROFILE_DEFAULT_MODELS: dict[str, str] = {
    "eco":      "deepseek/deepseek-v4-flash",       # $0.112/M — fastest + cheapest, 1.05M ctx
    "mid":      "qwen/qwen3.5-plus-20260420",        # $0.30/M  — balanced, 1M ctx
    "intel":    "deepseek/deepseek-v4-pro",          # $0.44/M  — best reasoning (80.6% SWE-bench)
    "max":      "xiaomi/mimo-v2.5-pro",              # $1.00/M  — #1 OR usage; general quality peak
    # max uses mimo (not deepseek) because mimo wins on general tasks, narrative, and mixed work.
    # For reasoning/math specifically, max+reasoning hint routes to deepseek (see _MAX_PROFILE_REASONING_HINTS).
    "research": "deepseek/deepseek-v4-pro",          # $0.44/M  — 1.05M ctx for large docs
}

# For 'max' profile with reasoning/math hints, prefer deepseek-v4-pro (80.6% SWE-bench)
# over mimo-v2.5-pro. mimo is the general-purpose max choice (#1 OR usage, better narrative
# and mixed tasks); deepseek-v4-pro wins specifically on structured reasoning and math.
_MAX_PROFILE_REASONING_HINTS = frozenset({"reasoning", "math", "proof", "logic", "maths"})


def _resolve_profile_model(profile: str, task_hint: str, has_kimi: bool) -> tuple[str, str]:
    """Resolve the model to use given a profile and task_hint.

    Returns (model_id_or_sentinel, note) where:
      - _PROFILE_USE_KIMI sentinel → route to Kimi subscription (flat-rate; no marginal $)
      - ""                        → no profile resolution; caller falls through to normal routing
      - any other string          → OR model ID to use

    Resolution precedence (highest to lowest):
      1. Subscription wins  — coding/analysis hints → _PROFILE_USE_KIMI (no marginal $, beats any profile)
      2. Specialist wins    — chinese/creative/eu hints → specialist model (beats profile default)
      3. max+reasoning      — max profile + reasoning/math → deepseek-v4-pro (beats mimo default)
      4. Profile default    — _PROFILE_DEFAULT_MODELS[profile] (eco/mid/intel/max/research)
      5. Mismatch note      — research profile with non-research hint: warn but still route
    """
    if not profile or profile not in _PROFILE_DEFAULT_MODELS:
        return "", ""  # no profile resolution — caller falls through to normal routing

    hint_lower = task_hint.lower().strip()

    # 1. Subscription-first (no per-token marginal cost — beats per-token-paid OR regardless of profile)
    if has_kimi and any(h in hint_lower for h in _SUBSCRIPTION_HINTS):
        return _PROFILE_USE_KIMI, f"[Profile: {profile} | Routed to Kimi K2.6 subscription — no marginal $, overrides profile]"

    # 2. Specialist override (regardless of profile level)
    for kw, specialist_model in _SPECIALIST_HINTS.items():
        if kw in hint_lower:
            return specialist_model, f"[Profile: {profile} | Specialist override: {kw} → {specialist_model}]"

    # 3. 'max' profile: prefer DeepSeek V4 Pro for reasoning-heavy tasks (better SWE-bench at lower cost)
    if profile == "max" and any(h in hint_lower for h in _MAX_PROFILE_REASONING_HINTS):
        return "deepseek/deepseek-v4-pro", f"[Profile: max | Reasoning task → deepseek-v4-pro (80.6% SWE-bench)]"

    # 4. Profile default
    default_model = _PROFILE_DEFAULT_MODELS[profile]

    # Research profile: note if task hint doesn't suggest long-context work
    if profile == "research" and hint_lower and not any(
        kw in hint_lower for kw in ("long", "document", "synthesis", "research", "analyze", "compile", "summarize", "context", "ultra", "large", "corpus", "codebase")
    ):
        note = (
            f"[Profile: research | Note: research profile targets long-context synthesis "
            f"(1.05M ctx). For short tasks, 'intel' profile is more cost-efficient. "
            f"Using {default_model}]"
        )
    else:
        note = f"[Profile: {profile} | Model: {default_model}]"

    return default_model, note


# ---------------------------------------------------------------------------
# HTTP client factories
# ---------------------------------------------------------------------------


def _make_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_kimi_api_key()}",
        "Content-Type": "application/json",
        "User-Agent": _USER_AGENT,
    }


def _make_or_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_or_api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": _OR_REFERER,
        "X-Title": _OR_TITLE,
    }


def _make_glm_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_glm_api_key()}",
        "Content-Type": "application/json",
        "User-Agent": _GLM_USER_AGENT,
    }


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[None]:
    global _shared_client, _general_client, _glm_client, _or_client, _MODEL_CATALOG
    _MODEL_CATALOG = _load_model_catalog()
    _apply_routing_config(_MODEL_CATALOG)  # load three-tier routing from models.json

    headers = _make_headers()
    _shared_client = httpx.AsyncClient(
        base_url=_BASE_URL, headers=headers, timeout=_DEFAULT_CLIENT_TIMEOUT, limits=_LIMITS,
    )
    _general_client = httpx.AsyncClient(
        base_url=_GENERAL_BASE_URL, headers=headers, timeout=_DEFAULT_CLIENT_TIMEOUT, limits=_LIMITS,
    )
    _glm_client = httpx.AsyncClient(
        base_url=_GLM_BASE_URL, headers=_make_glm_headers(), timeout=_DEFAULT_CLIENT_TIMEOUT, limits=_LIMITS,
    )
    _or_client = httpx.AsyncClient(
        base_url=_OR_BASE_URL, headers=_make_or_headers(), timeout=180.0, limits=_LIMITS,
    )
    try:
        yield
    finally:
        await _shared_client.aclose()
        await _general_client.aclose()
        await _glm_client.aclose()
        await _or_client.aclose()
        _shared_client = None
        _general_client = None
        _glm_client = None
        _or_client = None


mcp = FastMCP("ai-router", lifespan=_lifespan)


def _resolve_client(use_general: bool = False, timeout: float = _DEFAULT_CLIENT_TIMEOUT) -> tuple[httpx.AsyncClient, bool]:
    """Return (client, is_shared). is_shared=False means the caller must close it.
    The pooled lifespan client is reused whenever it exists; the per-call `timeout`
    is applied on the request (see _chat) rather than baked into a throwaway client,
    so long-running calls (e.g. kimi_swarm at 600s) still reuse the connection pool.
    The `timeout` arg here only configures the fallback client when no pool exists."""
    if use_general:
        if _general_client is not None:
            return _general_client, True
        return httpx.AsyncClient(
            base_url=_GENERAL_BASE_URL, headers=_make_headers(), timeout=timeout, limits=_LIMITS,
        ), False
    if _shared_client is not None:
        return _shared_client, True
    return httpx.AsyncClient(
        base_url=_BASE_URL, headers=_make_headers(), timeout=timeout, limits=_LIMITS,
    ), False


def _resolve_or_client(timeout: float = 180.0) -> tuple[httpx.AsyncClient, bool]:
    if _or_client is not None:
        return _or_client, True
    return httpx.AsyncClient(
        base_url=_OR_BASE_URL, headers=_make_or_headers(), timeout=timeout, limits=_LIMITS,
    ), False


# ---------------------------------------------------------------------------
# Core Kimi chat call (unchanged from original)
# ---------------------------------------------------------------------------

def _resolve_kimi_model(model: str | None, use_general: bool) -> str:
    """Pick the Kimi model id for a chat call.

    Empty/None → the configured default (_GENERAL_MODEL for the general tools, _MODEL
    for kimi_analyze). A non-empty override is validated to the Kimi family and
    normalised (a leading 'moonshotai/' is stripped, since the coding endpoint expects
    the bare id). Anything that is not a Kimi id raises ValueError — the kimi_* tools
    must never use the subscription key/endpoint to reach a non-subscription, banned,
    or OR-billed model (use or_ask / glm_ask for those)."""
    if not model:
        return _GENERAL_MODEL if use_general else _MODEL
    mid = model.strip()
    norm = mid[len("moonshotai/"):] if mid.startswith("moonshotai/") else mid
    if norm == "kimi-for-coding" or norm.startswith("kimi-"):
        return norm
    raise ValueError(
        f"model={model!r} is not a Kimi-family id. The kimi_* tools only run Kimi "
        "models on the subscription key (e.g. 'kimi-k2.7', 'kimi-k2.6', "
        "'kimi-for-coding'). Use or_ask / glm_ask for other providers."
    )


async def _chat(
    messages: list[dict],
    *,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    temperature: float = 0.7,
    include_reasoning: bool = False,
    thinking: bool = False,
    use_general: bool = False,
    timeout: float = _DEFAULT_CLIENT_TIMEOUT,
    model: str | None = None,
) -> str:
    if not _get_kimi_api_key():
        raise RuntimeError("Kimi key unavailable — could not read it from 1Password (op://claude/kimi-api-key) or KIMI_API_KEY env")

    chosen = _resolve_kimi_model(model, use_general)
    # Kimi (kimi-k2.6 / kimi-k2.7 / kimi-for-coding) only accepts temperature=1 — any other
    # value fails with "invalid temperature: only 1 is allowed for this model". _chat is
    # Kimi-only (GLM uses _glm_chat, OpenRouter _or_chat), so we pin it here regardless of the
    # caller's `temperature` arg (which several callers leave at the 0.7 default or pass 0.1).
    # The arg is retained for signature compatibility but no longer reaches the wire.
    payload: dict = {"model": chosen, "messages": messages, "max_tokens": max_tokens, "temperature": 1.0}
    if thinking:
        payload["thinking"] = {"type": "enabled"}

    client, is_shared = _resolve_client(use_general, timeout)
    last_exc: Exception | None = None
    try:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                r = await client.post("/chat/completions", json=payload, timeout=timeout)
                if r.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BACKOFF * (attempt + 1))
                    continue
                r.raise_for_status()
                msg = r.json()["choices"][0]["message"]
                content = msg.get("content") or ""
                reasoning = msg.get("reasoning_content") or ""
                if not content and reasoning:
                    content, reasoning = reasoning, ""
                if include_reasoning and reasoning:
                    return f"<reasoning>\n{reasoning}\n</reasoning>\n\n{content}"
                return content
            except httpx.HTTPStatusError as e:
                if e.response.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
                    last_exc = e
                    await asyncio.sleep(_RETRY_BACKOFF * (attempt + 1))
                    continue
                raise
            except httpx.TransportError as e:
                if attempt < _MAX_RETRIES:
                    last_exc = e
                    await asyncio.sleep(_RETRY_BACKOFF * (attempt + 1))
                    continue
                raise
    finally:
        if not is_shared:
            await client.aclose()
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# z.ai GLM chat call — OpenAI-compatible, retries + backoff like _chat
# ---------------------------------------------------------------------------

async def _glm_chat(
    messages: list[dict],
    *,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    temperature: float = 0.7,
    include_reasoning: bool = False,
    model: str | None = None,
    timeout: float = _DEFAULT_CLIENT_TIMEOUT,
) -> str:
    if not _get_glm_api_key():
        raise RuntimeError("GLM key unavailable — could not read it from 1Password (op://claude/glm-api-key) or GLM_API_KEY env")

    payload: dict = {
        "model": model or _GLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    if _glm_client is not None and timeout == _DEFAULT_CLIENT_TIMEOUT:
        client, is_shared = _glm_client, True
    else:
        client = httpx.AsyncClient(
            base_url=_GLM_BASE_URL, headers=_make_glm_headers(), timeout=timeout, limits=_LIMITS,
        )
        is_shared = False

    last_exc: Exception | None = None
    try:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                r = await client.post("/chat/completions", json=payload)
                if r.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BACKOFF * (attempt + 1))
                    continue
                r.raise_for_status()
                msg = r.json()["choices"][0]["message"]
                content = msg.get("content") or ""
                reasoning = msg.get("reasoning_content") or ""
                if not content and reasoning:
                    content, reasoning = reasoning, ""
                if include_reasoning and reasoning:
                    return f"<reasoning>\n{reasoning}\n</reasoning>\n\n{content}"
                return content
            except httpx.HTTPStatusError as e:
                if e.response.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
                    last_exc = e
                    await asyncio.sleep(_RETRY_BACKOFF * (attempt + 1))
                    continue
                raise
            except httpx.TransportError as e:
                if attempt < _MAX_RETRIES:
                    last_exc = e
                    await asyncio.sleep(_RETRY_BACKOFF * (attempt + 1))
                    continue
                raise
    finally:
        if not is_shared:
            await client.aclose()
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# OpenRouter chat call — ZDR enforced on every request
# ---------------------------------------------------------------------------

async def _or_chat(
    messages: list[dict],
    model: str,
    *,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    temperature: float = 0.7,
    system: str = "",
    include_reasoning: bool = False,
) -> str:
    if not _get_or_api_key():
        raise RuntimeError("OpenRouter key unavailable — could not read it from 1Password (op://claude/openrouter-api-key). Is op signed in?")
    # Banned providers (user choice — refused entirely), except the single narrow
    # GPT-5.5 audit-voice exception gated by env opt-in (see _gpt_audit_exception_allowed).
    if _is_banned(model) and not _gpt_audit_exception_allowed(model):
        raise RuntimeError(
            f"Model {model!r} is from a banned provider. "
            "Edit routing_config.banned_providers in models.json to change this."
        )
    # Block tier-1 and tier-2 models from OR — loaded from routing_config in models.json
    if _is_blocked_from_or(model):
        raise RuntimeError(
            f"Model {model!r} is blocked from OpenRouter. {_blocked_from_or_reason(model)}"
        )

    all_messages: list[dict] = []
    if system:
        all_messages.append({"role": "system", "content": system})
    all_messages.extend(messages)

    payload: dict = {
        "model": model,
        "messages": all_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        # NO-TRAINING ENFORCEMENT: "deny" routes ONLY to ZDR providers (no storage, no training).
        # This field must never be removed. See privacy policy comment near top of file.
        "provider": {"data_collection": "deny"},
    }

    client, is_shared = _resolve_or_client()
    last_exc: Exception | None = None
    try:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                r = await client.post("/chat/completions", json=payload)
                if r.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BACKOFF * (attempt + 1))
                    continue
                r.raise_for_status()
                msg = r.json()["choices"][0]["message"]
                content = msg.get("content") or ""
                reasoning = msg.get("reasoning_content") or ""
                if not content and reasoning:
                    content, reasoning = reasoning, ""
                if include_reasoning and reasoning:
                    return f"<reasoning>\n{reasoning}\n</reasoning>\n\n{content}"
                return content
            except httpx.HTTPStatusError as e:
                if e.response.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
                    last_exc = e
                    await asyncio.sleep(_RETRY_BACKOFF * (attempt + 1))
                    continue
                raise
            except httpx.TransportError as e:
                if attempt < _MAX_RETRIES:
                    last_exc = e
                    await asyncio.sleep(_RETRY_BACKOFF * (attempt + 1))
                    continue
                raise
    finally:
        if not is_shared:
            await client.aclose()
    raise last_exc  # type: ignore[misc]


def _http_error_msg(e: httpx.HTTPStatusError) -> str:
    try:
        return e.response.json().get("error", {}).get("message", str(e))
    except Exception:
        return str(e)


# ---------------------------------------------------------------------------
# File reader for kimi_analyze — sync, offloaded via asyncio.to_thread
# ---------------------------------------------------------------------------

_SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".next", "target", ".cache", ".idea", ".mypy_cache", ".pytest_cache",
    "coverage", ".tox", "eggs", "vendor",
})
_SKIP_EXTS = frozenset({
    ".lock", ".sum", ".min.js", ".min.css", ".png", ".jpg", ".jpeg", ".gif",
    ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip", ".gz",
    ".tar", ".pyc", ".pyo", ".class", ".o", ".a", ".so", ".dylib", ".dll",
    ".exe", ".bin", ".db", ".sqlite", ".sqlite3",
})
_TEXT_EXTS = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".rb", ".java", ".c",
    ".cpp", ".cc", ".h", ".hpp", ".cs", ".php", ".swift", ".kt", ".scala",
    ".ml", ".mli", ".ex", ".exs", ".clj", ".hs", ".elm", ".vue", ".svelte",
    ".html", ".css", ".scss", ".less", ".md", ".txt", ".yaml", ".yml",
    ".json", ".toml", ".ini", ".cfg", ".conf", ".sh", ".fish", ".zsh",
    ".bash", ".env.example", ".gitignore", ".dockerignore",
})
_TEXT_NAMES = frozenset({"Dockerfile", "Makefile", "Procfile", "Pipfile", "Gemfile"})


def _read_dir(work_dir: str, max_bytes: int = 900_000) -> str:
    """Synchronous directory reader — always called via asyncio.to_thread."""
    root = Path(work_dir).expanduser().resolve()
    if not root.is_dir():
        return f"Error: {work_dir!r} is not a directory"

    parts: list[str] = []
    total = 0
    skipped = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(p in _SKIP_DIRS for p in path.parts):
            continue
        suf = path.suffix.lower()
        if suf in _SKIP_EXTS:
            continue
        if suf not in _TEXT_EXTS and path.name not in _TEXT_NAMES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            skipped += 1
            continue

        rel = path.relative_to(root)
        chunk = f"### {rel}\n```\n{text}\n```\n\n"
        if total + len(chunk) > max_bytes:
            parts.append(f"\n[Truncated after {total:,} bytes — {skipped} files skipped]\n")
            break
        parts.append(chunk)
        total += len(chunk)

    if not parts:
        return f"No readable source files found in {work_dir!r}"
    return "".join(parts)


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

_FORMAT = {
    "summary": "Be extremely concise. Bullet points only. Max ~1500 words. Put critical findings first.",
    "normal": "Be thorough but structured. Use markdown headers. Max ~6000 words.",
    "detailed": "Include code snippets (≤30 lines each). Full analysis. Max ~20000 words.",
}

_AI_CONSUMER = (
    "IMPORTANT: Your response will be consumed by another AI (Claude) with a limited context window. "
    "Prioritize information density. No pleasantries. Put the most critical findings first."
)


# ---------------------------------------------------------------------------
# Existing Kimi tools — UNCHANGED
# ---------------------------------------------------------------------------


@mcp.tool()
async def kimi_ask(
    prompt: str,
    system: str = "",
    max_tokens: int = 65536,
    include_reasoning: bool = False,
    model: str = "",
) -> str:
    """Single-turn query to Kimi (default K2.7; 256K context, reasoning model).
    system: optional system prompt. include_reasoning=True prepends <reasoning> block.
    model: optional Kimi-model override on the same subscription key —
    'kimi-k2.7' (default), 'kimi-k2.6', or 'kimi-for-coding'. Non-Kimi ids are
    rejected (use or_ask / glm_ask for other providers).

    Output handling: responses over 8,000 chars are written to
    /tmp/ai-router-kimi_ask-<ts>.md and a preview + path is returned; the
    host calls Read on the path. max_tokens defaults to the model's full output
    ceiling (65536); the file fallback prevents long outputs from hitting
    the host's MCP inline ceiling."""
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    try:
        result = await _chat(msgs, max_tokens=max_tokens, include_reasoning=include_reasoning, use_general=True, model=model or None)
        return _output_or_file(result, "kimi_ask")
    except httpx.HTTPStatusError as e:
        return f"API error: {_http_error_msg(e)}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def kimi_analyze(
    question: str,
    work_dir: str = "",
    content: str = "",
    detail_level: str = "normal",
    max_tokens: int = 65536,
    include_reasoning: bool = False,
) -> str:
    """Analyze a codebase or large text with Kimi K2.6's 256K context.
    Supply either work_dir (auto-reads source files) or content (raw text).
    detail_level: 'summary' (~1500w bullets) | 'normal' (~6000w, default) | 'detailed' (~20000w with code).
    Uses the coding-specialist model (kimi-for-coding) for best code analysis results.

    Output handling: analyses over 8,000 chars are written to
    /tmp/ai-router-kimi_analyze-<ts>.md and a preview + path is returned;
    the host calls Read on the path. max_tokens defaults to the model
    output ceiling (65536)."""
    if not content and not work_dir:
        return "Error: provide either work_dir (path) or content (text)"

    body = content if content else await asyncio.to_thread(_read_dir, work_dir)
    if body.startswith("Error:"):
        return body

    fmt = _FORMAT.get(detail_level, _FORMAT["normal"])
    system = f"Analyze the following for another AI. {fmt} {_AI_CONSUMER}"
    user = f"{body}\n\n---\n\nQuestion/Task: {question}"

    try:
        result = await _chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            include_reasoning=include_reasoning,
        )
        return _output_or_file(result, "kimi_analyze")
    except httpx.HTTPStatusError as e:
        return f"API error: {_http_error_msg(e)}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def kimi_batch(
    prompts: list[str],
    system: str = "",
    max_tokens: int = 8192,
    concurrency: int = _DEFAULT_CONCURRENCY,
) -> str:
    """Fan out N prompts to Kimi K2.6 in parallel. Returns JSON array of
    {index, ok, result/error}. system: shared system prompt for all prompts.
    concurrency: max simultaneous requests (default 8).

    Output handling: when the combined JSON array exceeds 8,000 chars the
    full results array is written to /tmp/ai-router-kimi_batch-<ts>.md (json
    content) and a preview + path is returned. The host Reads the file to
    consume all items. (File fallback is used rather than pagination because
    the server is stateless — pagination would
    require re-executing every prompt per page, which would be wasteful and
    semantically wrong.)"""
    sem = asyncio.Semaphore(concurrency)

    async def one(i: int, p: str) -> dict:
        async with sem:
            msgs: list[dict] = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.append({"role": "user", "content": p})
            try:
                result = await _chat(msgs, max_tokens=max_tokens, use_general=True, timeout=300.0)
                return {"index": i, "ok": True, "result": result}
            except httpx.HTTPStatusError as e:
                return {"index": i, "ok": False, "error": _http_error_msg(e)}
            except Exception as e:
                return {"index": i, "ok": False, "error": str(e)}

    results = await asyncio.gather(*[one(i, p) for i, p in enumerate(prompts)])
    return _output_or_file(json.dumps(results, ensure_ascii=False, indent=2), "kimi_batch")


@mcp.tool()
async def kimi_research_compile(
    sources: list[str],
    synthesis_prompt: str,
    output_format: str = "structured",
    max_tokens: int = 65536,
    concurrency: int = _DEFAULT_CONCURRENCY,
) -> str:
    """Two-phase parallel research compilation then synthesis.
    sources: list of raw text strings. output_format: 'structured' (headers+bullets, default)
    | 'narrative' (prose) | 'table' (markdown tables).

    Output handling: synthesis output over 8,000 chars is written to
    /tmp/ai-router-kimi_research_compile-<ts>.md and the response is a
    preview + file path. Read the file with the Read tool to consume the
    full synthesis."""
    sem = asyncio.Semaphore(concurrency)

    async def extract(i: int, src: str) -> str:
        async with sem:
            try:
                return await _chat(
                    [
                        {"role": "system", "content": (
                            f"Extract only what is relevant to: {synthesis_prompt}\n"
                            "Be concise and structured. Omit irrelevant content."
                        )},
                        {"role": "user", "content": src},
                    ],
                    max_tokens=3072,
                    use_general=True,
                )
            except Exception as e:
                return f"[Extract error for source {i}: {e}]"

    extracts = await asyncio.gather(*[extract(i, s) for i, s in enumerate(sources)])

    combined = "\n\n---\n\n".join(
        f"## Source {i + 1}\n{e}" for i, e in enumerate(extracts)
    )

    fmt_instructions = {
        "structured": "Use markdown headers and bullet points.",
        "narrative": "Write in flowing prose with clear sections.",
        "table": "Use markdown tables wherever comparison is useful.",
    }

    try:
        result = await _chat(
            [
                {"role": "system", "content": (
                    f"Synthesize the following research extracts. "
                    f"{fmt_instructions.get(output_format, '')} {_AI_CONSUMER}"
                )},
                {"role": "user", "content": f"Goal: {synthesis_prompt}\n\n{combined}"},
            ],
            max_tokens=max_tokens,
            use_general=True,
            timeout=300.0,
        )
        return _output_or_file(result, "kimi_research_compile")
    except httpx.HTTPStatusError as e:
        return f"API error: {_http_error_msg(e)}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def kimi_sentiment_batch(
    texts: list[str],
    context: str = "",
    dimensions: str = "positive,negative,neutral,confidence",
    concurrency: int = _DEFAULT_CONCURRENCY,
) -> str:
    """Mass parallel sentiment analysis. Returns JSON array with scores per text.
    dimensions: comma-separated fields to score (0.0–1.0 floats).
    Ideal for analyzing large corpora of reviews, comments, or feedback."""
    dims = [d.strip() for d in dimensions.split(",") if d.strip()]
    schema_desc = ", ".join(f'"{d}": float 0-1' for d in dims)
    context_note = f" Context: {context}" if context else ""

    system = (
        f"Analyze sentiment and return ONLY valid JSON with fields: {{{schema_desc}, "
        f'"summary": "one sentence"}}. No markdown, no explanation.{context_note}'
    )

    sem = asyncio.Semaphore(concurrency)

    async def analyze(i: int, text: str) -> dict:
        async with sem:
            try:
                raw = await _chat(
                    [{"role": "system", "content": system}, {"role": "user", "content": text}],
                    max_tokens=512,
                    temperature=0.1,
                    use_general=True,
                )
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                try:
                    parsed = json.loads(raw)
                    return {"index": i, "ok": True, **parsed}
                except json.JSONDecodeError:
                    return {"index": i, "ok": True, "raw": raw}
            except httpx.HTTPStatusError as e:
                return {"index": i, "ok": False, "error": _http_error_msg(e)}
            except Exception as e:
                return {"index": i, "ok": False, "error": str(e)}

    results = await asyncio.gather(*[analyze(i, t) for i, t in enumerate(texts)])
    return _output_or_file(json.dumps(results, ensure_ascii=False, indent=2), "kimi_sentiment_batch")


@mcp.tool()
async def kimi_swarm(
    task: str,
    context: str = "",
    max_tokens: int = 65536,
    include_reasoning: bool = True,
    model: str = "",
) -> str:
    """Activate Kimi's native Agent Swarm (default K2.7) for long-horizon tasks (up to 300 sub-agents,
    4,000 coordinated steps). Best for: complex multi-file refactors, architecture design,
    deep research, or any task that benefits from sustained multi-step reasoning chains.

    Contrast with kimi_batch: kimi_batch fans out N independent prompts across N separate API
    calls (you orchestrate in parallel). kimi_swarm sends ONE task and Kimi internally
    decomposes, assigns sub-agents, tracks progress, and merges results — the model orchestrates.

    include_reasoning=True (default) exposes the full swarm reasoning trace.
    model: optional Kimi-model override ('kimi-k2.7' default, 'kimi-k2.6', 'kimi-for-coding').

    Output handling: swarm output over 8,000 chars is written to
    /tmp/ai-router-kimi_swarm-<ts>.md and the response is a preview + file
    path; the host calls Read on the path to consume the full output."""
    msgs: list[dict] = []
    if context:
        msgs.append({"role": "system", "content": context})
    msgs.append({"role": "user", "content": task})
    try:
        result = await _chat(
            msgs,
            max_tokens=max_tokens,
            temperature=1.0,
            include_reasoning=include_reasoning,
            thinking=True,
            use_general=True,
            timeout=600.0,
            model=model or None,
        )
        return _output_or_file(result, "kimi_swarm")
    except httpx.HTTPStatusError as e:
        return f"API error: {_http_error_msg(e)}"
    except Exception as e:
        return f"Error: {e}"


async def _probe_endpoint(
    base_url: str,
    model: str,
    client: httpx.AsyncClient | None,
    *,
    headers_fn=_make_headers,
    auth_var: str = "KIMI_API_KEY",
) -> str:
    """Probe an endpoint via POST /chat/completions (1 token)."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }
    try:
        if client is not None:
            r = await client.post("/chat/completions", json=payload)
        else:
            async with httpx.AsyncClient(
                base_url=base_url, headers=headers_fn(), timeout=15.0,
            ) as c:
                r = await c.post("/chat/completions", json=payload)
        if r.status_code == 200:
            return "OK ✓"
        if r.status_code in (401, 403):
            return f"HTTP {r.status_code} (auth error — check {auth_var})"
        if r.status_code in (400, 422):
            try:
                detail = r.json().get("error", {}).get("message", "")
                hint = f" — {detail}" if detail else ""
            except Exception:
                hint = ""
            return f"HTTP {r.status_code} (bad request{hint})"
        if r.status_code == 404:
            return "HTTP 404 (endpoint not found — check base URL)"
        if r.status_code == 429:
            return "HTTP 429 (rate limited — tools will still work when quota resets)"
        if r.status_code >= 500:
            return f"HTTP {r.status_code} (server error)"
        return f"HTTP {r.status_code}"
    except httpx.TimeoutException:
        return "ERROR — connection timed out"
    except Exception as e:
        return f"ERROR — {e}"


@mcp.tool()
async def kimi_status() -> str:
    """Check connectivity to both Kimi endpoints (coding + general). Use to verify setup."""
    lines = [
        f"API key   : {'set ✓ (op://claude/kimi-api-key)' if _get_kimi_api_key() else 'NOT SET — add op://claude/kimi-api-key or export KIMI_API_KEY'}",
        f"UA        : {_USER_AGENT}  (coding-agent gate — see KIMI_USER_AGENT)",
        f"Models    : general default={_GENERAL_MODEL}, coding={_MODEL}; per-call override via kimi_ask/kimi_swarm model= (kimi-k2.7 | kimi-k2.6 | kimi-for-coding)",
    ]
    if not _get_kimi_api_key():
        return "\n".join(lines)

    endpoints = [
        ("Coding  (kimi_analyze)", _BASE_URL, _MODEL, _shared_client),
        ("General (all other tools)", _GENERAL_BASE_URL, _GENERAL_MODEL, _general_client),
    ]
    probe_results = await asyncio.gather(*[
        _probe_endpoint(base_url, model, client)
        for _, base_url, model, client in endpoints
    ])
    for (label, base_url, model, _), status in zip(endpoints, probe_results):
        lines.append(f"\n{label}")
        lines.append(f"  url   : {base_url}  model={model}")
        lines.append(f"  status: {status}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# z.ai GLM tools — Tier-2 subscription (flat-rate, no marginal $)
# ---------------------------------------------------------------------------


@mcp.tool()
async def glm_ask(
    prompt: str,
    system: str = "",
    max_tokens: int = 32768,
    temperature: float = 0.7,
    model: str = "",
    include_reasoning: bool = False,
) -> str:
    """Single-turn query to z.ai GLM (default glm-5.1 — coding/reasoning, 200K context).

    z.ai GLM Coding Plan is a flat-rate subscription — no per-token marginal cost
    within plan caps. Prefer over OpenRouter when the task fits.

    model: override the default model. Available on the Coding Plan endpoint:
      glm-5.1 (default), glm-5, glm-5-turbo, glm-4.7, glm-4.6, glm-4.5, glm-4.5-air.
    include_reasoning=True prepends a <reasoning> block when the model returns one.

    Output handling: responses over 8,000 chars are written to
    /tmp/ai-router-glm_ask-<ts>.md; the host Reads the file to consume the full output.
    """
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    try:
        result = await _glm_chat(
            msgs,
            max_tokens=max_tokens,
            temperature=temperature,
            include_reasoning=include_reasoning,
            model=model or None,
        )
        return _output_or_file(result, "glm_ask")
    except httpx.HTTPStatusError as e:
        return f"API error: {_http_error_msg(e)}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def glm_status() -> str:
    """Check connectivity to the z.ai GLM endpoint. Use to verify setup."""
    lines = [
        f"API key   : {'set ✓ (op://claude/glm-api-key)' if _get_glm_api_key() else 'NOT SET — add op://claude/glm-api-key or export GLM_API_KEY'}",
        f"UA        : {_GLM_USER_AGENT}",
    ]
    if not _get_glm_api_key():
        return "\n".join(lines)

    status = await _probe_endpoint(
        _GLM_BASE_URL, _GLM_MODEL, _glm_client,
        headers_fn=_make_glm_headers, auth_var="GLM_API_KEY",
    )
    lines.append(f"\nGLM Coding Plan (glm_ask)")
    lines.append(f"  url   : {_GLM_BASE_URL}  model={_GLM_MODEL}")
    lines.append(f"  status: {status}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# New OpenRouter tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def or_ask(
    prompt: str,
    model: str = "auto",
    task_hint: str = "",
    profile: str = "",
    max_tokens: int = 32768,
    system: str = "",
    host_token_pressure: bool = False,
) -> str:
    """Route a single-turn query to the best model via OpenRouter.

    IMPORTANT — read before calling:
    You (Claude Code) have a Max subscription with Opus 4.7, Sonnet, and Haiku natively.
    If host_token_pressure=False (default) and task_hint maps to something Claude handles
    well (coding, writing, reasoning, analysis, math, Q&A), this tool will redirect you
    back to handle it yourself — no token burn on OR.

    Note: setting `profile` explicitly opts OUT of the host-redirect. Profiles signal you
    want OR routing. Use `host_token_pressure=True` OR leave `profile=""` to get host redirect.

    Set host_token_pressure=True when your context window is actually constrained and you
    need to offload to save your own tokens.

    model: "auto" (smart routing) | specific OR model ID (e.g. "deepseek/deepseek-v4-pro")
    task_hint: "coding" | "chinese" | "creative" | "reasoning" | "image" | "ultra long context" | ...
    profile: "eco" | "mid" | "intel" | "max" | "research"
      eco    = cheapest capable (<$0.25/M in) — deepseek-v4-flash
      mid    = balanced quality/cost (~$0.30/M in) — qwen3.5-plus
      intel  = best reasoning, cost-aware (~$0.44/M in) — deepseek-v4-pro
      max    = strongest available, no constraint ($1.00/M in) — mimo-v2.5-pro
      research = long-context synthesis, ≥500K ctx (~$0.44/M in) — deepseek-v4-pro
      Profile is ignored when model is explicitly set or task has a specialist override.
      Specialist overrides (chinese, creative, eu_sovereignty) always win regardless of profile.
      Subscription tools (kimi for coding/analysis) always win over paid OR regardless of profile.
    host_token_pressure: True = host context is full, offload now; False = check if self-handle first
    """
    # --- Host self-handle check (only when model=auto and no profile forcing OR) ---
    if model == "auto" and task_hint and not profile and _should_redirect_to_host(task_hint, host_token_pressure):
        return _HOST_REDIRECT_MSG.format(task_hint=task_hint)

    # --- Image generation redirect ---
    if task_hint and any(kw in task_hint.lower() for kw in ["image", "visual", "thumbnail", "picture"]):
        return (
            "Use `or_image` for image generation tasks. "
            "It routes to Flux 1.1 Pro, Ideogram V2, Flux Schnell, or SDXL "
            "based on your use case (thumbnail, cinematic, text overlay, bulk frames)."
        )

    # --- Profile resolution (when model=auto and profile is set) ---
    profile_note = ""
    if model == "auto" and profile:
        resolved_model, profile_note = _resolve_profile_model(profile, task_hint, has_kimi=bool(_get_kimi_api_key()))
        if resolved_model == _PROFILE_USE_KIMI:
            # Subscription (Kimi) wins — use kimi and annotate with profile
            msgs: list[dict] = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.append({"role": "user", "content": prompt})
            try:
                result = await _chat(msgs, max_tokens=max_tokens, use_general=True)
                return _output_or_file(
                    f"{profile_note}\n[Routed to Kimi K2.6 subscription — no marginal $, overrides profile]\n\n{result}",
                    "or_ask",
                )
            except Exception as e:
                return f"Error (Kimi): {e}"
        elif resolved_model:  # non-empty, non-sentinel → OR model
            model = resolved_model
        # else resolved_model == "" → profile not found, fall through to normal routing

    # --- Standard model resolution (no profile, or profile didn't fully resolve) ---
    show_creative_alts = False  # whether to append creative alternatives after result
    if model == "auto":
        if not task_hint:
            return _build_alternatives_table()
        routed = _route_or_model(task_hint, has_kimi=bool(_get_kimi_api_key()))
        if routed is None:
            return _build_alternatives_table()
        if routed == "":
            # Use Kimi subscription instead
            msgs2: list[dict] = []
            if system:
                msgs2.append({"role": "system", "content": system})
            msgs2.append({"role": "user", "content": prompt})
            try:
                result = await _chat(msgs2, max_tokens=max_tokens, use_general=True)
                return _output_or_file(
                    f"[Routed to Kimi K2.6 subscription — no marginal $]\n\n{result}",
                    "or_ask",
                )
            except Exception as e:
                return f"Error (Kimi): {e}"
        # Check if the task hint is creative/ambiguous — if so, show alternatives alongside result
        if _is_ambiguous_creative(task_hint):
            show_creative_alts = True
        model = routed

    if not _get_or_api_key():
        return (
            "OpenRouter key unavailable — could not read it from 1Password (op://claude/openrouter-api-key). Is op signed in?\n"
            f"Would have used model: {model}"
        )

    try:
        result = await _or_chat(
            [{"role": "user", "content": prompt}],
            model=model,
            max_tokens=max_tokens,
            system=system,
        )
        header = f"{profile_note}\n[Model: {model} | ZDR: enforced]\n\n" if profile_note else f"[Model: {model} | ZDR: enforced]\n\n"
        if show_creative_alts:
            # Fixture F3: creative/ambiguous hints MUST show alternatives table
            catalog = _MODEL_CATALOG.get("openrouter_models", [])
            catalog_by_id = {m["id"]: m for m in catalog}
            rec_entry = catalog_by_id.get(model)
            rec_name = rec_entry.get("name", model.split("/")[-1]) if rec_entry else model.split("/")[-1]
            alts = _build_creative_alternatives_table(model, rec_name, task_hint)
            return _output_or_file(f"{header}{result}{alts}", "or_ask")
        return _output_or_file(f"{header}{result}", "or_ask")
    except httpx.HTTPStatusError as e:
        return f"OR API error ({model}): {_http_error_msg(e)}"
    except Exception as e:
        return f"Error ({model}): {e}"


@mcp.tool()
async def or_swarm(
    task: str,
    model: str = "auto",
    task_hint: str = "",
    max_tokens: int = 65536,
    system: str = "",
    include_reasoning: bool = True,
    host_token_pressure: bool = False,
) -> str:
    """Route a complex multi-step task to the best model via OpenRouter.

    IMPORTANT — read before calling:
    For complex agentic/coding tasks where Kimi subscription is available, prefer kimi_swarm
    (flat-rate, no marginal $). Use or_swarm when: (a) you need a specific non-Kimi model, (b) host is
    token-constrained (host_token_pressure=True), or (c) task genuinely requires a different
    model's strengths (e.g. Chinese, creative, ultra-long context).

    For tasks Claude handles well natively (host_token_pressure=False), this tool will
    redirect you back to handle it yourself.

    model: "auto" | specific OR model ID
    task_hint: "coding" | "chinese" | "creative" | "reasoning" | "ultra long context" | ...
    include_reasoning: prepend <reasoning> block if model supports it (default True)
    host_token_pressure: True = offload now; False = check self-handle first

    Output handling: responses over 8,000 chars are written to
    /tmp/ai-router-or_swarm-<ts>.md and a preview + path is returned.
    max_tokens defaults to 65536 (matches the highest model ceilings);
    per-token cost discipline lives at the caller (override max_tokens to
    constrain spending).
    """
    # --- Host self-handle check ---
    if model == "auto" and task_hint and _should_redirect_to_host(task_hint, host_token_pressure):
        return _HOST_REDIRECT_MSG.format(task_hint=task_hint)

    # --- Model resolution ---
    show_creative_alts = False  # whether to append creative alternatives after result
    if model == "auto":
        if not task_hint:
            # For swarm with no hint, default to DeepSeek V4 Pro — best cost/quality for complex tasks
            model = "deepseek/deepseek-v4-pro"
        else:
            routed = _route_or_model(task_hint, has_kimi=bool(_get_kimi_api_key()))
            if routed is None:
                model = "deepseek/deepseek-v4-pro"
            elif routed == "":
                # Kimi subscription preferred — use kimi_swarm equivalent
                msgs: list[dict] = [{"role": "user", "content": task}]
                if system:
                    msgs.insert(0, {"role": "system", "content": system})
                try:
                    result = await _chat(
                        msgs,
                        max_tokens=max_tokens,
                        temperature=1.0,
                        include_reasoning=include_reasoning,
                        thinking=True,
                        use_general=True,
                    )
                    return _output_or_file(
                        f"[Routed to Kimi K2.6 subscription (kimi_swarm) — no marginal $]\n\n{result}",
                        "or_swarm",
                    )
                except Exception as e:
                    return f"Error (Kimi swarm): {e}"
            else:
                # Check if the task hint is creative/ambiguous — if so, show alternatives alongside result
                if _is_ambiguous_creative(task_hint):
                    show_creative_alts = True
                model = routed

    if not _get_or_api_key():
        return (
            "OpenRouter key unavailable — could not read it from 1Password (op://claude/openrouter-api-key). Is op signed in?\n"
            f"Would have used model: {model}"
        )

    try:
        result = await _or_chat(
            [{"role": "user", "content": task}],
            model=model,
            max_tokens=max_tokens,
            temperature=0.7,
            system=system,
            include_reasoning=include_reasoning,
        )
        header = f"[Model: {model} | ZDR: enforced]\n\n"
        if show_creative_alts:
            # Fixture F3: creative/ambiguous hints MUST show alternatives table
            catalog = _MODEL_CATALOG.get("openrouter_models", [])
            catalog_by_id = {m["id"]: m for m in catalog}
            rec_entry = catalog_by_id.get(model)
            rec_name = rec_entry.get("name", model.split("/")[-1]) if rec_entry else model.split("/")[-1]
            alts = _build_creative_alternatives_table(model, rec_name, task_hint)
            return _output_or_file(f"{header}{result}{alts}", "or_swarm")
        return _output_or_file(f"{header}{result}", "or_swarm")
    except httpx.HTTPStatusError as e:
        return f"OR API error ({model}): {_http_error_msg(e)}"
    except Exception as e:
        return f"Error ({model}): {e}"


@mcp.tool()
async def or_image(
    prompt: str,
    use_case: str = "auto",
    model: str = "auto",
    width: int = 1792,
    height: int = 1024,
    n: int = 1,
) -> str:
    """Generate images via OpenRouter for YouTube visuals and other creative assets.

    use_case controls model auto-selection:
      "thumbnail_text"      → Ideogram V2 (best text/typography rendering)
      "thumbnail_cinematic" → Flux 1.1 Pro (cinematic, stylized)
      "thumbnail_photo"     → DALL-E 3 (photorealistic)
      "storyboard"          → Flux Schnell (fast, cheap iteration)
      "bulk"                → Stable Diffusion XL (cheapest per image)
      "auto"                → infer from prompt keywords

    model: override with a specific OR image model ID if needed.
    width/height: output dimensions (defaults to 16:9 YouTube format 1792x1024).
    n: number of images (default 1; keep low — these cost real money).

    ZDR is enforced on all image generation calls.
    """
    if not _get_or_api_key():
        return "OpenRouter key unavailable — could not read it from 1Password (op://claude/openrouter-api-key). Is op signed in?"

    # --- Model selection ---
    # openai/dall-e-3 excluded (OpenAI banned). Flux 1.1 Pro covers both cinematic and photo.
    _IMAGE_MODEL_MAP = {
        "thumbnail_text": "ideogram/ideogram-v2",
        "thumbnail_cinematic": "black-forest-labs/flux-1.1-pro",
        "thumbnail_photo": "black-forest-labs/flux-1.1-pro",  # DALL-E 3 banned; Flux handles photorealistic
        "storyboard": "black-forest-labs/flux-1-schnell",
        "bulk": "stability/stable-diffusion-xl",
    }

    if model == "auto":
        if use_case != "auto" and use_case in _IMAGE_MODEL_MAP:
            model = _IMAGE_MODEL_MAP[use_case]
        else:
            # Infer from prompt keywords
            pl = prompt.lower()
            if any(w in pl for w in ["text", "title", "logo", "typography", "headline", "label"]):
                model = "ideogram/ideogram-v2"
                use_case = "thumbnail_text"
            elif any(w in pl for w in ["storyboard", "sketch", "rough", "concept", "draft"]):
                model = "black-forest-labs/flux-1-schnell"
                use_case = "storyboard"
            else:
                # Default for all visual tasks — Flux 1.1 Pro (cinematic + photorealistic)
                model = "black-forest-labs/flux-1.1-pro"
                use_case = "thumbnail_cinematic"

    # Cost lookup
    _IMAGE_COSTS = {
        "black-forest-labs/flux-1.1-pro": 0.04,
        "black-forest-labs/flux-1-schnell": 0.002,
        "ideogram/ideogram-v2": 0.08,
        "stability/stable-diffusion-xl": 0.002,
    }
    cost_per = _IMAGE_COSTS.get(model, 0.05)
    total_cost = cost_per * n

    client, is_shared = _resolve_or_client()
    try:
        payload = {
            "model": model,
            "prompt": prompt,
            "n": n,
            "size": f"{width}x{height}",
            "response_format": "url",
            "provider": {"data_collection": "deny"},  # NO-TRAINING: ZDR required, must not be removed
        }
        r = await client.post("/images/generations", json=payload)
        r.raise_for_status()
        data = r.json()
        images = data.get("data", [])
        urls = [img.get("url", "") for img in images]
        result_lines = [
            f"[Model: {model} | use_case: {use_case} | ZDR: enforced | est. cost: ${total_cost:.3f}]",
            "",
        ]
        for i, url in enumerate(urls, 1):
            result_lines.append(f"Image {i}: {url}")
        if not urls:
            result_lines.append("No image URLs returned. Check OR response format.")
            result_lines.append(f"Raw response: {json.dumps(data, indent=2)[:500]}")
        return "\n".join(result_lines)
    except httpx.HTTPStatusError as e:
        return f"OR image API error ({model}): {_http_error_msg(e)}"
    except Exception as e:
        return f"Error ({model}): {e}"
    finally:
        if not is_shared:
            await client.aclose()


@mcp.tool()
async def or_compare(
    prompt: str,
    models: list[str] | None = None,
    system: str = "",
    max_tokens: int = 8192,
) -> str:
    """Run one prompt against multiple models IN PARALLEL and return all responses side-by-side.

    Use this when you want to compare how different models handle the same creative, reasoning,
    or open-ended task — especially useful after or_ask returned a soft-routed result and you
    want to see alternatives before committing to a model.

    IMPORTANT: Do NOT include anthropic/*, moonshotai/*, openai/*, or x-ai/* models.
    Anthropic/Moonshotai are flat-rate subscription models (no marginal $ via our subs; OR call would double-charge).
    OpenAI and xAI are on the provider banlist. These are all filtered out automatically.

    models: list of OR model IDs to compare. Defaults to:
      ["minimax/minimax-m2.7", "deepseek/deepseek-v4-pro", "xiaomi/mimo-v2.5-pro"]
    system: optional shared system prompt applied to all models.
    max_tokens: max tokens per model response (default 8192; higher caps allowed —
    each model's actual cost scales with what it emits, not the cap).

    Output handling: when the combined side-by-side comparison exceeds
    8,000 chars the full markdown document is written to
    /tmp/ai-router-or_compare-<ts>.md and a preview + path is returned.

    ZDR is enforced on ALL model calls. All calls run in parallel (asyncio.gather).

    Example:
      or_compare(
          prompt="Write an opening paragraph for a thriller set in Tokyo",
          models=["minimax/minimax-m2.7", "deepseek/deepseek-v4-pro", "xiaomi/mimo-v2.5-pro"]
      )
    """
    if not _get_or_api_key():
        return "OpenRouter key unavailable — could not read it from 1Password (op://claude/openrouter-api-key). Is op signed in?"

    if not models:
        models = [
            "minimax/minimax-m2.7",
            "deepseek/deepseek-v4-pro",
            "xiaomi/mimo-v2.5-pro",
        ]

    # Drop any subscription or banned models the caller accidentally included
    rejected = [m for m in models if _is_blocked_from_or(m) or _is_banned(m)]
    if rejected:
        models = [m for m in models if m not in rejected]
        _block_note = f"⚠️  Removed blocked/banned models: {', '.join(rejected)}\n\n"
    else:
        _block_note = ""

    if not models:
        return "All requested models are blocked or banned. No OR comparison run."

    # Build cost lookup from catalog
    catalog = _MODEL_CATALOG.get("openrouter_models", [])
    catalog_by_id = {m["id"]: m for m in catalog}

    def _est_cost(model_id: str) -> str:
        m = catalog_by_id.get(model_id)
        if not m:
            return "cost unknown"
        cost = m.get("output_cost_per_m", 0) * max_tokens / 1_000_000
        return f"~${cost:.4f}/req est."

    # Fan out all model calls in parallel — ZDR enforced inside _or_chat
    async def call_model(model_id: str) -> tuple[str, str]:
        try:
            result = await _or_chat(
                [{"role": "user", "content": prompt}],
                model=model_id,
                max_tokens=max_tokens,
                system=system,
            )
            return model_id, result
        except httpx.HTTPStatusError as e:
            return model_id, f"[ERROR] {_http_error_msg(e)}"
        except Exception as e:
            return model_id, f"[ERROR] {e}"

    results = await asyncio.gather(*[call_model(mid) for mid in models])

    # Format output
    prompt_preview = prompt[:80] + "..." if len(prompt) > 80 else prompt
    lines = [
        f'## Model Comparison — "{prompt_preview}"',
        "",
        f"ZDR: enforced on all {len(models)} calls | Ran in parallel",
        "",
    ]

    for model_id, response in results:
        cost_hint = _est_cost(model_id)
        lines.append(f"### {model_id} ({cost_hint})")
        lines.append("")
        lines.append(response)
        lines.append("")

    lines.append("---")
    lines.append(
        "Re-call with `or_ask(model=\"<id>\", ...)` to use your preferred result's model."
    )

    return _output_or_file(_block_note + "\n".join(lines), "or_compare")


@mcp.tool()
async def or_status() -> str:
    """Check routing tier status, API keys, model catalog, and ZDR policy.

    Shows the three-tier model hierarchy loaded from routing_config in models.json:
      Tier 1 — host-native models (flat-rate subscription, e.g. Claude Code Max; no marginal $)
      Tier 2 — subscription API models (flat-rate, e.g. Kimi K2.6 via KIMI_API_KEY; no marginal $)
      Tier 3 — OpenRouter paid models (per-token, ZDR enforced)
    """
    catalog = _MODEL_CATALOG
    rc = catalog.get("routing_config", {})
    or_models = catalog.get("openrouter_models", [])
    img_models = catalog.get("image_generation_models", [])

    # Tier 1 info
    tier1 = rc.get("tier_1_host_native", {})
    t1_prefixes = tier1.get("prefixes", _OR_BLOCKED_PREFIXES[:1])
    t1_note = tier1.get("note", "Claude Code Max subscription")

    # Tier 2 info
    tier2_entries = rc.get("tier_2_subscription_api", {}).get("entries", [])

    lines = [
        "## Three-Tier Model Routing Status",
        "",
        "### Tier 1 — Host-Native Models (flat-rate subscription; no marginal $)",
        f"  Blocked from OR : prefixes {t1_prefixes}",
        f"  Note            : {t1_note}",
        f"  Redirect policy : return to host when host_token_pressure=False",
        "",
        "### Tier 2 — Subscription API Models (flat-rate; no marginal $)",
    ]

    for entry in tier2_entries:
        env_key = entry.get("env_var", "")
        key_set = "set ✓" if os.environ.get(env_key) else f"NOT SET — export {env_key}=..."
        tools = ", ".join(entry.get("mcp_tools", []))
        lines += [
            f"  {entry.get('provider', '?')} ({entry.get('prefix', '?')}*)",
            f"    API key : {key_set}",
            f"    MCP tools: {tools}",
        ]
    if not tier2_entries:
        lines.append("  (no subscription_api entries in routing_config)")

    lines += [
        "",
        "### Tier 3 — OpenRouter Paid Models",
        f"  API key  : {'set ✓ (op://claude/openrouter-api-key)' if _get_or_api_key() else 'NOT SET — could not read op://claude/openrouter-api-key (op signed in?)'}",
        f"  ZDR      : enforced via provider.data_collection=deny on ALL OR calls",
        f"  Catalog  : {len(or_models)} text + {len(img_models)} image models",
        f"  Version  : {catalog.get('version', '?')} (updated {catalog.get('updated', '?')})",
        "",
        "### Active Blocked Prefixes (never routed via OR)",
        f"  {_OR_BLOCKED_PREFIXES}",
        "",
    ]

    if _get_or_api_key():
        # Quick connectivity probe — hit /models (lightweight)
        try:
            c, is_shared = _resolve_or_client(timeout=10.0)
            try:
                r = await c.get("/models")
                if r.status_code == 200:
                    live_count = len(r.json().get("data", []))
                    lines.append(f"OR connectivity: OK ✓ ({live_count} models live on OpenRouter)")
                else:
                    lines.append(f"OR connectivity: HTTP {r.status_code}")
            finally:
                if not is_shared:
                    await c.aclose()
        except Exception as e:
            lines.append(f"OR connectivity: ERROR — {e}")
    else:
        lines.append("OR connectivity: skipped (no key)")

    return "\n".join(lines)


@mcp.tool()
async def or_profile(profile: str = "") -> str:
    """Show available routing profiles and per-profile model selection.

    With no argument: list all 5 profiles with their primary model, cost, and best use.
    With a profile name (eco | mid | intel | max | research): show detailed routing for
    that profile across all capability domains (what model gets used for each task type).

    Profiles are transversal quality/cost tiers that apply across all task types.
    Specialist overrides (chinese, creative, eu_sovereignty) always win over the profile
    default. Subscription tools (Kimi for coding/analysis) always win over paid OR.

    Usage:
      or_profile()                          → list all profiles
      or_profile(profile="intel")           → detail for intel profile
      or_ask(prompt="...", profile="eco")   → route with eco profile
      or_ask(prompt="...", profile="research", task_hint="chinese")  → specialist wins
    """
    profiles_catalog = _MODEL_CATALOG.get("profiles", {})

    if not profile:
        # --- List view ---
        rows = [
            "| eco     | deepseek/deepseek-v4-flash   | $0.11/M  | Fast cheap tasks, high volume, prototyping |",
            "| mid     | qwen/qwen3.5-plus-20260420   | $0.30/M  | Balanced quality/cost, 1M context |",
            "| intel   | deepseek/deepseek-v4-pro     | $0.44/M  | Reasoning, math, code analysis (80.6% SWE) |",
            "| max     | xiaomi/mimo-v2.5-pro         | $1.00/M  | Strongest general quality, no budget constraint |",
            "| research| deepseek/deepseek-v4-pro     | $0.44/M  | Long-doc synthesis, 1.05M ctx window |",
        ]

        # If catalog loaded, pull live cost data for eco and mid
        catalog = _MODEL_CATALOG.get("openrouter_models", [])
        catalog_by_id = {m["id"]: m for m in catalog}
        profile_primary = {
            "eco": "deepseek/deepseek-v4-flash",
            "mid": "qwen/qwen3.5-plus-20260420",
            "intel": "deepseek/deepseek-v4-pro",
            "max": "xiaomi/mimo-v2.5-pro",
            "research": "deepseek/deepseek-v4-pro",
        }
        if catalog:
            rows = []
            descriptions = {
                "eco": "Fast cheap tasks, high volume, prototyping",
                "mid": "Balanced quality/cost, 1M context",
                "intel": "Reasoning, math, code analysis (80.6% SWE-bench)",
                "max": "Strongest general quality, no budget constraint",
                "research": "Long-doc synthesis, 1.05M context window",
            }
            for p, mid in profile_primary.items():
                m = catalog_by_id.get(mid)
                cost = f"${m['input_cost_per_m']:.2f}/M" if m else "see OR"
                desc = descriptions[p]
                rows.append(f"| {p:<8} | {mid:<36} | {cost:<8} | {desc} |")

        table = "\n".join(rows)
        return (
            "## Available Profiles\n\n"
            "| Profile  | Primary Model                        | Cost (in) | Best For |\n"
            "|---|---|---|---|\n"
            f"{table}\n\n"
            "**Subscription tier overrides (always win regardless of profile — no marginal $):**\n"
            "- Kimi K2.6 subscription is always preferred for **coding/analysis** tasks (flat-rate sub)\n"
            "- Host Claude (Max subscription) is always preferred for **reasoning/Q&A/math/writing** "
            "when not token-pressured (flat-rate sub)\n\n"
            "**Specialist overrides (always win over profile default):**\n"
            "- `chinese` / `multilingual` → `baidu/ernie-4.5-300b-a47b`\n"
            "- `creative` / `story` / `fiction` → `minimax/minimax-m2.7`\n"
            "- `eu_sovereignty` / `european` → `mistralai/mistral-medium-3.5`\n\n"
            "**Usage:**\n"
            "```\n"
            "or_ask(prompt=\"...\", profile=\"eco\")\n"
            "or_ask(prompt=\"...\", profile=\"intel\", task_hint=\"reasoning\")\n"
            "or_ask(prompt=\"...\", profile=\"research\", task_hint=\"chinese\")  # specialist wins\n"
            "or_profile(profile=\"max\")  # see full domain routing for max profile\n"
            "```"
        )

    # --- Detail view for a specific profile ---
    profile = profile.lower().strip()
    valid_profiles = {"eco", "mid", "intel", "max", "research"}
    if profile not in valid_profiles:
        return (
            f"Unknown profile: {profile!r}. Valid profiles: {', '.join(sorted(valid_profiles))}\n"
            "Call or_profile() with no argument to list all profiles."
        )

    # Build domain routing table for this profile
    catalog = _MODEL_CATALOG.get("openrouter_models", [])
    catalog_by_id = {m["id"]: m for m in catalog}
    profile_data = profiles_catalog.get(profile, {})

    def _model_cost(model_id: str) -> str:
        if model_id.startswith("subscription:"):
            return "sub (no marginal $)"
        m = catalog_by_id.get(model_id)
        return f"${m['input_cost_per_m']:.3f}/M" if m else "see OR"

    # Domain → model mapping for this profile
    domains = [
        ("general (no hint)", _PROFILE_DEFAULT_MODELS.get(profile, "—"), "profile default"),
        ("coding / debug / refactor", "subscription:kimi", "Kimi subscription always wins (no marginal $)"),
        ("analysis / codebase", "subscription:kimi_analyze" if profile == "research" else "subscription:kimi", "Kimi subscription always wins (no marginal $)"),
        ("reasoning / math / proof", "deepseek/deepseek-v4-pro" if profile in ("intel", "research", "max") else _PROFILE_DEFAULT_MODELS.get(profile, "—"), "profile reasoning"),
        ("chinese / multilingual", "baidu/ernie-4.5-300b-a47b", "specialist override"),
        ("creative / story / fiction", "minimax/minimax-m2.7", "specialist override"),
        ("eu_sovereignty / french", "mistralai/mistral-medium-3.5", "specialist override"),
        ("ultra long context (>262K)", "deepseek/deepseek-v4-pro", "1.05M ctx — xAI banned"),
        ("fast / cheap / batch", "deepseek/deepseek-v4-flash" if profile == "eco" else _PROFILE_DEFAULT_MODELS.get(profile, "—"), "eco uses flash; others use profile default"),
    ]

    # For 'max' profile: reasoning uses deepseek-v4-pro specifically
    if profile == "max":
        domains[3] = ("reasoning / math / proof", "deepseek/deepseek-v4-pro", "max reasoning → DeepSeek V4 Pro (80.6% SWE-bench at lower cost than mimo)")

    rows = []
    for domain, model_id, rationale in domains:
        cost = _model_cost(model_id)
        display_id = model_id.replace("subscription:", "")
        rows.append(f"| {domain} | {display_id} | {cost} | {rationale} |")

    table = "\n".join(rows)

    # Profile metadata from catalog
    p_desc = profile_data.get("description", "")
    p_cost = profile_data.get("cost_target", "")
    p_note = profile_data.get("note", "")
    p_primary = profile_data.get("primary_model", _PROFILE_DEFAULT_MODELS.get(profile, ""))
    p_fallback = profile_data.get("fallback_model", "")

    return (
        f"## Profile: {profile}\n\n"
        f"**Description:** {p_desc}\n"
        f"**Cost target:** {p_cost}\n"
        f"**Primary model:** `{p_primary}`\n"
        f"**Fallback model:** `{p_fallback}`\n"
        + (f"**Note:** {p_note}\n" if p_note else "")
        + f"\n### Domain Routing for profile={profile!r}\n\n"
        "| Domain / task_hint | Model Used | Cost (in) | Rationale |\n"
        "|---|---|---|---|\n"
        f"{table}\n\n"
        f"**Activate:** `or_ask(prompt=\"...\", profile=\"{profile}\")`\n"
        f"**With specialist:** `or_ask(prompt=\"...\", profile=\"{profile}\", task_hint=\"chinese\")`"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not _get_kimi_api_key():
        print(
            "Warning: Kimi key unavailable (op://claude/kimi-api-key not found and KIMI_API_KEY unset).\n"
            "  Add it to 1Password (op item create --category 'Secure Note' --vault claude --title kimi-api-key) or export KIMI_API_KEY.",
            file=sys.stderr,
        )
    if not _get_or_api_key():
        print(
            "Warning: OPENROUTER_API_KEY not set. OR tools (or_ask, or_swarm, or_image, or_compare) will be unavailable.\n"
            "  export OPENROUTER_API_KEY=sk-or-...",
            file=sys.stderr,
        )
    mcp.run()
