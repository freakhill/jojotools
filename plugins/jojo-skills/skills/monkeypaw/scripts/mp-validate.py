#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
mp-validate.py — Phase A validation harness

Subcommands:
  parse-metrics <path>          Validate sweep_metrics.md schema; print summary
  parse-summary <path>          Validate sweep_summary.md schema; print summary
  compare                       Emit a per-task results block (paste into WAVES-ROADMAP.md)
  aggregate <result.json> ...   Compute aggregate table + gate decision across tasks

Options:
  -h, --help                    Show this help

Schemas: see SKILL.md Phase 4B.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


USAGE = __doc__.strip()


# ---------- sweep_metrics parser ----------

METRICS_HEADER_RE = re.compile(
    r"^\|\s*node_id\s*\|\s*baseline_score\s*\|\s*new_score\s*\|\s*delta\s*\|\s*refine\s*\|\s*budget_remaining\s*\|\s*timestamp\s*\|",
    re.IGNORECASE,
)

METRICS_ROW_RE = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*([\d.+-]+)\s*\|\s*([\d.+-]+)\s*\|\s*([+-]?[\d.]+)\s*\|\s*(yes|no)\s*\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*$",
    re.IGNORECASE,
)


def parse_sweep_metrics(path):
    """
    Returns dict:
      project, started_at, budget_total, rows (list of dict)
    Raises ValueError on schema violations.
    """
    text = Path(path).read_text()

    # Meta block
    meta = {}
    m = re.search(r"<!--\s*sweep-meta\s*\n(.*?)\n\s*-->", text, re.DOTALL)
    if not m:
        raise ValueError(f"{path}: missing <!-- sweep-meta ... --> block")
    for line in m.group(1).strip().split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()

    for required in ("project", "started_at", "budget_total"):
        if required not in meta:
            raise ValueError(f"{path}: sweep-meta missing '{required}'")

    try:
        meta["budget_total"] = int(meta["budget_total"])
    except ValueError:
        raise ValueError(f"{path}: budget_total must be int, got {meta['budget_total']!r}")

    # Find the header line
    lines = text.split("\n")
    header_idx = None
    for i, line in enumerate(lines):
        if METRICS_HEADER_RE.match(line):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(f"{path}: missing metrics table header (node_id | baseline_score | ...)")

    # Skip separator line
    if header_idx + 1 >= len(lines) or not re.match(r"^\|[\s\-:]+\|", lines[header_idx + 1]):
        raise ValueError(f"{path}: missing table separator below header")

    rows = []
    for line in lines[header_idx + 2 :]:
        if not line.strip():
            continue
        if not line.startswith("|"):
            break
        m = METRICS_ROW_RE.match(line)
        if not m:
            raise ValueError(f"{path}: malformed row: {line!r}")
        node_id, base, new, delta, refine, budget_rem, ts = m.groups()
        rows.append(
            {
                "node_id": node_id.strip(),
                "baseline_score": float(base),
                "new_score": float(new),
                "delta": float(delta),
                "refine": refine.strip().lower() == "yes",
                "budget_remaining": int(budget_rem),
                "timestamp": ts.strip(),
            }
        )

    return {
        "project": meta["project"],
        "started_at": meta["started_at"],
        "budget_total": meta["budget_total"],
        "rows": rows,
    }


# ---------- sweep_summary parser ----------

SUMMARY_KV_RE = re.compile(r"^\|\s*([a-z_]+)\s*\|\s*([^|]+?)\s*\|\s*$")

SUMMARY_FIELDS = {
    "total_nodes": int,
    "visited_nodes": int,
    "refine_count": int,
    "mean_delta": float,
    "max_delta": float,
    "budget_used": int,
    "budget_total": int,
    "converged": str,
    "terminated_reason": str,
}

VALID_TERMINATED = {"all_visited", "budget_exhausted", "oscillation_guard"}


def parse_sweep_summary(path):
    """
    Returns dict with all SUMMARY_FIELDS + project, completed_at, refine_nodes (list).
    """
    text = Path(path).read_text()

    meta = {}
    m = re.search(r"<!--\s*sweep-summary\s*\n(.*?)\n\s*-->", text, re.DOTALL)
    if not m:
        raise ValueError(f"{path}: missing <!-- sweep-summary ... --> block")
    for line in m.group(1).strip().split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()

    for required in ("project", "completed_at"):
        if required not in meta:
            raise ValueError(f"{path}: sweep-summary meta missing '{required}'")

    # Parse the kv table
    fields = {}
    for line in text.split("\n"):
        m = SUMMARY_KV_RE.match(line)
        if not m:
            continue
        k = m.group(1).strip()
        v = m.group(2).strip()
        if k == "field" or k == "value":
            continue
        if k in SUMMARY_FIELDS:
            try:
                fields[k] = SUMMARY_FIELDS[k](v.lstrip("+"))
            except ValueError:
                raise ValueError(f"{path}: field {k!r} could not be parsed as {SUMMARY_FIELDS[k].__name__}: {v!r}")

    missing = set(SUMMARY_FIELDS) - set(fields)
    if missing:
        raise ValueError(f"{path}: sweep-summary missing fields: {sorted(missing)}")

    if fields["terminated_reason"] not in VALID_TERMINATED:
        raise ValueError(
            f"{path}: terminated_reason must be one of {sorted(VALID_TERMINATED)}, got {fields['terminated_reason']!r}"
        )

    if fields["converged"] not in ("yes", "no"):
        raise ValueError(f"{path}: converged must be 'yes' or 'no', got {fields['converged']!r}")

    # Refine nodes list
    refine_nodes = []
    m = re.search(r"## \[REFINE\] nodes[^\n]*\n([^\n#]*)", text)
    if m:
        line = m.group(1).strip()
        if line and not line.startswith("(none)"):
            refine_nodes = [s.strip() for s in re.split(r"[\s,]+", line.lstrip("-").strip()) if s.strip()]

    return {
        "project": meta["project"],
        "completed_at": meta["completed_at"],
        "refine_nodes": refine_nodes,
        **fields,
    }


# ---------- diagnostics ----------

def diagnose_metrics(metrics):
    rows = metrics["rows"]
    if not rows:
        return {
            "visited": 0,
            "refine_count": 0,
            "mean_delta": 0.0,
            "max_delta": 0.0,
            "regressions": [],
        }

    refine_count = sum(1 for r in rows if r["refine"])
    deltas = [r["delta"] for r in rows]
    mean_delta = sum(deltas) / len(deltas)
    max_delta = max(deltas)
    regressions = [r["node_id"] for r in rows if r["delta"] < -1.0]

    return {
        "visited": len(rows),
        "refine_count": refine_count,
        "mean_delta": mean_delta,
        "max_delta": max_delta,
        "min_delta": min(deltas),
        "regressions": regressions,
    }


# ---------- compare: emit per-task block ----------

CRITERIA = [
    ("oracle_pass_rate", "Oracle pass rate", 40),
    ("coverage", "Coverage", 20),
    ("code_quality", "Code/output quality", 15),
    ("documentation", "Documentation", 10),
    ("reproducibility", "Reproducibility", 10),
    ("reconciliation", "Reconciliation", 5),
]


def emit_compare_block(task_id, baseline_scores, sweep_scores, summary, diagnostics, wall_clock=None):
    """
    baseline_scores / sweep_scores: dict mapping criterion key → score
    summary: parsed sweep_summary dict
    diagnostics: output of diagnose_metrics (may be None if metrics file unavailable)
    """
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"#### {task_id} — {today}",
        "",
        "| Criterion | Weight | Baseline | With Sweep | Δ | Notes |",
        "|---|---|---|---|---|---|",
    ]

    total_base = 0.0
    total_sweep = 0.0
    for key, label, weight in CRITERIA:
        b = baseline_scores.get(key, 0.0)
        s = sweep_scores.get(key, 0.0)
        d = s - b
        total_base += b
        total_sweep += s
        lines.append(f"| {label} | {weight} | {b:.1f}/{weight} | {s:.1f}/{weight} | {d:+.1f} | |")

    total_delta = total_sweep - total_base
    lines.append(f"| **TOTAL** | 100 | {total_base:.1f} | {total_sweep:.1f} | **{total_delta:+.1f}** | |")

    lines += [
        "",
        "Sweep diagnostics:",
        f"- nodes visited: {summary['visited_nodes']} / {summary['total_nodes']}",
        f"- [REFINE] count: {summary['refine_count']}",
        f"- mean per-node delta: {summary['mean_delta']:+.2f}",
        f"- max per-node delta: {summary['max_delta']:+.2f}",
        f"- budget used: {summary['budget_used']} / {summary['budget_total']}",
        f"- terminated_reason: {summary['terminated_reason']}",
    ]

    if diagnostics is not None:
        reg = diagnostics["regressions"] or ["none"]
        lines.append(f"- regressions (per-node delta < -1): {', '.join(reg)}")
    if wall_clock:
        lines.append(f"- wall-clock baseline / with-sweep: {wall_clock}")

    refine_list = ", ".join(summary["refine_nodes"]) if summary["refine_nodes"] else "(none)"
    lines.append(f"- [REFINE] nodes: {refine_list}")

    lines += [
        "",
        "Notes: <fill in qualitative summary; which late→early signal fired; surprises>",
        "",
    ]
    return "\n".join(lines), total_base, total_sweep, total_delta


# ---------- aggregate ----------

def aggregate_results(result_files):
    """
    Each result file: JSON like:
      {"task_id": "P2", "baseline_total": 78.5, "sweep_total": 81.2, "regressions": ["N03"], "refine_count": 3, "wall_clock_base_min": 120, "wall_clock_sweep_min": 145}
    """
    tasks = []
    for path in result_files:
        data = json.loads(Path(path).read_text())
        for required in ("task_id", "baseline_total", "sweep_total"):
            if required not in data:
                raise ValueError(f"{path}: missing '{required}'")
        data["delta"] = data["sweep_total"] - data["baseline_total"]
        tasks.append(data)

    n = len(tasks)
    mean_delta = sum(t["delta"] for t in tasks) / n if n else 0.0
    tasks_passing = sum(1 for t in tasks if t["delta"] >= 2.0)
    tasks_regressing = sum(1 for t in tasks if t["delta"] < -1.0)

    wall_clock_base = sum(t.get("wall_clock_base_min", 0) for t in tasks)
    wall_clock_sweep = sum(t.get("wall_clock_sweep_min", 0) for t in tasks)
    overhead_pct = (
        (wall_clock_sweep - wall_clock_base) / wall_clock_base * 100
        if wall_clock_base > 0
        else None
    )

    # Gate evaluation
    gate_mean = mean_delta >= 2.0
    gate_passing = tasks_passing >= 3
    gate_no_regression = tasks_regressing == 0
    gate_overhead = overhead_pct is None or overhead_pct <= 50.0  # ≤1.5× baseline

    out = [
        "# Phase A Aggregate Report",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Tasks: {n}",
        "",
        "## Per-task summary",
        "",
        "| Task | Baseline | With Sweep | Δ | Regressions | [REFINE] | Wall-clock (base / sweep) |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in tasks:
        regs = t.get("regressions", [])
        reg_str = ", ".join(regs) if regs else "—"
        wc = (
            f"{t.get('wall_clock_base_min', '—')} / {t.get('wall_clock_sweep_min', '—')} min"
            if "wall_clock_base_min" in t
            else "—"
        )
        out.append(
            f"| {t['task_id']} | {t['baseline_total']:.1f} | {t['sweep_total']:.1f} | "
            f"{t['delta']:+.1f} | {reg_str} | {t.get('refine_count', '—')} | {wc} |"
        )

    out += [
        "",
        "## Aggregate",
        "",
        f"- Mean Δ across {n} tasks: **{mean_delta:+.2f} pts**",
        f"- Tasks with Δ ≥ +2.0: **{tasks_passing} / {n}**",
        f"- Tasks regressing > 1 pt: **{tasks_regressing} / {n}**",
        f"- Mean wall-clock overhead: **{overhead_pct:+.1f}%**" if overhead_pct is not None else "- Mean wall-clock overhead: **— (not provided)**",
        "",
        "## Gate decision",
        "",
        "| Gate criterion | Threshold | Observed | Status |",
        "|---|---|---|---|",
        f"| Mean Δ on corpus subset | ≥ +2.0 pts | {mean_delta:+.2f} | {'✓' if gate_mean else '✗'} |",
        f"| Δ ≥ +2.0 on ≥3 / 5 tasks | yes | {tasks_passing}/{n} | {'✓' if gate_passing else '✗'} |",
        f"| No task regression > 1 pt | all pass | {tasks_regressing} regressions | {'✓' if gate_no_regression else '✗'} |",
        f"| Token overhead acceptable | ≤ 1.5× baseline | {f'{overhead_pct:+.1f}%' if overhead_pct is not None else 'n/a'} | {'✓' if gate_overhead else '✗'} |",
        "",
    ]

    authorized = gate_mean and gate_passing and gate_no_regression and gate_overhead
    out.append(f"**Phase B authorized:** {'YES' if authorized else 'NO'}")

    return "\n".join(out) + "\n"


# ---------- CLI ----------

def cmd_parse_metrics(args):
    metrics = parse_sweep_metrics(args.path)
    diag = diagnose_metrics(metrics)
    print(f"✓ {args.path} schema OK")
    print(f"  project: {metrics['project']}")
    print(f"  visited: {diag['visited']} nodes")
    print(f"  refine: {diag['refine_count']}")
    print(f"  mean Δ: {diag['mean_delta']:+.2f}  max Δ: {diag['max_delta']:+.2f}")
    if diag["regressions"]:
        print(f"  regressions: {', '.join(diag['regressions'])}")


def cmd_parse_summary(args):
    summary = parse_sweep_summary(args.path)
    print(f"✓ {args.path} schema OK")
    print(f"  project: {summary['project']}")
    print(f"  visited / total: {summary['visited_nodes']} / {summary['total_nodes']}")
    print(f"  refine_count: {summary['refine_count']}")
    print(f"  mean_delta: {summary['mean_delta']:+.2f}  max_delta: {summary['max_delta']:+.2f}")
    print(f"  budget: {summary['budget_used']} / {summary['budget_total']}")
    print(f"  terminated_reason: {summary['terminated_reason']}")
    print(f"  converged: {summary['converged']}")
    if summary["refine_nodes"]:
        print(f"  REFINE nodes: {', '.join(summary['refine_nodes'])}")


def cmd_compare(args):
    baseline = json.loads(Path(args.baseline_scores).read_text())
    sweep = json.loads(Path(args.sweep_scores).read_text())
    summary = parse_sweep_summary(args.sweep_summary)
    diagnostics = None
    if args.sweep_metrics:
        diagnostics = diagnose_metrics(parse_sweep_metrics(args.sweep_metrics))

    block, base_total, sweep_total, delta = emit_compare_block(
        args.task,
        baseline,
        sweep,
        summary,
        diagnostics,
        args.wall_clock,
    )
    print(block)

    # Also emit a JSON sidecar for aggregate
    if args.json_out:
        sidecar = {
            "task_id": args.task,
            "baseline_total": base_total,
            "sweep_total": sweep_total,
            "regressions": diagnostics["regressions"] if diagnostics else [],
            "refine_count": summary["refine_count"],
        }
        if args.wall_clock_base_min is not None:
            sidecar["wall_clock_base_min"] = args.wall_clock_base_min
        if args.wall_clock_sweep_min is not None:
            sidecar["wall_clock_sweep_min"] = args.wall_clock_sweep_min
        Path(args.json_out).write_text(json.dumps(sidecar, indent=2) + "\n")
        print(f"\n→ sidecar JSON: {args.json_out}", file=sys.stderr)


def cmd_aggregate(args):
    report = aggregate_results(args.results)
    print(report)


def build_parser():
    p = argparse.ArgumentParser(prog="mp-validate", description=USAGE, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("parse-metrics", help="Validate sweep_metrics.md")
    p1.add_argument("path")

    p2 = sub.add_parser("parse-summary", help="Validate sweep_summary.md")
    p2.add_argument("path")

    p3 = sub.add_parser("compare", help="Emit per-task results block")
    p3.add_argument("--task", required=True, help="Task ID (e.g. P2)")
    p3.add_argument("--baseline-scores", required=True, help="JSON file: criterion → score")
    p3.add_argument("--sweep-scores", required=True, help="JSON file: criterion → score")
    p3.add_argument("--sweep-summary", required=True, help="Path to sweep_summary.md from sweep run")
    p3.add_argument("--sweep-metrics", help="Path to sweep_metrics.md (optional, enables regression detection)")
    p3.add_argument("--wall-clock", help="Free-form string for wall-clock notes")
    p3.add_argument("--wall-clock-base-min", type=int)
    p3.add_argument("--wall-clock-sweep-min", type=int)
    p3.add_argument("--json-out", help="Write JSON sidecar for aggregate")

    p4 = sub.add_parser("aggregate", help="Aggregate task JSON sidecars + gate decision")
    p4.add_argument("results", nargs="+", help="Task JSON sidecar files")

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.cmd == "parse-metrics":
            cmd_parse_metrics(args)
        elif args.cmd == "parse-summary":
            cmd_parse_summary(args)
        elif args.cmd == "compare":
            cmd_compare(args)
        elif args.cmd == "aggregate":
            cmd_aggregate(args)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
