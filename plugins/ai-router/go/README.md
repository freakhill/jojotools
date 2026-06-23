# ai-router — Go port

A full rewrite of the Python `ai-router` MCP server in Go: **one static binary
per platform**, `models.json` embedded, all **15 tools** ported, routing logic
translated 1:1 and unit-tested. Runs over stdio via the official MCP Go SDK.

## Why Go

- Single self-contained binary (7–8 MB) — no `uv`/Python runtime on target machines.
- Trivial cross-compilation to 5 platforms from one host, all static (`CGO_ENABLED=0`).
- Goroutines replace asyncio for the parallel tools (`*_batch`, `or_compare`, `*_swarm`).
- Faster cold start (no interpreter + dependency resolution per launch).

## Tools (15/15)

| Group | Tools |
|---|---|
| Kimi (Tier 2) | `kimi_ask` `kimi_analyze` `kimi_batch` `kimi_research_compile` `kimi_sentiment_batch` `kimi_swarm` `kimi_status` |
| GLM (Tier 2)  | `glm_ask` `glm_status` |
| OpenRouter (Tier 3) | `or_ask` `or_swarm` `or_image` `or_compare` `or_status` `or_profile` |

## Layout

```
main.go        server bootstrap (stdio transport)
catalog.go     models.json embed + parse + routing-config application + ban/block
routing.go     pure routing logic (host-redirect, route table, profiles, GPT-5.5 gate)
keys.go        JIT secret fetch from 1Password via `op` (+ pure field-pickers)
http.go        OR/Kimi/GLM chat, image gen, probe, ZDR injection, parallel helper, overflow-to-file
dirread.go     codebase reader for kimi_analyze + analysis format helpers
tools.go       all 15 MCP tool registrations + handlers
*_test.go      routing/capability unit tests + httptest end-to-end (ZDR, ban/block, temp-pin)
```

## Build

```bash
make build    # native binary for this host → ./ai-router
make test     # unit + httptest suite
make all      # cross-compile all 5 targets → dist/bin/
make dist     # all + bundle the launcher → dist/
```

Cross-compile targets (static, no toolchain needed on the host):

```
darwin/arm64    macOS aarch64
linux/amd64     Linux x86_64
linux/arm64     Linux aarch64
windows/amd64   Windows x86_64
windows/arm64   Windows aarch64
```

## "The right one gets selected"

`make dist` produces a launcher + one binary per platform:

```
dist/ai-router                       # launcher: maps `uname -s`/`uname -m` → execs the match
dist/bin/ai-router-darwin-arm64
dist/bin/ai-router-linux-amd64
dist/bin/ai-router-linux-arm64
dist/bin/ai-router-windows-amd64.exe
dist/bin/ai-router-windows-arm64.exe
```

To switch the plugin from Python to Go, point `.mcp.json` at the launcher (see
`mcp.json.example`):

```json
{ "mcpServers": { "ai-router": { "command": "${CLAUDE_PLUGIN_ROOT}/go/dist/ai-router" } } }
```

The launcher covers macOS + Linux. Windows has no POSIX shell by default, so a
Windows install points `command` at the matching `.exe` directly. (Alternative
for wider distribution: install-time selection — copy the matching binary to a
stable `bin/ai-router(.exe)` once and always point at that path.)

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
