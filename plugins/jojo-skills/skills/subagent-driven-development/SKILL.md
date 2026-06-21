---
name: subagent-driven-development
description: 'Use whenever you have a written implementation plan (typically in `specs/<NNNN>-<name>.md`) and the tasks are mostly independent — dispatches a fresh subagent per task with a two-stage review (spec compliance, then code quality) before moving on. Trigger on phrases like "execute this plan", "implement the plan", "run through the spec", "build this out task by task" when subagents are available. Conserves the main session''s context (controller never reads implementation code) and produces higher quality than inline execution via review checkpoints. If subagents are not available, use `jojo-skills:executing-plans` instead.'
version: 0.1.0
---

# Subagent-Driven Development

Execute a plan by dispatching **a fresh subagent per task**, with **two-stage review after each task**: spec compliance first, then code quality. The controller (you) never reads implementation code directly — you orchestrate, the subagents do.

**Announce at start:** "Executing the plan with subagent-driven development."

## Why this works

- **Fresh context per task.** Each subagent starts clean — no pollution from earlier tasks, no creeping assumptions.
- **Controller context stays small.** You only handle plan text, task dispatch, and status reports. You never load the actual code.
- **Review is mandatory, not optional.** Two stages catch different classes of bug: spec review catches under/over-building; code review catches sloppiness.
- **The controller curates context.** You decide what each subagent sees. Subagents do not read the plan file — you paste the relevant task text into the dispatch prompt.

## Core principle

**Fresh subagent per task + two-stage review = high quality, fast iteration.**

Do not pause for "should I continue?" check-ins between tasks. The user asked you to execute the plan — execute it. The only reasons to stop: a `BLOCKED` status you can't resolve, genuine ambiguity, or all tasks done.

## The loop

### Setup (once, at the start)

1. Read the plan file in full.
2. Extract every task's full text into your own working memory (you'll paste each into a dispatch prompt later — do not make subagents read the plan).
3. Create a TodoWrite with one item per task.

### Per task

1. **Dispatch implementer subagent.** Paste the task's full text plus scene-setting context. Use the implementer prompt template (`./implementer-prompt.md`). Wait for status.
2. **Handle the status:**
   - `DONE` → proceed to spec review.
   - `DONE_WITH_CONCERNS` → read the concerns. If they're about correctness, fix before review. If they're observational ("file is getting large"), note and proceed.
   - `NEEDS_CONTEXT` → provide the missing context, re-dispatch.
   - `BLOCKED` → see "Handling BLOCKED" below.
3. **Dispatch spec compliance reviewer** (`./spec-reviewer-prompt.md`). They verify the implementation matches the task spec — nothing missing, nothing extra.
   - ✅ → proceed to code quality review.
   - ❌ → re-dispatch the *same implementer* with the spec reviewer's findings. Once fixed, re-dispatch the spec reviewer. Loop until ✅.
4. **Dispatch code quality reviewer** (`./code-quality-reviewer-prompt.md`) with the task's commit range (`BASE_SHA` = commit before this task, `HEAD_SHA` = current). They check cleanliness, tests, maintainability.
   - Approved → mark task complete.
   - Issues → implementer fixes, code reviewer re-reviews. Loop until approved.
5. **Mark the TodoWrite item complete.** Move to next task.

### After all tasks

- Dispatch a final code reviewer over the *entire* commit range (`<base>..HEAD`) for a holistic pass.
- Report to the user: where the plan lives, how many commits, final test status. Ask whether to open a PR, merge, or hand off — those are shared-state actions that need explicit consent.

## Handling BLOCKED

Never silently re-dispatch the same subagent with the same prompt expecting different results.

1. **Context problem?** Provide more context, re-dispatch with the same model.
2. **Reasoning problem?** Re-dispatch with a more capable model.
3. **Task too large?** Break it into smaller sub-tasks, dispatch each.
4. **Plan is wrong?** Escalate to the user. Don't paper over plan bugs in dispatch prompts.

## Model selection

Use the least capable model that can do the role. Save cycles and money.

| Task shape | Model |
|---|---|
| 1–2 files, complete spec, mechanical work | cheap/fast (Haiku tier) |
| Multi-file integration, debugging, judgment | standard (Sonnet tier) |
| Architecture, design, review of big diffs | most capable (Opus tier) |

Spec compliance review is mostly mechanical → cheap model usually fine. Code quality review benefits from a stronger model on non-trivial diffs.

## Prompt templates

Three subagent roles, three templates in this skill directory:

- **`./implementer-prompt.md`** — for the implementer subagent
- **`./spec-reviewer-prompt.md`** — for the spec compliance reviewer
- **`./code-quality-reviewer-prompt.md`** — for the code quality reviewer

Read each template when you're about to dispatch the corresponding subagent. Fill in the placeholders with the actual task text / commit SHAs.

## Hard rules

- **Never start implementation on the default branch** (`main`/`master`) without explicit consent.
- **Never make the implementer read the plan file** — paste the task text into the dispatch prompt. The plan is your context, not theirs.
- **Never dispatch multiple implementers in parallel for the same plan** — they'll conflict on shared files. Reviewers in parallel are fine.
- **Never skip a review stage.** Spec compliance before code quality, every time, no exceptions.
- **Never accept "close enough" on spec compliance.** If the spec reviewer found issues, the implementer fixes them and the spec reviewer re-reviews. Loop until ✅.
- **Never let the implementer's self-review replace the spec/code review.** Self-review is preliminary; the dispatched reviewers are the gate.
- **Never silently change the plan.** If a task is wrong, escalate.
