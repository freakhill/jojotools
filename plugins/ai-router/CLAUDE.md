# ai-router MCP

Personal multi-model AI router. Routes tasks to the right model across multiple access tiers, enforces no-training (ZDR) on every OpenRouter call, and exposes 21 MCP tools to Claude Code. (One documented exception to no-training: Sakana Fugu trains by default until you opt out — see its section below.)

> **Runtime: Go server** (`go/`, single static binary, `models.json` embedded — no `uv`/Python at runtime). Built **from source on first use**: `.mcp.json` runs `sh go/run.sh`, which compiles the binary into a content-hashed cache (`${XDG_CACHE_HOME:-~/.cache}/ai-router/<os>-<arch>-<srchash>/`) and execs it. The cache is keyed by a hash of the build inputs, so it's reused across plugin updates / reinstalls / restarts whenever the source is unchanged — only a real code change triggers one rebuild (primeable ahead of time via `sh go/run.sh </dev/null` from any checkout of the same revision). The Go toolchain must be present on the host. No binaries are committed. See `go/README.md`. The routing semantics, tiers, and tools below are unchanged from the original Python server; code-location references point into `go/*.go`. The only remaining Python is `update_models.py` (standalone yearly catalog-maintenance script).

---

## Architecture — Three Tiers

```
Tier 1 │ Host-native (flat-rate sub) │ anthropic/*   │ Claude Code Max subscription
       │ Redirect to host Claude     │               │ Opus 4.7 / Sonnet / Haiku
───────┼─────────────────────────────┼───────────────┼──────────────────────────────
Tier 2 │ Subscription API (flat-rate)│ moonshotai/*  │ Kimi key JIT from op (env fallback)
       │ Use kimi_* tools            │               │ kimi-k2.7 (default), kimi-k2.6, kimi-for-coding
       │                             │ zai/*         │ GLM key JIT from op (env fallback)
       │ Use glm_* tools             │               │ glm-5.1 (default), glm-4.6, …
───────┼─────────────────────────────┼───────────────┼──────────────────────────────
Tier 3 │ OpenRouter (per-token paid) │ everything    │ op://claude/openrouter-api-key
       │ or_* tools, ZDR enforced    │ else          │ $0.11–$1.00/M tokens (JIT from op)
```

**Banned (never used):** `openai/*`, `x-ai/*`

**Narrow exception allowlist (OFF by default) — GPT-5.5:** a 1-id allowlist `_GPT_AUDIT_MODEL_IDS` may pass the `openai/` ban *only* when the exception is enabled — by EITHER the env opt-in `AI_ROUTER_ALLOW_GPT55_AUDIT=1` OR a non-empty chat-acceptance gate file at `~/.config/ai-router/gpt55-accepted` (`go/routing.go` `gptAuditEnabled` / `gptAuditExceptionAllowed`; every other `openai/*` and all `x-ai/*` stay refused on every path). The gate file is written only after the typed-phrase + type-back self-abasement ceremony (FLO SKILL.md GPT-5.5 gate); it persists the exception with no env var or restart and is **revoked by deleting the file** (`rm ~/.config/ai-router/gpt55-accepted`). The one allowlisted id:
- `openai/gpt-5.5-pro` — GPT-5.5 Pro (deep-reasoning / "thinking" tier). Serves BOTH as the strong-gated FLO evaluator audit voice (the SKILL.md gate adds a typed-phrase confirmation + a type-back self-abasement re-confirm — retype a subagent-composed berating, no web search — on top of the env flag) AND as the general callable added 2026-06-14. The originally-specced `openai/gpt-5.5-thinking` does **not** exist on OpenRouter (verified S14b, 2026-06-14: "not a valid model ID"), so the calibrated `gpt-5.5-pro` fills the FLO-voice role.

ZDR still applies (`provider.data_collection=deny` on every call); S14b (2026-06-14) confirmed a zero-retention `openai/gpt-5.5(-pro)` endpoint IS reachable — contrary to the earlier "enterprise-gated / fails closed" assumption. Not catalogued in `models.json` and never auto-routed — reachable only by explicit `or_ask(model=…)`. The hole is exactly 1 id wide and shuts the moment the gate is removed.

**Terminology:** Tier 1 and Tier 2 are paid subscriptions (flat-rate, not free); they have no per-token marginal cost within plan caps. Tier 3 (OR) is per-token paid. Subscription tiers always win — the router redirects to Kimi or host Claude before spending OpenRouter tokens, because pushing tokens through a subscription has zero marginal cost while pushing through OR has direct per-token cost.

**Tier 3 key is fetched JIT from 1Password (2026-06-14):** the server no longer reads `OPENROUTER_API_KEY` from the environment. On first `or_*` use it reads the key from `op://claude/openrouter-api-key` (vault `claude`, item `openrouter-api-key`) via the `op` CLI, caches it for the process lifetime, and never logs the value (`go/keys.go:readORKeyFromOp` / `getORKey`). No standing export and no restart — but **`op` must be signed in** (or 1Password CLI app integration enabled), otherwise `or_*` report the key unavailable (expected when signed out, not a bug). The standalone `update_models.py` maintenance script still accepts the key via env (`OPENROUTER_API_KEY=sk-or-... uv run update_models.py …`).

---

## The 21 Tools

### Kimi Subscription — default K2.7 (flat-rate; use these first — no per-token marginal cost)

General tools (`kimi_ask`, `kimi_batch`, `kimi_swarm`, `kimi_research_compile`, `kimi_sentiment_batch`) default to **K2.7** (latest); `kimi_analyze` uses `kimi-for-coding` (rolling coding alias, currently K2.7). `kimi_ask` and `kimi_swarm` take a `model=` arg to pick `kimi-k2.7` / `kimi-k2.6` / `kimi-for-coding` on the same key (non-Kimi ids are refused). Global default override: `KIMI_GENERAL_MODEL` env. The coding endpoint only answers requests whose `User-Agent` identifies a coding agent (`KimiCLI/x`); the server sets this and it's overridable via `KIMI_USER_AGENT`.

| Tool | Use when |
|---|---|
| `kimi_ask` | Quick single-turn query; 256K context; Kimi's reasoning depth useful (`model=` selectable) |
| `kimi_analyze` | Whole codebase or large document (auto-reads directory); up to ~900KB |
| `kimi_swarm` | Complex long-horizon task (multi-file refactor, architecture design) |
| `kimi_batch` | N independent prompts in parallel — you orchestrate, Kimi executes |
| `kimi_research_compile` | Extract + synthesize across multiple text sources |
| `kimi_sentiment_batch` | Mass parallel sentiment scoring on text corpora |
| `kimi_status` | Check Kimi endpoint health + API key |

**kimi_swarm vs kimi_batch:**
- `kimi_swarm` → one complex task, Kimi decomposes internally (300 sub-agents, 4K steps)
- `kimi_batch` → you already decomposed N independent subtasks, parallelize them yourself

**Two Kimi access paths (deliberate division of labor):** these `kimi_*` MCP tools serve in-session queries and analysis; the standalone `kimi` CLI (`~/.local/bin/kimi`, one-shot via `kimi --print -p`) serves subagent/judge isolation — FLO evaluators invoke it out-of-process from a clean empty cwd so judges never see session context, repo state, or persistent memory (S13 probe, 2026-06-12: CLI judges read cwd files when their prompt is incomplete — the cwd must be empty, not merely neutral).

### z.ai GLM Coding Plan (flat-rate; alternative to Kimi for second opinions)

| Tool | Use when |
|---|---|
| `glm_ask` | Single-turn query to GLM (default `glm-5.1`). Override with `model="glm-4.6"` etc. |
| `glm_status` | Check connectivity + API key |

Available models on the endpoint: `glm-5.1` (default), `glm-5`, `glm-5-turbo`, `glm-4.7`, `glm-4.6`, `glm-4.5`, `glm-4.5-air`.

**When to use GLM instead of Kimi:** second-opinion runs, A/B comparisons, spreading load when Kimi quota is tight, or when you specifically want a GLM-family answer. Same Tier-2 cost profile (flat-rate sub, no marginal $) — pick based on quality fit per task.

### Sakana Fugu (direct, per-token paid — Fable-tier frontier; NOT ZDR by default)

| Tool | Use when |
|---|---|
| `sakana_ask` | Single-turn query to Sakana Fugu. `model=fugu` (fast default) or `model=fugu-ultra` (deep multi-step reasoning, 272K ctx). `effort=high\|xhigh` sets reasoning depth. |
| `sakana_status` | Check connectivity + API key **and the training/no-training opt-out state** |

Sakana Fugu is a multi-agent orchestration model (it dispatches to a pool of LLMs behind one OpenAI-compatible endpoint, `api.sakana.ai/v1`) that benchmarks against Fable 5 / GPT-5.5. Key at `op://claude/sakana-api-key` (env `SAKANA_API_KEY` fallback). Direct key → blocked from OR routing, never auto-routed; reach it only via `sakana_ask`.

> **⚠ NO-TRAINING CAVEAT — read before use.** Unlike OpenRouter (per-call `provider.data_collection=deny`), Sakana **trains on API prompts by default** and exposes **no per-call ZDR switch**. The no-training guarantee holds **only after you flip the training opt-out in the console** (`console.sakana.ai` → account/privacy); zero-retention is not confirmed available. The catalog marks it `no_training=false`; `sakana_status` prints a loud banner; `or_status` flags the key as "NOT ZDR by default". Treat Fugu as a non-ZDR route — don't send sensitive prompts until you've opted out. Billing is per-token (fugu $1.50/$6.00 per M, fugu-ultra $5.00/$30.00 per M), not flat-rate.

### Exa (web search / retrieval — per-token paid)

| Tool | Use when |
|---|---|
| `exa_search` | Web search. `type=auto\|fast\|instant\|deep-lite\|deep\|deep-reasoning`. Returns ranked results with highlights (or full `text=true`). Pass `output_schema` (a JSON-schema string) for grounded structured synthesis (`output.content` + field-level citations). |
| `exa_answer` | Grounded natural-language answer to a question, with source citations (Exa `/answer`). |
| `exa_contents` | Extract clean parsed content (highlights/text) for URLs you already have (Exa `/contents`). |
| `exa_status` | Check connectivity + API key |

Exa is a neural web-search/retrieval API (`api.exa.ai`, `x-api-key` auth — **not** chat-completions). Key at `op://claude/exa-ai-api-key` (env `EXA_API_KEY` fallback). It's a search tool, not a generative LLM, so it's not part of profile/model routing; the existing `deep-research` skill (and any agent loop) can call `exa_search`/`exa_answer` directly for grounded sources. Canonical reference: `docs.exa.ai/reference/search-api-guide-for-coding-agents`. Prefer `highlights` (token-efficient) by default; add `text=true` only when downstream reasoning needs full page context.

### OpenRouter (per-token paid — only when Kimi / host Claude can't do it)

| Tool | Use when |
|---|---|
| `or_ask` | Route a query to the best OR model by profile or task hint |
| `or_swarm` | Complex task on an OR model (defaults to DeepSeek V4 Pro) |
| `or_compare` | Same prompt → N models in parallel; see all responses side-by-side |
| `or_image` | Generate images (Kimi cannot generate images) |
| `or_profile` | Discover profiles and per-domain model routing |
| `or_status` | Check OR key, tier config, ZDR policy, model catalog version |

---

## Profiles — Quality/Cost Tiers

Profiles are transversal — they set the default model for any task type. Call `or_profile()` to see the live table.

| Profile | Primary Model | Cost | Best For |
|---|---|---|---|
| `eco` | deepseek/deepseek-v4-flash | $0.11/M | High volume, cheap tasks, prototyping |
| `mid` | qwen/qwen3.5-plus | $0.30/M | Balanced quality/cost, 1M context |
| `intel` | deepseek/deepseek-v4-pro | $0.44/M | Best reasoning — 80.6% SWE-bench, 95% HMMT math |
| `max` | xiaomi/mimo-v2.5-pro | $1.00/M | Strongest general quality (#1 OR usage volume) |
| `research` | deepseek/deepseek-v4-pro | $0.44/M | Long documents, synthesis — 1.05M context |

**Resolution precedence (highest first):**
1. **Subscription wins** — `coding`, `analysis`, `codebase` hints → Kimi (subscription, no marginal cost), beats any profile
2. **Specialist wins** — `creative`, `story`, `fiction`, `narrative` → MiniMax M2.7, beats profile
3. **max + reasoning** — `max` profile + `reasoning`/`math`/`proof` hint → DeepSeek V4 Pro
4. **Profile default** — falls to the profile's primary model

Setting a `profile` opts out of the host-redirect. `or_ask(profile="intel")` goes straight to OR.

---

## Specialist: Creative Writing

Only one specialist override remains: **MiniMax M2.7** for creative tasks.

| `task_hint` | Routes to | Why |
|---|---|---|
| `creative`, `story`, `fiction`, `narrative` | MiniMax M2.7 ($0.28/M) | Creative writing specialist, 78% SWE-bench |

For everything else, choose a **profile** or let the routing table handle it:

| `task_hint` | Routes to |
|---|---|
| `ultra long`, `very long document` | DeepSeek V4 Pro (1.05M ctx) |
| `fast`, `cheap`, `high volume` | DeepSeek V4 Flash ($0.11/M) |
| `reasoning`, `math`, `proof` | DeepSeek V4 Pro |
| `premium`, `frontier` | MiMo V2.5 Pro |
| `image`, `thumbnail`, `visual` | → redirect to `or_image` |

---

## Decision Flowchart

```
Coding / codebase analysis?
  └─ kimi_analyze or kimi_ask — subscription, no marginal cost

Long complex multi-step task?
  └─ kimi_swarm — subscription, no marginal cost

Creative writing?
  └─ or_ask(task_hint="creative")  →  MiniMax M2.7  ($0.28/M)

Need to compare how models handle something?
  └─ or_compare(prompt="...", models=["deepseek/deepseek-v4-pro", "minimax/minimax-m2.7"])

Image generation?
  └─ or_image(prompt="...", use_case="thumbnail_text|thumbnail_cinematic|storyboard")

Everything else — pick a profile:
  eco      → or_ask(profile="eco")       $0.11/M  fast + cheap
  mid      → or_ask(profile="mid")       $0.30/M  balanced
  intel    → or_ask(profile="intel")     $0.44/M  best reasoning
  max      → or_ask(profile="max")       $1.00/M  strongest general
  research → or_ask(profile="research")  $0.44/M  1.05M context
```

---

## Common Patterns

```python
# Profile — cheapest
or_ask(prompt="summarize this paragraph", profile="eco")

# Profile — best reasoning
or_ask(prompt="prove this theorem", profile="intel")

# Specialist: creative writing (overrides any profile)
or_ask(prompt="write an opening for a thriller", task_hint="creative")
or_ask(prompt="write a poem", profile="max", task_hint="story")  # MiniMax still wins

# Ultra-long context (1.05M)
or_ask(prompt="synthesize these 500 pages", profile="research")

# Host is full, force OR offload
or_ask(prompt="explain this architecture", task_hint="reasoning", host_token_pressure=True)

# Specific model
or_ask(prompt="...", model="deepseek/deepseek-v4-pro")

# Compare models side by side
or_compare(
    prompt="write an opening for a thriller set in Tokyo",
    models=["minimax/minimax-m2.7", "deepseek/deepseek-v4-pro", "xiaomi/mimo-v2.5-pro"]
)

# Images
or_image(prompt="bold title: AI REVOLUTION",      use_case="thumbnail_text")       # Ideogram V2
or_image(prompt="cinematic drone shot over Tokyo", use_case="thumbnail_cinematic")  # Flux 1.1 Pro
or_image(prompt="rough concept sketch",            use_case="storyboard")           # Flux Schnell $0.002

# Discover profiles
or_profile()                    # list all 5 profiles
or_profile(profile="intel")     # per-domain routing for intel
```

---

## OR Model Catalog

| Model | $/M in | Context | Strength |
|---|---|---|---|
| deepseek/deepseek-v4-pro | $0.44 | 1.05M | Best reasoning/coding — 80.6% SWE-bench |
| deepseek/deepseek-v4-flash | $0.11 | 1.05M | Fastest + cheapest |
| xiaomi/mimo-v2.5-pro | $1.00 | 1.05M | #1 OR usage, general quality |
| qwen/qwen3.5-plus | $0.30 | 1M | Balanced, multilingual-capable |
| minimax/minimax-m2.7 | $0.28 | 205K | Creative writing specialist |
| google/gemini-3.1-flash-lite | $0.25 | 1.05M | Cheap, multimodal |
| google/gemini-3.1-pro-preview | $2.00 | 1.05M | Frontier reasoning / LLM-as-judge (GPQA 94.3, HLE 44.4). Explicit-id only — not auto-routed; FLO gated audit voice (per-token, ZDR fails-closed) |

Image models: Flux 1.1 Pro ($0.04/img, cinematic), Ideogram V2 ($0.08/img, text overlays), Flux Schnell ($0.002/img, iteration), SDXL ($0.002/img, bulk).

All calls enforce ZDR (`provider.data_collection: deny`) — no training on sessions, ever.

---

## Output Handling — Filesystem Fallback for Large Results

Claude Code caps MCP tool results at the host's inline ceiling (~25K tokens by its own tokenizer). The router doesn't try to predict that ceiling from char count — different content types tokenize at wildly different densities and prior heuristics (4.0 then 3.5 chars/token) each let dense SQL/JSON/code outputs slip past. Instead, anything over a fixed **8,000-char cap** is written to disk and the response is a preview + file path.

**Per-tool default `max_tokens` (model output cap):**

| Tool | Default | Ceiling rationale | Overflow handling |
|---|---|---|---|
| `kimi_ask` | 65536 | K2.6 model ceiling — sub has no marginal $ | file fallback |
| `kimi_analyze` | 65536 | K2.6 ceiling — "detailed" mode often overflows | file fallback |
| `kimi_research_compile` | 65536 | Long-form synthesis often overflows | file fallback |
| `kimi_swarm` | 65536 | K2.6 ceiling — long-horizon by design | file fallback |
| `kimi_batch` | 8192 / item | per-item only; full array can still overflow | file fallback (JSON to file) |
| `kimi_sentiment_batch` | 512 / item | small structured outputs | file fallback (JSON to file) |
| `or_ask` | 32768 | mid-ground across OR catalog (per-token paid) | file fallback |
| `or_swarm` | 65536 | matches model ceilings; cost discipline via caller | file fallback |
| `or_compare` | 8192 / model | × N models; comparison docs can grow | file fallback |

**Fallback mechanics:**

When a tool's final output exceeds `_INLINE_MAX_CHARS = 8000`, the router writes the full text to `/tmp/ai-router-<tool>-<unix-ms>.md` and returns:

```
[Output too large to return inline; full result written to file]

File: /tmp/ai-router-kimi_swarm-1779537928611.md
Size: 99,000 chars

Read the file with the Read tool to consume the full output.

=== Preview (first 1500 chars) ===
...
```

The host then calls the `Read` tool on the file path to consume the full output. Status/probe tools (`kimi_status`, `or_status`, `or_profile`) and other short responses stay under the cap and return inline.

**Why 8,000 chars:** safe under any tokenizer. At the worst observed density (~1 char/token for CJK), that's still 8K host tokens — well under the 25K MCP cap. Eliminates the chars-per-token prediction game entirely.

**Why no pagination fallback:** this MCP server is stateless — paginating by `offset` would force every API call to be re-executed once per page. File-write is the only correct overflow mechanism in this architecture.

**Redirecting overflow files:** set `AI_ROUTER_FALLBACK_DIR` (default `/tmp`).

**Testing the fallback:** `cd go && go test -run TestOutputOrFile -v .` exercises the overflow-to-file path (`go/http.go:outputOrFile`).

---

## Yearly Maintenance

`update_models.py` is the only Python left — a self-contained PEP 723 uv script
(deps resolved on run). It refreshes `models.json`; the server itself is the Go
binary under `go/`, which **embeds** `models.json`. After any catalog change the
binary is **rebuilt automatically on the next MCP launch** (`run.sh` detects
`models.json` is newer than `go/.bin/ai-router` and rebuilds) — no manual step.

```bash
OPENROUTER_API_KEY=sk-or-... uv run update_models.py --check           # diff pricing
OPENROUTER_API_KEY=sk-or-... uv run update_models.py --check --update  # write changes
OPENROUTER_API_KEY=sk-or-... uv run update_models.py --check-zdr       # verify ZDR
OPENROUTER_API_KEY=sk-or-... uv run update_models.py --check-training  # audit no-training flags
# next ai-router launch picks up the new models.json automatically (rebuild-on-change)
```

**Add a new subscription** (e.g. future DeepSeek direct API):
Edit `routing_config.tier_2_subscription_api.entries` in `models.json` — rebuilt on next launch.

**Ban a provider:**
Edit `routing_config.banned_providers.prefixes` in `models.json` — rebuilt on next launch.

**Run tests:**
```bash
cd go && go test ./...
```

---

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| _(Kimi key)_ | Yes | Fetched JIT from `op://claude/kimi-api-key` (Secure Note) on first use and cached, mirroring the OR key — `op` must be signed in. **`KIMI_API_KEY` env is a deliberate fallback** (transition / standalone / CI): the server reads op first, then env. So an existing `KIMI_API_KEY` export keeps working, but the canonical source is op. |
| `KIMI_API_KEY` | No | Fallback for the Kimi key when op yields nothing (see above). |
| _(GLM key)_ | Yes | Fetched JIT from `op://claude/glm-api-key` (Secure Note) on first use and cached, mirroring the Kimi key — `op` must be signed in. **`GLM_API_KEY` env is a deliberate fallback** (op first, then env). |
| `GLM_API_KEY` | No | Fallback for the GLM key when op yields nothing (see above). |
| _(OpenRouter key)_ | Yes | Fetched JIT from `op://claude/openrouter-api-key` — **not** an env var for the server; `op` must be signed in. The standalone `update_models.py` script still reads `OPENROUTER_API_KEY` from env. |
| `GLM_BASE_URL` | No | Override z.ai endpoint (default `https://api.z.ai/api/coding/paas/v4`) |
| `GLM_MODEL` | No | Override default GLM model (default `glm-5.1`) |
