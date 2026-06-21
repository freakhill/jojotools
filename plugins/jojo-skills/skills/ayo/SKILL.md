---
name: ayo
description: 'Use when you want to mine hard-earned lessons from an external mature system, standard, or body of literature (e.g. "are there lessons we can learn from CBOR / the JVM / Hydro?", "what did X get right or wrong that applies to us?", "research Y in this style") and assess their pertinence to the current project. Runs several independent model families in parallel as blind research lanes, then compiles, pertinence-triages, and lands a research-derived design note. Distinct from feedback-loop-optimization: FLO scores/selects a specific artifact; this MINES and TRIAGES external prior art.'
version: 0.1.0
---

# ayo — Cross-Model Research

Mine the hard-earned lessons of an external mature system (a standard, a runtime, a research line, a deployed product) and triage them for what genuinely applies to *this* project. The point of running several independent model families is that one model's blind spots don't survive contact with another's — the same anti-sycophancy logic as cross-family FLO judging, applied to research instead of scoring.

**Announce at start:** "Running a cross-model research pass on <target>."

## When to use / when not

- **Use** when there is a *body of prior art* with decades of hard-won lessons bearing on a current open question — "what can we learn from X?", "what did X get right/wrong for our case?", "research X in the same style." You are *learning*, not *choosing*.
- **Don't use** (use `feedback-loop-optimization` instead) when you have candidate *artifacts/designs* to score and select. If a mined lesson implies a genuinely contested design decision, finish this pass, then hand that one decision to a FLO.
- **Don't use** for a single-fact lookup or current-API docs (use search / context7).

## The flow

### 0 — Frame (before spawning anything)
Write down three things and confirm the target with the user if it's ambiguous:
- **Corpus**: the external system(s) to mine. Pick targets rich in *hard-won* lessons relevant to an open question, not encyclopedic overviews.
- **Project surfaces**: the concrete parts of *our* design each lesson will be triaged against (name them — e.g. "the merge model", "the effect system", "the replay log"). Pull these from existing design docs so you don't re-derive what's already pinned.
- **Pertinence question**: the one sentence each lesson must answer ("…applicable to our case?").

### 1 — Fan out blind research lanes (parallel)
Spawn one lane per independent model **family**, each with the *same* project brief and the *same* output contract, none seeing another's output:
- **Host (you, the orchestrator's family)** — mine from your own knowledge.
- **Gemini** (Google) — `ai-router` `or_ask(model: "google/gemini-3.1-pro-preview", host_token_pressure: true)`; generous `max_tokens`.
- **Kimi** (Moonshot) — the `kimi` CLI out-of-process (clean cwd), or `kimi_*` MCP tools after one `kimi_status` (key `set ✓`).

Cross-family = independent vendors, so blind spots don't correlate. If a family is unavailable, proceed with the rest and say so in the method footer. **Privacy (hard lines):** ZDR / no-training routes only; never route `anthropic/*` or `moonshotai/*` through OpenRouter; Gemini goes via `ai-router`.

**Output contract — every lane, every lesson:**
```
LESSON:    <imperative, phrased for OUR project>
EVIDENCE:  <the concrete external mechanism + the hard-won lesson behind it>
RELEVANCE: <how it maps to a NAMED project surface; + any hard constraint it must respect>
```
Instruct each lane: prioritize **non-obvious + specifically actionable**; be critical and concrete, not generic; group under headings; aim for a stated count (typically 14–20).

### 2 — Compile (orchestrator only)
Merge the lanes into one corpus. Tag each lesson by **family agreement** — cross-model *consensus* (high confidence) vs *single-model-unique* (higher novelty, higher risk). **Synthesize, don't concatenate**: de-dup overlapping lessons, and where families *contradict*, surface it and resolve or flag it.

### 3 — Pertinence-triage
Rate every lesson against the named project surfaces:
- **HIGH** — native fit / mostly-free given our architecture / connects to an open question or an already-decided piece; non-obvious. Act on these.
- **MEDIUM** — actionable but needs design work, or secondary.
- **DEFERRED / LOW** — generic, already-known, or only relevant to a future phase. Name it, don't act.

Discard the generic and the already-pinned. Keep what is non-obvious *and* actionable. If a HIGH lesson implies a contested decision, note it as a FLO hand-off.

### 4 — Land a research-derived design note
Write to `docs/spec/design/<YYYY-MM-DD>-<topic>.md` (or the project's design-doc convention). Structure:
- **Headline** — the 1–2 load-bearing insights, stated plainly.
- **Triaged lessons** — grouped by theme, marked HIGH / MEDIUM / DEFERRED; each as a tight LESSON/EVIDENCE/RELEVANCE.
- **Actionables** — numbered, each pointing at a project surface.
- **Net** — one paragraph.
- **Method footer** — the families used + routing (so the provenance and any unavailable lane are on record).

Commit atomically (scoped to the new doc). Then update project memory with the load-bearing decisions so the next session doesn't re-litigate them.

## Notes
- The orchestrator stays the synthesizer; lanes only ever *propose*. Never let a lane both research and triage in the same context.
- Token economy: the research lanes are the expensive part — give each a complete brief once and don't re-spawn. Offload to flat-rate Kimi/GLM where it fits.
- This skill pairs with `feedback-loop-optimization` (decide a contested lesson) and `writing-plans` (turn an actionable into an implementation plan).
