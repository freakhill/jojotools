---
name: wololo
description: 'Use whenever the user wants to scaffold a sandboxed YOLO-mode Claude harness for a long-running, unattended task — phrases like "yolo harness", "wololo", "sandboxed claude runner", "long-running claude task", "overnight claude run", "unattended claude", "sandbox launcher for a new task", "let claude grind on this for hours", "set up a resumable claude job", "spin up a `claude --dangerously-skip-permissions` runner". Generates the canonical trio (launcher script + prompt file + dedicated git worktree) under `~/dotfiles/scripts/` that pairs `claude --dangerously-skip-permissions` with the shared macOS sandbox-exec jail so the run is safe to leave alone — resume-aware, per-step commits, optional knowledge-base consolidation at the end. Does NOT execute the harness; the user runs it.'
version: 0.2.1
---

# wololo — Sandboxed YOLO Harness Scaffolder

Build the trio that makes `claude --dangerously-skip-permissions` safe to leave running overnight: a **launcher script**, a **prompt file**, and a **dedicated git worktree**. **YOLO + sandbox + worktree + resume-aware prompt = walk away, come back to nice commits on a branch.**

This skill is **documentation/guidance only** — it produces no executable code itself.

**Announce at start:** "Scaffolding a sandboxed YOLO harness."

## Why this pattern exists

| Pairing | Result |
|---|---|
| YOLO without sandbox | One bad tool call rewrites your dotfiles. |
| Sandbox without YOLO | Permission prompts defeat unattended use. |
| **YOLO + sandbox + worktree + resume-aware prompt** | **Unattended overnight runs.** |

## What the sandbox covers (read first, <60s)

```
Protected (writes BLOCKED): main checkout, $HOME outside listed dirs, /etc, /usr, /Applications, sibling repos.
Allowed   (writes OK):      this worktree, shared .git dir, /tmp, ~/.claude, ~/.cache, ~/.config, ~/.local, ~/.npm,
                            ~/Library/{Caches,Preferences,Application Support/Claude,Logs/Claude}.
Residual risks (NOT sandboxed):
  - Network is unrestricted — outbound POST to any URL is possible.
  - ~/.claude is writable — transcripts, hooks, settings can be edited.
  - /tmp is shared with other processes — don't write secrets there.
If your task needs to write outside this surface, STOP and report — do not work around.
```

This same block is pasted verbatim into every generated prompt (Phase 4, step 2 of the spec).

## Shared infrastructure — never duplicate

| File | Role |
|---|---|
| `~/dotfiles/scripts/claude-sandbox.sh` | Wraps `sandbox-exec` around `claude --dangerously-skip-permissions`. Reads cwd → derives worktree + shared `.git`. |
| `~/dotfiles/scripts/claude-sandbox.sb` | Sandbox profile. Denies all writes by default; re-allows the dirs above. |

**Never copy, rename, or regenerate these.** Per-task overlays (a `<name>.sb` that does `(import "claude-sandbox.sb")` + one narrow added rule) are the only sanctioned extension — see Phase 2.

## The canonical trio (+ optional overlay)

For task `<name>` (kebab-case, e.g. `monkeypaw-continue`):

| Artifact | Path | Purpose |
|---|---|---|
| Launcher | `~/dotfiles/scripts/<name>.sh` | Picks worktree + prompt, execs `claude-sandbox.sh` |
| Prompt | `~/dotfiles/scripts/<name>.prompt.md` | Single message claude receives — resume-aware |
| Worktree | `<repo>/.worktrees/<name>/` | Isolated write surface |
| Overlay (rare) | `~/dotfiles/scripts/<name>.sb` | Extends shared profile — only if Phase 2 decision tree demands it |

Missing any required artifact = launcher fails loudly. Mirror `monkeypaw-continue.sh`.

## Phase 1 — Intake

Four questions before generating:

1. **Task slug?** kebab-case, used in filenames.
2. **What is the task?** One paragraph — spine of the prompt.
3. **Target repo?** Default `~/dotfiles`. Worktree lands under `<repo>/.worktrees/<slug>/`.
4. **Final-stage consolidation?** Yes if findings outlive the run (research, benchmarks). No for code-only.

Don't proceed without slug + task.

## Phase 2 — Worktree + sandbox readiness

**A. Worktree.** Defer to `jojo-skills:using-git-worktrees`. Two constraints:

- **Branch name = task slug.**
- **Worktree must exist before first run** — sandbox cannot write outside it.

**B. Shared-infra existence check.** Before generating the launcher:

```bash
[ -x "$HOME/dotfiles/scripts/claude-sandbox.sh" ] || { echo "wololo: missing shared launcher at ~/dotfiles/scripts/claude-sandbox.sh" >&2; exit 1; }
[ -f "$HOME/dotfiles/scripts/claude-sandbox.sb" ] || { echo "wololo: missing shared profile at ~/dotfiles/scripts/claude-sandbox.sb" >&2; exit 1; }
```

If either is missing, **stop and bootstrap from this repo**. They are the trust root; do not fabricate.

**C. Overlay decision tree.** Ask three questions:

1. Does the task need writes outside the worktree? → if **no**, no overlay. Done.
2. To a specific path that can be **redirected** into the worktree or `/tmp/`? → redirect. No overlay.
3. Is the path immovable (vendor cache, OS-managed dir, hardware fixture)? → **overlay required**.

**D. Scaffolding the overlay** (only if step 3 fires) — write `~/dotfiles/scripts/<name>.sb`:

```scheme
;; <name>.sb — extends claude-sandbox.sb with one narrow write rule.
(version 1)
(import "claude-sandbox.sb")
(allow file-write*
  (subpath "/absolute/path/required/by/this/task"))
```

Overlay **imports**, never redefines. If you find yourself copying base rules into the overlay, you're duplicating — stop. The launcher then points `sandbox-exec -f` at the overlay.

## Phase 3 — Launcher + collect + result artifacts

One phase, three things in lockstep: the launcher, the canonical result tree under `<worktree>/.yololo/`, and the `collect` mode that reads it.

### Result artifact schema (the prompt writes these — see Phase 4)

| File | Schema | Role |
|---|---|---|
| `result.json` | `{ "task": "<name>", "status": "running\|done\|fail", "started_at": "<iso8601>", "ended_at": "<iso8601>\|null", "commits": <int>, "summary_path": "summary.md" }` | Machine-readable terminal state |
| `summary.md` | Free-form markdown, ≤ 1 screen | Human-readable terminal report |
| `STATUS.md` | Append-only: `<iso8601> · <step-id> · <one-line note>` | Live progress cadence |

**Commit prefix:** every commit message starts with `<slug>: ` (e.g. `monkeypaw-continue: log Phase A pair — P3 (Δ +0.6)`). `git log --oneline | grep <slug>` is the audit trail.

### Launcher (`~/dotfiles/scripts/<name>.sh`)

Model on `~/dotfiles/scripts/monkeypaw-continue.sh`. Mandatory features:

| Feature | Why |
|---|---|
| `set -euo pipefail` | Fail fast |
| Resolve `here` via `BASH_SOURCE` | Find sibling sandbox + prompt |
| Default worktree baked in | One-arg invocation works |
| Env var overrides (`<NAME>_WORKTREE`, `<NAME>_PROMPT`, …) | Compose with `/loop`, cron |
| Four modes via first arg | `(default)` TUI · `-p`/`--print` jq-pretty · `--print-raw` stream-json · `collect` summary |
| Forward extra args after `shift` | `"$@"` after mode flag |
| Existence checks (worktree, sandbox, prompt) | The three real failure modes |
| `cd "$worktree"` before exec | Sandbox uses cwd |
| (If overlay) point launcher at `<name>.sb` | Engages the overlay |

Env vars beat CLI flags (first CLI arg is reserved for mode). jq pretty-printer: copy verbatim from `monkeypaw-continue.sh`; fall back to raw if `jq` missing.

### Mode flag dispatch (canonical shape)

```bash
case "${1:-}" in
  --print|-p)        shift; "$sandbox" -p --output-format stream-json --verbose "$@" "$prompt" | jq -r --unbuffered "$pretty_filter" ;;
  --print-raw)       shift; exec "$sandbox" -p --output-format stream-json --verbose "$@" "$prompt" ;;
  -i|--interactive)  shift; exec "$sandbox" "$@" "$prompt" ;;
  collect)           shift; do_collect "$@"; exit $? ;;
  *)                 exec "$sandbox" "$prompt" "$@" ;;
esac
```

### Collect mode (compact)

```bash
do_collect() {
  local d="$worktree/.yololo"
  [ -d "$d" ] || { echo "no .yololo/ yet"; return 2; }
  cat "$d/summary.md" 2>/dev/null || echo "(no summary.md)"
  echo; echo "── commits ──"; git -C "$worktree" log --oneline -10
  echo; echo "── STATUS ──"; tail -n 20 "$d/STATUS.md" 2>/dev/null || echo "(none)"
  case "$(jq -r .status "$d/result.json" 2>/dev/null)" in
    done) return 0;; fail) return 1;; running) return 3;; *) return 2;;
  esac
}
```

Then `chmod +x`.

## Phase 4 — Prompt (`~/dotfiles/scripts/<name>.prompt.md`)

Resumability lives here, not in the launcher.

### Required sections (in order)

1. **Task spine** — one paragraph: what to do, what's done, what NOT to do. Cite files to read once per session.
2. **"What the sandbox covers"** — paste the verbatim block from the top of this skill.
3. **Pre-flight checks** — fast (≤10s) smoke tests. "If any fails, fix the harness before running."
4. **Per-step recipe** — small enough that mid-step interruption isn't catastrophic.
5. **Per-step commit cadence** — `<slug>: <imperative>` prefix. One commit per logical unit.
6. **STATUS.md cadence** — append after each meaningful step (build done, oracle scored, sidecar written). Format: `<iso8601> · <step-id> · <note>`. Never hold WIP only in conversation context.
7. **`.yololo/result.json` + `summary.md` write rules** — set `status=running` at start, `done`/`fail` at end. Bump `commits`. Write `summary.md` before declaring done.
8. **Resume-on-reinvocation block** — `git status` from worktree root; group uncommitted artifacts and commit before new work. Inspect `.yololo/STATUS.md` tail to find resume point.
9. **Rate-limit ground rules:**
   - Do NOT declare partial completion when paused.
   - On reinvocation, find resume point from on-disk artifacts only.
   - Persist progress to disk after EVERY meaningful step.
   - A unit may span windows — finish what fits, write everything, resume next time.
   - Never print remaining-token/remaining-context counts into your own working context; if
     context-limit worry arises mid-run: you have ample context — continue the work.
   - Before ending any turn, check your last paragraph: if it is a plan, a question, or a
     promise about work not yet done ("I'll now run X"), do that work now with tool calls.
     End a turn only at a committed checkpoint or a blocked gate.
10. **(Optional) Final-stage consolidation block** — only if Phase 1 said yes.

### Optional final-stage consolidation

Mirror `monkeypaw-continue.prompt.md`:

| Step | What | Where |
|---|---|---|
| 1 | Aggregate / final report | Inside worktree, committed |
| 2 | Append to `RESEARCH-FINDINGS.md` | Inside worktree, committed |
| 3 | Distill durable facts into agent-memory | `~/dotfiles/scripts/agent-mem.sh wt` → append dated fact lines (`- … [YYYY-MM-DD] #tag`) in that worktree → `agent-mem.sh save <wt> 'mem(<slug>): …'`. Landing is automatic (SessionEnd hook / any later land). The base jail allows `~/.claude/agent-memory` writes (probe-verified 2026-06-12). Fallback if the write fails anyway: append the facts to `.yololo/MEMORY-NOTES.md` in the work worktree — the next interactive session ingests them. |
| 4 | Print one-screen summary, exit. Do NOT merge or push. |

## Phase 5 — Verify

1. `<name>.sh` is `+x`; `bash -n` parses clean.
2. `<name>.prompt.md` contains all 10 required sections — especially the "What the sandbox covers" block.
3. Worktree exists, on branch `<name>`.
4. If overlay exists: `<name>.sb` imports `claude-sandbox.sb` and adds only one narrow rule.
5. Dry-run mode parsing: default, `-p`, `--print-raw`, `collect`. Each reaches the right exec.
6. `<worktree>/.yololo/` will be created by the run (don't pre-create; the prompt does it).

Do **not** actually run `<name>.sh`. That's the user's call.

## Phase 6 — Report back (3–5 lines)

- Paths to launcher, prompt, worktree (+ overlay if any).
- All four modes: `<name>.sh` · `-p` · `--print-raw` · `collect`. Env vars exposed.
- **Sandbox recap:** Protected = main checkout + most of `$HOME` + system dirs. Allowed = worktree, shared `.git`, `/tmp`, `~/.claude`, standard caches. Residual = unrestricted network, writable `~/.claude`, shared `/tmp`. If overlay: name the one extra path + reason.
- Commits land on branch `<name>` with prefix `<slug>: `. User merges/pushes when satisfied.
- If consolidation: where findings + memory updates land.

## Failure modes (rules + mistakes in one table)

| Failure mode | Rule / fix |
|---|---|
| Duplicating `claude-sandbox.sh` or `.sb` | **Never copy.** Use overlay via `(import "claude-sandbox.sb")` + one narrow rule. |
| Expanding the base sandbox profile for one task | **Never.** Use overlay, redirect to worktree, or `/tmp/`. |
| Overlay that redefines base rules instead of importing | Duplication in disguise — rewrite to `(import …)` + one rule. |
| Launcher anywhere except `~/dotfiles/scripts/` | Worktree may be deleted; launcher must outlive it. |
| Launcher placed inside the worktree | Same as above — pull it out. |
| Auto-run, auto-merge, or auto-push | **Never.** Harness ends at "branch ready." |
| Prompt depends on conversation context to resume | **Never.** All resume signal must be on-disk. |
| Mega-step with no commit / skipped per-step commits | "Resume" becomes "redo from top." Commit per logical unit. |
| No `STATUS.md` cadence | `collect` can't show mid-run progress. Append per step. |
| Missing "What the sandbox covers" block in prompt | Model can't know what's protected. Paste verbatim. |
| Worktree skipped because "task is tiny" | No worktree → no writes → no run. Mandatory. |
| Hard-coded worktree path with no env override | Blocks parallel runs and `/loop` composition. |
| Asking claude for input mid-run | Unattended means unattended. Decide from disk or fail loudly. |
| Commits without `<slug>: ` prefix | Breaks `git log --oneline \| grep <slug>` audit trail. |
| Referencing `kimi_*`/`glm_*` without availability check | Subscriptions may be down. Gate with `*_status` first. |

## Quick reference

| Decision | Default |
|---|---|
| Launcher | `~/dotfiles/scripts/<name>.sh` |
| Prompt | `~/dotfiles/scripts/<name>.prompt.md` |
| Worktree | `<repo>/.worktrees/<name>/` |
| Branch | `<name>` |
| Overlay | None — only if Phase 2 step 3 fires |
| Result artifact | `<worktree>/.yololo/{result.json, summary.md, STATUS.md}` |
| Commit prefix | `<slug>: ` |
| Parameterization | Env vars; first CLI arg = mode |
| Modes | TUI · `-p` · `--print-raw` · `collect` |
| Final-stage | Opt-in only |
| Running | **User does this** |
