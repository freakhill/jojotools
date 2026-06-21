---
name: executing-plans
description: Use when you have a written implementation plan (typically specs/<NNNN>-<name>.md) and the user wants it executed inline in this session — task by task, with progress tracking and checkpoints. Trigger on "execute the plan", "run the spec", "go", "do it" about a recently-written plan. If tasks are independent and subagents are available, prefer subagent-driven-development.
---

# Executing Plans

Execute a plan one task at a time, verifying each before the next — so a failure halts you at one task instead of corrupting the whole run.

## Loop (one task at a time)
1. **Re-read the task from the plan file on disk** — not from memory. Over a long run your recollection drifts; the file is ground truth.
2. **Do exactly that task** — nothing extra, nothing borrowed from a later task.
3. **Run its `VERIFY` and compare real output to `EXPECTED`.** Verify *before* you mark anything — never after.
4. **Only on a real pass:** mark it done (TodoWrite + check the box) and **commit** (`git commit -m "<task>"`). One commit per verified task → a clean trail and single-task rollback.
5. Checkpoint, then the next task.

## The momentum gate
**On the first failed verification, stop.** Do not say "I'll fix it later" and move on — that's how you end with a broken repo and no idea which step broke it. Report the failure with its output; fix it, or amend the plan, before proceeding.

## Discipline
- **Never skip a task because the code "looks done."** A stub or an earlier partial can fool you — run the verification anyway.
- Don't silently widen scope mid-run; if the plan is wrong, surface it and amend the plan rather than improvising around it.
- Keep TodoWrite in lockstep with reality — exactly one task in progress.

If the tasks are mostly independent and subagents are available, **subagent-driven-development** runs them with less context pollution and a review gate — prefer it.
