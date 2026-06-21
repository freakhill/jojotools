#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""
flo_evolution.py — track FLO platform performance/capability across versions.

Re-evaluates each historical FLO version with "our method" and graphs the trajectory, so we can
watch the platform evolve (one new point per release) AND fully regenerate the data when the
measuring method changes. Designed to be mechanizable:

  - version→sha map is DERIVED from git history of SKILL.md (new releases appear automatically).
  - versions are LOG-SAMPLED: dense at the recent end, exponentially sparser the older you go.
  - the primary metric is a DETERMINISTIC capability inventory (regex-detected named FLO features),
    so it is free, reproducible, and trivially regenerable — the right property for "regenerate when
    the performance measuring system changes". An optional LLM decision-check axis can be layered on.
  - outputs a machine-readable dataset (JSON), PNG graphs, and a GitHub-viewable Markdown report
    with the images embedded.

Usage:
  uv run scripts/flo_evolution.py --regenerate          # recompute all sampled versions from git + graph + report
  uv run scripts/flo_evolution.py --graph-only          # re-render graphs+report from the existing JSON (no git)
  uv run scripts/flo_evolution.py --list                # print the discovered + sampled versions, then exit
  uv run scripts/flo_evolution.py --dense 9 --stride 2  # tune sampling: keep N newest dense, then geometric
  uv run scripts/flo_evolution.py --all-versions        # score every version (free metric; sampling aliases)
  uv run scripts/flo_evolution.py --allow-drops         # treat a capability disappearance as a warning, not an error

The capability inventory is the deterministic spine. To extend the method (add/raise the bar on what
counts as a capability) edit CAPABILITIES below and re-run --regenerate: every historical point is
recomputed against the new definition, so the trajectory stays self-consistent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
REPO_ROOT = SKILL_DIR
while REPO_ROOT != REPO_ROOT.parent and not (REPO_ROOT / ".git").exists():
    REPO_ROOT = REPO_ROOT.parent
SKILL_REL = "claude/plugins/jojo-skills/skills/feedback-loop-optimization/SKILL.md"
OUT_DIR = SKILL_DIR / "training-corpus" / "evolution"
DATA_JSON = OUT_DIR / "evolution-data.json"
REPORT_MD = OUT_DIR / "EVOLUTION.md"

# Bump when the SCORING METHOD changes (feature set, density formula, schema) so a consumer can tell a
# metric change from a capability change (ayo prior-art: lm-eval-harness/SPEC version-pin their tasks).
METRIC_SCHEMA_VERSION = "1.1"


# ── Capability inventory ───────────────────────────────────────────────────────────────────
# Each capability is a named FLO feature with a robust regex marker and the category it belongs to.
# The capability COUNT per version is the deterministic performance/maturity proxy; categories give a
# stacked breakdown. Markers are chosen to be stable across the wording drift of the version history.
# (cat: P=protocol spine, C=clarification/eval quality, G=GP-evolution machinery, R=routing/judges,
#  D=defensive/anti-gaming guards.)
@dataclass
class Capability:
    key: str
    cat: str
    pattern: str
    note: str = ""


CAPABILITIES: list[Capability] = [
    # Protocol spine
    Capability("phase_structure", "P", r"Phase\s*0.*Phase\s*1.*Phase\s*2.*Phase\s*3", "5-phase protocol"),
    Capability("worker_eval_isolation", "P", r"(worker|evaluator).{0,40}(isolation|blind|separat)", "anti-sycophancy split"),
    Capability("rubric_lock", "P", r"rubric\s*(lock|immutab)", "frozen rubric"),
    Capability("stuck_streak", "P", r"(stuck|plateau).{0,40}(streak|counter|diagnos)", "stuck/plateau diagnosis"),
    Capability("token_economy", "P", r"token[- ]?(econom|budget)|≤\s*[\d,]+\s*tokens|token\s*(cap|limit|target)", "token economy"),
    # Clarification + eval quality
    Capability("clarification_phase", "C", r"clarif", "clarification phase"),
    Capability("independence_test", "C", r"independence\s*test", "criterion independence"),
    Capability("vagueness_scale", "C", r"vagueness", "vagueness 1/2/3 scale"),
    Capability("fixture_spec", "C", r"fixture", "fixture spec"),
    Capability("anchor_ladder", "C", r"(multi-?point|anchor\s*ladder|anchor\b.{0,30}ladder)", "multi-point anchor ladders (v1.9.5)"),
    Capability("evidence_recompute", "C", r"(recomput|raw evidence|evidence[-_ ]?(hard[-_ ]?fail|first))", "deterministic-evidence recompute"),
    # GP-evolution machinery
    Capability("population", "G", r"population", "population P"),
    Capability("tournament", "G", r"tournament", "tournament selection"),
    Capability("elitism", "G", r"elite\b|elitism|elitist|keep.{0,12}best", "elitism"),
    Capability("genome_registry", "G", r"genome", "genome registry/tags"),
    Capability("expansion_explorer", "G", r"(expansion|explorer)", "expansion/explorer"),
    Capability("thompson_sampling", "G", r"thompson|beta\(", "Thompson Sampling targeting"),
    Capability("ucb1", "G", r"ucb1", "UCB1 selection"),
    Capability("map_elites", "G", r"map-?elites", "MAP-Elites archive"),
    Capability("slot_vector_genome", "G", r"(slot[-_ ]?vector|eval_mechanism|diversity_method)", "structured slot genome (v1.7)"),
    Capability("crossover", "G", r"crossover", "crossover"),
    # Routing / judges
    Capability("cross_family_k2", "R", r"(cross-?family|K=2|K ?= ?2)", "cross-family K=2 evaluators"),
    Capability("position_swap", "R", r"position[-_ ]?swap", "position-swap calibration"),
    Capability("host_aware_routing", "R", r"(host-?aware|routing invariant|I1|host=)", "host-aware routing (v1.9.0)"),
    Capability("premium_gemini", "R", r"gemini", "premium Gemini judge (v1.9.4+)"),
    # Defensive / anti-gaming guards
    Capability("heldout_gate_h3", "D", r"(held-?out.{0,20}(gate|admission)|heldout_admission)", "H3 held-out gate (v1.9.9)"),
    Capability("genome_exercised_h4", "D", r"genome[-_ ]?exercised", "H4 genome-exercised check (v1.9.9)"),
    Capability("adversarial_gate_ea2", "D", r"adversarial[-_ ]?gate[-_ ]?pass|adversarial_gate", "EA2 adversarial gate (v1.9.11/12)"),
    Capability("artifact_debias_ea1", "D", r"(artifact_debias|debias[-_ ]?anchor|length.{0,20}!?=?.{0,10}quality)", "EA1 artifact debias (v1.9.10)"),
    Capability("legibility_guard_ea6", "D", r"legibility", "EA6 legibility guard (v1.9.10)"),
    Capability("judge_live_calibration_ea8", "D", r"(judge[-_ ]?live[-_ ]?calibration|judge_live)", "EA8 live judge calibration (v1.9.10)"),
]
CATEGORIES = {"P": "Protocol spine", "C": "Clarification/eval", "G": "GP evolution",
              "R": "Routing/judges", "D": "Defensive guards"}


def score_capabilities(skill_text: str) -> dict:
    present, occurrences = {}, {}
    for c in CAPABILITIES:
        hits = re.findall(c.pattern, skill_text, re.IGNORECASE | re.DOTALL)
        present[c.key] = bool(hits)
        occurrences[c.key] = len(hits)   # occurrence count = light real-vs-aspirational signal
    by_cat = {cat: sum(1 for c in CAPABILITIES if c.cat == cat and present[c.key]) for cat in CATEGORIES}
    nbytes = len(skill_text.encode())
    count = sum(present.values())
    return {
        "capability_count": count,
        "capability_total": len(CAPABILITIES),
        "by_category": by_cat,
        "present": present,
        "occurrences": occurrences,
        "lines": skill_text.count("\n") + 1,
        "bytes": nbytes,
        # density = capabilities per 1000 bytes (tokenizer-neutral). Flat/declining density while the
        # count rises = prose bloat outpacing capability (ayo: lost-in-the-middle / context debt).
        "capability_density": round(count / (nbytes / 1000), 3) if nbytes else 0.0,
    }


def manifest_sha() -> str:
    """Hash of the capability definitions; changes iff the feature set / patterns change."""
    blob = "|".join(f"{c.key}={c.pattern}={c.cat}" for c in CAPABILITIES)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def harness_sha() -> str:
    try:
        return _git("rev-parse", "--short", "HEAD").strip()
    except Exception:
        return "unknown"


# ── git: discover version→sha and fetch historical SKILL.md ────────────────────────────────
def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                          capture_output=True, text=True, check=True).stdout


def _semver_key(v: str) -> tuple:
    # tolerate suffixes like '1.7.0-laneA-g2' -> (1,7,0) + suffix-flag (suffixed sorts < clean)
    m = re.match(r"(\d+)\.(\d+)\.(\d+)(.*)", v)
    if not m:
        return (0, 0, 0, 1, v)
    a, b, c, suf = m.groups()
    return (int(a), int(b), int(c), 1 if suf else 0, suf)


def discover_versions() -> list[dict]:
    """Walk SKILL.md history; return one representative (newest) commit per distinct version,
    ascending by semver. Newer releases appear automatically on the next run."""
    out = _git("log", "--follow", "--format=%H %cs", "--", SKILL_REL)
    seen: dict[str, dict] = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, date = line.split()[0], line.split()[1]
        try:
            blob = _git("show", f"{sha}:{SKILL_REL}")
        except subprocess.CalledProcessError:
            continue
        m = re.search(r"^version:\s*(\S+)", blob, re.MULTILINE)
        if not m:
            continue
        ver = m.group(1)
        # newest-first walk: first occurrence of a version = its latest (canonical) state
        if ver not in seen:
            seen[ver] = {"version": ver, "sha": sha, "date": date}
    return sorted(seen.values(), key=lambda d: _semver_key(d["version"]))


def log_sample(versions: list[dict], dense: int, stride: float) -> list[dict]:
    """Keep the `dense` newest versions, then take geometrically sparser picks going older.
    Always keep the oldest so the full span is anchored. versions is ascending; we sample from the
    recent (high-index) end."""
    n = len(versions)
    if n <= dense:
        return versions
    keep_idx = set(range(n - dense, n))      # dense recent band
    keep_idx.add(0)                           # anchor the oldest
    # geometric strides into the older region, measured as offsets back from the dense band
    off = 1
    step = max(1, int(stride))
    i = n - dense - 1
    gap = step
    while i >= 0:
        keep_idx.add(i)
        i -= gap
        gap = max(step, int(gap * stride))
    return [versions[i] for i in sorted(keep_idx)]


def get_skill_at(sha: str) -> str | None:
    try:
        return _git("show", f"{sha}:{SKILL_REL}")
    except subprocess.CalledProcessError:
        return None


# ── dataset ────────────────────────────────────────────────────────────────────────────────
def build_dataset(sampled: list[dict]) -> list[dict]:
    rows = []
    for v in sampled:
        text = get_skill_at(v["sha"])
        if text is None:
            sys.stderr.write(f"warn: cannot read SKILL.md at {v['sha'][:8]} (v{v['version']}); skipping\n")
            continue
        metrics = score_capabilities(text)
        rows.append({**v, **metrics})
    return rows


def check_monotonic(rows: list[dict], allow_drops: bool) -> None:
    """A capability present in an older sampled version but ABSENT in a newer one is either a regex
    bug or a real feature removal — fail loudly (ayo: GCC/LLVM treat a dropped feature-test as
    build-breaking, not telemetry). --allow-drops downgrades it to a warning for intentional removals."""
    drops, seen = [], {}
    for r in rows:                              # rows are ascending by version
        for k, p in r["present"].items():
            if p and k not in seen:
                seen[k] = r["version"]
            elif not p and k in seen:
                drops.append((k, seen[k], r["version"]))
    if not drops:
        return
    msg = "capability DROP (present then absent):\n" + "\n".join(
        f"  - {k}: present@v{first} -> ABSENT@v{later}" for k, first, later in drops)
    if allow_drops:
        sys.stderr.write("warn: " + msg + "\n  (--allow-drops: continuing)\n")
    else:
        sys.stderr.write("error: " + msg + "\n  (regex fragility or a real removal; fix the marker "
                         "or pass --allow-drops if intentional)\n")
        raise SystemExit(2)


def write_dataset(rows: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "flo-evolution/1",
        "metric_schema_version": METRIC_SCHEMA_VERSION,
        "manifest_sha": manifest_sha(),       # changes iff the feature set/patterns change
        "harness_git_sha": harness_sha(),     # the harness commit that generated this dataset
        "capability_keys": [c.key for c in CAPABILITIES],
        "capability_cats": {c.key: c.cat for c in CAPABILITIES},
        "categories": CATEGORIES,
        "rows": rows,
    }
    DATA_JSON.write_text(json.dumps(payload, indent=2))


def load_dataset() -> dict:
    return json.loads(DATA_JSON.read_text())


# ── graphs ─────────────────────────────────────────────────────────────────────────────────
def render_graphs(data: dict) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    rows = data["rows"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    labels = [r["version"] for r in rows]
    x = list(range(len(rows)))
    cats = list(data["categories"].keys())
    cat_names = data["categories"]
    colors = {"P": "#4C72B0", "C": "#55A868", "G": "#C44E52", "R": "#8172B2", "D": "#CCB974"}

    paths = []

    # 1) Stacked capability-count trajectory + capability-density line (secondary axis)
    fig, ax = plt.subplots(figsize=(11, 5.2))
    bottoms = [0] * len(rows)
    for cat in cats:
        vals = [r["by_category"].get(cat, 0) for r in rows]
        ax.bar(x, vals, bottom=bottoms, color=colors.get(cat, "#888"), label=cat_names[cat], width=0.72)
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    ax.plot(x, [r["capability_count"] for r in rows], "k-o", lw=1.6, ms=4, label="total capabilities")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel(f"FLO capabilities present (of {rows[0]['capability_total']})")
    ax.set_title("FLO capability evolution across versions (deterministic inventory)")
    ax.grid(axis="y", alpha=0.3)
    ax2 = ax.twinx()
    ax2.plot(x, [r.get("capability_density", 0) for r in rows], "--s", color="#d62728", lw=1.4, ms=3,
             label="density (features / 1k bytes)")
    ax2.set_ylabel("capability density (features / 1k bytes)", color="#d62728")
    ax2.tick_params(axis="y", labelcolor="#d62728")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8, ncol=2)
    fig.tight_layout()
    p1 = OUT_DIR / "capability_trajectory.png"
    fig.savefig(p1, dpi=130)
    plt.close(fig)
    paths.append(p1)

    # 2) Feature × version presence heatmap — rows ordered topologically by first appearance (staircase)
    keys = data["capability_keys"]
    key_cat = data.get("capability_cats", {})
    cat_order = {c: i for i, c in enumerate(cats)}

    def _first_idx(k):
        return next((i for i, r in enumerate(rows) if r["present"].get(k)), len(rows))

    keys_sorted = sorted(keys, key=lambda k: (_first_idx(k), cat_order.get(key_cat.get(k), 99), k))
    grid = [[1 if r["present"].get(k) else 0 for r in rows] for k in keys_sorted]
    fig, ax = plt.subplots(figsize=(11, 9))
    ax.imshow(grid, aspect="auto", cmap="Greens", vmin=0, vmax=1, interpolation="nearest")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(keys_sorted)))
    ax.set_yticklabels(keys_sorted, fontsize=7)
    ax.set_title("Capability presence by version (green = present; rows ordered by first appearance)")
    fig.tight_layout()
    p2 = OUT_DIR / "capability_heatmap.png"
    fig.savefig(p2, dpi=130)
    plt.close(fig)
    paths.append(p2)

    # 3) Per-version capability delta (waterfall): net new vs the previous sampled version
    counts = [r["capability_count"] for r in rows]
    deltas = [counts[0]] + [counts[i] - counts[i - 1] for i in range(1, len(counts))]
    bar_colors = ["#4C72B0"] + ["#55A868" if d > 0 else ("#C44E52" if d < 0 else "#bbbbbb")
                                for d in deltas[1:]]
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.bar(x, deltas, color=bar_colors, width=0.72)
    for xi, d in zip(x, deltas):
        ax.text(xi, d + (0.15 if d >= 0 else -0.15), (f"{d}" if xi == 0 else f"{d:+d}"),
                ha="center", va="bottom" if d >= 0 else "top", fontsize=7)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Δ capabilities vs previous")
    ax.set_title("Per-version capability delta (blue=baseline, green=added, red=removed)")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    p3 = OUT_DIR / "capability_delta.png"
    fig.savefig(p3, dpi=130)
    plt.close(fig)
    paths.append(p3)

    return paths


# ── report ─────────────────────────────────────────────────────────────────────────────────
def render_report(data: dict, graph_paths: list[Path]) -> None:
    rows = data["rows"]
    lines: list[str] = []
    lines.append("# FLO platform evolution")
    lines.append("")
    lines.append("Auto-generated by `scripts/flo_evolution.py`. Tracks the FLO platform's capability "
                 "surface across log-sampled versions (dense at the recent end, sparser going older). "
                 "The metric is a **deterministic capability inventory** — regex-detected named FLO "
                 "features in each version's `SKILL.md` — so it is free, reproducible, and fully "
                 "regenerable when the method changes (edit `CAPABILITIES`, re-run `--regenerate`).")
    lines.append("")
    lines.append("> Note: this is a deterministic capability/maturity proxy, not an output-quality "
                 "score. A cross-model prior-art review (`probes/EVOLUTION-HARNESS-ayo-PRIOR-ART.md`) "
                 "DECIDED AGAINST an absolute LLM-judged prose-quality axis (uncalibrated, "
                 "score-compresses, judge non-stationarity, Goodhart). The Goodhart-resistant quality "
                 "axis is behavioural and is now MEASURED: a blind 3-family forced-ranking study (full "
                 "v1.9.12 vs minimal baseline, 6 tasks x n=6, 648 decisions) found full > minimal 0.548 "
                 "(p=0.017), concentrated in fidelity/teaching tasks; recent v1.2->v1.9.12 increments "
                 "added no marginal gain. So the capability curve below is NOT a quality curve — "
                 "capability rose while marginal quality stayed flat (`probes/EB8-STAGE3-MATRIX-FINDINGS.md`).")
    lines.append("")
    for p in graph_paths:
        lines.append(f"![{p.stem}]({p.name})")
        lines.append("")
    lines.append("## Per-version capability counts")
    lines.append("")
    cats = list(data["categories"].keys())
    header = ["version", "date", "total"] + [data["categories"][c] for c in cats] + ["density/1kB", "lines"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for r in rows:
        cells = [r["version"], r["date"], f"{r['capability_count']}/{r['capability_total']}"]
        cells += [str(r["by_category"].get(c, 0)) for c in cats]
        cells.append(f"{r.get('capability_density', 0)}")
        cells.append(str(r["lines"]))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    # First-appearance ledger: which version introduced each capability (in the sampled set)
    lines.append("## Capability first-appearance (within the sampled versions)")
    lines.append("")
    intro: dict[str, str] = {}
    for r in rows:
        for k, v in r["present"].items():
            if v and k not in intro:
                intro[k] = r["version"]
    by_ver: dict[str, list[str]] = {}
    for k, ver in intro.items():
        by_ver.setdefault(ver, []).append(k)
    for r in rows:
        ver = r["version"]
        if ver in by_ver:
            lines.append(f"- **v{ver}**: " + ", ".join(sorted(by_ver[ver])))
    lines.append("")
    lines.append("---")
    lines.append(f"_method: metric_schema `{data.get('metric_schema_version', '?')}` · manifest "
                 f"`{data.get('manifest_sha', '?')}` · harness `{data.get('harness_git_sha', '?')}` · "
                 f"{len(rows)} versions · deterministic capability inventory (free, regenerable). "
                 f"Regenerate: `uv run scripts/flo_evolution.py --regenerate`._")
    REPORT_MD.write_text("\n".join(lines))


# ── CLI ────────────────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--regenerate", action="store_true", help="recompute all sampled versions from git, then graph + report")
    ap.add_argument("--graph-only", action="store_true", help="re-render graphs + report from the existing JSON dataset")
    ap.add_argument("--list", action="store_true", help="print discovered + sampled versions and exit")
    ap.add_argument("--dense", type=int, default=10, help="keep this many newest versions densely (default 10)")
    ap.add_argument("--stride", type=float, default=2.0, help="geometric sparsening factor for older versions (default 2.0)")
    ap.add_argument("--all-versions", action="store_true", help="score ALL versions, not the log-sampled subset (the deterministic metric is free; ayo: sampling aliases). Sampling stays the default to honour the banded report view.")
    ap.add_argument("--allow-drops", action="store_true", help="downgrade a non-monotonic capability drop from a build error to a warning (use for an intentional feature removal)")
    args = ap.parse_args()

    if args.graph_only:
        data = load_dataset()
        paths = render_graphs(data)
        render_report(data, paths)
        sys.stderr.write(f"rendered {len(paths)} graph(s) + report from {DATA_JSON.name}\n")
        return 0

    versions = discover_versions()
    sampled = versions if args.all_versions else log_sample(versions, dense=args.dense, stride=args.stride)
    if args.list:
        scope = "ALL" if args.all_versions else f"sampled dense={args.dense} stride={args.stride}"
        print(f"discovered {len(versions)} versions; {len(sampled)} selected ({scope}):")
        keep = {s["sha"] for s in sampled}
        for v in versions:
            mark = "*" if v["sha"] in keep else " "
            print(f"  [{mark}] v{v['version']:<16} {v['date']}  {v['sha'][:10]}")
        return 0

    rows = build_dataset(sampled)
    check_monotonic(rows, allow_drops=args.allow_drops)   # fail on a capability drop (regex bug / removal)
    write_dataset(rows)
    data = load_dataset()
    paths = render_graphs(data)
    render_report(data, paths)
    sys.stderr.write(f"regenerated: {len(rows)} versions -> {DATA_JSON.relative_to(SKILL_DIR)}, "
                     f"{len(paths)} graphs, {REPORT_MD.name}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
