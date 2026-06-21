---
name: test-driven-development
description: Use when implementing a feature or fixing a bug whose behaviour can be expressed as a test — write the test first. Enforces red → green → refactor with meaningful failures, against retrofitting tests onto finished code or gaming them to pass.
---

# Test-Driven Development

The test is a design tool and a commitment, not an afterthought. Write it first so it specifies the behaviour instead of ratifying whatever the code happens to do.

## Cycle
1. **RED — write the test first; watch it fail for the right reason.** The failure must be an assertion ("expected 7, got undefined"), not a missing import or a syntax error. A false-red proves nothing — fix the test's plumbing until the failure is real and about the missing behaviour.
2. **GREEN — the minimum to pass.** Hardcode or fake it if that's the smallest step. Resist writing the general algorithm before a test forces it; over-building now is how you ship code that's wrong for the next case.
3. **REFACTOR — only on green.** Never restructure while red — you'd conflate behaviour change with cleanup. Re-run the suite after.

## What to test
- **Behaviour and public contracts, not internals.** Don't assert on private state or call-order — those tests break on every honest refactor and tell you nothing about correctness.
- Write the test as if the ideal API already existed; let it shape the signature. If the test is painful to write (deep mocks, heavy setup), the design is wrong — fix the design, not the test.
- Mock only what you don't own (network, DB, clock). A test that mocks the thing under test passes vacuously.

## When NOT to TDD
Exploration and unknowns — a new API, an unproven approach. **Spike** instead: throwaway code to learn, then delete it and TDD the real thing. Tests written against code you don't yet understand just anchor you to wrong assumptions.

## Bug fixes
Start with a failing test that reproduces the bug (confirm it fails on the unpatched code), then fix to green — the test becomes the permanent regression guard. (This is the crossover with **systematic-debugging**.)
