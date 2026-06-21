# jojotools

A Claude Code plugin marketplace bundling the agentic tooling I use day to day —
a multi-model MCP router and a set of orchestration skills. Bring your own API keys.

## What's inside

| Plugin | What it is |
|---|---|
| **ai-router** | An MCP server that routes work across Kimi (subscription), z.ai GLM (subscription), and OpenRouter (per-token), with no-training (ZDR) enforced on every paid call. 15 tools. |
| **jojo-skills** | Orchestration skills: **FLO** (feedback-loop optimization — worker/evaluator separation, anti-sycophancy, adversarial gates), **monkeypaw** (multi-phase build harness), **ayo** (mine lessons from external prior art), **wololo** (unattended sandboxed runs), **writing-plans** / **executing-plans** / **subagent-driven-development**, **init-repo** / **init-memory**, **using-git-worktrees**. |

Also ships `scripts/agent-mem.sh` (a portable persistent-memory orchestrator) and a macOS
`claude-sandbox` jail for unattended `--dangerously-skip-permissions` runs.

## Install (Claude Code)

```
/plugin marketplace add freakhill/jojotools
/plugin install ai-router@jojotools
/plugin install jojo-skills@jojotools
```

Restart the session so plugin definitions bind. Then configure keys — see
[INSTALL.md](INSTALL.md) and [docs/SETUP.md](docs/SETUP.md).

## Bring your own keys

`ai-router` reads API keys just-in-time from 1Password (the `op` CLI) by default, or from
environment variables. Nothing here ships any credential. See `docs/SETUP.md`.

## License

MIT — see [LICENSE](LICENSE).
