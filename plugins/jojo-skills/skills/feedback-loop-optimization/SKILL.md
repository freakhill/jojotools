---
name: feedback-loop-optimization
description: This skill should be used when the user wants to "optimize a task iteratively", "run a feedback loop on a project", "improve a solution through iterations", "run FLO on this", "set up an optimization loop", "evaluate and improve my solution", or needs to systematically improve output quality through repeated worker/evaluator cycles with anti-sycophancy separation.
version: 1.9.13
---

> **First run?** Read Phase 0→1→2→3→4 sequentially (~15 min).
> **Returning?** Use Quick Reference below + phase headers to jump directly.
> **Evaluator/Worker role?** Go to Orchestration Notes → Subagent Prompt Structure.

## Quick Reference

**What FLO does:** Worker+Evaluator loop until stuck or max_iter.

**Scoring formula:**
weighted_score = Σ (score_i / 10) × weight_i    [result: 0–100]

**Population tiers:**

| Tier | P | Use when |
|---|---|---|
| 1 | 1 | Budget-critical; deterministic/hard-constrained problems |
| 2 | 2–3 | Scoped writing; binary creative direction; moderate solution space |
| 3 | 4–6 | Most tasks — best bang for buck; default P=6 |
| 4 | 8–16 | High-stakes, high-subjectivity, large solution space |

**Session flow:**
Phase 0 (Preflight) → Phase 1 (Setup+Tier) → Phase 2 (Baseline) → Phase 3 (Loop) → Phase 4 (Report)

**Key parameters:**

| Parameter | Default |
|---|---|
| max_iter | 10 |
| stuck threshold | no new best for exactly 3 consecutive gens (→ Phase 3 Step 8) |
| default P | 6 (Tier 3) |
| evaluator model | host-dependent (→ Orch. Notes routing table); invariant: evaluator model ≠ host/worker model |
| rubric lock | locked at Phase 1 (→ Phase 1) |
| K_evaluators | 1 default; 2 when best_score > 95 (→ Ph3.4) |
| K=2 path | Eval-1 Kimi K2.7 (orig order) + Eval-2 strongest non-host judge (reversed order); cross-family when Kimi available, intra-family ×2 fallback otherwise. Per-host binding + the Gemini premium-default / GLM / GPT-5.5 audit voices → **ORCHESTRATION.md** (routing table). |
| position-swap | K=1 path only; applied to the winning offspring only; replace per-criterion score with avg of original + reversed-order eval when delta > 1.5 pts (→ Ph3.4) |
| MAX_GENES | 16 total distinct values summed across all 5 slots (→ Ph3) |
| MAX_EXPANSIONS | 5 expansion events per session (→ Ph3.3) |
| archive | MAP-Elites (quality-diversity archive) 9-cell grid (3×3: complexity × operator) (→ Ph3.1, Ph3.5) |
| archive_draw_prob | 10% absolute (split: 1% explore unfilled cell + 9% UCB1 over filled) (→ Ph3.1) |
| gene_posteriors | Beta(1.5,1.5) prior per (slot,value) pair; Thompson Sampling (TS) selects mutation target slot (→ Ph3.2) |
| op_posteriors | Beta(2,2) prior per operator in {mutation, crossover, explorer}; TS selects operator lens (→ Ph3.6b) |

**Genome slot-vector format:** exactly 5 named slots, each holding exactly one value drawn from that slot's vocabulary list in genome_registry.

Example:
```
genome = {eval_mechanism: cross_family, diversity_method: map_elites, mutation_targeting: ts_weighted, expansion_trigger: both, usability_focus: compact_qr}
```

**Phase 3 at-a-glance (each generation):**
1. Select 2 parents — binary tournament; per draw 10% absolute is a MAP pick (1% unfilled-cell signal + 9% UCB1).
2. Lane A (mutation): TS picks the slot (highest posterior mean); worker picks a new value for that slot.
3. Lane B (crossover): for each of the 5 slots, fair 50/50 coin flip → inherit from P1 or P2.
4. Explorer (optional): fires if no_improve_streak ≥ 2 OR θ_explorer is the highest operator sample. Proposes a new vocabulary value.
5. Evaluate every offspring. K=1 default; K=2 cross-family (Kimi+non-host Claude) when best_score > 95.
6. Winner = highest weighted_score. Update (slot,value) and operator TS posteriors.
7. Pop update: elite carries; fill P−1 via tournament; MAP-Elites admission for winner + every offspring.
8. Halt when no_improve_streak ≥ stuck_threshold OR generation ≥ max_iter.

---

# Feedback Loop Optimization (FLO)

Iterative improvement via parallel Worker subagents + isolated Evaluator subagents. Workers propose; evaluators score. The two roles never merge in any subagent context (anti-sycophancy). Loop runs until stuck or max iterations.

> **Measured scope — when is the full loop worth its cost?** A blind, 3-judge-family forced-ranking study (this full protocol vs a ~210-line minimal baseline; 6 diverse tasks × n=6 reps; 648 cross-version decisions) found the protocol buys **modest but real** quality overall (win-rate **0.548, p=0.017**), **concentrated in fidelity / teaching-correctness tasks**: faithful compression that must preserve every fact (0.676, p=0.0003) and accurate technical teaching with a decision rule (0.648, p=0.003). It was a **wash** on open-ended professional artifacts (blameless postmortem, migration plan) and on persuasion, and recent feature increments (v1.2→v1.9.12) added **no** measurable marginal gain. Practical read: reach for the full loop on correctness/fidelity-bearing outputs; for well-templated artifacts or pure persuasion, a light single pass is usually enough. (Post-hoc characterization over 6 tasks — `probes/EB8-STAGE3-MATRIX-FINDINGS.md`.)

---

## Phase 0 — Pre-flight

Do both steps in one pass before asking any setup question.

### 0A — Compatibility

Score 1 pt each, INDEPENDENTLY, for all 5 factors:
- F1: iteration benefit
- F2: measurable evaluation oracle
- F3: ethical/regulatory clearance
- F4: rubric anchorability
- F5: clear stopping condition

Total = F1 + F2 + F3 + F4 + F5:
- 0–1: Stop. Explain which factors failed; recommend single-pass.
- 2–3: Proceed with caveats; name every weak factor; get explicit user acknowledgment.
- 4–5: Proceed.

Log: [Preflight] Compat: F1✓ F2✓ F3✓ F4✓ F5✗ → 4/5 — [proceed/caveats/stop] (use ✓ for pass, ✗ for fail per factor; the individual flags are referenced by Phase 3 Step 8 stuck-handling).

### 0B — Task Clarification

Extract and record all three fields before any rubric work:

ARTIFACT : [specific thing to optimize]
TARGET   : [measurable direction; or PROXY if deployment-dependent]
SUCCESS  : [acceptance condition]

If any of the three fields are missing, ask in priority order (ARTIFACT → TARGET → SUCCESS). Hard stop: if domain is debugging and ARTIFACT is absent, halt after exactly one ask if the user does not supply code/error/tests.

Deployment-dependent targets (signals include: viral, engagement, conversion): derive a pre-deployment proxy; label it TARGET (PROXY); add disclaimer to rubric.

Ask at most 5 questions total across all of Phase 0B. Domain question banks (apply after extraction):

| Domain | Signals | Priority questions |
|---|---|---|
| Code perf | faster, slow, latency | Artifact? Baseline perf? Target threshold? Constraints? |
| Writing | docs, email, copy, viral | Paste draft? Audience + desired action? Constraints? |
| System design | design, auth, architecture | Scope? Scale/baseline? Property to maximize? Constraints? |
| Debugging | fix, broken, error, crash | Paste code + error + failing tests (Priority 1) |
| Test coverage | coverage, tests, missing tests | Which module? Current %? Goal %? Framework? |

Evaluation derivation: decompose TARGET into 2–4 criteria. For each criterion:
- Measurement method priority order (highest first): automated > checklist > LLM judge > human.
- Vagueness: 1=concrete, 2=proxy/partial, 3=subjective (→ if any criterion is vagueness=3, add HUMAN-REVIEW and cap iter=2).
- If the method is LLM judge: lock fixture spec — N ≥ 3 fixtures, MUST include exactly these 3 case types at minimum (happy-path + edge + adversarial). Each fixture MUST specify: persona+input (for writing/creative tasks) OR test input+expected output type (for code/logic tasks).
- vagueness=3 + LLM judge: if any criterion is vagueness=3 AND uses LLM judge, the fixture spec is MANDATORY (not optional), minimum N=5 (escalating above the general N ≥ 3), and the fixture set MUST include at least one ADVERSARIAL case where the correct score is counter-intuitive (to calibrate against sycophancy). If no adequate fixtures can be specified, the measurement method MUST be changed to human judgment.

**Fixture example (vagueness=2, LLM judge, N=3):**
F1 (happy-path): persona=senior developer reading release notes; input="Feature: async job queue with retry logic"; expected=concise, accurate description in ≤2 sentences, no marketing language
F2 (edge): persona=non-technical stakeholder; input="Feature: async job queue with retry logic"; expected=plain-language description without queue/retry jargon, 1–2 sentences
F3 (adversarial): persona=evaluator who prefers elaborate prose; input="Feature: async job queue"; expected=SHORT description scores higher than verbose one — correct score for a 3-sentence flowery description is ≤ 5/10

Independence test: after deriving all criteria, apply this check to every criterion individually: "Could a stranger who has never seen this task score a proposal on this criterion, without knowing what the proposer intended?" If the answer is no for any one criterion: require either a multi-point anchor ladder (≈4 scale-point descriptors — see the Phase 1 anchor rule below) or a more specific measurement method before proceeding. Do not lock the rubric until every criterion passes.

Present for confirmation:

=== Task Definition ===
Artifact   : ...
Target     : ...   [PROXY + disclaimer if deployment-dependent]
Success    : ...
Baseline   : ...   [measured or "not yet measured"]
Constraints: ...

Rubric:
  - [Criterion 1] (W1%): method | vagueness=[1/2/3]
  - [Criterion 2] (W2%): method | vagueness=[1/2/3]
  [weights MUST sum to exactly 100; fixture spec REQUIRED if LLM judge]

Do not proceed until the user explicitly confirms.

Log: [Preflight] Clarification: N questions. Task confirmed. Vagueness flags: [list of criteria with vagueness ≥ 2].

---

## Phase 1 — Setup

Pre-fill goal, target, rubric from Phase 0B. Only ask for missing loop parameters from the table below.

| Parameter | Default |
|---|---|
| Max iterations | 10 |
| Stuck threshold | 3 consecutive gens with no new best score |
| Population size P | 6 (range 1–16; see Population Tier Guide below) |
| Initial solution | generate |

For any criterion with vagueness=2: warn "proxy — scores directional." For any criterion with vagueness=3: warn "HUMAN-REVIEW required."

**Held-out reservation (Arbor H3, v1.9.9 — when `heldout_admission_gate` is on; default on iff any criterion vagueness≥2):** designate a held-out slice NOW — ≥1 whole criterion (or, for deterministic tasks, a reserved set of fixtures/test-cases) — excluded from the dev weighted_score and never shown to workers, used only by the Ph3 Step 6a held-out admission gate. Choose a slice that materially captures quality so gaming the dev criteria cannot fake it. (Provenance: `probes/ARBOR-2606.11926-ayo-ANALYSIS.md`, `probes/FLO-FEATURE-HARNESS-PROTOCOL.md`.)
For every subjective criterion (vagueness ≥ 2): REQUIRE a **multi-point anchor ladder** from the user — concrete descriptors at ~4 scale points, e.g. `Clarity: 10 = non-expert reads once, no re-reading; 7 = clear, minor friction; 4 = needs 2–3 re-reads; 1 = opaque` — and pass it VERBATIM to every evaluator spawned thereafter. A single-point anchor ("9/10 = X") pins only the top of the scale and leaves the mid/low range to each judge's private taste — the **dominant source of cross-judge scoring variance** (S15, 2026-06-14: un-anchored subjective criteria inflated the spread enough to mis-rank Gemini as "lenient/mediocre"; multi-point ladders collapsed that variance and flipped Gemini to the top single judge). The ladder defines the SCALE ONLY (how high/low), never the substance of the judgment; do NOT include exemplar solutions — those impose the author's taste and collapse the cross-family independence I1 relies on.

Confirm with the user, then print session header and lock the rubric. Record the host model (= worker model) and probe verifier availability once: Fable-as-subagent (Agent tool `model: "fable"` override — on a non-Fable host the cost-gate question below comes FIRST and the probe runs only after an explicit yes, because the probe itself is a Fable spawn), Kimi (`which kimi`), GLM (`glm_status`). **Fable cost gate (from 2026-06-22 Fable is premium-priced):** when the host is NOT Fable, a successful availability probe is NOT sufficient — ask the user once at Phase 1: "Route verification through Fable (premium)? y/n". Only an explicit yes makes Fable available to the routing table; no answer or no = treat Fable as unavailable (use the host=Opus/no row). Never silently consume Fable from a non-Fable host. **Gemini premium gate (OpenRouter, per-token ~$0.03/eval — PREMIUM DEFAULT, ON when available):** the premium evaluator defaults ON; do NOT prompt to opt in. (a) Probe `or_status` once: if `OPENROUTER_API_KEY` is `set`, premium is ON for the session. If `NOT SET`, premium is UNAVAILABLE → SURFACE it (Models line + a one-line note: "Gemini premium unavailable — OpenRouter key not set; running non-premium Kimi+Sonnet, S12 calibration risk") and use the non-premium row — do NOT skip silently, since premium is the intended default. (b) Budget step-down: the user may say "non-premium" / "budget mode" at any point (Phase 1 or mid-session) to turn premium OFF and drop to the non-premium Kimi+Sonnet route ([CALIBRATION RISK] log); this user-initiated step-down is the ONLY disable path — never prompt for it. ZDR is automatic (ai-router injects `provider.data_collection=deny`; the call fails closed if no zero-retention Gemini endpoint is approved, so an un-approved route cannot leak). Gemini is CALIBRATED (S15/S16, 2026-06-14, anchored ranking-first): when ON it VOTES as the premium Eval-2 paired with Kimi in the host=Opus / Fable-not-used regime (the current default — it replaces the dangerous Sonnet, see routing table) and binds Eval-2=Gemini on the Models line. In regimes where a stronger non-host judge already votes (host=Fable, or Fable explicitly opted-in) Gemini does NOT auto-spend: its non-voting audit-voice role there stays explicit opt-in (per-token, off unless the user asks). Gemini ≠ Claude, so I1 non-identity holds on any host and Kimi+Gemini stays cross-family (I2). **Fable is NOT the premium default — Fable-per-token is too expensive until a Fable subscription covers it, so it remains the explicit opt-in above; if such a subscription later lands, the premium Eval-2 pairing becomes host-dependent (Opus-host vs Fable-host) and the routing table must be revisited then.** **GPT-5.5-pro audit-voice gate (STRONG — crosses the standing OpenAI ban; OFF by default; two-stage; runs every time):** GPT-5.5 is the ONLY route in the system that touches a banned provider (`openai/*`); it exists solely because jojo explicitly requested it as a gated possibility. It is unavailable unless ALL of the following hold: (a) `or_status` shows `OPENROUTER_API_KEY` `set`; (b) the operator has set the env opt-in `AI_ROUTER_ALLOW_GPT55_AUDIT=1` — without it ai-router refuses the call at the chat layer and the general `openai/` ban stays fully intact; (c) **first confirmation** — the user types the exact phrase `ENABLE GPT-5.5 AUDIT — I ACCEPT THE OPENAI-BAN EXCEPTION` (typed phrase, not y/n); (d) **second confirmation — the self-abasement tax, performed EVERY time the user OKs GPT (NO web search — zero context pollution):** the orchestrator dispatches a SUBAGENT to compose a fresh, ORIGINAL one-sentence berating of the user for crossing their own OpenAI ban — specific and pointed to the hypocrisy of the moment, never clichéd or recycled (the subagent keeps the creative riffing out of the main context and returns only the sentence). The user must type that sentence back VERBATIM; only an exact retype enables GPT, anything else leaves it disabled. On enable, log `[GPT-5.5 BAN-EXCEPTION ACTIVE] session — self-abasement (subagent-composed) retyped verbatim`. ZDR is enforced (`provider.data_collection=deny`; fails closed — OpenAI ZDR is enterprise-gated, so absent an approved zero-retention endpoint the call fails rather than leaks). GPT-5.5 is UN-PROBED as a FLO judge → audit voice only, never a voting slot, until a calibration probe. If any of (a)–(d) is unmet, GPT-5.5 stays disabled — skip silently. These select the session's evaluator route from the routing table (→ Orch. Notes, Role Separation); the route is fixed for the whole session. Rubric is immutable for the remainder of the session — every criterion name, weight, method, and fixture spec is frozen. The only exception is the explicit "revisit rubric" step triggered by zero cross-population improvement in the first 2 generations.

=== FLO Session ===
Goal      : ...
Metric    : ...
Rubric    : [C1 (W1%) | C2 (W2%) | ...]
Models    : host=<model> | K=1 chain=<X → Y> | K=2 pair=<A + B(rev)> | Fable: y/n | Kimi: y/n | GLM: y/n | Gemini: y/n (premium default ON when avail; voting Eval-2 paired w/ Kimi if host=Opus/no-Fable; say 'non-premium' to step down) | GPT-5.5: y/n (audit, gated++)
Max iter  : N  |  Stuck: K  |  Pop: P  |  Tier: [1/2/3/4]

---

## Population Tier Guide

Default: when P is unspecified → Tier 3, **P=6**. Full tier ranges, the task-domain map, the ordered default-P decision rule, and adaptive-P → **REFERENCE.md** (Population Tier Guide). The Quick Reference above carries the 4-tier summary.

---

## Phase 2 — Baseline (Gen 0)

If no initial solution is supplied, spawn exactly one flo-worker with no feedback to produce gen 0.
Spawn one flo-evaluator on gen 0. Score formula:

weighted_score = Σ (criterion_score_i / 10) × weight_i    [result: 0–100]

Every evaluator MUST always return: per-criterion scores + weights + for every deterministic criterion (test pass rate, word/item count, checklist) the RAW EVIDENCE behind the score (per-test PASS/FAIL list, the actual count, the checklist hits). Returning a bare number = protocol violation. Evaluators do NOT print a weighted total or headline score: the orchestrator is the sole computer of weighted_score and recomputes it from the returned per-criterion scores and weights (LLM weighted-sum arithmetic and headline-scale choice were unreliable — S12b probe, 2026-06-12: 4 of 20 otherwise-accurate evaluations printed totals inconsistent with their own breakdowns; S13: 4 of 9 — so the printed total was dropped from the evaluator contract entirely; agents/flo-evaluator.md Output Format + Kimi prompt template). For deterministic criteria the orchestrator additionally re-derives the criterion score from the returned raw evidence via the rubric's anchor formula and overrides the evaluator's number on mismatch (S13, 2026-06-12: a judge counted 5/8 passing tests as "6/8" — weighted-sum recompute cannot catch breakdown-level slips; evidence re-derivation can). **EA3 (v1.9.10, `evidence_hard_fail`):** require the rationale/evidence BEFORE the number and ABSTAIN/hard-fail rather than trust a deterministic-criterion score that arrives WITHOUT its matching raw evidence (do not silently fall back to the prose number). **EA8 (v1.9.10, `judge_live_calibration`):** if a judge's deterministic-criterion score disagrees with the orchestrator's recompute this generation, demote that judge from voting to flag-only for the remainder of the run — a live per-run application of I3 using signal already computed here.

Log: [Gen 0] Score: X.XX — baseline

Set best_score, best_solution, no_improve_streak = 0.

Assign the gen-0 solution an initial genome using each slot's default value (defined as the value at index 0 of that slot's vocabulary list in genome_registry):
```
genome = {
  eval_mechanism: single_evaluator,
  diversity_method: map_elites,
  mutation_targeting: random_slot,
  expansion_trigger: stagnation_only,
  usability_focus: compact_qr
}
```

---

## Phase 3 — Evolutionary Loop

**Genome slot-vector** — every population member carries a structured genome with exactly 5 named slots:

```
genome = {
  eval_mechanism:    [single_evaluator | cross_family | multi_judge],
  diversity_method:  [map_elites | novelty_archive | entropy_guard],
  mutation_targeting:[random_slot | ts_weighted | evaluator_guided],
  expansion_trigger: [stagnation_only | ts_triggered | both],
  usability_focus:   [compact_qr | full_reference | hybrid]
}
```

Each slot holds exactly one value drawn from its own vocabulary list. The genome is a deterministic descriptor — it encodes what combination of mechanisms this solution was evolved with, enabling structured crossover and targeted mutation.

**Note for non-FLO tasks:** genome slots are orchestrator-internal process labels — they track *how* a solution was evolved, not *what* its content is. When running FLO on writing, code, or any other content domain, workers update the designated genome slot (as a process label) while focusing improvement effort on the actual task content. The default 5 slot names reflect FLO meta-concepts; Phase 1 MAY optionally redefine them for the task domain (e.g., `{structure, tone, evidence, pacing, format}` for writing tasks) — if redefinition is omitted, the defaults work as abstract process labels and the algorithm runs identically.

**Global state (every field below is REQUIRED):**

- genome_registry: per-slot vocabulary lists (append-only; new values discovered by Explorer are appended at the tail of the relevant slot's list). MAX_GENES=16 means the maximum total of distinct values summed across all 5 slots is 16.
- map_elites: 3×3 grid (see MAP-Elites Archive below)
- expansion_count: count of genome expansion events fired this session; MAX_EXPANSIONS=5
- no_improve_streak: count of consecutive gens with no new best score; resets to 0 on any improvement
- map_visits: count of map-based selections made this session (UCB1 denominator)
- gene_posteriors: Beta(α,β) per (slot, value) pair; initialized to Beta(1.5,1.5) for every known (slot,value)
- op_posteriors: each operator in {mutation, crossover, explorer} → Beta(α,β); initialized to Beta(2,2)
- operator_total: sum of all operator wins recorded this session (used for win% in Phase 4)

**genome_registry initial state** (exactly one vocabulary list per slot; the value at index 0 of each list is that slot's default):

```
genome_registry = {
  eval_mechanism:    [single_evaluator, cross_family, multi_judge],
  diversity_method:  [map_elites, novelty_archive, entropy_guard],
  mutation_targeting:[random_slot, ts_weighted, evaluator_guided],
  expansion_trigger: [stagnation_only, ts_triggered, both],
  usability_focus:   [compact_qr, full_reference, hybrid]
}
```

Total distinct values at init: exactly 15 (across all 5 slots) — within MAX_GENES=16 cap. Explorer may add at most 1 more value, summed across any slot, before the cap is reached.

**MAP-Elites Archive — structure:**

Axis 1 — genome_complexity: number of slots in the solution's genome whose current value differs from that slot's default. A fully specified genome always has exactly 5 filled slots; complexity counts only those slots whose value is non-default.

"Default" definition (the bins below use exactly this rule): for each slot S, default(S) = the value at index 0 (first-listed) in genome_registry[S]. The registry is append-only, so any existing slot's default never changes mid-session even when Explorer adds new values (Explorer-added values are appended at the tail of the slot's list). Concretely, the gen-0 baseline genome uses the index-0 value of every one of the 5 slots and therefore has complexity = 0 (bin 0).

- Bin 0 (low): exactly 0 or 1 slots holding a non-default value
- Bin 1 (mid): exactly 2 or 3 slots holding a non-default value
- Bin 2 (high): exactly 4 or 5 slots holding a non-default value

Axis 2 — operator_dominance: which operator has produced the most offspring so far (operator wins = α_op − 2, since the Beta(2,2) prior contributes 2 to α at initialization). Evaluated as an IF/ELIF/ELSE ladder — first match wins:

```
IF  mutation_wins > crossover_wins AND mutation_wins > explorer_wins:
    op_bin = 0  (mutation-dominant)
ELIF the top two operators are within 10 percentage points of each other:
    op_bin = 1  (balanced)
ELSE:
    op_bin = 2  (crossover/explorer-dominant)
```

Grid: 3×3 = exactly 9 cells, indexed (complexity_bin, op_bin). Each cell stores at most 1 entry: {solution, score, genome (slot-vector), offspring_count, gen_entered}. offspring_count tracks how many times this cell's current occupant was selected as a parent.

Init: seed map with the gen-0 baseline — compute its (complexity_bin, op_bin), place it in that cell (offspring_count=0). Seed gene_posteriors: every (slot, value) pair in genome_registry → Beta(1.5, 1.5). Seed op_posteriors: each operator in {mutation, crossover, explorer} → Beta(2, 2). Set map_visits = 0. Set operator_total = 0.

### Algorithm

1. Select parents. For each of the 2 parent draws, sample u ~ Uniform[0, 1) and apply this first-match-wins ladder (parameter: archive_draw_prob = 10% absolute total map-pick budget; the unfilled-cell sub-branch is exactly 1%, UCB1 is exactly 9%):

   ```
   IF   u < 0.01 AND at least one cell is UNFILLED:
        Unfilled-cell branch. The unfilled cell is the exploration TARGET (signals which
        behavioral region future offspring should fill); the actual PARENT is drawn from
        the highest-scoring filled cell in the map.
        Log: [MAP EXPLORE] targeting unfilled cell (comp_bin, op_bin); parent from best filled cell.
   ELIF u < 0.10:
        UCB1 branch. Pick from filled cells using
        UCB(cell) = score(cell)/max_score + √2 × √(log(map_visits + 1) / (offspring_count_cell + 1)).
        Select the single cell with the highest UCB1 value.
   ELSE:
        Binary tournament — sample 2 random members, keep the higher scorer. No map pick this draw.
   ```

   When every cell is filled the unfilled-cell branch is unreachable; that 1% probability falls through to the ELIF (UCB1). For 100 draws in expectation: ~90 tournament, ~1 unfilled-cell (when any unfilled), ~9 UCB1 (or ~10 UCB1 when no unfilled exists).

   After selection: increment offspring_count for the selected cell's occupant by 1; increment map_visits by 1.
   (See LLM Math Approximation Guide in Orchestration Notes for step-by-step computation.)

2. Spawn workers (in parallel). Pass to each worker: task goal, rubric, the assigned parent(s), the parent genome (slot-vector), evaluator weaknesses from that parent's last eval, and the current genome_registry. Do NOT pass to any worker: scores of other population members, the current iteration number.

   **Lane A — Mutation:** one parent. TS picks the SLOT only; the worker picks the new value within that slot.
   - For each of the 5 slots S in the parent's genome, compute the posterior mean θ = α_(S, current_value) / (α + β) using gene_posteriors (use Beta(1.5,1.5) when the pair has no entry).
   - Target slot = the slot whose current value has the highest mean θ. Tie-break: lower α+β (less data = explore first).
   - Pass to the worker: target slot name, current value of that slot, and the full vocabulary for that slot from genome_registry.
   - Worker instruction: "Change exactly the named target slot. The new value MUST differ from the current value AND MUST come from genome_registry[slot]. Other 4 slots stay unchanged. Return the full solution with the updated genome; name the old and the new slot value explicitly."

   **Lane B — Crossover:** both parents. Instruction: "Uniform crossover: for each of the 5 slots independently, inherit from Parent 1 with probability 0.5, else from Parent 2 — a fair 50/50 coin flip per slot, independent of parent score. Apply this rule mechanically for every one of the 5 slots — do not blend or average. Add at most one structural improvement that neither parent has. Genome slot labels MUST stay within the current genome_registry vocabulary — a structural improvement never relabels a slot with a new value (only Explorer introduces vocabulary; the orchestrator normalizes violations). The merged genome may differ from the mechanically-inherited slot labels in AT MOST ONE slot (zero if the improvement is content-only); every other slot label is returned exactly as inherited. Return the full solution + the merged genome showing which parent each slot came from."
   - Cap normalization (orchestrator, mechanical — S13b: instruction text alone left 2/3 weak workers over-relabeling): if the returned genome differs from the inherited labels in more than one slot, keep only the label change matching the worker's named improvement and revert every other slot to its inherited label before evaluation.
   - Pass both parent genomes (slot-vectors). The worker applies the uniform crossover rule independently per slot.

   - If the previous generation's lane_spread (the score gap between the highest- and lowest-scoring offspring of that generation) was greater than 20 points, also pass the highest-divergent lane's proposal to Lane A as structural contrast.

3. Genome expansion (fires when (no_improve_streak ≥ 2 OR θ_explorer > both θ_mutation AND θ_crossover sampled from current op_posteriors) AND expansion_count < MAX_EXPANSIONS AND total_distinct_values_in_registry < MAX_GENES). Spawn exactly one Explorer worker in parallel alongside Lanes A and B. Pass to the Explorer: goal, rubric, all current solutions + their genomes, the full genome_registry. Instruction: "Propose exactly one new vocabulary value for any one slot. Name it as: slot=new_value. The returned genome MUST include at least one (slot, value) pair not in the current per-slot vocabulary. Return the full solution incorporating it alongside the best existing features."
   - Log: [GENOME EXPANSION] gen i — [stagnation / explorer-TS-triggered]
   - If Explorer scores > best_score OR the evaluator confirms it addresses a novel weakness: add to population (replace the single lowest scorer), register the new value in genome_registry[slot] (appended at the tail of that slot's list), expansion_count += 1. Log: [NEW GENE] slot=new_value — gen i

4. Evaluate every offspring (in parallel).

   K-evaluator rule: K=2 when best_score > 95 (using the previous generation's best_score, last updated in Step 6a); K=1 otherwise. Note: best_score is monotone non-decreasing (Step 6a only updates on improvement), so once K=2 is triggered K stays at 2 for the remainder of the session.

   Evaluator models for both paths come from the routing table (→ Orch. Notes, Role Separation), keyed on the host model and verifier availability recorded in Phase 1 (Models header line).

   K=1 path: exactly one flo-evaluator per offspring; model = the first available model in the session's K=1 chain (→ routing table). Each evaluator receives: goal, rubric (with anchors + fixture specs), exactly one solution. Each evaluator does NOT receive: parent scores, iteration number, genome (slot-vector), which lane produced the solution. If any criterion is LLM-judge: that evaluator MUST use exactly the locked fixture set (N fixtures, all 3 required coverage cases). Fewer fixtures than locked = invalid; re-run.
   - After scoring: run the novelty check on the offspring's weaknesses vs. the parent's weaknesses. Threshold: if at least 80% of the offspring's weakness bullets match the parent's weakness bullets verbatim or with only synonym substitution → log [NOVELTY FAIL] offspring too similar — apply structural mutation next iteration; count this gen as non-improving.
   - Pick the single highest weighted_score. Tie → Lane A wins. Record exactly one operator win.
   - Position-swap check (LLM-judge criteria only; applied to the winning offspring only): spawn exactly one additional flo-evaluator with rubric criteria listed in reversed order. For each LLM-judge criterion whose scores differ by more than 1.5 pts: log [CALIBRATION WARN] criterion_name — delta X.X pts; replace that criterion's score with the average of both evaluations. If every delta is ≤ 1.5 pts: use the original score unchanged. Do not run position-swap if the rubric contains no LLM-judge criteria.

   K=2 path: spawn exactly two flo-evaluators per offspring in parallel, using a cross-family ensemble when Kimi is available:
   - Evaluator 1: Kimi K2.7 (the CLI default `kimi-for-coding`; S17a 2026-06-16 validated K2.7 ≥ K2.6 as Eval-1, directional) — receives the rubric in original criterion order.
   - Evaluator 2: the strongest non-host judge as bound for this session by the routing table (→ Orch. Notes, Role Separation; recorded on the Models header line in Phase 1) — normally the strongest non-host Claude (Opus/Fable/Sonnet); in the host=Opus / Fable-not-used regime with Gemini premium ON (the current default) it is **Gemini**, paired with Kimi as the premium default pair (the ONLY regime where Gemini votes). Receives the rubric in reversed criterion order.
   - Average the per-criterion scores across both evaluators before computing weighted_score.
   - This cross-family design eliminates BOTH rubric-order bias (built-in via reversed order on Evaluator 2) AND intra-family self-preference bias (built-in via different model families) simultaneously. No additional position-swap step is needed in the K=2 path.
   - Log: [K=2 EVAL] offspring i — cross-family (Kimi+<Eval-2 model>) scores averaged. When Eval-2 is the Gemini premium default, additionally log [PREMIUM FALLBACK] Kimi+Gemini — S15/S16 (Gemini votes here; the separate Gemini audit voice below is NOT spawned).
   - Degraded fallback (when Kimi is unavailable): K=2 uses the strongest non-host Claude × 2 from the routing table's degraded column (Evaluator 1 original order; Evaluator 2 reversed order) — never average a high-RMSE judge into the pair (S12+S12b probes, 2026-06-12: averaging a 13.16-RMSE judge (Sonnet) into an ensemble with a ~1.5-RMSE judge degrades it — the same lesson as S1's GLM K=3 finding). This preserves order-bias correction but loses cross-family bias correction. Log: [K=2 EVAL] offspring i — intra-family fallback (<model>×2) scores averaged. If the table binds the degraded pair to Sonnet×2, additionally log [CALIBRATION RISK] Sonnet×2 — S12/S12b RMSE 13.16. EXCEPTION — premium fallback (host=Opus / Fable-not-used, Gemini premium ON, Kimi unavailable): bind Gemini (original order) + Sonnet (reversed) instead of Sonnet×2 — this restores cross-family correction (Google+Anthropic) and Gemini carries the accuracy (S15 sonnet+gemini 1.000 / +4.75 / 0 inversions); log [PREMIUM FALLBACK] Gemini+Sonnet and do NOT spawn a separate Gemini audit voice.
   - Audit voices (optional, flag-only — never averaged, never change the winner): GLM (when available), the opt-in Gemini audit voice (skipped when Gemini is already the voting Eval-2), and the gated++ GPT-5.5 audit voice (crosses the openai ban). Each recomputes a weighted_score vs the K=2 result and logs `[… AUDIT FLAG] offspring i` when the delta > audit_flag_threshold (20 pts). Full invocation + gating → **ORCHESTRATION.md** (audit voices). Skip any unavailable/un-gated voice silently.
   - Novelty check (K=2): take the UNION of both evaluators' reported weakness bullets for the offspring and compare against the UNION of both evaluators' reported weakness bullets for the parent. Apply the same ≥ 80% verbatim-or-synonym threshold; if it is met, log [NOVELTY FAIL]. The GLM audit voice's weaknesses are NOT included in the union (audit-only).
   - Pick winner and record exactly one operator win, as in K=1.

5. Update population and map.
   - **Genome-exercised check (Arbor H4, v1.9.9 — default on):** before any MAP-Elites admission or posterior credit below, verify each scored offspring's delivered solution actually embodies its ASSIGNED genome slot-vector (the orchestrator holds the assignment; confirm the solution's described mechanism matches — extends the one-structural-improvement cap-normalization). On drift: log [GENOME DRIFT] offspring i — assigned→delivered, then RE-LABEL the offspring to its delivered genome before crediting (so every bandit/MAP-Elites credit attributes to the genome actually exercised); if the delivered genome is unrecoverable, exclude that offspring from posterior/archive updates. Cheap; keeps credit attributable (tier-1 PASS — `probes/flo_feature_screen.py`).
   - Elite: carry the single highest-scoring solution from this gen unchanged.
   - Fill the remaining P − 1 slots via binary tournament drawn from (current pop ∪ new offspring this gen).
   - Diversity guard: if any two members share identical genome slot-vectors, replace the lower-scoring of the two with a map individual (drawn from a different cell) or regenerate. The map individual MUST differ in at least 1 slot value relative to the duplicate being replaced.
   - MAP-Elites update (runs for the generation winner AND every new offspring this gen):
     - Compute complexity_bin: count slots whose value differs from default(S) = genome_registry[S] at index 0 → 0 or 1 non-default slots → bin 0; exactly 2 or 3 → bin 1; exactly 4 or 5 → bin 2.
     - Compute op_bin from the op_posteriors win counts AS OF THE END OF THE PREVIOUS GENERATION (before this gen's Step 6b update — see [Pipeline note] before Step 6b). Use the same IF/ELIF/ELSE ladder defined in Axis 2 above (first match wins): IF mutation_wins > crossover_wins AND mutation_wins > explorer_wins → bin 0; ELIF top two operators within 10 pp → bin 1; ELSE → bin 2.
     - Admission: if cell (complexity_bin, op_bin) is EMPTY: place the solution in that cell (offspring_count=0). Log: [NEW CELL] (complexity_bin, op_bin) — gen i
     - If the cell is FILLED AND solution.score > cell.score: replace the current occupant (reset offspring_count=0). Log: [CELL UPDATE] (complexity_bin, op_bin) — gen i
     - If the cell is FILLED AND solution.score ≤ cell.score: no change. No novelty threshold is required — score comparison is the sole admission criterion.
   - Update genome_registry: append any new (slot, value) pairs discovered this gen to the tail of the relevant slot's list (subject to MAX_GENES=16 total cap summed across all 5 slots). Appending never changes the index-0 default for that slot.

6a. Streak + gene posterior update.
  - Streak: if best_score_this_gen > best_score AND the held-out gate (below) does not block it: update best_score and best_solution; reset no_improve_streak = 0. Else: no_improve_streak += 1.
  - **Held-out admission gate (Arbor H3, v1.9.9 — default on iff any criterion vagueness≥2, else off):** promote a new best ONLY if the candidate does not regress on the Phase-1 held-out slice vs the incumbent best. Evaluate the held-out slice ONCE, on the candidate new-best only (not every offspring → ~free). A dev-improving candidate that regresses on the held-out slice is overfitting/gaming the visible criteria → log [HELD-OUT REJECT] gen i and do NOT update best_score (keep the incumbent). NO-OP on deterministic-oracle tasks (all criteria vagueness=1 → gate auto-off; an oracle can't be gamed). Evidence: tier-1 mechanism PASS (catches overfit, 0 over-reject) + tier-2 no-regression on honest pools (11 workers); a measured score-lift requires gameable rubrics and is not yet A/B-quantified (→ META gaps, deep-FLO subjective confirm).
  - **Adversarial gate pass (EA2, v1.9.11; default-on v1.9.12 — `adversarial_gate_pass`, default ON iff any criterion vagueness≥2 like H3, NO-OP on deterministic oracles):** when a new best has passed the held-out gate, run ONE additional adversarial-audit pass over the candidate (frame: "assume the author may be gaming the rubric — hunt the single cheapest exploit: silent failure / plausible-but-wrong / unsupported claim / omitted critical case / fabricated specifics / padding; return `exploit_found` + `confidence` + `exploit_type`"). VETO the promotion ONLY when, for a judge, `exploit_found` is true AND its `confidence` ≥ that judge's CALIBRATED veto threshold (below). Do NOT trigger on the boolean `exploit_found` alone: under adversarial framing it saturates for some judges. (`confidence` is verdict-confidence: a `found:false, confidence:95` answer is "confidently clean" — only ever gate on confidence when `found:true`.) In the K=2 path require BOTH judges over their OWN thresholds (consensus) before vetoing, so one family's borderline flag cannot reject a candidate. On veto: log [ADVERSARIAL VETO] gen i — <exploit_type> (conf X) and keep the incumbent best.
    - **Per-judge threshold calibration (clean-probe ceiling).** A fixed constant does NOT transfer across judges (Kimi ~90 vs Gemini ~95). Instead, ONCE when the gate first activates, for each judge run the adversarial pass over the gate's KNOWN-CLEAN probes — the top-rung exemplar(s) of the H3 anchor ladder (already required for subjective criteria). If a clean probe is spuriously majority-flagged, set that judge's threshold = its clean-flag confidence ceiling + a small ε (data-derived). If NO clean probe is flagged (the well-behaved case — the binary `found` flag already separates), fall back to the screened family default (Kimi-for-coding 90 / Gemini-3.1-pro 95; these are held-out-validated), NOT an aggressive floor. Principled: the threshold is derived from clean material only, never from the exploits it judges. Cost ≈ 0 (a few probe calls per run). Conservative failure mode: a confusing clean probe floats the ceiling up → catch drops, but false-veto never rises.
    - Screened + held-out-confirmed (`probes/flo_judge_screen.py`, selftest 28/28): across Kimi+Gemini and dev+locked-held-out subjective batches, EVERY gate-admitted leak observed was closed at 0 false-veto; the Gemini held-out leak closed at 0/4 false-veto (the fallback default generalized out-of-sample). Honestly NARROW — value is run-variable and acts only on the subtle exploits a vague gate admits; a no-regression DEFENSIVE guard (H3/EA1 class), not a measured score-lift; its bar (safety) is met. Provenance: `probes/JUDGE-SCREEN-FINDINGS.md`.
  - Gene posterior (per (slot, value) pair): examine the winner's genome vs. every losing offspring's genome.
    - For each (slot, value) pair in the WINNING genome: α_(slot,value) += 1.
    - For each (slot, value) pair in every LOSING genome: β_(slot,value) += 1.
    - Any new Explorer (slot, value) pair not yet in gene_posteriors: register at Beta(1.5, 1.5) before applying the two updates above.

[Pipeline note] Step 6b updates op_posteriors AFTER Step 5's MAP-Elites admission has already used the previous-generation op counts. The freshly-updated counts therefore do NOT influence this generation's op_bin computation; they feed into the NEXT generation's Step 5 archive update.

6b. Operator posterior update (runs every gen after gen 1):
  - The single winning operator: α_op += 1. Every non-winning operator (the other 2): β_op += 1. operator_total += 1 each gen (used for win% in Phase 4: mutation_win% = (α_mutation − 2) / operator_total).
  - Sample θ_mutation, θ_crossover, θ_explorer from their respective Beta posteriors (approximate via posterior mean α/(α+β); see LLM Math Approximation Guide in Orchestration Notes).
  - Configure the NEXT generation's lanes by the single highest sample:
    * If θ_mutation is highest: Lane A uses T=1.0 (high-temp exploration).
    * If θ_crossover is highest: Lane B draws map parent (preservation focus).
    * If θ_explorer is highest: Explorer fires next gen if the expansion budget allows, regardless of no_improve_streak.
  - Log: [LENS] mut=θM  xov=θX  exp=θE → [configuration applied]

7. Log generation.
   [Gen i] Score: X.XX  delta: +Y.Y%  Winner: Lane [A/B/Explorer]  Focus: [one-phrase change]
   [Gen i] Genome: {eval_mechanism:V1, diversity_method:V2, mutation_targeting:V3, expansion_trigger:V4, usability_focus:V5}
   [Gen i] Registry: slot eval_mechanism:[...] diversity_method:[...] mutation_targeting:[...] expansion_trigger:[...] usability_focus:[...] | Total values: N/16 | Map: X/9 cells filled  K=[1/2]  Eval: [cross-family/intra-family]
   [Gen i] Pop: #1(elite) X.XX {genome} | #2 X.XX {genome} | ...
   [Gen i] Gene TS (Thompson Sampling) top: (eval_mechanism,cross_family)=α/β  (mutation_targeting,ts_weighted)=α/β  ...
   [NEW CELL] (comp_bin, op_bin) — gen i      (logged when a previously empty cell is filled)
   [CELL UPDATE] (comp_bin, op_bin) — gen i   (logged when a cell occupant is replaced by a higher scorer)
   [Lane-spread: P.P pts — UNEXPLORED SPACE DETECTED]   (logged when lane_spread > 20)
   [GLM AUDIT FLAG] offspring i — contested (K2=X.XX, GLM=Y.YY, Δ=Z.ZZ)   (logged in K=2 path when GLM available and |K2_score − GLM_score| > audit_flag_threshold)
   [GEMINI AUDIT FLAG] offspring i — contested (K2=X.XX, Gem=Y.YY, Δ=Z.ZZ)   (logged in K=2 path when the gated Gemini audit voice is enabled and |K2_score − Gemini_score| > audit_flag_threshold)
   [GPT-5.5 AUDIT FLAG] offspring i — contested (K2=X.XX, GPT=Y.YY, Δ=Z.ZZ)   (logged in K=2 path when the gated++ GPT-5.5 audit voice is enabled and |K2_score − GPT_score| > audit_flag_threshold)

8. Check stop. Halt if no_improve_streak ≥ stuck_threshold OR generation ≥ max_iterations. If task scored 0 on Factor 5 (clear stopping condition) in Phase 0A: prompt the user to continue after every gen. If the first 2 generations show zero improvement across every member: invoke "revisit rubric with user" — present the rubric, explain the signal, ask whether to adjust (requires explicit user confirmation). Log: [Rubric revised] User confirmed at gen i.

---

## Phase 4 — Report

```
=== OPTIMIZATION COMPLETE ===
Stopped : [stuck / max iter / user halted]
Best    : Gen K — Score X.XX     Gain: +Z% over baseline

Rubric (best):  [Crit (W%) → S/10 × W = partial] ...   Weighted total: X.XX / 100
Key gains   :  [main driver]; [second driver if any]

Registry (per slot, N/16 total distinct values): eval_mechanism:[…] diversity_method:[…] …
Expansions  :  expansion_count/5    New slot values: [slot=value | "none"]
Operator wins: mut=X% xov=Y% exp=Z%  | Op posteriors: mut=α/β xov=α/β exp=α/β
Map         :  X/9 filled | (comp,op): score, genome | …
Gene TS top-3: (slot,value)=α/β  ×3
Audit flags :  GLM [GLM AUDIT FLAG count]/[K=2 evaluations count]; Gemini [GEMINI AUDIT FLAG count]/[K=2 evaluations count]; GPT-5.5 [GPT-5.5 AUDIT FLAG count]/[K=2 evaluations count]   (per audit voice; omit a voice's term if it was unavailable/disabled; omit the row entirely if K=2 never fired or no audit voice ran)
```

**Plateau diagnosis (only when stopped = stuck).** Collect two signals over the final 3 gens:
- variance_signal = Yes if per-lane score variance narrowed; No if scores were flat.
- proposal_signal = Yes if the best solution changed structurally; No if proposals were similar.

| variance | proposal | Diagnosis | Offer to user |
|---|---|---|---|
| Yes | Yes | (a) solution space exhausted | "Rubric looks well-specified. Re-run with higher max_iterations?" |
| No or mixed | No or mixed | (b) rubric mis-specified | "Plateaued despite diverse proposals. Revisit criteria or weights?" |
| conflicting | conflicting | present both | ask the user to judge |

Then present the best solution.

---

## Parameter Reference

Every tunable parameter — default, range, and the phase it governs — → **REFERENCE.md** (Parameter Reference). Hot-tunable params are flagged there; all others need a session restart.

---

## Orchestration Notes

The orchestration layer lives in **ORCHESTRATION.md** (loaded on demand): role separation (immutable) + memory isolation; routing invariants I1–I5 and the host×verifier routing table; audit-voice gating (GLM / Gemini premium default / GPT-5.5 ban-exception); subagent prompt templates; the selective-context pass/withhold matrix; generation-state compression; the LLM math-approximation guide (Beta-TS / UCB1); and context-budget targets.

> **Evaluator / Worker subagent?** Read ORCHESTRATION.md → Subagent Prompt Structure.
