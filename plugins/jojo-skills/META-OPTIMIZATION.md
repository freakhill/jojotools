# jojo-skills — periodic meta-optimization (keeping the process skills evolving)

The 10 process/workflow skills — systematic-debugging, verification-before-completion, brainstorming,
test-driven-development, using-git-worktrees, writing-plans, executing-plans, subagent-driven-development,
init-memory, init-repo — are GPLv3 clean-room originals (authored 2026-06-21 from a deep cross-model `ayo`
pass). They are meant to **evolve** via periodic FLO meta-optimization. Freeze nothing.

## Design invariant — what "better" means here
A process skill is better when it changes a FRONTIER agent's behaviour more reliably with LESS text.
Score every revision on:
1. **GATE** — does it state the one load-bearing gate unmissably? (reproduce-before-fix; run-the-check-before-done; design-before-code; red-with-a-meaningful-failure; verify-before-check; …)
2. **LEAN / OPUS-FIT** — zero remedial hand-holding a frontier host already does; zero enterprise / multi-agent-CI bloat (bare-repo hubs, AST context bundles, per-worktree port maps, orphan memory branches). Every line earns its place. Target ≤ ~60 lines.
3. **CONVENTION-FIT** — encodes jojo's actual patterns (`.worktrees/`, `specs/<NNNN>`, two-stage review, 3-layer memory, private+`~/workspace` repos).
4. **NON-OBVIOUS** — keeps the 1-2 things even a strong model skips under momentum; cuts the obvious.
5. **CLEAN-ROOM / GPLv3** — original prose; never derived from third-party skill text.

## Baseline + corpus
- Research design note + raw cross-model lanes: `~/workspace/skills-research/` (`DESIGN-NOTE.md`, `disc-*.md`, `wf-*.md`).
- Ground truth is the canonical literature (Beck, Zeller, Agans, Fowler, Meyer, Brooks, the Design Council), not any plugin.
- Behavioural test: give a frontier agent a gameable task that tempts skipping the gate, with vs without the skill; blind-judge whether the discipline was actually followed.

## How to run a cycle (per skill or batched) — via feedback-loop-optimization
1. **Worker lane(s)** propose a revised `SKILL.md`; lens = "tighter gate / fewer lines / sharper non-obvious".
2. **Evaluator** (cross-family, anti-sycophancy — the Kimi+Opus K=2 default) scores against the 5-criterion rubric; penalise length and remedial content; reward an unmissable gate.
3. Adopt the winner only if it beats the incumbent on the rubric AND is ≤ incumbent length (or justifies the delta).
4. *(higher confidence)* run the eb8-matrix-style behavioural harness for the skill's discipline.
5. Bump `plugin.json` version; scoped commit; rebuild + push jojotools.

## Cadence
Monthly, or when: (a) a skill misfires in real use, (b) the **host model generation changes** — re-tune for the new floor, because what counts as "remedial" shifts upward, or (c) a new canonical practice emerges. A scheduled monthly trigger opens a meta-opt pass (see the periodic FLO routine).

## Provenance
Clean-room 2026-06-21 — `ayo`: Gemini-3.1-pro + DeepSeek-V4-Pro + Kimi-K2.7 + GLM-5.1 + Opus-4.8 host. GPLv3
(`LICENSE`, `NOTICE`) — jojo's own IP, relicensable at will precisely because nothing was lifted.
