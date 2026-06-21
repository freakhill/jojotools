---
name: init-memory
description: 'Use this skill when the user wants to "set up memory", "initialize the memory architecture", "init memory", "create a memory system for this project", or "set up AGENTS.md with memory". Creates the 3-layer memory architecture: AGENTS.md (stable foundation), memory.md hub + memory/ domain files (evolving knowledge), and in-context (ephemeral).'
version: 0.1.0
---

# Init Memory

Bootstrap the 3-layer memory architecture for the current project:

| Layer | What | Persistence |
|---|---|---|
| **1 — In-context** | Conversation, tool outputs, active file | Ephemeral (session only) |
| **2 — Domain files** | `memory.md` hub + `memory/` domain files | Dynamic, evolves across sessions |
| **3 — Foundation** | `AGENTS.md` | Stable, rarely changes |

## Phase 1 — Discover

Scan the project to form an initial picture before talking to the user:
- Identify language/framework from root manifests (package.json, Cargo.toml, pyproject.toml, go.mod, build.gradle, etc.)
- List top-level directories
- Check for existing README, CLAUDE.md, AGENTS.md, memory.md — note what already exists

Then ask the user in **one message**:
1. What is this project? (one sentence purpose)
2. Any key architectural constraints or coding standards to lock in? (optional)
3. Any working preferences — things to always do or never do? (optional)
4. Any ongoing work or decisions worth capturing right now? (optional)

## Phase 2 — Write Layer 3: AGENTS.md

Create or update `AGENTS.md` in the project root. Structure:

```markdown
# [Project Name]

[One paragraph: what the project does, tech stack, key architectural facts.]

## Architecture

[Top-level directory tour, one line per directory.]

## Standards & Constraints

[Coding standards, hard constraints, things that must never happen.]

## Memory System

This project uses a 3-layer memory architecture. Use it as follows:

**At the start of each session:**
1. Read `memory.md` to get the index of domain files.
2. Load the domain files relevant to the current task.

**During work — keep memory current:**
- New architectural decision made → append to `memory/decisions.md`
- New code pattern or idiom discovered → append to `memory/code-patterns.md`
- User states a working preference → update `memory/user-preferences.md`
- Project focus or background shifts → update `memory/project-context.md`

**Self-healing:** If a domain file contains stale or wrong information, correct it immediately. Do not let memory drift from reality.

**Scope discipline:** AGENTS.md is stable — update it only for permanent architectural facts. Dynamic knowledge lives in `memory/`.
```

If `AGENTS.md` already exists, preserve its existing content and integrate the Memory System section rather than overwriting.

## Phase 3 — Write Layer 2: memory.md + domain files

### memory.md

Create `memory.md` in the project root as the index hub:

```markdown
# Memory Index

Layer 2 of the project memory system. Each file below holds dynamic knowledge that evolves across sessions. Load files relevant to the current task at session start.

| File | Contents |
|---|---|
| [memory/project-context.md](memory/project-context.md) | Current goals, background, active focus areas |
| [memory/decisions.md](memory/decisions.md) | Architectural and design decisions with rationale |
| [memory/code-patterns.md](memory/code-patterns.md) | Conventions, idioms, and patterns used in this codebase |
| [memory/user-preferences.md](memory/user-preferences.md) | Working preferences — what to always/never do |

Last updated: [date]
```

### memory/ domain files

Create `memory/` directory and populate each file with what you discovered in Phase 1 plus what the user told you. Leave sections empty (with a `_none yet_` placeholder) rather than inventing content.

**memory/project-context.md**
```markdown
# Project Context

## Purpose
[What the project does and why it exists.]

## Current Focus
[What is actively being worked on right now, if known.]

## Background
[Any important history or context that shapes current decisions.]
```

**memory/decisions.md**
```markdown
# Architectural Decisions

Append new decisions here as they are made. Format each as:

## [Decision title] — [date]
**Decision:** [what was decided]
**Why:** [rationale]
**Alternatives rejected:** [if any]

---
_none yet_
```

**memory/code-patterns.md**
```markdown
# Code Patterns

Patterns, conventions, and idioms used in this codebase. Update when a new pattern is established or discovered.

[Populate from codebase scan and user input, or leave placeholder:]
_none yet_
```

**memory/user-preferences.md**
```markdown
# User Preferences

Working preferences that apply across all sessions.

[Populate from user input, or leave placeholder:]
_none yet_
```

## Phase 4 — Confirm

Print a summary:

```
=== Memory Architecture Initialized ===

Layer 3 (foundation):  AGENTS.md         [created / updated]
Layer 2 (dynamic hub): memory.md          [created / updated]
Layer 2 (domain):      memory/project-context.md   [created]
                       memory/decisions.md          [created]
                       memory/code-patterns.md      [created]
                       memory/user-preferences.md   [created]
Layer 1 (in-context):  ephemeral — no file needed

At the start of each session, read memory.md and load relevant domain files.
Update domain files as you learn — keep memory current.
```

## Notes

- If any file already exists, merge rather than overwrite — preserve existing content.
- Do not invent architectural facts. When uncertain, use placeholders.
- The `memory/decisions.md` file is append-only by convention — never delete past decisions, mark them superseded instead.
- This skill is idempotent: running it again on an existing project only fills gaps and adds the Memory System section to AGENTS.md if missing.
- **Scope split with agent-memory:** if `~/.claude/agent-memory` exists, route personal/session knowledge (preferences, lessons, session arcs, gotchas) there per the global CLAUDE.md → agent-memory section; the in-repo memory this skill creates holds only project-intrinsic, shippable knowledge (architecture, decisions, code patterns).
