---
name: init-memory
description: Use when the user wants to set up persistent project memory — "set up memory", "init the memory architecture", "create a memory system", "set up AGENTS.md". Creates the layered, file-based memory architecture so a long-lived agent keeps durable knowledge across sessions without re-deriving it.
---

# Init Memory

Set up a layered, file-based memory so the project's hard-won knowledge survives across sessions — without bloating context or drifting stale.

## The layers
- **`AGENTS.md` — foundation (stable).** Project axioms: stack, invariants, hard constraints, the things that must not change. Written once at bootstrap, rarely edited, loaded every session.
- **`memory.md` — hub (evolving).** The index + current state: what's in progress, key decisions, and pointers into the domain files. The map.
- **`memory/<domain>.md` — domain files.** One per area (`auth`, `data-model`, `deploy`, …). The detail lives here; the hub points at it.
- **In-context — ephemeral.** This session's scratch; persisted only if it becomes a durable lesson.

## What to persist (and what not)
Persist **durable** things: decisions and their rationale, gotchas, FAILs, invariants, open threads. **Not** transcripts, secrets, or play-by-play — a future agent needs the conclusion, not the conversation. Prefer one dated fact to a paragraph.

## Discipline (write these rules into AGENTS.md)
- **Recall narrowly.** Load the foundation + the *relevant* domain file, not the whole corpus — loading everything dilutes attention and invites cross-domain hallucination.
- **Verify before trusting.** A memory is a point-in-time note. If a fact names a file/flag/function, confirm it still exists before acting on it; treat stale entries as suspect, not gospel.
- **Never overwrite the foundation from a session's findings** — foundation changes are deliberate, not incidental.

## Create
Write `AGENTS.md` (foundation) + `memory.md` (hub with a one-line index) + an empty `memory/` dir, and put the recall/persist rules above into `AGENTS.md` so every session follows them.
