# FLO — Orchestration Notes (loaded on demand)

Reference layer for `SKILL.md`. Read this when you need the routing/eval-model decisions, the subagent prompt contracts, or the math approximations — the core Phase 0–4 loop in SKILL.md does not require it inline.

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
- GLM as audit voice, NOT voting member: empirical probe (S1 fixture, 2026-05-31) showed GLM (glm-5.1) is the least accurate single evaluator on this task — it anchors on stated values rather than independently verifying (e.g., scored claimed word counts at face value across all 4 cells where the actual count was outside the rubric range). Naive K=3 mean tripled the truth RMSE vs K=2 mean. However, GLM's disagreement with the K=2 ensemble correctly identified the adversarial case without false-alarming on the honest case. Hence: when GLM is available in K=2 mode, spawn it as an audit voice (flag only, no vote). Do not add it to any averaging or median computation. **Current model (v1.9.13, 2026-06-27):** the GLM audit voice now runs **glm-5.2** (`glm_ask` default since the ai-router bump; the `-pro` suffix is rejected HTTP 400, so the id is bare `glm-5.2`). The S1 calibration above was glm-5.1; glm-5.2 is anecdotally a stronger *review* lane (it caught holes a cross-family panel missed in slopysheet design work) but reasons verbosely — give it a fat `max_tokens` and a "lead with the structured answer" directive. It stays **audit-only** (flag, never vote) until a glm-5.2 calibration re-probe under I3 — a stronger-seeming lane is not yet a measured one.
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
