---
name: ayoflo
description: 'Use to solve ONE specific, substantial problem well via a three-stage pipeline: subject Expansion (broaden the problem surface) -> Research (ayo cross-model prior-art mining over the expanded subject) -> FLO (feedback-loop-optimization that actually produces and selects the solution, grounded in the research). The unit solver — point it at a thorny design decision or sub-problem. dago calls ayoflo to produce a DAG plan and to resolve heavy nodes. Distinct from ayo (mines lessons, does not solve) and feedback-loop-optimization (optimizes with no expansion/research front-end).'
version: 0.1.0
---

# ayoflo — Expansion → Research → FLO

ayoflo solves one specific problem well by front-loading context before optimizing. A naive single pass under-frames a meaty problem; ayoflo first **expands the subject** (surfaces the full problem surface and adjacent territory), then **researches** it cross-model (ayo-style prior-art mining over the expanded subject), then runs a **FLO** that produces and selects the solution with that expansion + research as grounding. The research feeds the FLO workers' and evaluators' context, so the optimization is *informed* rather than blind.

**Announce at start:** "Running ayoflo on <problem>: subject expansion → research → FLO."

## When to use / when not

- **Use** for a single, substantial problem worth solving well — a design decision, a thorny artifact, a sub-problem — where expanding the subject and mining prior art would materially improve what the FLO has to work with.
- **Don't use** for a trivial problem (just answer it, or a bare FLO), or to break a large problem into many *interdependent* sub-problems resolved in dependency order — that is `dago` (which calls ayoflo to plan and per node).
- ayoflo is the **unit solver**; `dago` is ayoflo-at-scale across a DAG.

## The flow

### 0 — Frame
The one problem to solve, and the grounding docs/specs/constraints it must respect.

### 1 — Subject expansion
Broaden the problem surface before researching: what is actually being asked, the adjacent concerns, the framings and hard constraints, the candidate solution shapes. The goal is to not under-scope — a narrow frame produces narrow research and a narrow FLO. (Host does this; a quick fan-out is optional.)

### 2 — Research (ayo)
Run an `ayo` cross-model pass over the *expanded* subject — mine how mature systems handled this shape and what they learned the hard way, cross-family so blind spots don't correlate. Synthesize into a tight, triaged brief the FLO can consume (not raw lane dumps).

### 3 — FLO (solve)
Run `feedback-loop-optimization` to actually produce and select the solution, seeding the worker prompt **and** the evaluator rubric with the expansion + research brief. Workers propose; isolated cross-family evaluators score; loop to stuck/max. This is where the solution is produced — ayoflo's first two stages exist to make this stage well-grounded.

### 4 — Land
The solved artifact + a method footer (expansion notes, ayo families used, FLO config + final score). Update memory with the load-bearing decision so it isn't re-litigated. Commit atomically.

## Notes

- The research **grounds** the FLO — that is the whole point. Don't let the FLO run blind when expansion + research would have framed it.
- The orchestrator stays the synthesizer; research lanes and evaluators only ever *propose* or *score*, never both in one context (anti-sycophancy, as in `ayo` / FLO).
- In slopysheet, this same Expansion→ayo→FLO shape both produced the #16 world-model DAG plan (planning use, driven by `dago`) and resolved individual nodes (e.g. the U-unification node, FLO 100/100).
- Pairs with: `dago` (orchestrates ayoflo across a DAG — to produce the plan and to resolve heavy nodes), `ayo` (the research stage, standalone), `feedback-loop-optimization` (the solve stage, standalone).
