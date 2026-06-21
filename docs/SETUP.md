# Setup — credentials & configuration

`ai-router` never ships or stores a credential. It resolves each provider key at call time.

## Key resolution

| Provider | 1Password (default) | Env fallback |
|---|---|---|
| Kimi (`kimi_*`) | `op://<vault>/kimi-api-key` | `KIMI_API_KEY` |
| z.ai GLM (`glm_*`) | `op://<vault>/glm-api-key` | `GLM_API_KEY` |
| OpenRouter (`or_*`) | `op://<vault>/openrouter-api-key` | — (1Password only, by design) |

`<vault>` defaults to `claude`; override with **`AI_ROUTER_OP_VAULT`**. The server reads `op`
first, then the env fallback (where one exists), caches the key for the process lifetime, and
never logs it. OpenRouter is deliberately 1Password-only (no standing key export) — if you don't
use 1Password you can still use the Kimi/GLM tools via their env fallbacks.

`op` must be signed in (or 1Password CLI app-integration enabled). When it's signed out, the
affected tools report the key as unavailable — expected, not a bug.

## Quick start

**1Password:**
```bash
# store keys in a vault of your choice, then:
export AI_ROUTER_OP_VAULT=my-vault     # default is "claude"
op signin                              # or enable desktop app CLI integration
```

**Environment only (Kimi/GLM):**
```bash
export KIMI_API_KEY=...
export GLM_API_KEY=...
```

See `.env.example` at the repo root for the full list.

## Optional configuration

| Variable | Purpose | Default |
|---|---|---|
| `AI_ROUTER_OP_VAULT` | 1Password vault holding all keys | `claude` |
| `KIMI_API_KEY` / `GLM_API_KEY` | raw-key fallbacks | unset |
| `AI_ROUTER_FALLBACK_DIR` | where oversized tool outputs spill to disk | `/tmp` |
| `AGENT_MEM_REPO` | persistent-memory git repo for memory-aware skills | `~/.claude/agent-memory` |

## Skills that assume external setup

- **FLO / monkeypaw / wololo** can call `ai-router` tools — configure keys above first.
- Memory-aware skills expect a git repo at `$AGENT_MEM_REPO` (see `scripts/agent-mem.sh` and the
  `init-memory` skill to bootstrap one).
- **wololo** writes generated run-scripts to `$WOLOLO_OUTPUT_DIR` (default `./generated`) — point
  it wherever you keep personal run artifacts.

## ai-router maintenance

The yearly model-catalog refresh (`plugins/ai-router/update_models.py`) reads
`OPENROUTER_API_KEY` from the environment (standalone script, separate from the server's op flow):
```bash
OPENROUTER_API_KEY=sk-or-... uv run plugins/ai-router/update_models.py --check
```
