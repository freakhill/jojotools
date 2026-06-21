# monkeypaw Phase A Runbook
**Status:** All 5 corpus fixtures complete (2026-05-31). Phase A is execution-ready.

## What you are doing

Running monkeypaw on one of the corpus tasks **twice** — once with `MP_SKIP_PHASE_A=1` (baseline) and once normally (with the backward refinement sweep). Each pair takes one full multi-hour session. The deltas across 5 pairs decide whether `WAVES-ROADMAP.md` Phase B is authorized.

## Recommended order

X1 → P3 → P2 → D2 → N1. (Easiest oracle → hardest oracle. Independent ETL + REST API + truss are the slowest because each needs an installable Python package.)

## Pre-flight (run once per session, ~5 seconds)

```bash
cd ~/dotfiles/claude/plugins/jojo-skills/skills/monkeypaw

# 1. Harness tests still green
bash scripts/tests/test_mp_validate.sh         # expect: PASS: all mp-validate tests (9/9)
bash scripts/tests/test_oracle_smoke.sh        # expect: SMOKE OK

# 2. Confirm the fixture you're about to use
ls corpus/fixtures/<TASK>/                     # X1 needs reference_interpreter/; D2 needs orders.csv etc.
```

If either test fails, **stop** — fix the harness before burning a multi-hour run.

## Per-task one-line briefs

| Task | Brief source | Authoritative ref | Oracle | Checks |
|---|---|---|---|---|
| X1 | `PHASE-A-CORPUS.md` § X1 + `corpus/fixtures/X1/SPEC.md` | `corpus/fixtures/X1/reference_interpreter/stax.py` | `corpus/fixtures/X1/oracle.sh` | 10 reference programs |
| P3 | `PHASE-A-CORPUS.md` § P3 | `corpus/fixtures/P3/expected_files.txt` | `corpus/fixtures/P3/oracle.sh` | 14 |
| P2 | `PHASE-A-CORPUS.md` § P2 | `corpus/fixtures/P2/expected_invariants.json` | `corpus/fixtures/P2/oracle.sh` | 8 |
| D2 | `PHASE-A-CORPUS.md` § D2 | `corpus/fixtures/D2/expected_invariants.json` | `corpus/fixtures/D2/oracle.sh` | 13 |
| N1 | `corpus/fixtures/N1/geometry.md` | `corpus/fixtures/N1/reference_solution.md` | `corpus/fixtures/N1/oracle.py` | 19 |

## Running a baseline+sweep pair

### Baseline (no sweep)

1. Start a fresh session.
2. Set `MP_SKIP_PHASE_A=1` in the environment monkeypaw sees.
3. Hand monkeypaw the brief (e.g., copy-paste the entire `PHASE-A-CORPUS.md` § X1 block as the user message).
4. Let it run to completion. Capture the produced project directory.
5. Run the oracle: `bash corpus/fixtures/X1/oracle.sh /path/to/produced/project`
6. Score using the rubric in `PHASE-A-CORPUS.md` § Common Rubric. Record per-criterion scores in JSON form for `mp-validate compare`.

### Sweep (normal monkeypaw)

1. Start another fresh session.
2. Do not set `MP_SKIP_PHASE_A`.
3. Same brief, same procedure.
4. Same oracle invocation.
5. Score again.

### Record the delta

```bash
python3 scripts/mp-validate.py compare \
  --task X1 \
  --baseline /path/to/baseline_scores.json \
  --sweep /path/to/sweep_scores.json \
  --out-report results/X1.md
```

Append the per-task block (template in `WAVES-ROADMAP.md` § Phase A Validation Results) to `WAVES-ROADMAP.md` under `<!-- Begin per-task results -->`.

## After all 5 pairs are done

```bash
python3 scripts/mp-validate.py aggregate --results-dir results/ --out WAVES-ROADMAP.md
```

This fills in the Phase A aggregate table and the gate decision checkboxes. If all four boxes check:
- Authorize Phase B (windowed pass) per `WAVES-ROADMAP.md`
- Consider implementing Tier 1 v2 enhancements per `V2-BACKLOG.md` (T1-1 topology router, T1-2 USE dashboard, T1-3 progressive disclosure)
- Optionally author P4/N2 neutral-control fixtures per `PHASE-A-CORPUS.md` § Phase A v1.1 — this lets you tell whether Phase A's mechanism is specifically late→early signal or a generic re-do pass

If the gate fails, **do not** authorize Phase B. Read the per-task failure modes in your results and decide whether to fix the sweep mechanism or kill the line entirely. `WAVES-ROADMAP.md` Phase C/D are speculative and should not be touched while Phase A is unvalidated.

## Things that have already gone wrong (so you don't redo them)

- **Spec-author guesses ≠ reality.** PHASE-A-CORPUS.md originally had hardcoded numerics for D2 ($87,392.41) and N1 (reactions Ay=13/By=12, critical=M7, zero-force={M4,M11}). All were placeholder guesses. Fixture authors recomputed from generated/solved data. Lesson: trust `expected_invariants.json` and `reference_solution.md`, not the markdown spec.
- **Spec member-list bug.** N1 originally had M14=(J8,J7) and M15=(J7,J8) — two members between the same joints. Corrected to M15=(J8,J9) for a proper Pratt apex.
- **Fragile data-dependent checks.** P2's original `?tag=urgent → 4 items` check required monkeypaw to produce a tag literally named "urgent". Replaced with dynamic discovery in `oracle.sh`. Don't add literal-name checks unless a frozen seed snapshot is also committed.
- **Smoke test empty-dir probe.** Don't try to probe oracles with empty directories — most try to `pip install -e <dir>` which hangs. The smoke test only covers no-args + nonexistent-dir.

## Where to look when something is confusing

| Question | File |
|---|---|
| What is monkeypaw's current behavior? | `SKILL.md` (507 lines, v2.2.2) |
| What is Phase A and what gate authorizes Phase B? | `WAVES-ROADMAP.md` |
| What are the 5 corpus tasks and their oracles? | `PHASE-A-CORPUS.md` |
| What's on the v2 wishlist and what's the priority? | `V2-BACKLOG.md` |
| Where did the FLO score 94.25 come from? | `META-OPTIMIZATION.md` |
| What does the literature say about agentic orchestration? | `RESEARCH-FINDINGS.md` (drained into `V2-BACKLOG.md`) |
| Context-folding mechanism details (if T2-2 ever activates) | `RESEARCH-CONTEXT-FOLDING.md` |
