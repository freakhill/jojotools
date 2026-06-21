---
name: using-git-worktrees
description: 'Use whenever you are about to start feature work, a refactor, an experiment, or any change that should be isolated from the current checkout — and the user has not already created a worktree for you. Sets up an isolated workspace under `.worktrees/<branch>/` so the main checkout stays clean and multiple branches can be worked on in parallel. Trigger even when the user does not say the word "worktree" — phrases like "let''s try X", "spin up a branch for Y", "experiment with Z" all count.'
version: 0.1.0
---

# Using Git Worktrees

Keep the main checkout clean by doing feature work in a sibling worktree under `.worktrees/<branch>/`. The main checkout stays usable for orienting / reading; the worktree is where you edit, run tests, and commit.

**Announce at start:** "Setting up an isolated worktree."

## Step 0 — Detect existing isolation (do this first)

Before creating anything, check whether you're *already* inside a worktree. Creating a worktree inside a worktree is a mess.

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
SUBMODULE=$(git rev-parse --show-superproject-working-tree 2>/dev/null)
```

- **`GIT_DIR != GIT_COMMON` and `SUBMODULE` is empty** → already in a linked worktree. Skip to Step 2.
- **`SUBMODULE` is non-empty** → you're in a submodule, not a worktree. Treat as a normal repo (Step 1).
- **`GIT_DIR == GIT_COMMON`** → normal checkout. Continue to Step 1.

Why the submodule check matters: `GIT_DIR != GIT_COMMON` is also true inside submodules, and the false positive will make you skip worktree creation when you shouldn't.

## Step 1 — Create the worktree

### Pick the branch name

If the user gave you a feature name, slugify it: `add-export-feature` → branch `add-export-feature`. Otherwise ask for one short noun-phrase. No date prefixes, no `feat/` prefix unless the repo already uses them.

### Pick the directory

Priority order — explicit user preference always wins:

1. **User instruction in this conversation or in CLAUDE.md** — use it.
2. **Existing `.worktrees/` at repo root** — use it.
3. **Existing `worktrees/` at repo root** (no dot) — use it.
4. **Default: `.worktrees/`** at repo root.

If both `.worktrees/` and `worktrees/` exist, `.worktrees/` wins.

### Verify the directory is ignored

Critical: if `.worktrees/` is not gitignored, every worktree's files will show up in `git status` and can be accidentally committed.

```bash
git check-ignore -q .worktrees 2>/dev/null
```

If it returns non-zero (not ignored), add it and commit before creating the worktree:

```bash
printf '\n# Local git worktrees\n.worktrees/\n' >> .gitignore
git add .gitignore && git commit -m "chore: ignore .worktrees/"
```

### Create it

```bash
git worktree add .worktrees/<branch-name> -b <branch-name>
cd .worktrees/<branch-name>
```

**If `git worktree add` fails with a permission/sandbox error:** report it, tell the user you're falling back to working in place on the current branch, and ask if that's OK.

## Step 2 — Project setup in the worktree

Worktrees share `.git` but not build artifacts or `node_modules`. Auto-detect and install:

```bash
[ -f package.json ]      && npm install
[ -f Cargo.toml ]        && cargo build
[ -f requirements.txt ]  && pip install -r requirements.txt
[ -f pyproject.toml ]    && (command -v uv >/dev/null && uv sync || poetry install)
[ -f go.mod ]            && go mod download
```

Run only what applies. Don't install if the worktree clearly inherits state (e.g., `node_modules` was symlinked or the project uses a workspace-shared cache).

## Step 3 — Verify a clean baseline

Before writing any new code, run the project's tests. If they fail *now*, you can't tell later whether you broke something or it was already broken.

```bash
# project-appropriate: npm test / cargo test / pytest / go test ./...
```

- **Pass** → report ready, proceed with the actual work.
- **Fail** → report the failures and ask whether to proceed or investigate first. Do not silently move on.

## When you're done

When the branch's work is merged or abandoned, clean up:

```bash
git worktree remove .worktrees/<branch-name>
git branch -d <branch-name>   # or -D if abandoning unmerged work
```

Don't `rm -rf` a worktree directory — that leaves dangling metadata in `.git/worktrees/`. Always use `git worktree remove`.

## Quick reference

| Situation | Action |
|---|---|
| Already in a linked worktree (Step 0 detects it) | Skip creation, go to Step 2 |
| In a submodule | Treat as normal repo |
| `.worktrees/` not gitignored | Add + commit before creating worktree |
| Permission/sandbox error on `git worktree add` | Fall back to in-place, ask user |
| Baseline tests fail | Report + ask, don't proceed silently |
| Cleanup | `git worktree remove`, never `rm -rf` |

## Common mistakes

- **Skipping Step 0** — ends up with nested worktrees, very confusing.
- **Skipping the submodule guard** — you'll skip worktree creation when you shouldn't.
- **Forgetting to gitignore `.worktrees/`** — worktree files leak into the parent's `git status`.
- **Working without a baseline test run** — can't distinguish your bugs from pre-existing ones.
- **`rm -rf`-ing a worktree** — leaves dangling `.git/worktrees/<name>` metadata. Use `git worktree remove`.
