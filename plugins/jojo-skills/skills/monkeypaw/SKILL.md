---
name: monkeypaw
description: Use when the user wants to build a complete project from scratch, "one-shot" a complex system, implement an end-to-end application, orchestrate a multi-phase research or creative endeavour, or says things like "build this for me", "create this project", "implement the whole thing", "make this happen". Guides Claude through project analysis, DAG planning, FLO-optimized orchestration, context management, and quality safeguards for any non-trivial undertaking.
version: 2.2.2
---

# monkeypaw — Full-Project Orchestration Skill
## Quick Reference

| What | Detail |
|---|---|
| Purpose | Take any project from zero to done in one coordinated effort |
| When to use | "Build X", "implement the whole thing", "one-shot this", multi-phase projects |
| Not for | Single-function tasks, quick edits, simple Q&A |
| Key output | Working repo + docs + tests/criteria + status trail |
| Phases | 0 Intake → 1 DAG+FLO → 2 Env Setup → 3 Execute → 4 Finalize |
| project_type | code \| non-code \| mixed (declared end of Phase 0A) |
| Context rule | >50% session tokens → split; spawn subagent + write handoff to `/tmp/mp_handoff_<node>.md` |
| Hallucination guard | No fact without a source; sanity-check every 5 nodes; randomized spot-checks |
| Parallel protocol | Write manifest → spawn N → poll return files → merge on layer completion |
| Output tiers | T1 progress line (`--tier 1`) · T2 node grid (default) · T3 verbose (`--verbose`) — detail in `## Output Format` |
| Drill-down | `/tmp/mp_status_<project>.md` = live T2 node grid; `/tmp/mp_*` handoff/return files = T3 on demand; `expand <node-id>` drills one node, global tier unchanged |
| Gate telemetry | after each run `mp-gate.py log …`; `mp-gate check` shows gate status; accrues the re-opt corpus in `~/.monkeypaw/` |

## Scale Gate (read before Phase 1)
| Scale | Node count | Adjust |
|---|---|---|
| **Tiny** | 1–4 | Skip Phase 2C validation baseline; use inline validate step only. Skip status doc if <3 nodes. |
| **Standard** | 5–20 | Follow all phases as written. |
| **Large** | >20 | Budget context splits from Phase 1. Expect subagent spawning. Start Phase 2 lean (defer CI stub and doc stubs until nodes complete). |

**Non-code compression** (additive to Scale Gate; applies when `project_type=non-code AND deliverables ≤ 10`):
| Phase | Compressed action |
|---|---|
| 0C STPA | One line: "single-controller, single-session: low UCA risk" |
| 1C Topology | Skip metric computation; default to Sequential |
| 1D Context budget | Skip explicit check (small non-code rarely hits 50%) |
| 1E Pre-flight | Replace Z3 with one-line topological sort sanity check |
| 4C Diataxis | Relax to ≥1 doc per quadrant *if quadrant has natural content*; don't generate empty content |
## Phase 0 — Intake

### 0A. Project Analysis (always)
```
PROJECT BRIEF
─────────────
Goal        : <one sentence>
Input(s)    : <what user/system provides>
Outcome(s)  : <measurable success>
Primary user: <who uses it>
Use case    : <main scenario>
Constraints : <language, platform, perf, compliance, style>
Deliverables: <numbered list of concrete artifacts the project must produce>
project_type: code | non-code | mixed
```
Ask user to confirm brief before Phase 1.

### 0B. Operator Doc Indexing (when docs provided)
Write index to `/tmp/mp_doc_index.md`:
```markdown
## Sources: [S1] <title>·<type>·<key claims>
## Entities: <Name>: <def> [S?]
## Constraints: <constraint> [S?]
## Open Questions: <question>
```
Source tags [S1..] on every extracted claim.

### 0C. STPA Control Structure Audit (always)
Before Phase 1, map the control structure and check for unsafe control actions:

Control structure: User → Orchestrator → [Subagents] → Artifacts/APIs → (feedback) → Orchestrator

Check 4 UCA types before executing each phase transition:
| UCA Type | Hazard example | Compensating guard node to inject |
|---|---|---|
| Not provided when needed | No test gate before production deploy | Add mandatory test-pass gate node |
| Provided when not needed | Deploy node fires on test failure | Add pass-condition pre-check |
| Wrong action | Subagent writes to shared artifact | Add artifact-locking handoff |
| Wrong timing/order | Phase 3 starts before Phase 2 complete | Enforce phase-sequencing dependency |

Write audit to `/tmp/mp_stpa_<project>.md`. Inject identified guard nodes into DAG before execution.

## Phase 1 — DAG Planning + FLO Optimization

### 1A. Draft the DAG
Each node:
```markdown
NODE <id>: <name>
- Depends on: [<ids>]
- Input: <what consumed>
- Output: <concrete artifact>
- Risk: low|medium|high
- Feedback?: yes|no (max 2 per project)
- Parallel?: yes|no
```

### 1B. FLO Optimization Pass
| Check | Action |
|---|---|
| Parallelizable | Mark [PARALLEL]; mark ~20% randomly with [SPOT] for spot-check |
| Long-chain | Insert checkpoint node |
| High-risk | Prepend spike node |
| Repeated pattern | Extract to shared module |
| Non-deterministic | Isolate node with clean I/O contract |
| Scope creep | Cut if not traceable to Project Brief |

Output: `/tmp/mp_dag_<project>.md`

### 1C. Topology Selection
After drafting the DAG, compute these metrics and select topology:

| Metric | Compute | Value |
|---|---|---|
| Width | Max nodes in any single layer | _______ |
| Depth | Longest dependency chain (node count) | _______ |
| Coupling | Shared artifact references / total edges | _______ |

| Topology | Trigger condition | Pattern |
|---|---|---|
| Parallel | Width>3, Depth≤4, Coupling<0.3 | Batch all independent layers to concurrent subagents |
| Hierarchical | Depth>8, tight serial deps | Gate each layer on prior layer completion |
| Sequential | Width≤2, Depth≤6 | Single-thread; no subagent spawning needed |
| **Hybrid** | Everything else (~50% of projects) | Parallel within layers; hierarchical across layers |

Example: 15-node Python microservice — Width=4, Depth=7, Coupling=0.35 → **Hybrid**
→ Parallel within auth/API/DB layers; hierarchical across backend→frontend→deploy phases

Record selected topology in `/tmp/mp_dag_<project>.md` header.

### 1D. Context Budget + Spawn Triggers (canonical — do not duplicate elsewhere)
```
if (nodes × avg_tokens) > 0.5 × session_limit: split at natural seam
```

| Spawn trigger | Action |
|---|---|
| Node reads >3 large files | Spawn reader subagent; receive summary only |
| Node produces >500 lines code | Spawn implementer; receive artifact path + smoke result only |
| Context > 50% session limit | Spawn continuation; pass handoff doc only |
| 20+ nodes complete | Spawn fresh orchestrator; pass status doc only |
| 2+ [PARALLEL] siblings | Use Parallel Coordination Protocol (Phase 3E) |
| Long-form multi-section document (non-code) | Spawn writer subagent per section; merge on completion |

### 1E. Formal Pre-flight Check
Verify schedulability before executing the DAG (all projects). Checks: (1) no transitive self-dependency cycle; (2) max concurrent workers ≤ limit; (3) ≥1 valid execution order exists. One method MUST run; document in `/tmp/mp_preflight_<project>.md`.

**Method A — Z3 (preferred, `pip install z3-solver`):** Solver with `start_B >= end_A` for each A→B dep; `Or(end_ta <= start_tb, end_tb <= start_ta)` for exclusive resources; `s.check() == sat` → schedulable.

**Method B — Manual:** (1) Topo sort → cycle? stop, fix DAG. (2) Max concurrent per layer ≤ worker limit? if not, add sequencing. (3) All nodes reachable from start? if not, fix missing deps. (4) On conflict: add X→Y dep or increase pool; document resolution.

## Phase 2 — Environment Setup

### 2A. Repo Creation

Branch by `project_type` (declared in Phase 0A):

```bash
# code:     mkdir -p <root>/{src,tests,docs/{tutorials,how-to,reference,explanation},scripts}; git init <root>
# non-code: mkdir -p <root>/{drafts,sources,docs/{tutorials,how-to,reference,explanation},output}  # git optional
# mixed:    union of both; git init <root>
```

All types: create README.md (Brief + quickstart), docs/reference/architecture.md (DAG), CHANGELOG.md.
Add .gitignore when git is initialised.

### 2B. Doc Scaffolding (Diataxis)
| Type | Path | Fill when |
|---|---|---|
| Tutorial | docs/tutorials/getting-started.md | After first working slice |
| How-to | docs/how-to/<task>.md | Per user task; stubs now |
| Reference | docs/reference/ | API/schema/config stubs now |
| Explanation | docs/explanation/ | As nodes complete |

### 2C. Validation Baseline First

Branch by `project_type`:

**code / mixed**
- tests/conftest.py — shared fixtures
- tests/test_smoke.py — one failing test per output node
- CI stub (.github/workflows/ci.yml)
Smoke tests must fail now. Passing = node done.

**non-code**
- docs/reference/acceptance-criteria.md — one acceptance criterion per output node
Criterion format: `- [ ] <node name>: <measurable condition>`
Criterion unchecked now. Checked = node done.

### 2D. Status Document
`/tmp/mp_status_<project>.md`:
```markdown
# Status — <name> · <date>
project_type: <code|non-code|mixed>
## Nodes
| ID | Name | Status | Output | Notes |

## DORA (update every 5 nodes)
| Metric | Current | Target |
|---|---|---|
| Lead Time | — | Minimize |
| Change Failure Rate | — | <10% |
| MTTR | — | <15 min |
| Reliability | — | >90% |
```
Update after every node.

## Phase 3 — Iterative DAG Execution

### 3A. Per-Node Protocol
```
1. Read node spec (mp_dag) + status (mp_status)
2. FLO-loop (3B)
3. Mark DONE in status; record output path
4. Context check → spawn if triggered (1D table)
```

### 3B. FLO Per Node

| Step | code | non-code |
|---|---|---|
| Plan | 5-bullet implementation plan; review if Feedback?=yes | 5-bullet implementation plan; review if Feedback?=yes |
| Implement | Write to output spec | Draft/research/compose; for numeric/derivational work use: Setup → Compute → Unit-check → Compare to limit → Document derivation |
| Test | Run smoke test → must pass | Review artifact against acceptance criterion → must pass |
| Document | Fill doc stub: what + how-to-use | Fill doc stub: what + how-to-read/apply |
| Validate | Output ≡ spec? No silent new deps? | Output ≡ spec? No scope drift? |

**When a non-code node fails Validate ≥ 1 time → ReTreVal escalation:**
1. **[ToT]** Generate 3 alternative approaches to the node's goal (different reasoning trees)
2. **[Self-Refine]** Apply one refinement pass to each candidate against the acceptance criterion
3. **[Pick]** Select highest-scoring candidate as the node's output
4. **[Remember]** Log failed paths + failure reason to Reflections slot (see Context-Folding)

Max 2 ReTreVal cycles per node. If still failing after 2: surface to user with all 3 candidates.

**Reconciliation rule:** If a node silently changes any value from the Brief or an upstream node's output (e.g., effective span L=900 → L=862, deliverable count, material spec), Validate FAILS. The node must either (a) explicitly reconcile in its output ("using L=862 because pins bear inside carcass; check vs. brief L=900"), or (b) revert to the brief value. Silent changes are bugs.

### 3C. Context Management
| Condition | Action |
|---|---|
| Context > 50% | Write handoff; fold stale slots (see Context-Folding below); spawn subagent if needed (see 1D table) |
| 20+ nodes done | Spawn fresh orchestrator; pass status doc only |
| Subagent incomplete | Write /tmp/mp_blocker_<node>.md; don't re-spawn |

**Context-Folding Protocol** (replaces summarization):
Maintain 6 indexed memory slots. When context >50%, fold stale slots to free budget.
Fold = compress slot per schema → write to `.monkeypaw/folds/<slot>.md` (OVERWRITE in place; archive previous to `.monkeypaw/folds/archive/<slot>.<sha8>.md` only if content hash changed).
Unfold = read `.monkeypaw/folds/<slot>.md` + cascade-unfold any `depends_on` items.

| Slot | Token budget | Fold trigger | Unfold when |
|---|---|---|---|
| Requirements | 500 | Never fold | Always in context |
| Architecture | 500 | Fold when ≥50% of planned nodes are marked DONE | Starting any new DAG node |
| Decisions | 300 | Fold after node completes | Node modifies code/logic touched by prior decisions |
| Risks | 300 | Fold when resolved | Node has risk=medium or high |
| Test Results | 200 | Rolling (keep last 5) | Running sanity check or Phase 4 |
| Reflections | 200 | Fold after incorporating | Node type matches a prior ReTreVal failure |

**Fold schemas** (write to .monkeypaw/folds/<slot>.md as YAML):

| Slot | Folded format |
|---|---|
| Requirements | `goal: "..."` ; `project_type: code\|non-code\|mixed` ; `scope: ["..."]` |
| Architecture | `nodes_done: ["N01", ...]` ; `nodes_open: ["..."]` ; `files_touched: ["..."]` ; `topology: hybrid\|...` |
| Decisions | list of `{id, choice, status, depends_on: [refs]}` |
| Risks | list of `{id, severity: high\|medium\|low, mitigation, status}` |
| Test Results | `pass_count: N` ; `fail: [test_names]` ; `last_run: ISO8601` |
| Reflections | list of `{node_id, failure_mode, lesson}` |

**OPEN vs. ARCHIVED:** in Decisions and Risks slots, items with `status: open` stay resident (never folded, structured YAML); items with `status: closed` fold per schema. Graduate on status change.

**Dependency-aware unfold:** ARCHIVED Decisions/Risks items carry `depends_on: [refs]` (e.g., `Arch:auth_module`, `D3`). Before unfolding an item, recursively unfold any folded `depends_on` items in topological order; inject as blockquote context above the requested item.

**Meta-Slot index** (`.monkeypaw/folds/_meta.yaml`, kept in active context ≤150 tokens):
each entry `{path, sha8, folded_at, status: resident|folded}`. Verify sha8 before consuming any fold; if mismatched → treat as stale, refuse to use.

**Slot Selection Guide** — which slots to unfold before starting a node:

| Node characteristic | Unfold these slots |
|---|---|
| First node in a new DAG layer | Architecture |
| risk=medium or high | Risks |
| Touches same module/file as a prior node | Decisions |
| Marked [SPOT] or is a checkpoint node | Test Results |
| Node type previously failed ReTreVal | Reflections |
| Phase 4 finalization | Test Results + Architecture |

Subagent handoff (`/tmp/mp_handoff_<node>.md`):
```markdown
# Handoff — <project> — Node <id>
## Context: <3-sentence summary>
## Done: <node list + artifact paths>
## Task: Execute nodes <start>–<end> per /tmp/mp_dag_<project>.md
## Return: Write /tmp/mp_return_<node>.md (node ids, artifact paths, blockers)
```
Orchestrator holds: Brief + DAG + status + active node. Reads on demand only.

### 3D. Cohesion & Modularity

**Principle: Determinism by default.** Every behavior should be deterministic unless LLM inference, external API calls, or genuine randomness is required.

| Rule | code | non-code |
|---|---|---|
| Co-location | Co-changing logic → same module | Co-changing content → same file/section |
| Deterministic core | `src/core/` — pure fn, no side-effects | Canonical source document |
| Non-deterministic isolation | `src/adapters/` — typed interfaces | Bounded section with explicit I/O |
| Reusable extraction | `src/utils/` on 2nd use | `docs/reference/` on 2nd use |

### 3E. Parallel Subagent Coordination

Use when 2+ sibling nodes marked [PARALLEL].

1. **Pre-spawn**: Write `/tmp/mp_parallel_<L>.md` — list all expected `/tmp/mp_return_<node>.md` paths.
2. **Spawn**: All N subagents simultaneously (one handoff file each). Do not wait between spawns.
3. **Poll**: For each expected return file: exists→COMPLETE, blocker file exists→FAILED, else→IN-FLIGHT. Poll after working on serial nodes — don't spin-wait.
4. **Failure**: Write `/tmp/mp_blocker_<node>.md`. Continue all other nodes. Defer only downstream dependents.
5. **Merge**: When all non-failed nodes have return files — batch-update `/tmp/mp_status_<project>.md` once.

| Step | Writes | Reads | Gate |
|---|---|---|---|
| Pre-spawn | mp_parallel_<L>.md | — | All return paths listed |
| Spawn | mp_handoff_<node>.md × N | — | All N sent |
| Poll | mp_parallel_<L>.md (updates) | mp_return_<node>.md | File exists |
| Failure | mp_blocker_<node>.md | — | Per-node, not per-layer |
| Merge | mp_status.md | All layer returns | Layer complete |

### 3F. Context Budget Governor

Header every prompt — host-adaptive (numeric countdowns trigger context-anxiety on Fable-family hosts per Anthropic guidance; the policy tier carries all actionable signal):
- Host is Fable/Mythos: `<!-- BUDGET policy: NORMAL|PROACTIVE|EMERGENCY -->` (policy only — never surface used/total numbers or percentages to the model; track them in `sweep_metrics.md` instead)
- Other hosts: `<!-- BUDGET: used/total (pct%) | policy: NORMAL|PROACTIVE|EMERGENCY -->`

| Policy | Trigger | Action |
|---|---|---|
| NORMAL | <50% | Standard folding (3C) |
| PROACTIVE | 50-80% | Fold all eligible; defer borderline decisions |
| EMERGENCY | >80% | Collapse all slots except Requirements; route remaining work to subagents |

Update budget after each node; re-evaluate policy on every fold.

## Phase 4 — Integration & Finalization

### 4A. Integration Checklist

**code / mixed**
- [ ] All smoke tests pass
- [ ] E2E test: primary use case from cold start
- [ ] README quickstart works from clean env

**non-code / mixed**
- [ ] All acceptance criteria in docs/reference/acceptance-criteria.md checked
- [ ] No [UNVERIFIED] tags remain in any artifact
- [ ] All claims have source citations [S?]

**all project types**
- [ ] Doc stubs filled (no TODO in docs/)
- [ ] CHANGELOG.md updated
- [ ] Architecture doc matches actual structure

### 4B. Backward Refinement Sweep (fires when: node_count>15 AND coupling>0.2 AND code/mixed AND env MP_SKIP_PHASE_A is unset)

> **Skip sentinel:** if env var `MP_SKIP_PHASE_A=1`, log `Phase 4B skipped (MP_SKIP_PHASE_A=1)` to status doc and proceed to 4C. Used for Phase A validation baselines (see `PHASE-A-CORPUS.md`).

Propagate downstream evidence upstream — corrects early design decisions using late-stage test/integration results.

Budget: `min(2 × node_count, 64)` FLO loops total.

**Protocol:**
```
For each node in reverse topological order (bottom→top):
  1. Unfold slots: Decisions + Test Results (from context-folding)
  2. Run 1 FLO loop: does this node's output still satisfy downstream inputs?
  3. If FLO improvement > 2 pts: mark node [REFINE] in status doc
  4. Decrement budget by 1; if budget=0 → dump state and stop
  5. Append metric row → .monkeypaw/sweep_metrics.md (schema below)
After sweep: write .monkeypaw/sweep_summary.md (schema below), then re-execute [REFINE] nodes in forward order
```

**.monkeypaw/sweep_metrics.md schema** (one row per visited node, append-only):
```markdown
# sweep_metrics: <project>

<!-- sweep-meta
project: <project>
started_at: <iso8601>
budget_total: <int>
-->

| node_id | baseline_score | new_score | delta | refine | budget_remaining | timestamp |
|---------|----------------|-----------|-------|--------|------------------|-----------|
| N15     | 82             | 89        | +7.0  | yes    | 29               | <iso8601> |
| N14     | 91             | 91        | +0.0  | no     | 28               | <iso8601> |
```
Scores are integers or one-decimal floats. `refine` is `yes`/`no`. Deltas printed with sign.

**.monkeypaw/sweep_summary.md schema** (single doc, written once at sweep end):
```markdown
# sweep_summary: <project>

<!-- sweep-summary
project: <project>
completed_at: <iso8601>
-->

| field | value |
|-------|-------|
| total_nodes        | 18    |
| visited_nodes      | 18    |
| refine_count       | 3     |
| mean_delta         | +1.4  |
| max_delta          | +7.0  |
| budget_used        | 18    |
| budget_total       | 30    |
| converged          | yes   |
| terminated_reason  | all_visited |

## [REFINE] nodes (forward execution order)
- N03, N07, N15
```

`terminated_reason` is one of: `all_visited` · `budget_exhausted` · `oscillation_guard`.
`converged` is `yes` when `refine_count == 0` AND `terminated_reason == all_visited`.

| Signal | Action |
|---|---|
| No [REFINE] nodes after sweep | System converged — skip re-execution |
| Budget exhausted before sweep completes | Dump to `/tmp/mp_wave_backward_<p>.md`; resume later |
| coupling > 0.7 | Add warning: "high coupling — oscillation risk; limit to 1 sweep" |

Serialize state to `/tmp/mp_wave_backward_<project>.md` (DAG range covered, budget used/remaining, [REFINE] node list).

### 4C. Diataxis Quadrant Enforcement (all types)
Before marking project complete, classify every generated document:

| Quadrant | Identifies by | Enforce ≥1 |
|---|---|---|
| Tutorial | Step-by-step learning sequence | ✓ required |
| How-to | "How to..." goal-oriented procedure | ✓ required |
| Reference | Facts, schema, API, config | ✓ required |
| Explanation | "Why..." rationale, trade-offs | ✓ required |

If any quadrant is empty: generate the missing document from available artifacts before finalizing.

### 4D. Final Report
`/tmp/mp_final_<project>.md` — sections: `## Delivered` (artifacts + paths), `## Not delivered` (why / "none"), `## Known limitations`, `## Next steps`.

**4E. Gate telemetry (every run).** After the final report, harvest gate data:
`uv run <skill>/scripts/mp-gate.py log --project <p> --archetype <code|data|lang|numeric|creative|mixed> --scale <tiny|standard|large> --score <oracle%|FLO|NA> [--score-kind oracle|flo] [--governor NORMAL|PROACTIVE|EMERGENCY] [--handoff-recovered yes|no] [--nodes-unrecovered N] [--misroute] [--resource-saturated] [--manual-resolution]`
It reads `/tmp/mp_preflight_<p>.md`, `/tmp/mp_topology_<p>.md`, `.monkeypaw/sweep_summary.md`, `.monkeypaw/folds/` automatically. If it prints a `GATE MET` line, surface it to the user as a re-optimization opportunity.

## Filesystem Conventions

| File | Purpose |
|---|---|
| /tmp/mp_dag_<p>.md | Authoritative DAG + topology header |
| /tmp/mp_doc_index.md | Doc index (Phase 0B) |
| /tmp/mp_stpa_<p>.md | STPA audit + guard nodes (Phase 0C) |
| /tmp/mp_preflight_<p>.md | Z3/formal pre-flight result (Phase 1E) |
| /tmp/mp_status_<p>.md | Live node status + DORA metrics |
| /tmp/mp_handoff_<n>.md | Orchestrator → subagent |
| /tmp/mp_return_<n>.md | Subagent → orchestrator |
| /tmp/mp_blocker_<n>.md | Blocked node |
| /tmp/mp_parallel_<L>.md | Parallel layer manifest |
| <repo>/.monkeypaw/folds/<slot>.md | Persistent folded slot (overwrite in place) |
| <repo>/.monkeypaw/folds/archive/ | Versioned fold history (hash-keyed) |
| <repo>/.monkeypaw/folds/_meta.yaml | Slot index: path + sha8 + fold_timestamp per slot |
| ~/.monkeypaw/gate_telemetry.jsonl | Cross-run gate telemetry ledger (mp-gate) |
| /tmp/mp_wave_backward_<p>.md | Backward sweep state |
| /tmp/mp_final_<p>.md | Final report |
| <repo>/docs/ | Permanent Diataxis docs |

Anti-ping-pong: incomplete result → write blocker → don't re-spawn → fix in context → surface to user → re-spawn only after cleared.

## Output Format

Emit status at 3 tiers (default: Tier 2):

| Tier | Content | How to switch |
|---|---|---|
| 1 | `[Phase X/5] [Node Y/N] [Z tokens]` — one line | `--tier 1` |
| 2 | Node grid: `ID · icon · elapsed · artifact` (default) | _(default)_ |
| 3 | Full: DAG rationale + token logs + subagent spawn logs | `--verbose` |

`expand <node-id>` → drill into that node's detail without changing global tier.

Standard node completion line (always emitted):
`[DONE] <id>: <artifact-path> · <Xs elapsed> → next: <downstream-id>`

Status icons: ✓ done · ⟳ running · ✗ failed · ⏸ deferred (awaiting approval or blocked)

## Quality Protocols

| Protocol | Mechanism |
|---|---|
| Hallucination prevention | [S?] source tags; [UNVERIFIED] cleared before DONE; spike node before high-risk |
| Source validation | Verify dep exists + current version; read actual docs, not memory |
| Deviation detection | Compare output to spec → update status → re-run FLO subgraph → user approval |

**Sanity Checks**:
| Type | Frequency | Mechanism |
|---|---|---|
| Smoke | Every node | Test/criterion passes before DONE |
| Integration | Every 5 nodes | All tests/criteria; no regression |
| Spot-check | ~20% [SPOT] nodes (Phase 1B) | Re-read artifact; matches spec |
| Full | Phase 4 | E2E + doc completeness + arch diff |

## Reusable Tool Extraction

When a utility is used twice across nodes:

| Step | code | non-code |
|---|---|---|
| Extract | src/utils/<name>.py | docs/reference/<pattern>.md |
| Wire callers | Update all imports | Link from every node doc |
| Test | tests/test_utils_<name>.py | — |
| Docs | docs/reference/ entry | — |
| Log | CHANGELOG.md | CHANGELOG.md |

Cross-project skill → ~/dotfiles/claude/skills/<name>.md
