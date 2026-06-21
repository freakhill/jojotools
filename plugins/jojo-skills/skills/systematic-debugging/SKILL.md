---
name: systematic-debugging
description: Use when facing any bug, test failure, crash, or surprising behaviour — before proposing or writing a fix. Enforces reproduce → hypothesize → instrument → root-cause → fix → re-verify, instead of pattern-matching a patch from a stack trace.
---

# Systematic Debugging

A fix you haven't watched the failure resist is a guess. The whole discipline: never change code until you've reproduced the failure and can name its cause.

## The one inviolable gate
**No fix before a reproduction you have run and watched fail.** Produce the exact command or test that triggers the bug, run it, and confirm you see the real failure. If you can't reproduce it, your job is to get a reproduction — not to patch.

## Loop
1. **Reproduce.** A minimal command/test that fails deterministically. Run it; capture the *actual* error, not the one you assume from the description.
2. **Hypothesize — one at a time.** State it falsifiably: "X is wrong because Y; if so I will observe Z." If you can't predict an observation, you're guessing, not debugging.
3. **Instrument, don't simulate.** Print/log/assert the real values at the suspected point and re-run. Don't reason purely from reading source — the code you think runs is not always the code that runs.
4. **Root cause, not symptom.** Trace the bad state back to where an invariant first broke. A null-check at the crash site that hides *why* the null appeared is not a fix.
5. **Fix, then re-run the exact reproduction.** It must now pass. Then run the adjacent cases on the same path.

## Sharp tools
- **Regression?** `git bisect` (or test the midpoint between last-good and first-bad) instead of reading diffs and guessing.
- **Many interacting parts?** Reduce to the smallest failing case; delete whatever doesn't change the failure.
- **Opaque error string?** Grep the codebase for it — it's usually application-specific, not what you'd assume it means.
- **Check the environment** (versions, branch, config, deps) before suspecting deep logic.

## Discipline
- **One change per experiment.** If the result doesn't match your prediction, **revert it** before the next — never stack patches on failed hypotheses.
- If ~3 hypotheses fail without a coherent causal story, write the failure out in plain language; the gap usually shows itself. If it's still not reproducible, switch to adding instrumentation and stop theorizing.

You are guessing, not debugging, if: you're editing code you haven't seen fail, you can't state the current hypothesis in one sentence, or you're changing more than one thing "to see if it helps."
