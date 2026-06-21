---
name: executing-plans
description: 'Use when you have a written implementation plan (typically in `specs/<NNNN>-<name>.md`) and the user wants you to execute it inline in the current session — task by task, with TodoWrite tracking and checkpoints between tasks. Trigger on phrases like "execute this plan", "implement the plan", "let''s run through this spec", "go", "do it" when said in reference to a recently-written plan. If subagents are available and the tasks are mostly independent, prefer `jojo-skills:subagent-driven-development` instead — it gives higher quality with less context pollution.'
version: 0.1.0
---

# Executing Plans

Execute a written implementation plan inline: load it, sanity-check it, track tasks with TodoWrite, then work through each task following its steps exactly.

**Announce at start:** "Executing the plan."

**Heads up:** If you have subagents available and the plan's tasks are mostly independent, `jojo-skills:subagent-driven-development` produces noticeably better results — fresh context per task, automatic two-stage review. Use this skill when you specifically want same-session inline execution.

## Step 1 — Load and sanity-check

1. Read the plan file in full.
2. Skim critically with these checks:
   - **Placeholders.** Does any step say "TBD", "TODO", "implement later", or describe code without showing it? If yes, those tasks aren't ready to execute — ask the user to fix the plan first.
   - **Path consistency.** Do later tasks reference files / types / functions that earlier tasks actually create? Mismatches mean the plan has a bug.
   - **Scope.** Is anything obviously missing — e.g., the spec mentions a feature with no corresponding task?
3. If you find blocking issues, raise them with the user before starting. If the plan is solid, create a TodoWrite with one item per task and proceed.

Be willing to push back. A bad plan executed precisely still produces bad code.

## Step 2 — Execute task-by-task

For each task in the plan:

1. **Mark the TodoWrite item `in_progress`.**
2. **Follow each step exactly as written.** The plan was written so steps are bite-sized (2–5 min each) — don't batch them, don't reorder them. Steps usually go: write failing test → run it to confirm it fails → write minimal impl → run tests → commit.
3. **Run every verification the plan specifies.** If a step says "Expected: PASS" and you get FAIL, stop and investigate. Don't move on assuming it'll work itself out.
4. **Commit at the end of the task** (the plan should have a commit step). One commit per task keeps history readable and gives clean rollback points.
5. **Mark the TodoWrite item `completed`.**

Checkpoint between tasks — do not silently chain all of them. The user may want to inspect after each one. A short "Task N done — tests pass, committed as `<sha>`. Continuing." is enough.

## Step 3 — When to stop

Stop and ask the user when:

- A verification step keeps failing and you don't understand why (don't loop on the same failing command — diagnose).
- A step's instruction is ambiguous or assumes something that isn't true in this codebase.
- You discover the plan has a structural gap that affects more than one task.
- You'd be making a meaningful design decision the plan didn't specify.

Asking is cheap. Guessing on a bad assumption is expensive — you'll write code that has to be unwritten.

## Step 4 — When all tasks are done

Once every task is `completed`:

1. Run the project's full test suite once more (not just the per-task tests) to confirm nothing regressed.
2. Report back to the user with: where the plan lived, how many commits the work produced (`git log --oneline <base>..HEAD`), and the test status.
3. Ask whether to open a PR, merge to default, or leave the branch for review. Don't do that step automatically — pushing/merging is a "shared state" action that needs explicit consent.

## Hard rules

- **Never start implementation on the default branch (`main`/`master`) without explicit consent.** Plans assume you're on a feature branch / worktree — verify with `git branch --show-current` before the first commit.
- **Never skip verification steps.** If the plan says "run `pytest tests/foo.py`", run it. Don't assume "looks fine to me" replaces actually running tests.
- **Never silently modify the plan.** If you realize a step is wrong, stop and discuss — don't quietly do something different.
- **Never force through repeated failures.** Two failures of the same step = stop and diagnose. Three = ask the user.
