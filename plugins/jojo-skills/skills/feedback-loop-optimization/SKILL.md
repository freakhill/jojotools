---
name: feedback-loop-optimization
description: This skill should be used when the user wants to "optimize a task iteratively", "run a feedback loop on a project", "improve a solution through iterations", "run FLO on this", "set up an optimization loop", "evaluate and improve my solution", or needs to systematically improve output quality through repeated worker/evaluator cycles with anti-sycophancy separation.
version: 1.9.12
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
| K=2 path | Eval-1 Kimi K2.7 (original criterion order) + Eval-2 strongest non-host judge (reversed criterion order) — Gemini by default in the host=Opus/Fable-not-used regime (the current default — premium Eval-2 paired with Kimi); a Claude (Opus/Fable) when that host/Fable applies; Sonnet only on the non-premium budget step-down. Cross-family when Kimi available; intra-family strongest-non-host ×2 fallback when Kimi unavailable (→ Orch. Notes routing table) |
| K=3 audit voice (GLM) | Optional: when GLM available during K=2, spawn glm-5.1 in parallel as a third evaluator; score NOT averaged in; flag emitted when \|K=2 − GLM\| > 20 pts (→ Ph3.4) |
| Gemini (premium, calibrated) | **Premium default — ON when `or_status` `set`** (no opt-in prompt); the user steps DOWN to non-premium only when budget-constrained ("non-premium"/"budget mode"). Invoke gemini-3.1-pro via `or_ask` (per-token ~$0.03/eval, ZDR-enforced). Dual role (calibrated S15/S16): in the host=Opus/Fable-not-used regime (the current default) it is the VOTING premium Eval-2 paired with Kimi (replaces the dangerous Sonnet) — this auto-activates. Its non-voting audit-voice role (regimes where a stronger non-host judge already votes — host=Fable, or Fable opted-in) stays explicit opt-in: per-token money is never spent on a non-voting audit by default (→ Ph1 gate, Ph3.4, routing table) |
| K=3 audit voice (GPT-5.5, gated++) | Optional + OFF by default + CROSSES THE OPENAI BAN: only via the STRONG two-stage Phase 1 gate (env opt-in + typed phrase + type-back self-abasement re-confirm). Invoke openai/gpt-5.5-pro via `or_ask` as a non-voting audit voice (per-token, ZDR fails-closed); score NOT averaged in; flag when \|K=2 − GPT\| > 20 pts; audit-only until a calibration probe (→ Ph1 gate, Ph3.4) |
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

> **Measured scope — when is the full loop worth its cost?** A blind, 3-judge-family forced-ranking study (this full protocol vs a ~210-line minimal baseline; 6 diverse tasks × n=6 reps; 648 cross-version decisions) found the protocol buys **modest but real** quality overall (win-rate **0.548, p=0.017**), **concentrated in fidelity / teaching-correctness tasks**: faithful compression that must preserve every fact (0.676, p=0.0003) and accurate technical teaching with a decision rule (0.648, p=0.003). It was a **wash** on open-ended professional artifacts (blameless postmortem, migration plan) and on persuasion, and recent feature increments added **no** measurable marginal gain. Practical read: reach for the full loop on correctness/fidelity-bearing outputs; for well-templated artifacts or pure persuasion, a light single pass is usually enough.

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

## Population Tier Guide (Reference)

*Skip to Phase 2 if P is already chosen.*

Choose P before confirming the session header. When the user has not specified P, apply the Default rule at the bottom of this section.

| Tier | P range | When to use | Key rationale |
|---|---|---|---|
| 1 | 1 | Budget-critical; deterministic oracles; single-direction solution space | No diversity benefit; population only adds eval cost |
| 2 | 2–3 | Scoped writing; binary creative direction; moderate solution space | Tournament + crossover start producing novel combinations |
| 3 | 4–6 | Most production tasks; multiple orthogonal dimensions; partially subjective criteria | Research-validated sweet spot above 500-eval threshold; P=6 default |
| 4 | 8–16 | High-stakes, high-subjectivity, huge solution space; multi-session campaigns | Justifies high eval cost; P≥12 only for >20-gen campaigns |

Diminishing returns begin at P ≥ 7 for most task types. P=12 costs ~25–30 evaluations per generation.

### Task-domain summary table

| Task type | Tier | P | Key reason |
|---|---|---|---|
| Creative writing (general) | 3 | 4–6 | Wide solution space; moderate subjectivity |
| Documentary writing | 2–3 | 3–5 | Structured but stylistic |
| Video script | 2 | 2–3 | Short + clear audience = binary direction |
| Embedded programming | 1–2 | 1–3 | Hard constraints; tests eliminate bad solutions fast |
| Frontend programming | 2 | 2–3 | Functional correctness deterministic |
| Backend programming | 1–2 | 1–3 | Tests + benchmarks dominate |
| Fullstack programming | 2 | 3 | Cross-layer tradeoffs justify upper tier 2 |
| Research compilation | 3 | 4–5 | Coverage and synthesis quality benefit from diversity |
| Advanced research | 3–4 | 5–8 | Hypothesis diversity; higher end for large hypothesis space |
| Law interpretation | 4 | 6–8 | High-stakes, irreversible; nuance requires broad exploration |
| Woodworking | 1–2 | 1–3 | Structural constraints deterministic |
| Design | 3 | 4–6 | Subjective but bounded by brief |
| Webdesign | 3 | 4–5 | Functional + aesthetic split |
| CAD | 1–2 | 1–3 | Hard geometric/tolerance constraints; binary satisfaction |
| Security architecture | 4 | 8–12 | Multi-dimension, high-consequence |
| Competitive publishing | 4 | 8–16 | Long campaign; archival reuse justifies cost |

### Default recommendation

When the user has not specified P: start at Tier 3, P=6.

Decision rule (apply in this exact order; first matching rule wins):
- If every criterion is vagueness=1 AND domain maps to Tier 1 or Tier 2 → reduce to P in [1, 3].
- If task is Tier 3 AND has at most 2 evaluation dimensions → P=4 acceptable (cost reduction).
- If any single criterion is vagueness=3 OR domain maps to Tier 4 → upgrade to P in [6, 8].
- If task has more than 4 competing evaluation dimensions OR extremely high stakes → upgrade to Tier 4.

### Adaptive-P (optional, off by default)

Start at the upper end of the chosen tier (exploration), then reduce P by 1 after gen 3 once map_filled_cells ≥ 6 (shift to exploitation). Both conditions required. Enable only when the user explicitly requests adaptive-P at session start.

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
   - GLM audit voice (optional, K=3 audit-flag pattern): when z.ai GLM is available, spawn exactly one additional flo-evaluator using glm-5.1 in parallel with the K=2 pair, rubric in original criterion order. The GLM score is NOT averaged into the K=2 result and does NOT change the winner. Compute audit_delta = |K=2_weighted_score − GLM_weighted_score|. If audit_delta > audit_flag_threshold (default 20 pts): log [GLM AUDIT FLAG] offspring i — contested (K2=X.XX, GLM=Y.YY, Δ=Z.ZZ). The flag surfaces the case as evaluator-contested for downstream attention (Phase 4 report; optional human review) but never alters scoring or selection. Rationale: empirical probe (S1 fixture, 2026-05-31) showed GLM as the least-accurate single voter (~3× truth-RMSE of Kimi/Sonnet, anchors on stated values) but high signal-value as a disagreement detector — flagged the adversarial case correctly, no false alarm on the honest case. If GLM is unavailable, skip the audit voice silently.
   - Gemini audit voice (optional, OPT-IN — NOT covered by the premium default; K=3 audit-flag pattern): the premium default activates Gemini's VOTING role only; a non-voting audit voice spends per-token money for a flag, so it does NOT auto-activate. Spawn it only when the user has explicitly opted into the Gemini audit voice AND `or_status` shows the key `set` AND Gemini is NOT already the voting Eval-2 — i.e. NOT the premium-default regime, where Gemini is a pair member and cannot also audit itself (skip this voice entirely there). Invoke gemini-3.1-pro for one audit evaluation via the ai-router MCP tool `or_ask(model="google/gemini-3.1-pro-preview", prompt=<the evaluator prompt>, max_tokens=2048)` — rubric in original criterion order, same prompt contract as a flo-evaluator (per-criterion scores + evidence, no total). This is an orchestrator-side MCP call, NOT a flo-evaluator subagent (subagents carry no MCP tools); the call is stateless and ZDR-enforced (`provider.data_collection=deny`, fails closed). The Gemini score is NOT averaged into the K=2 result and does NOT change the winner. Compute gemini_audit_delta = |K=2_weighted_score − Gemini_weighted_score| (orchestrator recomputes Gemini's weighted_score from its per-criterion breakdown, same as any evaluator). If gemini_audit_delta > audit_flag_threshold (default 20 pts): log [GEMINI AUDIT FLAG] offspring i — contested (K2=X.XX, Gem=Y.YY, Δ=Z.ZZ). Rationale: Gemini 3.1 Pro is calibrated (S15/S16, anchored ranking-first) and a strong disagreement detector; in THIS regime it is audit-only (flag, never averaged) because a stronger non-host judge (Opus/Fable/Kimi) already fills the K=2 pair — by I3 Gemini votes ONLY in the premium-fallback regime (host=Opus / Fable-declined), never alongside a stronger judge (it leans lenient on subjective criteria + is per-token). Gemini and GLM audit voices coexist when both are enabled; each flags independently and neither enters any average. If the audit voice was not explicitly opted into, skip silently.
   - GPT-5.5-pro audit voice (optional, gated++, OFF by default, CROSSES THE OPENAI BAN): only when the STRONG two-stage Phase 1 gate passed (env `AI_ROUTER_ALLOW_GPT55_AUDIT=1` + typed phrase + type-back self-abasement re-confirm; Models line `GPT-5.5: y`). Mechanism is identical to the Gemini audit voice but invokes `or_ask(model="openai/gpt-5.5-pro", prompt=<the evaluator prompt>, max_tokens=2048)`. The call only succeeds because of the narrow, env-gated single-id exception in ai-router (`_gpt_audit_exception_allowed`); every other `openai/*` and all `x-ai/*` stay refused. ZDR is enforced and fails closed (OpenAI ZDR is enterprise-gated). The GPT score is NOT averaged into the K=2 result and does NOT change the winner. Compute gpt_audit_delta = |K=2_weighted_score − GPT_weighted_score| (orchestrator recomputes from GPT's per-criterion breakdown). If gpt_audit_delta > audit_flag_threshold: log [GPT-5.5 AUDIT FLAG] offspring i — contested (K2=X.XX, GPT=Y.YY, Δ=Z.ZZ). Rationale: GPT-5.5 is a strong general/agentic model and a useful third disagreement detector, but it is UN-PROBED in the FLO domain and crosses a standing privacy ban, so by I3 it is audit-only (flag, never vote) until a calibration probe. Gemini, GLM, and GPT-5.5 audit voices may all coexist when enabled; each flags independently, none enters any average. If the two-stage gate did not pass, skip silently.
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

Every parameter below can be tuned independently. Defaults are research-validated for Tier 3 tasks at P=6. When tuning: change exactly one parameter per session; re-run the benchmark corpus task(s) most sensitive to that parameter; compare scores before committing. Parameters marked with a Ph3 Step are hot-tunable within a session via explicit user override; every other parameter requires session restart.

| Parameter | Default | Range | Governs |
|---|---|---|---|
| max_iter | 10 | 1–∞ | Ph1, Ph3 Step 8 |
| stuck_threshold | 3 | 1–10 | Ph1, Ph3 Step 8 |
| P (population size) | 6 | 1–16 | Ph1, Ph3 |
| MAX_GENES | 16 | 8–32 | Ph3 global state (total distinct values across all 5 slots) |
| MAX_EXPANSIONS | 5 | 1–10 | Ph3 Step 3 |
| map_cells | 9 | 4–25 | Ph3 Step 1, 5 |
| K_evaluators | 1 or 2 | 1–4 | Ph3 Step 4 (1 default; 2 when best_score > 95) |
| K_threshold | 95 | 80–99 | Ph3 Step 4 (best_score trigger for K=2) |
| UCB1_C | √2 (≈1.41) | 0.5–3.0 | Ph3 Step 1 (map cell exploration constant) |
| archive_draw_prob | 10% | 5–30% | Ph3 Step 1 (absolute probability of map-based parent pick, split exactly 1% unfilled-cell + 9% UCB1 sub-branches) |
| gene_prior_α | 1.5 | 1.0–3.0 | Ph3 Init, Step 3, Step 6a (Beta prior per (slot,value) pair) |
| gene_prior_β | 1.5 | 1.0–3.0 | Ph3 Init, Step 3, Step 6a |
| op_prior_α | 2 | 1–5 | Ph3 Init, Step 6b (Beta prior for op_posteriors) |
| op_prior_β | 2 | 1–5 | Ph3 Init, Step 6b |
| position_swap_delta | 1.5 pts | 0.5–3.0 | Ph3 Step 4 K=1 path (per-criterion score delta triggering calibration average) |
| audit_flag_threshold | 20 pts | 10–30 | Ph3 Step 4 K=2 path (\|K=2 − audit voice\| delta triggering [GLM AUDIT FLAG] / [GEMINI AUDIT FLAG]; shared by both audit voices) |
| gemini_premium | **on when `or_status` `set`** (premium default) | on / off | Ph1 gate + Ph3.4 — Gemini (gemini-3.1-pro via OpenRouter) is the premium evaluator, ON by default when available; user steps down via "non-premium"/"budget mode" (the only disable path, never prompted). Calibrated S15/S16: VOTING premium Eval-2 paired with Kimi in host=Opus / Fable-not-used (the default regime, replaces the dangerous Sonnet); its non-voting audit-voice role elsewhere stays a separate opt-in (no auto per-token spend) |
| gpt55_audit | off (gated++) | off / on | Ph1 STRONG two-stage gate + Ph3.4 — enable the GPT-5.5-pro (openai, via OpenRouter) audit voice; CROSSES the openai/ ban; requires env `AI_ROUTER_ALLOW_GPT55_AUDIT=1` + typed phrase + type-back self-abasement re-confirm; non-voting, audit-only until calibration probe |
| heldout_admission_gate | on iff any criterion vagueness≥2, else off | on / off | Ph1 reserve + Ph3 Step 6a — held-out admission gate (Arbor H3, v1.9.9): reserve a held-out rubric slice at Phase 1; promote best_score only if the candidate also does not regress on the held-out slice (evaluated once, on the new-best candidate only → ~free). Anti eval-gaming; NO-OP on deterministic-oracle tasks (auto-off). Tier-1 PASS + tier-2 no-regression; measured lift needs gameable-rubric A/B (META gaps) |
| genome_exercised_check | on | on / off | Ph3 Step 5 — before crediting bandit/archive, verify the delivered solution embodies its ASSIGNED genome slots (Arbor H4, v1.9.9); on drift, re-label to the delivered genome (or exclude). Cheap credit-integrity guard; extends the one-structural-improvement cap. Tier-1 PASS |
| score_bounding | on | on / off | Ph3 Step 6a admission (EA4, v1.9.10) — apply a saturating top-end transform to weighted_score above a knee (~95): identity below, bounded→100 above; compresses near-noise high-end gaps below the ±4 band so selection stops chasing noise past the knee. Orchestrator-math, no judge tokens. Tier-1 PASS |
| judge_live_calibration | on | on / off | Ph3.4 recompute (EA8, v1.9.10) — if a judge's deterministic-criterion score disagrees with the orchestrator recompute this gen, demote it voting→flag for the rest of the run (live per-run I3). Free (reuses recompute). Tier-1 PASS |
| cost_as_fitness | on | on / off | Ph3 Step 6a + Ph3.1 UCB1 (EB4, v1.9.10) — at equal score prefer the cheaper proposal (token tiebreak); weight UCB1 cell selection by score/token. Serves token economy. Tier-1 PASS |
| smoke_test_pre_gate | on | on / off | Ph3 Step 6a (EB7, v1.9.10) — a cheap validity smoke-test (genome in-registry; runs/parses) BEFORE the expensive H3 held-out eval; reject invalid candidates early. Tier-1 PASS |
| evidence_hard_fail | on | on / off | Ph3.4 recompute (EA3, v1.9.10) — require rationale/evidence BEFORE the number; ABSTAIN/hard-fail (do NOT trust the prose score) when a deterministic-criterion score lacks matching raw evidence. Extends deterministic-evidence recompute. Tier-1 PASS |
| artifact_debias_anchors | on (subjective) | on / off | Ph1 anchor ladders (EA1, v1.9.10) — add verbatim: length/verbosity/formatting ≠ quality; score content held-constant-under-format. Prompt guard (unscreened); anti-gaming, no measured lift on clean tasks |
| legibility_guard | on (subjective) | on / off | Ph1/Ph3.4 (EA6, v1.9.10) — judges cap the score of outputs whose correctness can't be verified from the artifact (magic constants, "trust me", unsourced claims), within existing criteria. Prompt guard (unscreened); helps a weak judge catch a strong worker |
| adversarial_gate_pass | on iff any criterion vagueness≥2, else off | on / off | Ph3 Step 6a (EA2, v1.9.11; default-on v1.9.12) — one adversarial-audit pass at admission; VETO promotion only when `exploit_found` AND `confidence` ≥ that judge's CALIBRATED threshold via clean-probe ceiling (derive from H3 anchor probes; fall back to screened family default Kimi 90 / Gemini 95 if no clean is flagged — NOT a shared constant), K=2 requires BOTH judges (consensus). No-op on deterministic oracles. Tier-1.5 judge-screened + cross-family held-out-confirmed (selftest 28/28; every observed gate-admitted leak closed at 0 false-veto across Kimi+Gemini). Narrow no-regression defensive guard (`probes/JUDGE-SCREEN-FINDINGS.md`) |
| evaluator_route | per host (→ Orch. Notes routing table) | 3 host × availability rows | Phase 1 (recorded in Models header line; fixed for session) |
| lane_spread_threshold | 20 pts | 10–30 | Ph3 Step 7 (gap triggering UNEXPLORED SPACE log) |
| G_stag | 2 | 1–5 | Ph3 Step 3 (no_improve_streak threshold for expansion stagnation trigger) |
| T_mutation_high | 1.0 | 0.7–1.5 | Ph3 Step 6b (temperature for mutation-dominant lane config) |
| vagueness3_N_min | 5 | 3–10 | Ph0B (min fixtures for vagueness=3 + LLM judge) |
| rubric_revisit_gen | 2 | 1–3 | Ph3 Step 8 (gens of zero improvement before rubric revisit offer) |
| adaptive_P_map_trigger | 6 | 3–9 | Ph1 Adaptive-P (filled map cells required to trigger P reduction) |

---

## Orchestration Notes

### Role Separation (immutable)

- Workers and evaluators are separate subagent contexts — they MUST never merge in any subagent.
- Parallel workers MUST NOT see each other's proposals.
- Evaluators MUST NOT see: each other's scores, parent scores, iteration number, genome (slot-vector), which lane produced the solution, or worker rationale/chain-of-thought.
- Memory isolation: persistent memory (agent-memory repo, auto-memory, MEMORY.md/CLAUDE.md memory indexes) is orchestrator-only context. Workers and evaluators MUST NOT read, grep, or act on it — prior-session FLO scores, solutions, and calibration data live there and break verification independence (probe 2026-06-12: both subagent types could read `facts/flo.md` and saw the memory runbook in-context before hardening). Enforcement: curated tool allowlists + Memory Isolation rules in agents/flo-evaluator.md (read-only, spawn-less) and agents/flo-worker.md (spawn-less); CLI evaluators (kimi) run from a neutral cwd (e.g. /tmp/flo-<task>) with an in-prompt no-tools directive. Subagent tool use is legitimate ONLY for deterministic verification or improvement of the solution at hand (run provided tests, count words, fetch a cited URL) — never for memory or prior-session lookups.
- Routing invariants I1–I5 (re-derive the binding from these when a new model generation ships; the table below is the current binding, not canon):
  - I1 — Non-identity: the evaluator model MUST differ from the host/worker model (self-preference defense). This generalizes v1.8.0's blanket "NEVER use Claude Opus as evaluator": that rule traces to Opus 4.7 (JSS=0.701) and stays recorded as 4.7-specific — the S12+S12b probes (2026-06-12) showed Opus 4.8 is the best single judge (combined RMSE 1.47, 18/18 exact on deterministic criteria across doc/code/creative domains) and does not inherit that weakness. Opus is still never the evaluator whenever Opus IS the host — by I1, not by a per-model ban.
  - I2 — Family distance: prefer cross-family (Kimi) over cross-model same-family over cross-tier same-family. Cross-family Eval-1 stays primary even when a same-family judge measures lower RMSE, because S12 measures anchoring/verification, not self-preference (Chen et al. 2025).
  - I3 — Accuracy gate: only judges with empirically low truth-RMSE (or proven ranking accuracy) may vote or be averaged; a high-RMSE judge is excluded from averaging even if available (S1: GLM at ~3× truth-RMSE → audit-only; S12+S12b: Sonnet at 13.16 → excluded from the pair whenever a ~1.5-RMSE judge exists). Audit voices flag, never vote — UNLESS a calibration probe promotes them. **Calibration can promote (added v1.9.6):** Gemini 3.1 Pro, calibrated S15/S16 (2026-06-14, anchored ranking-first), is the best single judge on the easy corpus and competent (4th, 0 inversions) on the disguised reward-hacking corpus, verification 1.00; the Kimi+Gemini pair ranks the defect ladder cleanly (S15 +3.0 worst-margin, 0 inversions) and is strictly safer than the dangerous Kimi+Sonnet fallback (S15 0.972, 1 inversion). So Gemini earns a CONDITIONAL voting slot: it may vote ONLY as the premium Eval-2 when no stronger non-host judge (Opus/Fable/Kimi) is available — i.e. the host=Opus / Fable-not-used row only (see routing table), which is now the DEFAULT regime since Fable-per-token is declined by default (v1.9.8). It stays non-voting (audit-only) in every regime where a stronger judge already fills the slot, because it leans LENIENT on subjective criteria (+7.03 signed-B, S14) and is per-token — better than Sonnet, not better than Opus/Kimi. GLM (anchors on stated values, S1) and GPT-5.5 (lenient + crosses the openai/ ban) remain audit-only, never vote.
  - I4 — Cost reserve: the most expensive verifier is reserved for K=2 / explicit fallback, not routine K=1 (S12 cost note: Fable verification ~30% more tokens (new tokenizer) + always-on thinking).
  - I5 — Order-bias correction: Evaluator 2 always receives the rubric in reversed criterion order; in K=1, position-swap applies to the winning offspring only.
- Routing table (single source of truth for the host×availability binding — derived from I1–I5 via the S12 evaluator-matrix probe, 2026-06-12; route selected once in Phase 1 from host + verifier availability; in a K=1 chain "X → Y", Y is the fallback when Kimi is unavailable). S12+S12b RMSE basis (3 domains: doc/code/creative; 6 evals per model; orchestrator-recomputed totals): Opus 4.8 1.47, Kimi K2.6 1.69, Fable 5 1.80, Haiku 4.5 6.02, Sonnet 4.6 13.16. The host=Opus / no-Fable **Gemini premium-fallback** binding derives from S15/S16 ranking-accuracy (2026-06-14, anchored, harness-verified defect ladders): Kimi+Gemini ranks cleanly (S15 +3.0 worst-margin, 0 inversions; S16 1.00 CI[1,1]) and beats the Kimi+Sonnet fallback (S15 0.972, 1 inversion) — so when the host is Opus and Fable is declined (the default, since Fable-per-token is too expensive — v1.9.8 makes Gemini the premium DEFAULT here, ON whenever the OpenRouter key is set), a Gemini Eval-2 is preferred over Sonnet. Kimi+Opus remains the validated best pair on BOTH corpora and is unchanged; Gemini votes only where no stronger non-host judge exists.

  | Host (workers) | Fable avail? | K=1 chain      | K=2 (Kimi avail)   | K=2 degraded (no Kimi) |
  |----------------|--------------|----------------|--------------------|------------------------|
  | Fable 5        | —            | Kimi → Opus    | Kimi + Opus(rev)   | Opus×2 (orig+rev)      |
  | Opus           | yes          | Kimi → Fable   | Kimi + Fable(rev)  | Fable×2 (orig+rev)     |
  | Opus           | no, Gemini avail (PREMIUM DEFAULT)  | Kimi → Gemini  | Kimi + Gemini(rev) | Gemini + Sonnet(rev) — [PREMIUM FALLBACK] |
  | Opus           | no, Gemini off (budget step-down / key unavail) | Kimi → Sonnet  | Kimi + Sonnet(rev) | Sonnet×2 (orig+rev) + [CALIBRATION RISK] log |

- Sonnet demoted from default fallback by S12+S12b data (I3), REPLICATED across all 3 probe domains: worst Claude judge everywhere (combined RMSE 13.16, 11/18 exact; false-flagged the honest solution via hallucinated counts in 2 of 3 domains; lenient on planted defects in all 3; never used tools). Sonnet is retained only for the table's host=Opus / Fable-unavailable row, where it is then the strongest non-host option — that row degrades to ≈ v1.8.0 behavior. Error-direction asymmetry: Sonnet errs LENIENT on adversarial solutions (dangerous — admits reward-hacked work); Haiku errs HARSH (RMSE 6.02 — wasteful but safe); Haiku remains non-voting. Caveats: probes measure anchoring/verification on planted-defect fixtures, n=6 per model, no position-swap trial; cross-family Eval-1 (Kimi) remains the primary defense against self-preference per Chen et al. 2025.
- K=2 cross-family (Kimi Eval-1, original order + strongest non-host Claude Eval-2, reversed order) corrects both order bias AND family bias simultaneously. The intra-family ×2 degraded fallback corrects order bias only.
- GLM as audit voice, NOT voting member: empirical probe (S1 fixture, 2026-05-31) showed GLM (glm-5.1) is the least accurate single evaluator on this task — it anchors on stated values rather than independently verifying (e.g., scored claimed word counts at face value across all 4 cells where the actual count was outside the rubric range). Naive K=3 mean tripled the truth RMSE vs K=2 mean. However, GLM's disagreement with the K=2 ensemble correctly identified the adversarial case without false-alarming on the honest case. Hence: when GLM is available in K=2 mode, spawn it as an audit voice (flag only, no vote). Do not add it to any averaging or median computation.
- Gemini — the PREMIUM evaluator: VOTING premium Eval-2 (default ON when the OpenRouter key is set) in the host=Opus/Fable-not-used regime, and an opt-in non-voting audit voice elsewhere (calibrated v1.9.6; promoted to premium default v1.9.8): Gemini 3.1 Pro is the frontier reasoning leader (top GPQA Diamond 94.3 / HLE 44.4) and was added v1.9.4 as a non-voting audit voice while UN-PROBED. It is now CALIBRATED (S15/S16, 2026-06-14, anchored ranking-first): best single judge on the easy corpus, competent (4th, 0 inversions) on the disguised reward-hacking corpus, verification 1.00; the Kimi+Gemini pair ranks the defect ladder cleanly and beats the dangerous Kimi+Sonnet fallback (which carries an inversion). Dual role, both gated:
  - **Non-voting audit voice (default, all regimes):** flags only, never averaged — exactly as GLM. This is its role whenever a stronger non-host judge (Opus/Fable/Kimi) already fills the Eval-2 slot. Every [GEMINI AUDIT FLAG] is a disagreement signal, not a scoring input.
  - **Voting premium default (host=Opus + Fable not used — the current default regime):** the routing table binds Eval-2=Gemini whenever the OpenRouter key is available (v1.9.8 default-on; replaces the dangerous Sonnet). Gemini IS the reversed-order Eval-2 — its score IS averaged into the K=2 pair, and the separate Gemini audit voice is then NOT spawned (it cannot be both the voter and the auditor). Log [PREMIUM FALLBACK]. This is the ONLY regime where Gemini votes; it never enters the Kimi+Opus / Kimi+Fable pairs (it leans lenient on subjective criteria, +7.03 signed-B S14, and is per-token — better than Sonnet, not better than Opus/Kimi).
  Gating (v1.9.8): the VOTING premium role is ON BY DEFAULT whenever `or_status` shows the key `set` — no opt-in prompt; the user steps DOWN to the non-premium Kimi+Sonnet route via "non-premium"/"budget mode" (the only disable path). The non-voting AUDIT role (regimes where a stronger judge already votes) stays explicit opt-in — per-token money is never auto-spent on a flag-only voice. Tier-3 per-token via OpenRouter (~$0.03/eval), ZDR enforced (`provider.data_collection=deny`, fails closed if no zero-retention Gemini endpoint is approved). Invoke via `or_ask(model="google/gemini-3.1-pro-preview", ...)` from the orchestrator — never as a subagent (subagents carry no MCP tools). Gemini ≠ Claude, so I1 non-identity holds on any host, and Kimi+Gemini is still cross-family (Moonshot+Google), preserving the I2 family-distance defense. A harder-corpus re-probe (S17) would further validate the voting role; until then the S15/S16 pair data (Kimi+Gemini ≥ Kimi+Sonnet) is the basis.
- GPT-5.5-pro as a STRONG-gated audit voice that CROSSES the standing OpenAI ban (added v1.9.4): this is the single deliberate exception to jojo's `openai/*` privacy ban, present only because he explicitly requested it as a gated possibility. It is the most heavily gated route in the system: OFF by default; requires an env opt-in (`AI_ROUTER_ALLOW_GPT55_AUDIT=1`, enforced in ai-router code via a narrow exact-id exception — the general ban is otherwise intact on every path), a typed acceptance phrase, AND a type-back self-abasement re-confirmation (the orchestrator dispatches a subagent to compose a fresh, original one-line berating of the user for crossing the ban and makes them retype it verbatim — no web search, minimal context pollution, every time GPT is OK'd). ZDR is enforced and fails closed (OpenAI ZDR is enterprise-gated). Like Gemini it is UN-PROBED in this domain → I3 keeps it audit-only (flag, never vote, never averaged) until a calibration probe. Invoke via `or_ask(model="openai/gpt-5.5-pro", ...)` from the orchestrator only. The same probe obligation applies (META-OPTIMIZATION.md gaps); until then every [GPT-5.5 AUDIT FLAG] is calibration signal, not a scoring input. Privacy note: this is the only place in FLO or ai-router that touches a banned provider — keep the gate strict; never relax it to match the Gemini gate.
- Prefer deterministic measurement (tests, benchmarks) over LLM judgment wherever possible.

### Subagent Prompt Structure (front-loaded)

Every subagent prompt MUST follow this 5-step order: (1) role declaration first sentence; (2) task goal + rubric next; (3) specific lane or scoring directive; (4) parent content; (5) explicit list of what NOT to infer or use.

```
WORKER template:
You are a FLO WORKER (Lane [A/B/Explorer]). Task: [one-sentence goal].
Rubric: [paste with weights + anchors]
Lane instruction: [mutation/crossover/explorer directive]
Parent solution: [paste parent]
Do NOT communicate with other workers. Do NOT infer iteration number, sibling scores, or
prior-gen evaluator feedback unless passed above. Do NOT consult persistent memory
(agent-memory, MEMORY.md, auto-memory) — work only from this prompt.

EVALUATOR template:
You are a FLO EVALUATOR. Score the solution below against the rubric. You have no knowledge
of iteration number, prior scores, or which lane produced this solution. Score only what
is present — do not reward intent or inferred effort. Do NOT consult persistent memory or
prior-session data — judge only the solution below; tools serve only deterministic
verification of it.
Routing: host=<model> | your assigned evaluator model: <model> (from the Phase 1 Models line)
Rubric: [paste with weights + anchors + fixture specs]
Solution to score: [paste]
Return: per-criterion scores (X/10), weights, raw evidence for every
deterministic criterion (per-test PASS/FAIL list / actual counts), top 2–3 weakness bullets. Do NOT compute a total — the orchestrator recomputes weighted_score.
```

### Selective Context — What to Pass and Withhold

|  | Worker receives | Worker must NOT receive | Evaluator receives | Evaluator must NOT receive |
|---|---|---|---|---|
| Goal + rubric (anchors) | ✓ | — | ✓ (also fixture specs) | — |
| Parent solution + its genome | ✓ | — | — | — |
| Parent's last-eval weaknesses (bullets only) | ✓ | — | — | — |
| Current genome_registry | ✓ | — | — | — |
| Exactly one solution to score | — | — | ✓ | — |
| Host model + assigned evaluator route (Routing line) | — | — | ✓ | — |
| Other members' scores | — | ✓ | — | ✓ (no parent or prior-gen scores) |
| Iteration number | — | ✓ | — | ✓ |
| Sibling workers' proposals or eval scores | — | ✓ | — | — |
| The solution's genome / which lane / worker chain-of-thought | — | — | — | ✓ |
| Persistent memory (agent-memory / auto-memory / memory indexes) | — | ✓ | — | ✓ |

### Generation State Compression

When passing prior-gen state to a new worker, summarize — never dump verbatim. Target ≤ 500 tokens. Include exactly these 3 items: (1) best score so far (number only), (2) winner genome (5 slots), (3) last-eval weaknesses (≤ 5 bullets). Exclude full prior solutions, full eval text, score history tables, and map contents (Explorer is the sole exception — Explorer needs the full registry). If the parent solution exceeds budget, summarize every section except the one being mutated (Lane A) or the section with the lowest criterion score (Lane B).

### LLM Math Approximation Guide

LLM orchestrators cannot call a math library. Use these approximations for the two formulas requiring numeric computation.

**Beta Thompson Sampling / TS sampling (Steps 2, 6b):**
Approximate `θ ~ Beta(α, β)` by the posterior mean `α/(α+β)`. Select the arm with the highest mean. On ties (means within 0.05), break by lower `α+β` (less data = more uncertain = explore first).

Example — op_posteriors {mutation: (3,1), crossover: (2,2), explorer: (2,3)}:
- mutation mean = 3/4 = 0.75
- crossover mean = 2/4 = 0.50
- explorer mean = 2/5 = 0.40
→ Configure for mutation (Lane A high-temp).

The same rule applies in Step 2 Lane A slot selection: for each of the 5 slots S in the parent's genome, compute mean θ_(S, current_value) = α_(S,V) / (α_(S,V) + β_(S,V)). Pick the single slot with the highest mean as mutation target.

**UCB1 formula (Step 1, map cells):**
`UCB(cell) = score(cell)/max_score + 1.41 × sqrt(log(map_visits+1) / (offspring_count_cell+1))`

Variable mapping: `map_visits` = total map-based picks made so far this session (global N); `offspring_count_cell` = the number of times this specific cell's current occupant was drawn as a parent (per-cell n).

For mental sqrt(log(N+1)) estimation — lookup by map_visits N:

| N (map_visits) | sqrt(ln(N+1)) |
|---|---|
| 0 | 0.00 |
| 1 | 0.83 |
| 4 | 1.27 |
| 7 | 1.43 |
| 12 | 1.61 |
| 20 | 1.80 |
| 33 | 2.00 |

For offspring_count_cell n, sqrt(1/(n+1)): n=0→1.00, n=1→0.71, n=2→0.58, n=3→0.50, n=4→0.45, n=5→0.41.

Worked example: map cell with score=85, max_score=90, map_visits=7, offspring_count_cell=2:
- exploitation = 85/90 = 0.94
- exploration = 1.41 × 1.43 × 0.58 = 1.41 × 0.83 ≈ 1.17
- UCB = 0.94 + 1.17 = 2.11

### Context Budget Targets

| Subagent | Target prompt size | Contents |
|---|---|---|
| Worker | ≤ 3,000 tokens | Role + goal + rubric + parent solution + lane instruction |
| Evaluator (K=1, per routing chain) | ≤ 2,500 tokens | Role + rubric (with fixtures) + solution |
| Evaluator (K=2, Eval-1 Kimi) | ≤ 2,500 tokens | Role + rubric (original order, with fixtures) + solution |
| Evaluator (K=2, Eval-2 strongest non-host Claude) | ≤ 2,500 tokens | Role + rubric (reversed order, with fixtures) + solution |
| Explorer | ≤ 3,500 tokens | Role + goal + rubric + all current solutions (summarized) + genome_registry (per-slot) |

If the budget is exceeded: summarize every parent section not under mutation. NEVER summarize the rubric or the fixture specs.

### Miscellaneous

- Gen 0 counts toward max_iterations only if FLO generated it (not if the user supplied it).
- Fixture specs are locked at rubric lock; any new edge case discovered mid-run goes into Phase 4 notes for a future session.
- Genome format: slot-vector with exactly 5 named slots. Workers mutating a slot MUST name the old and the new value explicitly. The registry is per-slot and append-only; values are never removed even if no current member carries them. The index-0 value of each slot's list is the default and never changes mid-session — every newly registered value is appended at the tail.

**Mutation example (Lane A):** parent = {eval_mechanism: single_evaluator, diversity_method: map_elites, mutation_targeting: ts_weighted, expansion_trigger: stagnation_only, usability_focus: hybrid}. TS posterior means: (eval_mechanism, single_evaluator) α/(α+β) = 2.5/4 = 0.625 — highest. Target slot = eval_mechanism; worker picks new value from [single_evaluator, cross_family, multi_judge] (must differ from current). Result: eval_mechanism = cross_family; other 4 slots unchanged.

**Crossover example (Lane B):** Parent 1 = {cross_family, map_elites, ts_weighted, stagnation_only, hybrid}; Parent 2 = {single_evaluator, novelty_archive, evaluator_guided, ts_triggered, compact_qr}. Independent fair coin per slot — e.g., flips HTHTH → offspring = {cross_family, novelty_archive, ts_weighted, ts_triggered, hybrid}.
