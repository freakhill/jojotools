---
name: dago
description: 'Use to solve a LARGE problem that decomposes into interdependent sub-problems. dago uses ayoflo to produce a DAG plan (subject expansion -> research -> FLO yields the decomposition), schedules the nodes into dependency waves, then resolves each node with the right tool for it — a raw host-session agent, a feedback-loop-optimization, or a nested ayoflo — wave by wave. For a tiny/obvious graph the plan is hand-built (waiver rule) instead of via ayoflo. Distinct from ayoflo (solves one problem) and feedback-loop-optimization (optimizes one artifact).'
version: 0.1.0
---

# dago — DAG-Orchestrated Problem Solving

dago solves a problem too big for one pass by turning it into a dependency DAG and resolving it node by node. First it gets a **plan**: it runs `ayoflo` (expansion → research → FLO) aimed at *decomposing* the problem into an acyclic DAG of sub-problems. Then it schedules the nodes into dependency **waves** and **resolves each node** with whatever fits that node — a raw host-session agent for the easy ones, a `feedback-loop-optimization` for a single contested decision, or a nested `ayoflo` for a node that is itself a substantial sub-problem. The DAG keeps the order honest (no node resolved before its inputs exist); the per-node tool choice keeps cost proportional to difficulty.

**Announce at start:** "Running a dago pass on <problem>: ayoflo plan → resolve nodes wave by wave."

## When to use / when not

- **Use** when the problem is large and decomposes into *interdependent* sub-problems that must be resolved in dependency order.
- **Don't use** for a single problem (use `ayoflo`), a single artifact to score (`feedback-loop-optimization`), or a flat list of *independent* tasks (just do them, or `writing-plans`).

## The flow

### 0 — Frame
The overall problem, and the grounding docs/specs/constraints.

### 1 — Plan via ayoflo
Run `ayoflo` to produce the DAG: **nodes** (one sub-problem each), **edges** (`X → Y` = Y consumes X, each with a one-line *why*), a single root and terminal. ayoflo's FLO stage is where a bad decomposition — a cycle, a mis-ordering — gets caught and re-scored before any node is resolved.

**Waiver rule:** if the graph is tiny and obvious — rule of thumb ≤3 nodes, no shared substrate that all nodes touch — skip ayoflo and hand-build the DAG.

### 2 — Verify acyclic + schedule waves
DFS / topological sort; **reject any cycle** (fix by making a node consume *fewer* inputs / cutting the back-edge). Confirm a single root (consumes nothing internal) and terminal (consumed by nothing). Emit the **waves**: W1 = roots; each later wave = nodes whose predecessors are all resolved. Nodes within one wave are independent and may be resolved in parallel.

### 3 — Resolve node by node, wave by wave
For each node in wave order, pick the **lightest sufficient** tool:
- **raw host agent** — the node is small/obvious; just resolve it directly.
- **`feedback-loop-optimization`** — one contested decision over candidate solutions.
- **`ayoflo`** — the node is itself a meaty sub-problem needing its own expansion + research + FLO.

Resolve grounded in the node's predecessors; each node's output pins what its downstream nodes consume.

### 4 — Integrate + land
Assemble the resolved nodes; optionally run one final adversarial FLO over the whole. Land a design note (`docs/spec/design/<YYYY-MM-DD>-<topic>.md`) with: the DAG (nodes + edges + waves), per-node resolutions, rejections / deferred / owed, and a method footer (ayoflo-or-waiver for the plan, the per-node tool each node got, evaluator families). Update project memory with the load-bearing decisions. Commit atomically.

## Notes

- Match the tool to the node — don't FLO a trivial node, don't raw-agent a load-bearing one. The DAG tells you which is which: deeper / more-consumed nodes deserve heavier tools.
- "Consume fewer inputs" is the recurring cycle-breaker: when a central node seems to need everything, suspect a miscut. The slopysheet #16 substrate cycle (`S4→S5→M→S4`) was killed by making the merge core consume *only* S1+S3.
- In slopysheet, #16 was a dago run: ayoflo produced the 9-node `U..V` DAG (its FLO stage, DeepSeek, caught the cycle and re-scored ~98.65/100), then each node was resolved in waves (U via FLO 100/100, then S2/S6, …).
- Pairs with: `ayoflo` (its planning engine, and a per-node option), `feedback-loop-optimization` (per-node resolution / final check), `ayo` (research within a node), `writing-plans` (turn the resolved DAG into a build plan).
