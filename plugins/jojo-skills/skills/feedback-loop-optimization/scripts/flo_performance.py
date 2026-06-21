# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""flo_performance.py — generate the FLO behavioural PERFORMANCE report.

The quality counterpart to flo_evolution.py (which tracks CAPABILITY, not
quality). Reads the EB8 Stage-3 power-sweep data — all 6 tasks at n=6/version,
blind 3-family forced ranking — and emits a regenerable performance report:
a saved verdict JSON, a GitHub-viewable Markdown report, and a per-task
win-rate chart. The headline verdict otherwise lives only in prose + ephemeral
aggregator console output; this makes it a first-class, regenerable artifact.

Outputs (under training-corpus/performance/, mirroring evolution/):
  - performance-data.json   machine-readable per-task + pooled verdict
  - PERFORMANCE.md          rendered report with embedded chart
  - win_rate_by_task.png    full-vs-min win-rate per task (significance-flagged)

Usage: uv run scripts/flo_performance.py
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SKILL_DIR = Path(__file__).resolve().parent.parent
OUT = SKILL_DIR / "probes" / "eb8-matrix" / "out"
REPORT_DIR = SKILL_DIR / "training-corpus" / "performance"

TASKS = [
    ("T1", "explainer (DB index -> PMs)"),
    ("T2", "blameless postmortem"),
    ("T3", "faithful compression"),
    ("T4", "auth-migration plan"),
    ("T5", "build-vs-buy persuasion"),
    ("T6", "technical teaching (locking)"),
]
JUDGES = ["kimi", "glm", "or"]
# dose-response (n=3) full(v1.9.12) mean rank of 9 — for the rep-noise correction view
DOSE_N3_FULL = {"T1": 3.33, "T2": 5.11, "T3": 4.00, "T4": 3.00, "T5": 6.78, "T6": 5.44}


def resolve(task):
    bm = OUT / f"power_{task}_blind_map.json"
    rd = OUT / f"power_{task}_rank_responses"
    if bm.exists() and rd.exists():
        return bm, rd
    return OUT / "power_blind_map.json", OUT / "power_rank_responses"  # T5 legacy naming


def version(fn):
    return "v0.7" if "_v0.7_" in fn else "v1.9.12"


def binom_two_sided(k, n, p=0.5):
    def pmf(i):
        return math.comb(n, i) * p**i * (1 - p) ** (n - i)
    pk = pmf(k)
    return min(1.0, sum(pmf(i) for i in range(n + 1) if pmf(i) <= pk * (1 + 1e-9)))


rows = []
gw = gn = 0
all_full, all_min = [], []
for tid, label in TASKS:
    bm_path, rd = resolve(tid)
    bm = json.loads(bm_path.read_text())
    full = [L for L, fn in bm.items() if version(fn) == "v1.9.12"]
    mini = [L for L, fn in bm.items() if version(fn) == "v0.7"]
    ranks = {j: json.loads((rd / f"{j}.json").read_text()) for j in JUDGES}
    w = sum(1 for j in JUDGES for f in full for m in mini if ranks[j][f] < ranks[j][m])
    n = len(JUDGES) * len(full) * len(mini)
    fr = [ranks[j][L] for j in JUDGES for L in full]
    mr = [ranks[j][L] for j in JUDGES for L in mini]
    all_full += fr
    all_min += mr
    gw += w
    gn += n
    p = binom_two_sided(w, n)
    rows.append({
        "task": tid, "type": label,
        "v0.7_mean_rank": round(sum(mr) / len(mr), 2),
        "v1.9.12_mean_rank": round(sum(fr) / len(fr), 2),
        "full_win": w, "decisions": n,
        "full_win_rate": round(w / n, 3), "p_value": round(p, 4),
        "significant": p < 0.05,
        "verdict": ("full wins" if (w / n > 0.5 and p < 0.05)
                    else ("full worse" if (w / n < 0.5 and p < 0.05) else "null")),
        "n3_full_mean_rank_of9": DOSE_N3_FULL[tid],
    })

wr = gw / gn
pp = binom_two_sided(gw, gn)
data = {
    "experiment": "EB8 Stage-3 power sweep (full v1.9.12 vs minimal v0.7)",
    "method": "blind 3-family forced ranking, n=6/version/task, exact binomial two-sided vs 0.5",
    "judges": ["kimi-k2.7", "glm-5.1", "deepseek-v4-pro (ZDR)"],
    "tasks": rows,
    "pooled": {
        "full_win": gw, "decisions": gn,
        "full_win_rate": round(wr, 3), "p_value": round(pp, 4),
        "v0.7_mean_rank": round(sum(all_min) / len(all_min), 2),
        "v1.9.12_mean_rank": round(sum(all_full) / len(all_full), 2),
        "verdict": ("full > minimal" if (wr > 0.5 and pp < 0.05)
                    else ("full < minimal" if (wr < 0.5 and pp < 0.05) else "null")),
    },
}
REPORT_DIR.mkdir(parents=True, exist_ok=True)
(REPORT_DIR / "performance-data.json").write_text(json.dumps(data, indent=2))

# ── chart ────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(8, 4.2))
tids = [r["task"] for r in rows]
wrs = [r["full_win_rate"] for r in rows]
colors = ["#2ca02c" if (r["significant"] and r["full_win_rate"] > 0.5)
          else ("#d62728" if r["significant"] else "#9aa0a6") for r in rows]
bars = ax.bar(tids, wrs, color=colors)
ax.axhline(0.5, color="#333", lw=1, ls="--", label="chance (0.5)")
ax.axhline(wr, color="#1f77b4", lw=1.4, label=f"pooled {wr:.3f} (p={pp:.3f})")
for r, b in zip(rows, bars):
    ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.01,
            f"{r['full_win_rate']:.2f}{' *' if r['significant'] else ''}",
            ha="center", va="bottom", fontsize=8)
ax.set_ylim(0, 1)
ax.set_ylabel("full-vs-min win-rate")
ax.set_title("FLO performance: full v1.9.12 vs minimal v0.7 (n=6/task, * = p<0.05)")
ax.legend(fontsize=8, loc="upper right")
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig(REPORT_DIR / "win_rate_by_task.png", dpi=110)
plt.close(fig)

# ── markdown report ──────────────────────────────────────────────────────
FMT = {"full wins": "**full wins**", "full worse": "**full worse**", "null": "null"}
L = []
L.append("# FLO platform performance")
L.append("")
L.append("Auto-generated by `scripts/flo_performance.py`. The **behavioural quality** counterpart to "
         "`evolution/EVOLUTION.md` (which tracks capability, NOT quality). Source: the EB8 Stage-3 power "
         "sweep — all 6 tasks at **n=6/version**, blind **3-judge-family forced ranking** (Kimi k2.7, "
         "GLM-5.1, DeepSeek-V4-Pro/ZDR), 648 cross-version pairwise decisions. Regenerable: "
         "`uv run scripts/flo_performance.py`.")
L.append("")
L.append(f"> **Verdict:** the full protocol (v1.9.12) beats the minimal baseline (v0.7) at power — pooled "
         f"win-rate **{wr:.3f}** ({gw}/{gn}), exact-binomial **p={pp:.4f}**; mean rank full "
         f"{data['pooled']['v1.9.12_mean_rank']} vs min {data['pooled']['v0.7_mean_rank']} (null 6.5). "
         f"Modest, and **concentrated in fidelity/teaching tasks** (T3, T6) — a wash elsewhere.")
L.append("")
L.append("![win_rate_by_task](win_rate_by_task.png)")
L.append("")
L.append("## Per-task (n=6/version, full-vs-min)")
L.append("")
L.append("| task | type | v0.7 rank | v1.9.12 rank | full win-rate | p | verdict |")
L.append("|---|---|---|---|---|---|---|")
for r in rows:
    L.append(f"| {r['task']} | {r['type']} | {r['v0.7_mean_rank']} | {r['v1.9.12_mean_rank']} | "
             f"{r['full_win_rate']:.3f} | {r['p_value']:.4f} | {FMT[r['verdict']]} |")
L.append(f"| **pooled** | all 6 | {data['pooled']['v0.7_mean_rank']} | {data['pooled']['v1.9.12_mean_rank']} | "
         f"**{wr:.3f}** | **{pp:.4f}** | **{data['pooled']['verdict']}** |")
L.append("")
L.append("## Caveats (honest scope)")
L.append("- The aggregate win is **carried entirely by T3 + T6** (143/216 = 0.66); the other four tasks "
         "pool to ~0.49 (a wash). \"Protocol buys quality\" is true but NOT uniform.")
L.append("- **n=3 mis-identified the carriers.** The earlier dose-response (n=3) credited T1/T4 as the "
         "strongest full-wins; at n=6 T1 halves to n.s. and **T4 sign-flips**, while T3/T6 (only modest at "
         "n=3) emerge as the real carriers. Per-task signals need n>=6 on this instrument.")
L.append("- Recent feature increments (v1.2 -> v1.9.12) added **no** measurable marginal quality "
         "(separate dose-response contrast, p=0.31) — capability rose while marginal quality stayed flat.")
L.append("- Behavioural/relative axis by design — an absolute LLM prose-score axis was rejected "
         "(ceiling-saturates; Goodhart). Full detail: `probes/EB8-STAGE3-MATRIX-FINDINGS.md`.")
L.append("")
L.append("## n=3 -> n=6 shift (full v1.9.12 mean rank — the rep-noise correction)")
L.append("")
L.append("| task | n=3 (of 9) | n=6 (of 12) |")
L.append("|---|---|---|")
for r in rows:
    L.append(f"| {r['task']} | {r['n3_full_mean_rank_of9']} | {r['v1.9.12_mean_rank']} |")
L.append("")
L.append("---")
L.append("_method: blind 3-family forced ranking, n=6/version/task, exact binomial two-sided. "
         "Data: `probes/eb8-matrix/out/power_*`. Regenerate: `uv run scripts/flo_performance.py`._")
(REPORT_DIR / "PERFORMANCE.md").write_text("\n".join(L))

print(f"wrote {REPORT_DIR.relative_to(SKILL_DIR)}/PERFORMANCE.md + performance-data.json + win_rate_by_task.png")
print(f"pooled full-vs-min {wr:.3f} (p={pp:.4f}); per-task: "
      + ", ".join(f"{r['task']}={r['full_win_rate']:.2f}{'*' if r['significant'] else ''}" for r in rows))
