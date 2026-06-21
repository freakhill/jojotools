---
name: subagent-driven-development
description: Use when you have a written plan (specs/<NNNN>-<name>.md) and the tasks are mostly independent — dispatch a fresh subagent per task with a two-stage review before moving on. Conserves the controller's context (it never reads implementation code) and raises quality via review checkpoints. Trigger on "execute the plan / build this out task by task" when subagents are available.
---

# Subagent-Driven Development

Run a plan by delegating each task to a fresh subagent and reviewing the result. The controller orchestrates and **never reads implementation code**, so its context stays clean across a long build.

## Per task
1. **Brief a fresh subagent** with only what this task needs: its spec (FILE/CHANGE/VERIFY/EXPECTED), the relevant interfaces, and the conventions to follow. **Not the whole plan** — a subagent that sees future tasks will helpfully start them and cause conflicts.
2. **It implements + runs the task's `VERIFY`**, and returns: what it changed, a diff summary, and the verification output. It does the reading and the work; you don't pull the code into your context.
3. **Two-stage review, in order:**
   - **Stage 1 — spec compliance.** Did it do the task, and does `VERIFY` actually pass (real output, not a claim)? If not, discard and re-dispatch — don't negotiate with it.
   - **Stage 2 — code quality.** Only if stage 1 passes: a reviewer subagent checks clarity, reuse, scope, and convention adherence.
4. **On rejection, dispatch a *fresh* subagent** with the raw failure — never keep conversing with the failed one (stale, apologetic context yields worse code). Cap retries (~3), then escalate.

## Parallelism
Dispatch tasks in parallel **only when their file sets are disjoint.** Two subagents editing the same file produce conflicts you'll resolve by hand. Otherwise serialize.

## Why it beats inline execution
The controller never loads implementation code, so it can drive a long plan without context rot, and the review gate catches the broken-but-confident patch before it lands. If subagents aren't available, fall back to **executing-plans**.
