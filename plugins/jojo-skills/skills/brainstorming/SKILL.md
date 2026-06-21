---
name: brainstorming
description: Use before any creative or build work — a new feature, component, refactor, or behaviour change — to turn an idea into an agreed design before writing code. Trigger on "let's build X", "add Y", "I want Z". Explores intent, surfaces alternatives, and gets sign-off before implementation.
---

# Brainstorming

Code is the expensive way to discover you misunderstood the problem. Design first, cheaply, and agree before building.

## Gate
**No implementation until there is a stated problem and a chosen design the user has signed off on.** The simplest task still gets a design — it can be three sentences, but it is explicit and approved.

## Flow
1. **Restate the problem in one line + success criteria.** If you can't, you don't understand it yet.
2. **Resolve ambiguity by asking, not assuming.** Where scale, format, edge cases, or integration points are unstated, ask 1-3 sharp questions — don't hallucinate a requirement to fill the gap.
3. **Offer 2-3 distinct approaches with trade-offs; lead with a recommendation.** The first idea you generate is rarely the best — forcing alternatives breaks first-answer bias. Present a ranked list with a clear #1 and why.
4. **Apply YAGNI.** Drop anything not needed for the stated criteria — no speculative abstraction, config, or extension hooks "for later."
5. **Pin the contract.** For non-trivial work, sketch the key interface / data shape / flow in text before internals.
6. **Get sign-off, then stop.** Present the chosen design and wait for approval before coding. Don't make the user reject 300 lines they never wanted.

## Scope first
If the request is really several independent systems, say so and decompose before designing — don't refine the details of something that needs splitting. Each sub-project gets its own design → plan → build cycle.

Go back to design if: you're writing code without a one-line problem statement, you have only one approach, or you're filling an ambiguity with a guess instead of a question.

When the design is agreed and the work is multi-step, hand it to **writing-plans**.
