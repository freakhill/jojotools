# ai-router — Go port

A full rewrite of the Python `ai-router` MCP server in Go: **one static binary
per platform**, `models.json` embedded, **21 tools**, routing logic
translated 1:1 and unit-tested. Runs over stdio via the official MCP Go SDK.

## Why Go

- Single self-contained binary (7–8 MB) — no `uv`/Python runtime on target machines.
- Trivial cross-compilation to 5 platforms from one host, all static (`CGO_ENABLED=0`).
- Goroutines replace asyncio for the parallel tools (`*_batch`, `or_compare`, `*_swarm`).
- Faster cold start (no interpreter + dependency resolution per launch).

## Tools (21)

| Group | Tools |
|---|---|
| Kimi (Tier 2) | `kimi_ask` `kimi_analyze` `kimi_batch` `kimi_research_compile` `kimi_sentiment_batch` `kimi_swarm` `kimi_status` |
| GLM (Tier 2)  | `glm_ask` `glm_status` |
| Sakana Fugu (direct, per-token; NOT ZDR by default) | `sakana_ask` `sakana_status` |
| Exa search (direct, per-token) | `exa_search` `exa_answer` `exa_contents` `exa_status` |
| OpenRouter (Tier 3) | `or_ask` `or_swarm` `or_image` `or_compare` `or_status` `or_profile` |

## Layout

```
main.go        server bootstrap (stdio transport)
catalog.go     models.json embed + parse + routing-config application + ban/block
routing.go     pure routing logic (host-redirect, route table, profiles, GPT-5.5 gate)
keys.go        JIT secret fetch from 1Password via `op` (+ pure field-pickers)
http.go        OR/Kimi/GLM/Sakana chat, Exa search POST, image gen, probe, ZDR injection, parallel helper, overflow-to-file
dirread.go     codebase reader for kimi_analyze + analysis format helpers
tools.go       all 21 MCP tool registrations + handlers
run.sh         build-on-first-use launcher (what .mcp.json invokes)
*_test.go      routing/capability unit tests + httptest end-to-end (ZDR, ban/block, temp-pin)
```

## How it runs: build-on-install

No binaries are committed. `.mcp.json` launches `run.sh`, which **builds the
server from source the first time a given source revision runs**, then execs it.

```json
{ "mcpServers": { "ai-router": { "command": "sh", "args": ["${CLAUDE_PLUGIN_ROOT}/go/run.sh"] } } }
```

(`${CLAUDE_PLUGIN_ROOT}` only expands in `args`, not `command` — so launch via
`sh` with the path in `args`. See `mcp.json.example`.)

### Stable, content-hashed build cache

The compiled binary is cached **outside** the plugin dir at:

```
${XDG_CACHE_HOME:-~/.cache}/ai-router/<os>-<arch>-<srchash>/ai-router
```

`<srchash>` is a hash of the build inputs (`*.go`, `go.mod`, `go.sum`,
`models.json` — *not* `run.sh`). Consequences:

- The build is **reused across plugin updates, reinstalls, and Claude Code
  restarts** — anytime the source is byte-identical, the key matches and launch
  is instant (~0.1 s). Only a genuine code change yields a new key (one rebuild).
- A build can be **primed ahead of an update**: run `sh go/run.sh </dev/null`
  from any checkout of the same revision (your workspace clone, say) — it builds
  into the shared cache, and the matching install then launches with no rebuild.
- Builds are written atomically (temp + rename), so a build killed mid-way (e.g.
  by an MCP startup timeout) never leaves a half-binary — the next launch rebuilds.
- Old builds for the platform are pruned, so the cache holds one ~11 MB binary.

**Requires the Go toolchain on the target.** MCP servers get a minimal PATH, so
`run.sh` searches the usual install locations for `go` (Homebrew, `/usr/local/go`,
`$HOME/go/bin`, `$GOROOT`, …) and prints an install hint to stderr if missing.

**First-launch latency (new code only):** the first connect to a *new* revision
builds (~2–3 s; longer if module deps must download). If your MCP client times
out on that first build, reconnect — the binary is cached by then — or prime it
ahead of time as above. All wrapper output goes to stderr, so it never corrupts
the MCP stdout stream.

### Manual / dev builds

```bash
make build    # native binary for this host → ./ai-router
make test     # unit + httptest suite
```

### Optional: prebuilt cross-platform binaries

If you'd rather hand someone a binary (no Go on their machine), `make dist`
cross-compiles all 5 targets + a `uname`-selecting launcher under `dist/`
(gitignored). Point `.mcp.json` at `dist/ai-router` instead of `run.sh`.

```
darwin/arm64  linux/amd64  linux/arm64  windows/amd64  windows/arm64   (static, CGO_ENABLED=0)
```

## Parity with the Python server

- **ZDR** (`provider.data_collection=deny`) injected on every OpenRouter call
  (chat + image) in `http.go`, not caller-overridable. Verified by `http_test.go`.
- **Ban/block**: `openai/`, `x-ai/` banned; `anthropic/`, `moonshotai/`, `zai/`
  blocked from OR. Loaded from `routing_config` in the embedded `models.json`.
- **GPT-5.5 audit gate**: env opt-in **or** gate file, off by default; exactly one
  allowlisted id (`openai/gpt-5.5-pro`).
- **Kimi**: temperature pinned to 1.0 (only value Kimi accepts); model resolver
  rejects non-Kimi ids; coding-agent UA gate preserved.
- **Secrets**: read from `op` once per process, cached, never logged; env-var
  fallbacks (`KIMI_API_KEY`/`GLM_API_KEY`) preserved. (OR has no env fallback,
  matching the Python JIT-only discipline.)
- **Overflow-to-file**: outputs over 8,000 chars written to
  `$AI_ROUTER_FALLBACK_DIR` (default `/tmp`) with a preview + path.
- **Env knobs**: `KIMI_USER_AGENT`, `KIMI_GENERAL_MODEL`, `GLM_BASE_URL`,
  `GLM_MODEL`, `GLM_USER_AGENT`, `AI_ROUTER_OP_VAULT`, `AI_ROUTER_FALLBACK_DIR`,
  `AI_ROUTER_ALLOW_GPT55_AUDIT`, `AI_ROUTER_GPT_GATE_FILE`.

## Not carried over (intentional)

- No host-redirect "warning" stderr lines on startup (the Python `__main__` block).
- The standalone `update_models.py` maintenance script stays Python — it's a
  yearly CLI, not part of the server.
