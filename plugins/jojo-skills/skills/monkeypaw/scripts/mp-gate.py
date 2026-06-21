#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
mp-gate.py — cross-run gate telemetry for monkeypaw

Subcommands:
  log     Harvest one run into the ledger; evaluate gates; print edge-triggered nudge
  check   Re-evaluate all documented gates against the ledger; print status table
  report  Write a committable Markdown report + JSON corpus snapshot into telemetry/

Ledger:  $MP_GATE_HOME/gate_telemetry.jsonl   (default ~/.monkeypaw)
State:   $MP_GATE_HOME/gate_state.json        (edge-trigger memory)

See SKILL.md §4D and GATE-TELEMETRY-DESIGN.md.
"""

import argparse
import json
import os
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

USAGE = __doc__.strip()

GATES = ["T2-1", "T2-2", "T2-3", "T2-4", "T1-1", "T1-2"]
GATE_NAMES = {
    "T2-1": "Z3 Pre-flight",
    "T2-2": "Context-Folding",
    "T2-3": "Operational Profile",
    "T2-4": "ReTreVal",
    "T1-1": "Topology Router revisit",
    "T1-2": "USE/resource revisit",
}


# ---------- ledger / state I/O ----------

def gate_home() -> Path:
    return Path(os.environ.get("MP_GATE_HOME", str(Path.home() / ".monkeypaw")))


def ledger_path() -> Path:
    return gate_home() / "gate_telemetry.jsonl"


def state_path() -> Path:
    return gate_home() / "gate_state.json"


def read_ledger() -> list:
    p = ledger_path()
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def write_ledger(rows) -> None:
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def append_row(row) -> None:
    rows = read_ledger()
    rows = [r for r in rows if r.get("run_id") != row["run_id"]]  # idempotent on run_id
    rows.append(row)
    write_ledger(rows)


def read_state() -> dict:
    p = state_path()
    return json.loads(p.read_text()) if p.exists() else {}


def write_state(state) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


# ---------- convention-read artifact parsers ----------

def _read(path):
    try:
        return Path(path).read_text()
    except FileNotFoundError:
        return None


def parse_preflight(path):
    text = _read(path)
    if text is None:
        return {"method": None, "schedulable": None}
    m_eng = re.search(r"^Engine:\s*(\S+)", text, re.MULTILINE)
    m_res = re.search(r"^Result:\s*\*\*(PASS|FAIL)\*\*", text, re.MULTILINE)
    return {
        "method": m_eng.group(1) if m_eng else None,
        "schedulable": (m_res.group(1) == "PASS") if m_res else None,
    }


def parse_preflight_nodes(path):
    text = _read(path)
    if text is None:
        return None
    m = re.search(r"^-\s*Nodes:\s*(\d+)", text, re.MULTILINE)
    return int(m.group(1)) if m else None


def parse_topology(path):
    text = _read(path)
    if text is None:
        return {"pattern": None, "width": None, "depth": None, "coupling": None}

    def grab(label, conv):
        m = re.search(rf"^\|\s*{label}\s*\|\s*([\d.]+)\s*\|", text, re.MULTILINE)
        return conv(m.group(1)) if m else None

    m_pat = re.search(r"## Selected Topology\s*\n+\s*\*\*([A-Za-z]+)\*\*", text)
    return {
        "pattern": m_pat.group(1) if m_pat else None,
        "width": grab("Width", int),
        "depth": grab("Depth", int),
        "coupling": grab("Coupling", float),
    }


def parse_sweep_summary(path):
    text = _read(path)
    if text is None:
        return {"ran": False, "nodes_visited": None,
                "nodes_refined": None, "max_flo_delta": None}

    def kv(field, conv):
        m = re.search(rf"^\|\s*{field}\s*\|\s*([+-]?[\d.]+)\s*\|", text, re.MULTILINE)
        return conv(m.group(1).lstrip("+")) if m else None

    return {
        "ran": True,
        "nodes_visited": kv("visited_nodes", int),
        "nodes_refined": kv("refine_count", int),
        "max_flo_delta": kv("max_delta", float),
    }


def count_folds(folds_dir):
    d = Path(folds_dir)
    if not d.is_dir():
        return 0
    return sum(1 for f in d.glob("*.md") if f.name != "_meta.yaml")


# ---------- build a ledger row ----------

def build_row(args) -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ts = now.isoformat().replace("+00:00", "Z")
    run_id = args.run_id or f"{args.project}-{now.strftime('%Y%m%dT%H%M%S')}"

    pf_path = args.preflight or f"/tmp/mp_preflight_{args.project}.md"
    topo_path = args.topology or f"/tmp/mp_topology_{args.project}.md"
    sweep_path = args.sweep_summary or "./.monkeypaw/sweep_summary.md"
    folds_dir = args.folds_dir or "./.monkeypaw/folds"

    pf = parse_preflight(pf_path)
    topo = parse_topology(topo_path)
    sweep = parse_sweep_summary(sweep_path)
    folds = count_folds(folds_dir)
    nodes = args.nodes if args.nodes is not None else parse_preflight_nodes(pf_path)

    if args.score is None or str(args.score).upper() == "NA":
        score = {"kind": "na", "value": None, "baseline": args.baseline, "delta": None}
    else:
        val = float(args.score)
        delta = (val - args.baseline) if args.baseline is not None else None
        score = {"kind": args.score_kind, "value": val, "baseline": args.baseline, "delta": delta}

    handoff = None if args.handoff_recovered is None else (args.handoff_recovered == "yes")

    return {
        "run_id": run_id,
        "ts": ts,
        "project": args.project,
        "archetype": args.archetype,
        "scale": args.scale,
        "nodes": nodes,
        "topology": {**topo, "misroute": bool(args.misroute)},
        "preflight": {**pf, "manual_resolution": bool(args.manual_resolution)},
        "context": {"max_governor_state": args.governor, "folds": folds,
                    "handoff_recovered": handoff},
        "sweep": {**sweep, "nodes_unrecovered": args.nodes_unrecovered},
        "resources": {"saturated": bool(args.resource_saturated)},
        "score": score,
    }


# ---------- gate evaluation ----------

def evaluate_gates(rows) -> dict:
    res = {}

    # T2-1: >=2 runs unschedulable or manually resolved
    c = sum(1 for r in rows
            if r["preflight"].get("schedulable") is False
            or r["preflight"].get("manual_resolution"))
    res["T2-1"] = {"met": c >= 2, "detail": f"{c}/2 unschedulable-or-manual runs"}

    # T2-2: >=1 run hit EMERGENCY and handoff failed to recover (or score dropped >=3)
    def t22(r):
        if r["context"].get("max_governor_state") != "EMERGENCY":
            return False
        if r["context"].get("handoff_recovered") is False:
            return True
        d = r["score"].get("delta")
        return d is not None and d <= -3
    c = sum(1 for r in rows if t22(r))
    res["T2-2"] = {"met": c >= 1, "detail": f"{c}/1 emergency+unrecovered runs"}

    # T2-3: any (archetype, score.kind) group with n>=5 and population sigma>5
    groups = {}
    for r in rows:
        s = r["score"]
        if s.get("kind") in ("oracle", "flo") and s.get("value") is not None:
            groups.setdefault((r["archetype"], s["kind"]), []).append(s["value"])
    crossed = []
    for (arch, kind), vals in groups.items():
        if len(vals) >= 5:
            sigma = statistics.pstdev(vals)
            if sigma > 5:
                crossed.append((arch, kind, len(vals), sigma))
    if crossed:
        arch, kind, n, sigma = max(crossed, key=lambda x: x[3])
        detail = f"archetype={arch} kind={kind} n={n} σ={sigma:.1f} (>5.0)"
    else:
        detail = "no archetype has n≥5 with σ>5"
    res["T2-3"] = {"met": bool(crossed), "detail": detail}

    # T2-4: total unrecovered threshold-failing nodes >= 3
    total = sum((r["sweep"].get("nodes_unrecovered") or 0) for r in rows)
    res["T2-4"] = {"met": total >= 3, "detail": f"{total}/3 unrecovered threshold-failing nodes"}

    # T1-1: any topology misroute
    c = sum(1 for r in rows if r["topology"].get("misroute"))
    res["T1-1"] = {"met": c >= 1, "detail": f"{c}/1 topology misroutes"}

    # T1-2: any resource saturation
    c = sum(1 for r in rows if r["resources"].get("saturated"))
    res["T1-2"] = {"met": c >= 1, "detail": f"{c}/1 resource saturations"}

    return res


def newly_crossed(results, prev_state):
    crossed = []
    for g in GATES:
        was = prev_state.get(g, "UNMET")
        now = "MET" if results[g]["met"] else "UNMET"
        if was == "UNMET" and now == "MET":
            crossed.append(g)
    return crossed


# ---------- CLI handlers ----------

def cmd_log(args):
    row = build_row(args)
    append_row(row)
    rows = read_ledger()
    results = evaluate_gates(rows)
    prev = read_state()
    crossed = newly_crossed(results, prev)
    write_state({g: ("MET" if results[g]["met"] else "UNMET") for g in GATES})
    print(f"✓ logged run {row['run_id']} → {ledger_path()}  ({len(rows)} rows total)")
    for g in crossed:
        print(f"ℹ️  GATE MET — {g} {GATE_NAMES[g]}: {results[g]['detail']}.")
        print(f"   Re-optimization opportunity → run `mp-gate report`, "
              f"then revisit V2-BACKLOG.md {g}.")


def cmd_check(args):
    rows = read_ledger()
    results = evaluate_gates(rows)
    print(f"Gate status over {len(rows)} runs ({ledger_path()}):")
    print("| Gate | Name | Status | Detail |")
    print("|---|---|---|---|")
    for g in GATES:
        st = "MET" if results[g]["met"] else "—"
        print(f"| {g} | {GATE_NAMES[g]} | {st} | {results[g]['detail']} |")


def cmd_report(args):
    rows = read_ledger()
    results = evaluate_gates(rows)
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        out_dir = Path(__file__).resolve().parent.parent / "telemetry"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    md = out_dir / f"gate_report_{today}.md"
    snap = out_dir / "corpus_snapshot.json"

    lines = [
        f"# monkeypaw gate report — {today}", "",
        f"Runs in ledger: {len(rows)}", "",
        "## Gate status", "",
        "| Gate | Name | Status | Detail |", "|---|---|---|---|",
    ]
    for g in GATES:
        st = "**MET**" if results[g]["met"] else "unmet"
        lines.append(f"| {g} | {GATE_NAMES[g]} | {st} | {results[g]['detail']} |")

    lines += ["", "## Score distribution (per archetype × kind)", "",
              "| Archetype | Kind | n | mean | σ |", "|---|---|---|---|---|"]
    groups = {}
    for r in rows:
        s = r["score"]
        if s.get("kind") in ("oracle", "flo") and s.get("value") is not None:
            groups.setdefault((r["archetype"], s["kind"]), []).append(s["value"])
    for (arch, kind), vals in sorted(groups.items()):
        mean = statistics.mean(vals)
        sigma = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        lines.append(f"| {arch} | {kind} | {len(vals)} | {mean:.1f} | {sigma:.1f} |")

    md.write_text("\n".join(lines) + "\n")
    snap.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")
    print(f"→ {md}")
    print(f"→ {snap}")


# ---------- argument parser ----------

def add_log_args(p):
    p.add_argument("--project", required=True)
    p.add_argument("--archetype", required=True,
                   choices=["code", "data", "lang", "numeric", "creative", "mixed"])
    p.add_argument("--scale", required=True, choices=["tiny", "standard", "large"])
    p.add_argument("--score", help="numeric score, or NA")
    p.add_argument("--score-kind", default="oracle", choices=["oracle", "flo"])
    p.add_argument("--baseline", type=float, default=None)
    p.add_argument("--nodes", type=int, default=None)
    p.add_argument("--governor", default="NORMAL",
                   choices=["NORMAL", "PROACTIVE", "EMERGENCY"])
    p.add_argument("--handoff-recovered", default=None, choices=["yes", "no"])
    p.add_argument("--nodes-unrecovered", type=int, default=0)
    p.add_argument("--misroute", action="store_true")
    p.add_argument("--resource-saturated", action="store_true")
    p.add_argument("--manual-resolution", action="store_true")
    p.add_argument("--run-id", default=None, help="override run_id (idempotency/testing)")
    # artifact path overrides (default to conventional paths)
    p.add_argument("--preflight", default=None)
    p.add_argument("--topology", default=None)
    p.add_argument("--sweep-summary", default=None)
    p.add_argument("--folds-dir", default=None)


def build_parser():
    p = argparse.ArgumentParser(prog="mp-gate", description=USAGE,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    add_log_args(sub.add_parser("log", help="Harvest one run into the ledger"))
    sub.add_parser("check", help="Print gate status table")
    rp = sub.add_parser("report", help="Write committable report + snapshot")
    rp.add_argument("--out-dir", default=None)
    return p


def main():
    args = build_parser().parse_args()
    try:
        if args.cmd == "log":
            cmd_log(args)
        elif args.cmd == "check":
            cmd_check(args)
        elif args.cmd == "report":
            cmd_report(args)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
