---
name: init-repo
description: Use whenever the user wants to start a new project or repo from scratch — "create a new repo", "start a new project", "bootstrap a project", "spin up a new codebase". Creates a PRIVATE repo on your Forgejo/Gitea instance (via the tea CLI) cloned into ~/workspace, set up worktree-friendly, with a CLAUDE.md documenting the workflow and a specs/ folder for plans. Defaults to private + worktree even if not asked.
---

# Init Repo

Bootstrap a new project so it's ready for isolated, plan-driven agent work from the first commit. Default to **private**.

## Create
1. **Private repo on your Forgejo/Gitea**, via the `tea` CLI (logged into your instance once with `tea login add`), cloned into `~/workspace/<name>` — projects live in `~/workspace`, never loose in `$HOME`:
   ```
   tea repos create --name <name> --private --init     # add --login <login> if you have no default login
   # tea prints the new repo's URLs; clone the SSH one:
   git clone <ssh-url> ~/workspace/<name>               # or capture it: tea repos create … -o json | jq -r .ssh_url
   ```
   The instance comes from your `tea` login, so nothing host-specific is baked in. On GitHub instead, swap in `gh repo create <name> --private --clone`.
2. **Worktree-friendly layout.** Add `.worktrees/` to `.gitignore`, and note in the README/CLAUDE.md that feature work happens in `.worktrees/<branch>/`, not the main checkout (see **using-git-worktrees**).
3. **`CLAUDE.md`** documenting the workflow: the worktree convention, where specs live, the verify-before-done expectation, and project conventions. It's the first thing a fresh agent reads.
4. **`specs/` folder** for implementation plans, pointing at **writing-plans** as the format. Seed `specs/0001-*.md` if there's a first task.
5. *(optional)* a **bootstrap canary**: one trivially-failing test you then make pass, proving the test runner actually runs before any real code goes in.

## Don't
Over-scaffold — no Docker, topology maps, or tooling the project doesn't need yet. A new repo needs: private + worktree-ready + `CLAUDE.md` + `specs/`. Add the rest when a real need appears.

Initial commit, push, and it's ready for **writing-plans** → **executing-plans** / **subagent-driven-development**.
