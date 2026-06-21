---
name: using-git-worktrees
description: Use before starting feature work, a refactor, an experiment, or any change that should be isolated from the current checkout — even when the user doesn't say "worktree" (phrases like "try X", "spin up a branch for Y"). Sets up an isolated workspace under .worktrees/<branch>/ so the main checkout stays clean and branches run in parallel.
---

# Using Git Worktrees

Isolate work so the main checkout stays clean and several branches can run at once — without re-cloning.

## When
Before any change that isn't a trivial one-liner: a feature, refactor, experiment, or anything you might throw away. "Try X", "experiment with Y", "spin up a branch for Z" all mean: make a worktree.

## Setup
Create the worktree under the repo, in the gitignored `.worktrees/` dir, on a named branch:
```
git worktree add .worktrees/<branch> -b <branch>
cd .worktrees/<branch>
```
`.worktrees/` is gitignored (init-repo seeds this). One worktree = one branch = one task. **Never do the work in the main checkout** — that's the thing you're protecting.

## While working
- Each worktree is a full checkout sharing the same `.git`; commits and branches are visible from all of them.
- Run parallel tasks in separate worktrees on separate branches — no stashing, no branch-switch churn in the main tree.
- If a branch needs different dependencies, install them inside its worktree.

## Cleanup
When done (merged or abandoned), remove it properly so git's registry stays consistent:
```
git worktree remove .worktrees/<branch>     # NOT rm -rf — that orphans the registry entry
git branch -d <branch>                        # -D if abandoning unmerged
```
`git worktree list` shows what's live; `git worktree prune` clears stale entries.

Don't: work in the main checkout, `rm -rf` a worktree directory, or leave a pile of stale worktrees behind.
