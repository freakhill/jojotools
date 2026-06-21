---
name: writing-plans
description: 'Use whenever the user hands you a spec, a feature description, or a multi-step request and you are about to start coding. Produces a complete implementation plan as bite-sized, checkbox-tracked tasks with exact file paths, test code, and commands — written so a fresh engineer with zero context could execute it. Trigger even when the user does not say "plan" — phrases like "let''s build X", "implement Y", "I want to add Z" all warrant a plan first if the work is non-trivial.'
version: 0.1.0
---

# Writing Plans

Write implementation plans for a skilled engineer who knows nothing about this codebase or domain. Document every file they need to touch, every test they need to write, every command they need to run. The plan should stand on its own — if you find yourself writing "you'll figure this out", stop and write the actual content.

**Announce at start:** "Writing the implementation plan."

**Save plans to:** `specs/<NNNN>-<feature-name>.md` where `<NNNN>` is the next zero-padded sequence number (`0001`, `0002`, ...). If the project uses a different convention (e.g., `docs/plans/`, `RFCs/`), follow that instead.

## Principles

- **DRY, YAGNI, TDD, frequent commits.** Each task should end with a passing test and a commit.
- **Bite-sized steps.** Each step is one concrete action (write a test, run it, write the impl, commit). 2–5 minutes each.
- **No placeholders.** "TBD", "implement later", "add error handling", "similar to Task 3" are plan failures. Write the actual code, paths, and commands.
- **Exact paths.** Every file reference includes the full path from repo root. Line numbers when modifying.

## Scope check (before writing)

If the spec covers multiple independent subsystems (e.g., "a CLI tool AND a web dashboard AND a Slack bot"), don't cram them into one plan. Suggest splitting into one plan per subsystem — each producing working, testable software on its own. Bundling unrelated work makes the plan hard to follow and hard to review.

## File structure (do this before defining tasks)

List every file that will be created or modified, with one line on what each is responsible for. This locks in decomposition decisions before you write tasks.

Guidelines:
- One clear responsibility per file. Files that change together should live together.
- Prefer smaller, focused files over large grab-bags — they're easier to hold in context.
- In existing codebases, follow the established structure. Don't unilaterally restructure a repo as part of a feature plan.

## Plan document header

Every plan starts with this header:

```markdown
# <Feature Name> Implementation Plan

**Goal:** <one sentence>

**Architecture:** <2-3 sentences on the approach>

**Tech stack:** <key libraries / frameworks>

**File structure:**
- `path/to/new_file.py` — <one-line responsibility>
- `path/to/existing.py` (modify) — <what changes>
- `tests/test_new.py` — <what it tests>

---
```

## Task structure

Each task is a numbered section with its files listed up top, then checkbox-tracked steps. Use this template:

````markdown
### Task N: <Component Name>

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test_file.py`

- [ ] **Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

- [ ] **Step 2: Run the test, verify it fails**

```bash
pytest tests/exact/path/to/test_file.py::test_specific_behavior -v
```
Expected: FAIL with "function not defined" (or similar).

- [ ] **Step 3: Write the minimal implementation**

```python
def function(input):
    return expected
```

- [ ] **Step 4: Run the test, verify it passes**

```bash
pytest tests/exact/path/to/test_file.py::test_specific_behavior -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/exact/path/to/test_file.py src/exact/path/to/file.py
git commit -m "feat: <what this task added>"
```
````

## No-placeholders rule

These patterns are plan failures — never write them:

- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling", "add validation", "handle edge cases" without showing what code to add
- "Write tests for the above" without the actual test code
- "Similar to Task N" — repeat the code, since the engineer may read tasks out of order
- Steps that describe *what* without showing *how* (code steps must contain code blocks)
- References to types, functions, or methods that aren't defined anywhere in the plan

If you catch yourself writing one of these, stop and write the actual thing.

## Self-review (before handing off)

After the plan is drafted, re-read it once with fresh eyes. Three quick checks:

1. **Spec coverage.** Walk through each requirement in the spec. Can you point at the task that implements it? List gaps. Add tasks for any gap.
2. **Placeholder scan.** Grep your plan for the patterns above. Replace with concrete content.
3. **Type/name consistency.** Function names, type names, and field names used in later tasks should match what earlier tasks define. `clearLayers()` in Task 3 and `clearFullLayers()` in Task 7 is a bug.

Fix issues inline. No need to re-review — just fix and move on.

## Handoff

Once the plan is saved, summarize in two lines: where the plan is, and how many tasks it has. Then ask whether to start executing it now or whether the user wants to review first.

If executing in the same session, work task-by-task: do all steps in Task 1, confirm tests pass and commit, then move to Task 2. Don't batch multiple tasks together — checkpoints between tasks are what make this safe.
