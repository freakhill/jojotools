# Installing jojotools

## 1. Add the marketplace + plugins

```
/plugin marketplace add freakhill/jojotools
/plugin install ai-router@jojotools
/plugin install jojo-skills@jojotools
```

Restart your Claude Code session — plugin frontmatter (skills, MCP servers, agent tool
allowlists) binds at session start, not mid-session.

## 2. Configure ai-router keys

`ai-router` needs at least one provider key. It reads them just-in-time from 1Password, or
from environment variables. See [docs/SETUP.md](docs/SETUP.md) for the full matrix. Quick start:

- **1Password users:** put your keys in items `kimi-api-key`, `glm-api-key`,
  `openrouter-api-key` in a vault, and set `AI_ROUTER_OP_VAULT=<your-vault>` (default `claude`).
- **No 1Password:** export `KIMI_API_KEY` and/or `GLM_API_KEY` (OpenRouter is 1Password-only by
  design — see SETUP).

## 3. Verify

```
# in a Claude Code session, ask the ai-router status tools:
kimi_status   ·   glm_status   ·   or_status
```

A `set ✓` line means a key resolved. Skills appear under `/help` and activate by description.

## Requirements

- Claude Code with plugin/marketplace support.
- [`uv`](https://docs.astral.sh/uv/) for the Python MCP + skill scripts.
- macOS for the `claude-sandbox` jail (optional; the rest is cross-platform).
- 1Password `op` CLI if you use the default key source (optional).
