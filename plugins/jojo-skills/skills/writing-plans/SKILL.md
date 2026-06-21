---
name: writing-plans
description: Use when you have a spec, feature description, or multi-step request and are about to start coding — produces a complete implementation plan as checkbox-tracked tasks with exact paths, commands, and test code. Trigger even when the user doesn't say "plan" — "let's build X", "implement Y", "add Z" warrant a plan first when the work is non-trivial.
---

# Writing Plans

A good plan is one a fresh agent with zero context could execute correctly without you in the room. Write it to `specs/<NNNN>-<name>.md`.

## Each task carries everything it needs
```
- [ ] <imperative task title>
  FILE:     <exact path(s)>
  CHANGE:   <what to do — unambiguous, naming the function/anchor>
  VERIFY:   <one shell command that returns 0 on success>
  EXPECTED: <the output/behaviour that proves it worked>
```
`VERIFY` + `EXPECTED` are the point — they lock the definition of done into the plan so execution can't drift into "looks fine."

## What makes a plan good
- **Bite-sized + independently verifiable.** One thing per task, each with its own check. A task with no executable verification is underspecified.
- **Exact, not narrative.** Real paths, real commands, real test code — not "update the config." Specificity also curbs over-engineering ("add an `lru_cache` decorator", not "add caching" → a Redis dependency).
- **Refactor and behaviour are separate tasks.** A task that moves/renames code and a task that changes logic are distinct and sequential — never the same one. Mixed diffs are where patches break.
- **State scope + off-limits.** Name the files/areas that must NOT be touched; capable agents helpfully refactor adjacent things and balloon the scope.
- **Order by dependency.** A later task may consume an earlier task's output; no two open tasks edit the same region.

## Don't
Pad with per-step token budgets, AST diff-shapes, or rollback ceremony — keep it the task plus its check. When the plan is ready, hand it to **executing-plans**, or **subagent-driven-development** if the tasks are independent.
