# FLO — Reference (loaded on demand)

Reference tables for `SKILL.md`: the Population Tier Guide and the full tunable-Parameter Reference. The core loop runs from SKILL.md; consult this for tier selection detail or to tune a parameter.

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

