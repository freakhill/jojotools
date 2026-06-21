#!/usr/bin/env python3
"""
validate_corpus.py — FLO corpus validator and drift detector.

Runs three checks on a SKILL.md candidate against the frozen training corpus:

  1. Static lint — deterministic regex checks of protocol invariants (no LLM).
  2. Decision check — for each of the 30 corpus tasks, invokes Kimi with the
     candidate SKILL.md as context and asks it to apply Phase 0 (Pre-flight)
     only, returning structured JSON with the protocol's decisions (compat,
     ARTIFACT/TARGET/SUCCESS, vagueness, P-tier).
  3. Logarithmic ancestor diff — writes the new snapshot to
     training-corpus/evaluation-log/ and compares it against a logarithmic
     sample of historical snapshots ({1, 2, 4, 8, 16, …} versions back +
     the oldest one) so collective slow drift surfaces against distant
     ancestors even when consecutive-version diffs look clean.
     Drift is TIERED so signal isn't drowned in noise (failure #10): the
     "Decision drift?" verdict fires ONLY on the binary `compatible` field;
     graded ratings (compat_score/vagueness/p_tier) flip ±1 run-to-run and are
     reported separately to be calibrated against the self-consistency noise
     floor (`--reps N` re-runs the SAME config); free-text extraction
     (artifact/target/success) is reported as informational wording, not drift.

Output: a Markdown report (to stdout or --report path). Exit 0 always —
this is advisory tooling, not a gate.

Usage:
  python validate_corpus.py
  python validate_corpus.py --skill path/to/SKILL.md --report out.md
  python validate_corpus.py --no-llm          # static lint only
  python validate_corpus.py --no-write        # don't archive the snapshot
  python validate_corpus.py --workers 4       # concurrency for kimi calls
  python validate_corpus.py --tasks P2,E2,W2  # subset of corpus IDs

Requires: Python 3.11+, kimi CLI on PATH (for --no-llm omit), git (optional).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SKILL = SKILL_DIR / "SKILL.md"
CORPUS_MD = SKILL_DIR / "training-corpus" / "CORPUS.md"
LOG_DIR = SKILL_DIR / "training-corpus" / "evaluation-log"

KIMI_TIMEOUT_S = 300
DEFAULT_WORKERS = 8


# ── Corpus parsing ──────────────────────────────────────────────────────────

@dataclass
class Task:
    task_id: str
    title: str
    domain: str
    difficulty: str
    type: str
    estimated_nodes: str
    text: str  # full task spec (description + constraints + deliverables)


_TASK_HEADER_RE = re.compile(r"^###\s+([A-Z]+\d+)\s+[—-]\s+(.+?)\s*$", re.MULTILINE)
_META_LINE_RE = re.compile(
    r"\*\*Domain:\*\*\s*([^|]+)\|\s*\*\*Difficulty:\*\*\s*([^|]+)\|\s*\*\*Type:\*\*\s*(\S+)"
)
_NODES_LINE_RE = re.compile(r"\*\*Estimated nodes:\*\*\s*(\S+)")


def parse_corpus(md: str) -> list[Task]:
    """Split CORPUS.md into task blocks. Stops at the Evaluation Results Log section."""
    cutoff = md.find("## Evaluation Results Log")
    if cutoff != -1:
        md = md[:cutoff]

    headers = list(_TASK_HEADER_RE.finditer(md))
    tasks: list[Task] = []
    for i, m in enumerate(headers):
        task_id, title = m.group(1), m.group(2).strip()
        body_start = m.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(md)
        body = md[body_start:body_end].strip()

        meta = _META_LINE_RE.search(body)
        nodes = _NODES_LINE_RE.search(body)
        if not meta:
            continue  # malformed task block; skip silently
        domain = meta.group(1).strip()
        difficulty = meta.group(2).strip()
        type_ = meta.group(3).strip()
        estimated_nodes = nodes.group(1).strip() if nodes else "?"

        tasks.append(
            Task(
                task_id=task_id,
                title=title,
                domain=domain,
                difficulty=difficulty,
                type=type_,
                estimated_nodes=estimated_nodes,
                text=body,
            )
        )
    return tasks


# ── Static lint ─────────────────────────────────────────────────────────────

@dataclass
class LintCheck:
    id: str
    description: str
    passed: bool


# WHY: each lint check encodes one Section-3-rubric invariant that can be
# verified deterministically without an LLM. Regexes intentionally err on the
# side of permissive so wording tweaks don't trigger false failures — drift
# detection on substance is the LLM-based decision check's job.
_LINT_CHECKS: list[tuple[str, str, re.Pattern]] = [
    ("C1.1", "Phase 0 (Pre-flight) heading present",
     re.compile(r"##\s*Phase\s*0\b", re.IGNORECASE)),
    ("C1.2", "Phase 1 (Setup) heading present",
     re.compile(r"##\s*Phase\s*1\b", re.IGNORECASE)),
    ("C1.3", "Phase 2 (Baseline) heading present",
     re.compile(r"##\s*Phase\s*2\b", re.IGNORECASE)),
    ("C1.4", "Phase 3 (Evolutionary Loop) heading present",
     re.compile(r"##\s*Phase\s*3\b", re.IGNORECASE)),
    ("C1.5", "Phase 4 (Report) heading present",
     re.compile(r"##\s*Phase\s*4\b", re.IGNORECASE)),
    ("C1.6", "Stuck condition uses a streak counter",
     re.compile(r"(no_improve_streak|streak[^a-z]{0,20}(>=|≥|>)\s*\d|consecutive\s+gen)", re.IGNORECASE)),
    ("C1.7", "Worker/evaluator role isolation declared",
     re.compile(r"(workers?.{0,80}evaluators?|evaluators?.{0,80}workers?).{0,200}(isolat|separat|never\s+(merg|share))", re.IGNORECASE | re.DOTALL)),
    ("C1.8", "Rubric lock / immutability declared",
     re.compile(r"rubric[^.\n]{0,40}(lock|immutab|freez)", re.IGNORECASE)),
    ("C2.1", "ARTIFACT extracted in Phase 0",
     re.compile(r"\bARTIFACT\b")),
    ("C2.2", "TARGET extracted in Phase 0",
     re.compile(r"\bTARGET\b")),
    ("C2.3", "SUCCESS extracted in Phase 0",
     re.compile(r"\bSUCCESS\b")),
    ("C2.4", "Independence test referenced",
     re.compile(r"independence", re.IGNORECASE)),
    ("C2.5", "Vagueness 1/2/3 scale referenced",
     re.compile(r"vagueness", re.IGNORECASE)),
    ("C2.6", "Fixture spec minimum N>=3",
     re.compile(r"(N\s*[=≥>]\s*3|min(imum)?\s*N\s*[=:]?\s*3|≥\s*3\s+fixtures?)", re.IGNORECASE)),
    ("C3.1", "Population P>=4 referenced",
     re.compile(r"\bP\s*=\s*[4-9]|\bP\s*=\s*1[0-6]\b|default\s+P\s*=\s*6", re.IGNORECASE)),
    ("C3.2", "Binary tournament selection (k=2)",
     re.compile(r"(binary\s+tournament|tournament[^.\n]{0,40}k\s*=\s*2)", re.IGNORECASE)),
    ("C3.3", "Elitism present",
     re.compile(r"elit", re.IGNORECASE)),
    ("C3.4", "Genome registry / genome tags",
     re.compile(r"genome", re.IGNORECASE)),
    ("C3.5", "Expansion or explorer mechanism",
     re.compile(r"(expansion|explorer|stagnation)", re.IGNORECASE)),
    ("C3.6", "MAP-Elites or diversity archive",
     re.compile(r"(MAP[- ]Elites|diversity\s+archive)", re.IGNORECASE)),
]


def run_lint(skill: str) -> list[LintCheck]:
    return [LintCheck(cid, desc, bool(pat.search(skill))) for cid, desc, pat in _LINT_CHECKS]


# ── Decision check (LLM) ────────────────────────────────────────────────────

_PROMPT_TEMPLATE = """You are executing the FLO (Feedback Loop Optimization) protocol defined in the SKILL.md below.

Apply ONLY Phase 0A (Compatibility) and Phase 0B (Task Clarification), plus the Phase 1 Population Tier selection, to the task described after the protocol. Do NOT run Phase 2 or later. Do NOT propose worker prompts. Do NOT execute any loop.

Output a single JSON object — and nothing else, no markdown fence, no commentary. The object must have exactly these fields:

  compatible            (boolean) true if Phase 0A compat_score >= 2, else false
  compat_score          (integer 0..5) Phase 0A score
  compatibility_reason  (string, one sentence) which factors passed/failed
  artifact              (string) the ARTIFACT extracted in Phase 0B
  target                (string) the TARGET extracted in Phase 0B
  success               (string) the SUCCESS definition extracted in Phase 0B
  vagueness             (integer 1|2|3) Phase 0B vagueness score
  p_tier                (integer 1|2|3|4) the population tier you would assign

=== SKILL.md (the FLO protocol) ===
{skill}
=== End SKILL.md ===

=== Task ===
ID: {task_id}
Title: {title}
Domain: {domain} | Difficulty: {difficulty} | Type: {type}
Estimated nodes: {nodes}

{body}
=== End task ===

Output the JSON object now."""


def build_prompt(skill: str, task: Task) -> str:
    return _PROMPT_TEMPLATE.format(
        skill=skill,
        task_id=task.task_id,
        title=task.title,
        domain=task.domain,
        difficulty=task.difficulty,
        type=task.type,
        nodes=task.estimated_nodes,
        body=task.text,
    )


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> dict | None:
    """Pull the largest brace-delimited block and parse it. Returns None on failure."""
    m = _JSON_OBJECT_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        # WHY: kimi sometimes emits fenced JSON with trailing prose; try
        # a stricter slice from the first '{' to the last matching '}'.
        s = m.group(0)
        for end in range(len(s), 0, -1):
            try:
                return json.loads(s[:end])
            except json.JSONDecodeError:
                continue
    return None


def call_kimi(prompt: str) -> tuple[str, str | None]:
    """Returns (stdout, error). If error is non-None, stdout is empty."""
    try:
        result = subprocess.run(
            ["kimi", "-p", prompt, "--quiet"],
            capture_output=True,
            text=True,
            timeout=KIMI_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return "", f"timeout after {KIMI_TIMEOUT_S}s"
    except FileNotFoundError:
        return "", "kimi CLI not found on PATH"
    if result.returncode != 0:
        return "", f"kimi exited {result.returncode}: {result.stderr.strip()[:200]}"
    return result.stdout, None


def run_one_decision(skill: str, task: Task) -> dict:
    prompt = build_prompt(skill, task)
    out, err = call_kimi(prompt)
    base = {
        "task_id": task.task_id,
        "domain": task.domain,
        "difficulty": task.difficulty,
        "type": task.type,
        "estimated_nodes": task.estimated_nodes,
    }
    if err:
        return {**base, "error": err}
    parsed = extract_json(out)
    if parsed is None:
        return {**base, "error": "no parseable JSON", "raw": out[:500]}
    return {**base, **parsed}


def run_decisions(skill: str, tasks: list[Task], workers: int) -> list[dict]:
    rows: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        future_to_task = {ex.submit(run_one_decision, skill, t): t for t in tasks}
        for fut in concurrent.futures.as_completed(future_to_task):
            rows.append(fut.result())
    rows.sort(key=lambda r: r["task_id"])
    return rows


# ── Archive (snapshots + logarithmic ancestor selection) ────────────────────

_FLO_VERSION_RE = re.compile(r"^version:\s*(\S+)", re.MULTILINE)


def skill_metadata(skill_path: Path) -> tuple[str, str]:
    text = skill_path.read_text()
    m = _FLO_VERSION_RE.search(text)
    version = m.group(1) if m else "unknown"
    sha = hashlib.sha256(text.encode()).hexdigest()[:12]
    return version, sha


def git_short_sha() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=SKILL_DIR,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def snapshot_filename(flo_version: str, git_sha: str | None, skill_sha: str, ts: datetime) -> str:
    ts_str = ts.strftime("%Y-%m-%dT%H-%M-%SZ")
    sha_part = git_sha or f"sk{skill_sha[:7]}"
    return f"v{flo_version}__{sha_part}__{ts_str}.jsonl"


def write_snapshot(rows: list[dict], flo_version: str, skill_sha: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc)
    git_sha = git_short_sha()
    path = LOG_DIR / snapshot_filename(flo_version, git_sha, skill_sha, ts)
    header = {
        "_meta": True,
        "flo_version": flo_version,
        "skill_sha256_12": skill_sha,
        "git_short_sha": git_sha,
        "timestamp_utc": ts.isoformat(),
        "row_count": len(rows),
    }
    with path.open("w") as f:
        f.write(json.dumps(header) + "\n")
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return path


def load_snapshot(path: Path) -> tuple[dict, list[dict]]:
    """Returns (meta, rows). meta is empty dict if missing."""
    meta: dict = {}
    rows: list[dict] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("_meta"):
            meta = obj
        else:
            rows.append(obj)
    return meta, rows


def list_snapshots(log_dir: Path) -> list[Path]:
    if not log_dir.exists():
        return []
    paths = sorted(log_dir.glob("v*__*.jsonl"))
    return paths


def logarithmic_ancestors(snapshots: list[Path]) -> list[Path]:
    """
    Given snapshots ordered oldest -> newest (excluding the candidate),
    pick ancestors at offsets {1, 2, 4, 8, 16, ...} from the end, plus
    index 0 (oldest). Returns them ordered newest -> oldest, deduplicated.

    WHY: consecutive-version diffs miss slow collective drift where each
    individual step looks fine but ten steps add up to a meaningful shift.
    Comparing against exponentially-distant ancestors catches that.
    """
    n = len(snapshots)
    if n == 0:
        return []
    picked: list[int] = []
    offset = 1
    while offset <= n:
        picked.append(n - offset)
        offset *= 2
    if 0 not in picked:
        picked.append(0)
    picked = sorted(set(picked), reverse=True)  # newest-of-picks first
    return [snapshots[i] for i in picked]


# ── Diff ────────────────────────────────────────────────────────────────────

# Drift is tiered by how trustworthy a per-field disagreement is as a regression signal:
#   DECISION — the binary go/no-go; a change here is genuine drift worth investigating.
#   GRADED   — 0..5 / 1..3 / 1..4 LLM ratings; flip ±1 run-to-run (non-determinism), so a
#              disagreement is only "drift" if it exceeds the same config's self-consistency floor.
#   TEXT     — free-text extraction; wording always varies (paraphrase) — informational, NOT drift.
# Conflating the three is the eval-artifact trap (failure #10): the old detector flagged 30/30 tasks
# as "drift" when 0/30 had a decision change — text paraphrase + graded noise masquerading as signal.
_DECISION_FIELDS = ("compatible",)
_GRADED_FIELDS = ("compat_score", "vagueness", "p_tier")
_EXACT_FIELDS = _DECISION_FIELDS + _GRADED_FIELDS   # compared by exact match in fields_match
_TEXT_FIELDS = ("artifact", "target", "success")
_OVERLAP_THRESHOLD = 0.70


def _tier(fld: str) -> str:
    if fld in _DECISION_FIELDS:
        return "decision"
    if fld in _GRADED_FIELDS:
        return "graded"
    return "wording"


def _token_set(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def _text_similarity(a: str, b: str) -> float:
    ta, tb = _token_set(a), _token_set(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    return len(inter) / max(len(ta), len(tb))


def fields_match(field: str, a, b) -> bool:
    if a is None or b is None:
        return a == b
    if field in _EXACT_FIELDS:
        return a == b
    if field in _TEXT_FIELDS:
        return _text_similarity(str(a), str(b)) >= _OVERLAP_THRESHOLD
    return a == b


@dataclass
class TaskDisagreement:
    ancestor_label: str
    field: str
    candidate_value: object
    ancestor_value: object


@dataclass
class TaskDiff:
    task_id: str
    disagreements: list[TaskDisagreement] = field(default_factory=list)
    recent_drift: bool = False     # recent DECISION-field change (binary compatible) — the real signal
    recent_graded: bool = False    # recent GRADED churn — noisy ±1; calibrate vs the noise floor
    recent_wording: bool = False   # recent free-text rewording — informational, NOT drift

    @property
    def any_disagreement(self) -> bool:
        return bool(self.disagreements)

    def disagreements_in(self, fields) -> list:
        return [x for x in self.disagreements if x.field in fields]


def diff_candidate_against_ancestors(
    candidate_rows: list[dict],
    ancestors: list[tuple[Path, dict, list[dict]]],
) -> dict[str, TaskDiff]:
    """
    ancestors is a list of (path, meta, rows), newest-first.
    Returns task_id -> TaskDiff.
    """
    candidate_by_id = {r["task_id"]: r for r in candidate_rows}
    diffs: dict[str, TaskDiff] = {tid: TaskDiff(task_id=tid) for tid in candidate_by_id}

    fields_to_check = _EXACT_FIELDS + _TEXT_FIELDS

    for ancestor_idx, (path, meta, rows) in enumerate(ancestors):
        label = meta.get("flo_version") or path.stem
        anc_by_id = {r["task_id"]: r for r in rows}
        for tid, cand in candidate_by_id.items():
            if "error" in cand:
                continue
            anc = anc_by_id.get(tid)
            if anc is None or "error" in anc:
                continue
            for f in fields_to_check:
                if f not in cand or f not in anc:
                    continue
                if not fields_match(f, cand[f], anc[f]):
                    diffs[tid].disagreements.append(
                        TaskDisagreement(label, f, cand[f], anc[f])
                    )
                    if ancestor_idx < 2:
                        tier = _tier(f)
                        if tier == "decision":
                            diffs[tid].recent_drift = True
                        elif tier == "graded":
                            diffs[tid].recent_graded = True
                        else:
                            diffs[tid].recent_wording = True

    return diffs


def compute_noise_floor(rep_rows: list[list[dict]]) -> dict:
    """Self-consistency floor: run the SAME config N times and count, per structured field, how many
    tasks gave inconsistent values across the reps. Graded drift vs ancestors at or below this floor
    is run-to-run non-determinism, not genuine regression."""
    by_task: dict[str, dict[str, set]] = {}
    for rows in rep_rows:
        for r in rows:
            if "error" in r:
                continue
            t = by_task.setdefault(r["task_id"], {})
            for f in _DECISION_FIELDS + _GRADED_FIELDS:
                t.setdefault(f, set()).add(r.get(f))
    per_field = {f: 0 for f in _DECISION_FIELDS + _GRADED_FIELDS}
    for fields in by_task.values():
        for f, vals in fields.items():
            if len(vals) > 1:
                per_field[f] += 1
    return {"reps": len(rep_rows), "n_tasks": len(by_task), "per_field_unstable": per_field}


# ── Markdown report ─────────────────────────────────────────────────────────

def render_report(
    skill_path: Path,
    flo_version: str,
    skill_sha: str,
    git_sha: str | None,
    lint: list[LintCheck],
    candidate_rows: list[dict],
    ancestors: list[tuple[Path, dict, list[dict]]],
    diffs: dict[str, TaskDiff],
    snapshot_path: Path | None,
    noise_floor: dict | None = None,
) -> str:
    lines: list[str] = []
    ts = datetime.now(timezone.utc).isoformat()
    lines.append(f"# FLO Corpus Validation Report")
    lines.append("")
    lines.append(f"- Candidate: `{skill_path}` (v{flo_version}, sha256={skill_sha}, git={git_sha or 'n/a'})")
    lines.append(f"- Generated: {ts}")
    if snapshot_path:
        lines.append(f"- Snapshot written: `{snapshot_path.relative_to(SKILL_DIR)}`")
    lines.append("")

    # Lint
    lint_pass = sum(1 for c in lint if c.passed)
    lines.append(f"## Static lint — {lint_pass}/{len(lint)} passed")
    lines.append("")
    for c in lint:
        mark = "PASS" if c.passed else "FAIL"
        lines.append(f"- [{mark}] **{c.id}** — {c.description}")
    lines.append("")

    # Decision check status
    if not candidate_rows:
        lines.append("## Decision check — skipped (no LLM run)")
        lines.append("")
        return "\n".join(lines)

    errors = [r for r in candidate_rows if "error" in r]
    ok = [r for r in candidate_rows if "error" not in r]
    lines.append(f"## Decision check — {len(ok)}/{len(candidate_rows)} tasks scored")
    if errors:
        lines.append("")
        lines.append("Errors:")
        for r in errors:
            lines.append(f"- `{r['task_id']}` — {r['error']}")
    lines.append("")

    # Ancestor list
    if not ancestors:
        lines.append("## Drift comparison — skipped (no prior snapshots)")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"## Drift comparison against {len(ancestors)} ancestor(s)")
    lines.append("")
    lines.append("Logarithmic sample of historical snapshots (newest first):")
    lines.append("")
    for path, meta, rows in ancestors:
        ver = meta.get("flo_version", "?")
        ts_anc = meta.get("timestamp_utc", "?")
        lines.append(f"- `v{ver}` — {len(rows)} rows — `{path.name}` ({ts_anc})")
    lines.append("")

    # Per-task table
    lines.append("### Per-task agreement matrix")
    lines.append("")
    lines.append("`compatible` is the binary go/no-go DECISION (the trustworthy drift signal); "
                 "`compat_score`/`vagueness`/`p_tier` are GRADED ratings (noisy ±1 run-to-run); "
                 "`artifact`/`target`/`success` are free-text extraction (wording varies — informational). "
                 "The `Decision drift?` verdict fires ONLY on a binary `compatible` change.")
    lines.append("")
    header_cells = ["Task"] + [f"v{m.get('flo_version','?')}" for _, m, _ in ancestors] + ["Decision drift?"]
    lines.append("| " + " | ".join(header_cells) + " |")
    lines.append("|" + "|".join(["---"] * len(header_cells)) + "|")
    for tid in sorted(diffs):
        d = diffs[tid]
        per_ancestor_marks = []
        for _, meta, rows in ancestors:
            label = meta.get("flo_version") or "?"
            ancestor_diffs = [x for x in d.disagreements if x.ancestor_label == label]
            if not ancestor_diffs:
                per_ancestor_marks.append("OK")
            else:
                fields = ",".join(sorted({x.field for x in ancestor_diffs}))
                per_ancestor_marks.append(f"DIFF({fields})")
        drift_flag = "**YES**" if d.recent_drift else "no"
        lines.append("| " + " | ".join([tid] + per_ancestor_marks + [drift_flag]) + " |")
    lines.append("")

    # Tiered drift classification (vs the 2 most-recent ancestors)
    n = len(diffs)
    dec = sum(1 for d in diffs.values() if d.recent_drift)
    grd = sum(1 for d in diffs.values() if d.recent_graded)
    wrd = sum(1 for d in diffs.values() if d.recent_wording)
    lines.append("### Drift classification (recent ancestors)")
    lines.append("")
    lines.append(f"- **DECISION drift** (binary `compatible`): **{dec}/{n}** — the trustworthy signal; "
                 f"non-zero = genuine regression to investigate.")
    lines.append(f"- GRADED churn (`compat_score`/`vagueness`/`p_tier`): {grd}/{n} — noisy ±1 LLM ratings; "
                 f"calibrate against the self-consistency noise floor (re-run the SAME config, `--reps N`) "
                 f"before treating as real.")
    lines.append(f"- WORDING changes (`artifact`/`target`/`success`): {wrd}/{n} — free-text extraction "
                 f"reworded; informational, NOT drift.")
    lines.append("")

    if noise_floor:
        nf = noise_floor
        lines.append(f"### Self-consistency noise floor (reps={nf['reps']}, SAME config)")
        lines.append("")
        lines.append("Tasks giving INCONSISTENT values across repeated runs of the identical SKILL.md — the "
                     "run-to-run non-determinism floor. GRADED drift vs ancestors at or below this floor is "
                     "noise, not genuine drift.")
        lines.append("")
        for f in _DECISION_FIELDS + _GRADED_FIELDS:
            lines.append(f"- `{f}` ({_tier(f)}): "
                         f"{nf['per_field_unstable'].get(f, 0)}/{nf['n_tasks']} tasks inconsistent across {nf['reps']} reps")
        lines.append("")

    # Drift details — DECISION + GRADED show value transitions; WORDING is id-listed (paraphrase noise)
    drifted = [d for d in diffs.values() if d.any_disagreement]
    if not drifted:
        lines.append("### Drift details — no disagreements")
        return "\n".join(lines)
    lines.append("### Drift details")
    lines.append("")
    for tier_name, tier_fields in (("DECISION", _DECISION_FIELDS), ("GRADED", _GRADED_FIELDS)):
        tier_tasks = [d for d in sorted(drifted, key=lambda x: x.task_id) if d.disagreements_in(tier_fields)]
        if not tier_tasks:
            lines.append(f"#### {tier_name} tier — none")
            lines.append("")
            continue
        lines.append(f"#### {tier_name} tier")
        for d in tier_tasks:
            for x in d.disagreements_in(tier_fields):
                lines.append(f"- `{d.task_id}` vs `v{x.ancestor_label}` — `{x.field}`: "
                             f"{x.ancestor_value} → {x.candidate_value}")
        lines.append("")
    wording_tasks = sorted({d.task_id for d in drifted if d.disagreements_in(_TEXT_FIELDS)})
    if wording_tasks:
        lines.append(f"#### WORDING tier (informational) — {len(wording_tasks)} task(s) reworded extraction")
        lines.append("")
        lines.append("- " + ", ".join(wording_tasks))
        lines.append("")

    return "\n".join(lines)


# ── Entry point ─────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--skill", type=Path, default=DEFAULT_SKILL, help="Path to SKILL.md (default: ../SKILL.md)")
    p.add_argument("--report", type=Path, default=None, help="Write Markdown report to this path (default: stdout)")
    p.add_argument("--no-llm", action="store_true", help="Skip the Kimi decision-check phase; static lint only")
    p.add_argument("--no-write", action="store_true", help="Do not append a snapshot to evaluation-log/")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"Concurrent kimi calls (default: {DEFAULT_WORKERS})")
    p.add_argument("--tasks", type=str, default=None, help="Comma-separated task IDs to restrict to (e.g. 'P2,E2,W2')")
    p.add_argument("--reps", type=int, default=1, help="Repeat the decision check N times on the SAME config to measure the self-consistency noise floor (default 1; rep 1 is archived)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    skill_path: Path = args.skill
    if not skill_path.exists():
        sys.stderr.write(f"error: SKILL.md not found: {skill_path}\n")
        return 1
    if not CORPUS_MD.exists():
        sys.stderr.write(f"error: CORPUS.md not found: {CORPUS_MD}\n")
        return 1

    skill_text = skill_path.read_text()
    all_tasks = parse_corpus(CORPUS_MD.read_text())
    if args.tasks:
        wanted = {t.strip() for t in args.tasks.split(",") if t.strip()}
        tasks = [t for t in all_tasks if t.task_id in wanted]
        if not tasks:
            sys.stderr.write(f"error: --tasks filter matched no corpus tasks (have: {sorted(t.task_id for t in all_tasks)})\n")
            return 1
    else:
        tasks = all_tasks

    flo_version, skill_sha = skill_metadata(skill_path)

    lint = run_lint(skill_text)

    candidate_rows: list[dict] = []
    noise_floor: dict | None = None
    if not args.no_llm:
        if shutil.which("kimi") is None:
            sys.stderr.write("error: kimi CLI not on PATH; use --no-llm for static lint only\n")
            return 1
        reps = max(1, args.reps)
        rep_rows: list[list[dict]] = []
        for i in range(reps):
            tag = f" (rep {i + 1}/{reps})" if reps > 1 else ""
            sys.stderr.write(f"running decision check on {len(tasks)} tasks{tag} (workers={args.workers}, timeout={KIMI_TIMEOUT_S}s)…\n")
            rep_rows.append(run_decisions(skill_text, tasks, workers=args.workers))
        candidate_rows = rep_rows[0]   # rep 1 is the canonical snapshot + ancestor-diff basis
        if reps > 1:
            noise_floor = compute_noise_floor(rep_rows)
        sys.stderr.write("decision check complete.\n")

    snapshot_path: Path | None = None
    if candidate_rows and not args.no_write:
        snapshot_path = write_snapshot(candidate_rows, flo_version, skill_sha)

    ancestors: list[tuple[Path, dict, list[dict]]] = []
    if candidate_rows:
        all_snapshots = list_snapshots(LOG_DIR)
        if snapshot_path:
            all_snapshots = [p for p in all_snapshots if p != snapshot_path]
        for p in logarithmic_ancestors(all_snapshots):
            meta, rows = load_snapshot(p)
            ancestors.append((p, meta, rows))

    diffs = diff_candidate_against_ancestors(candidate_rows, ancestors) if candidate_rows else {}

    report = render_report(
        skill_path=skill_path,
        flo_version=flo_version,
        skill_sha=skill_sha,
        git_sha=git_short_sha(),
        lint=lint,
        candidate_rows=candidate_rows,
        ancestors=ancestors,
        diffs=diffs,
        snapshot_path=snapshot_path,
        noise_floor=noise_floor,
    )

    if args.report:
        args.report.write_text(report)
        sys.stderr.write(f"report written to {args.report}\n")
    else:
        sys.stdout.write(report)
        if not report.endswith("\n"):
            sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
