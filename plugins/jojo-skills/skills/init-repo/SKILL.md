---
name: init-repo
description: 'Use this skill whenever the user wants to "create a new repo", "start a new project", "init a new repository", "spin up a new project", "bootstrap a project", or otherwise begin a brand-new codebase from scratch. Creates a PRIVATE GitHub repo, clones it into ~/workspace, sets the clone up as a worktree-friendly root (with .worktrees/ ignored and explained), drops a CLAUDE.md that documents the worktree workflow, and seeds a specs/ folder pointing at the jojo-skills:writing-plans skill for future plans. Trigger even when the user does not explicitly say "private" or "worktree" — those are the defaults here.'
version: 0.1.0
---

# Init Repo

Bootstrap a new project the way we like it: **private GitHub repo, cloned into `~/workspace`, ready for worktree-based feature work, with a `specs/` folder primed for future plans.**

This skill captures the "new project" convention so you don't have to remember it every time. If anything below conflicts with what the user explicitly asks for in the moment, the user wins — these are defaults, not rules.

## Phase 1 — Confirm intent (one short message)

Before doing anything destructive on GitHub, ask the user in **one message**:

1. **Repo name?** (suggest one based on the project description if they gave one; otherwise ask)
2. **One-line description?** (used for the GitHub repo description and the seed plan)
3. **Visibility = private?** (default yes — only ask if there's any signal it might be public)
4. **GitHub owner?** (default to current `gh auth status` active account; only ask if the user mentioned an org)

Do not proceed until you have at least a name. Everything else has a sensible default.

## Phase 2 — Create the GitHub repo

Use `gh` — it handles auth, default branch, and the initial commit dance for you.

```bash
gh repo create <owner>/<name> \
  --private \
  --description "<one-line description>" \
  --clone \
  --add-readme
```

Notes:
- `--add-readme` ensures the repo has an initial commit on the default branch so `git worktree add` works immediately.
- `--clone` will clone into the **current** directory. Run this from `~/workspace` (or `cd ~/workspace` first) so the clone lands at `~/workspace/<name>/`.
- If `~/workspace` does not exist yet, create it: `mkdir -p ~/workspace`.
- If the user already has a local directory they want to push, switch to `gh repo create <name> --private --source=. --remote=origin --push` instead — but the default flow is the one above.

After cloning, `cd ~/workspace/<name>`.

## Phase 3 — Set up the worktree-friendly layout

This repo is meant to be worked on via **git worktrees**: the clone at `~/workspace/<name>/` is the "main" worktree, and feature branches get their own checkouts under `.worktrees/<branch>/`. When a worktree is actually needed, defer to the `jojo-skills:using-git-worktrees` skill — do not re-derive the workflow.

Steps:

1. **Add `.worktrees/` to `.gitignore`** (create the file if it doesn't exist). Critical: if `.worktrees/` is not ignored, worktree contents will pollute `git status` and can be accidentally committed.

   ```bash
   touch .gitignore
   grep -qxF '.worktrees/' .gitignore || printf '\n# Local git worktrees (see CLAUDE.md)\n.worktrees/\n' >> .gitignore
   ```

2. **Write `CLAUDE.md`** at the repo root. Use the template at `assets/CLAUDE.md.template` in this skill (read it with the Read tool, fill in `{{REPO_NAME}}` and `{{ONE_LINE_DESCRIPTION}}`, then Write to the new repo root). This file tells future Claude sessions in this repo how the worktree workflow works and where plans live.

3. **Create `specs/`** with a starter README. Use `assets/specs-README.md.template` in this skill. The `specs/` folder is where implementation plans go — written using the `jojo-skills:writing-plans` skill. Do **not** copy the writing-plans skill into the repo; just reference it.

4. **Seed one starter plan** at `specs/0001-bootstrap.md` describing what the user just told you they want to build. Keep it brief — a stub the user can flesh out, not a full plan. Mention that subsequent plans should be authored via `jojo-skills:writing-plans`.

## Phase 4 — First commit and push

```bash
git add CLAUDE.md .gitignore specs/
git commit -m "chore: bootstrap repo layout (worktrees + specs/)"
git push
```

Use a single bootstrap commit — no need to split. The `--add-readme` step already created the initial commit, so this is the second commit on the default branch.

## Phase 5 — Report back

Tell the user, in two or three lines:
- Where the clone lives (`~/workspace/<name>/`)
- The GitHub URL (`gh repo view --web` URL, or just construct `https://github.com/<owner>/<name>`)
- That `specs/0001-bootstrap.md` is the seed plan and that future plans should use `jojo-skills:writing-plans`
- That feature work should happen in worktrees under `.worktrees/<branch>/` via `jojo-skills:using-git-worktrees`

Do not list every file you created. The user can see them.

## Quick reference

| Default | Value |
|---|---|
| Visibility | private |
| Clone location | `~/workspace/<name>/` |
| Worktrees location | `.worktrees/<branch>/` (gitignored) |
| Plans location | `specs/` |
| Plans authoring skill | `jojo-skills:writing-plans` |
| Worktree workflow skill | `jojo-skills:using-git-worktrees` |
| GitHub CLI | `gh` (already authenticated) |

## Common mistakes

- **Forgetting `.worktrees/` in `.gitignore`** — worktree contents end up tracked. Always verify with `git check-ignore .worktrees` before pushing.
- **Cloning outside `~/workspace`** — breaks the user's mental model of where projects live. Always `cd ~/workspace` first.
- **Creating a public repo by accident** — `gh repo create` defaults to interactive prompts that can land on public if you skip flags. Always pass `--private` explicitly.
- **Copy-pasting the worktree skill into CLAUDE.md** — the CLAUDE.md just *references* `jojo-skills:using-git-worktrees`; it does not duplicate it. Skills evolve; references stay correct.
- **Writing a full plan in `specs/0001-bootstrap.md`** — it is a stub. The user will flesh out real plans via `jojo-skills:writing-plans` when they actually need one.
