---
name: verification-before-completion
description: Use before claiming any work is done, fixed, passing, or complete — and before committing or opening a PR. Requires running the actual check and showing its output; bans asserting success from code inspection or optimism.
---

# Verification Before Completion

The cardinal sin is claiming done without proof. "Should work" is not a status; a pasted green run is.

## The gate
Before you say done / fixed / passing: **run the exact check and put its real output in front of the user.** No verification command run and shown → not done. Inspection, reasoning, and "this will work" do not count.

## What "the check" is
- The **exact** acceptance command for the task — the one that returns 0 on success — not a proxy. Green unit tests ≠ a working service if the criterion was an end-to-end call.
- The **full** relevant suite, not only the test you touched — confirm you didn't break a neighbour.
- **Each stated acceptance criterion** mapped to its own run and reported pass/fail. Don't collapse them into "it all works."
- For a bug fix: **re-trigger the original failure** and show it's gone — not just that the happy path passes.

## Evidence travels with the claim
Paste the literal command and its output (or a CI link) in the same message as the "done." The claim and its proof together are what make it auditable. Ban future-tense success ("should now work", "this will fix it") — if you're predicting, you haven't verified.

## On failure
If the check fails, it is not done — say so, with the output. Prefer reverting to a known-good state over piling another speculative patch on a failed approach. If you can't verify after a few honest attempts, report the blocker; never fabricate success.

Before finishing, read your own diff: every changed line must be explainable as part of the verified solution — revert stray edits.
