# Feedback Loop Optimization (FLO) — Skill Architecture

This is a developer-facing map of the skill bundle: what each file is for and how the pieces fit together. The skill itself is `SKILL.md`; everything else exists to evolve, evaluate, or support it.

## File map

```
feedback-loop-optimization/
├── SKILL.md                       # ← the skill Claude reads at runtime
├── META-OPTIMIZATION.md           # state file for re-running FLO on FLO itself
├── SKILL-0.6.1-minimal.md         # frozen historical variant (population seed)
├── SKILL-v0.6.1-island.md         # frozen historical variant (population seed)
├── README.md                      # this file
├── scripts/
│   ├── flo_math.py                # FLO-specific math primitives (TS, UCB1, weighted score)
│   ├── validate_corpus.py         # corpus validator + drift detector (static lint + Phase 0/0.5 via kimi)
│   ├── algebra.py                 # general SymPy helper (bundled, not FLO-specific)
│   ├── stats.py                   # general NumPy/SciPy helper (bundled, not FLO-specific)
│   ├── linalg.py                  # general NumPy helper (bundled, not FLO-specific)
│   └── numtheory.py               # general number-theory helper (bundled, not FLO-specific)
└── training-corpus/
    ├── CORPUS.md                  # frozen 30-task benchmark for measuring FLO improvements
    └── evaluation-log/             # append-only per-version snapshots written by validate_corpus.py
```

## What each part is for

### `SKILL.md` — the protocol Claude executes

The file Claude actually loads when a user invokes the skill. Defines the 5-phase protocol (Pre-flight → Setup → Baseline → Evolutionary Loop → Report), the genetic-programming machinery (slot-vector genome, MAP-Elites archive, Thompson Sampling over slot values and operators, cross-family K=2 evaluation), and the orchestration notes for dispatching Worker and Evaluator subagents. Self-contained: at runtime it depends on nothing else in this directory except optionally `scripts/flo_math.py`.

### `META-OPTIMIZATION.md` — the state file for FLO-on-FLO

Captures everything needed to re-run the meta-optimization (running FLO with `SKILL.md` itself as the artifact being improved). Contains: version history with scores, augmented evaluation rubric (C1–C6), genome registry of every design feature ever introduced, initial population seeds, remaining gaps, and "next optimization targets." Read this before any meta-optimization session. Updated at the end of each session to record what changed and what's still open.

### `SKILL-0.6.1-minimal.md` and `SKILL-v0.6.1-island.md` — frozen ancestors

Historical SKILL.md variants kept as diverse seeds for the meta-optimization GP loop. They are **not loaded at runtime** and **not advertised to users** — they exist purely to give the meta-optimization a non-trivial initial population without spending tokens generating diversity from scratch. Do not edit them; treat as immutable snapshots. New variants discovered during meta-optimization can be added here under a versioned filename.

### `scripts/flo_math.py` — runtime math helpers

A `uv`-runnable CLI that exposes the math primitives FLO's algorithm uses: weighted scoring, Beta-distribution posterior + Thompson Sampling, UCB1 for MAP-Elites cell selection, percent-gain calculation. `SKILL.md`'s "LLM Math Approximation Guide" section points workers and the host orchestrator at this script when exact arithmetic matters (LLMs are unreliable at multi-step probabilistic calculations).

Usage examples are in the script docstring; invoke as `uv run scripts/flo_math.py <command> ...`.

### `scripts/algebra.py`, `stats.py`, `linalg.py`, `numtheory.py` — general utilities

General-purpose math helpers bundled in the same `scripts/` directory but **not part of the FLO protocol**. They exist alongside `flo_math.py` for convenience (and may be referenced by other skills); they could be moved elsewhere without breaking FLO. If you are reading FLO source to understand it, you can ignore these.

### `training-corpus/CORPUS.md` — the evaluation oracle

A frozen 30-task benchmark spanning 10 domains (programming, embedded, woodworking, CAD, metalworking, design, scriptwriting, creative writing, engineering analysis, interdisciplinary). Each task has a fixed-seed constraint set and a quality rubric so two FLO versions can be compared on the same problem. Stability contract: existing tasks are immutable; new tasks may be added under a new version. The "Evaluation Results Log" section at the bottom is where benchmark runs append results.

## How the parts interact

There are three workflows, each touching a different subset of files.

### Workflow 1 — Normal runtime use (user invokes the skill)

```
user request
   │
   ▼
SKILL.md  ←  Claude reads + executes Phases 0–4
   │
   ▼
spawns Worker and Evaluator subagents (separate contexts, no shared history)
   │
   ▼
(optionally) scripts/flo_math.py  ←  shell out for exact TS / UCB1 / weighted-score math
   │
   ▼
returns the optimized artifact + Phase 4 report
```

Only `SKILL.md` and (optionally) `flo_math.py` are touched. Everything else in the directory is dormant.

### Workflow 2 — Meta-optimization (improving FLO itself)

```
user: "resume FLO meta-optimization"
   │
   ▼
META-OPTIMIZATION.md  ←  Claude reads state (genome registry, gaps, rubric)
   │
   ▼
Initial population = current SKILL.md + frozen ancestors (SKILL-0.6.1-*.md) + git-history seeds
   │
   ▼
Run FLO on the FLO-skill-improvement task (SKILL.md is both the tool AND the artifact)
   │
   ▼
Winner installed → new SKILL.md
   │
   ▼
META-OPTIMIZATION.md updated (version table, remaining gaps, new genes discovered)
```

This is the "FLO on FLO" loop. `SKILL.md` plays a dual role: the protocol being executed, and the artifact being optimized. The frozen `SKILL-*.md` variants give the GP loop diverse initial parents.

### Workflow 3 — Benchmark / drift detection (against the corpus)

```
SKILL.md (any version)
   │
   ▼
For each task in training-corpus/CORPUS.md:
   run SKILL.md against the task → record output + decisions
   │
   ▼
Score against the task's rubric (or compare decisions to historical snapshots)
   │
   ▼
Aggregate → comparison to prior FLO versions
```

Automated via `scripts/validate_corpus.py`. Three phases in one command:

1. **Static lint** (no LLM) — checks ~20 deterministic SKILL.md invariants from the Section 3 rubric.
2. **Decision check** (parallel Kimi shell-outs) — for each of the 30 tasks, asks Kimi to apply Phase 0A/0B with SKILL.md as context, returning structured JSON for `{compatible, artifact, target, success, vagueness, p_tier}`.
3. **Drift diff** — writes the snapshot to `training-corpus/evaluation-log/v<version>__<git-sha>__<utc>.jsonl`, then compares against a logarithmic sample of ancestors ({1, 2, 4, 8, …} versions back plus the oldest), flagging per-task field disagreements. Recent disagreement against 1–2 immediate predecessors = regression candidate; disagreement only against distant ancestors = intentional shift.

Output is a Markdown report. Exit code is always 0 (advisory only — gating is intentionally not enforced). Add to your meta-optimization session checklist; see META-OPTIMIZATION.md.

The "Full FLO loop on regression-flagged tasks" piece (Section 9 "verifiable execution") is still future work.

## Conceptual layering

| Layer | Purpose | Files |
|---|---|---|
| **Protocol** (what FLO does) | Defines the algorithm Claude executes | `SKILL.md` |
| **Math substrate** | Exact arithmetic for the algorithm's probabilistic machinery | `scripts/flo_math.py` |
| **Meta-state** | Records the history and ongoing improvement of the protocol | `META-OPTIMIZATION.md`, `SKILL-*-*.md` ancestors |
| **Evaluation oracle** | External, version-stable yardstick for measuring protocol changes | `training-corpus/CORPUS.md`, (planned) `evaluation-log/` |
| **Unrelated bundling** | General-purpose helpers that happen to live here | `scripts/algebra.py`, `stats.py`, `linalg.py`, `numtheory.py` |

The first two layers are the **runtime stack**. The next two are the **improvement stack** (how the runtime evolves over time). The last is incidental.

## If you are…

- **Using the skill for a real task** — read `SKILL.md` only. Nothing else is load-bearing.
- **Running a meta-optimization session** — read `META-OPTIMIZATION.md` first, then `SKILL.md`. The frozen ancestors and corpus may also be relevant.
- **Adding a new design feature to FLO** — propose it as a new gene in `META-OPTIMIZATION.md` Section 4, then run a meta-optimization session to evaluate it competitively against existing variants.
- **Adding a benchmark task** — append to `training-corpus/CORPUS.md` and bump its version per the stability contract at the top of that file.
- **Investigating why FLO produces different outputs across versions** — diff snapshots in `training-corpus/evaluation-log/` (once the validator is in place); fall back to running both versions manually on the same corpus task.
