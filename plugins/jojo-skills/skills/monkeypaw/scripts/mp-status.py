#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
mp-status.py — Status doc management and DORA metrics

Subcommands:
  init  <project> [dag.json]   Create fresh status doc (DAG from stdin or file)
  done  <project> <node_id> <artifact_path>  Mark node DONE
  dora  <project>              Print DORA dashboard
  show  <project>              Print full status + SUMMARY line

Options:
  -h, --help    Show this help message and exit

Status doc: /tmp/mp_status_<project>.md
"""

import json
import sys
import os
import re
from datetime import datetime, timezone


USAGE = """\
Usage:
  mp-status.py init <project> [dag.json]
  mp-status.py done <project> <node_id> <artifact_path>
  mp-status.py dora <project>
  mp-status.py show <project>

Options:
  -h, --help    Show this help message and exit

Status doc: /tmp/mp_status_<project>.md

Examples:
  echo '{...}' | mp-status.py init myproject
  mp-status.py done myproject N01 /tmp/artifact.md
  mp-status.py show myproject
"""


def status_path(project):
    return f"/tmp/mp_status_{project}.md"


def load_dag_from_file_or_stdin(path=None):
    if path:
        try:
            with open(path) as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"Error: file not found: {path}", file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON in {path}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        data = sys.stdin.read().strip()
        if not data:
            print(USAGE, file=sys.stderr)
            sys.exit(1)
        try:
            return json.loads(data)
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON on stdin: {e}", file=sys.stderr)
            sys.exit(1)


def load_status(project):
    path = status_path(project)
    if not os.path.exists(path):
        print(f"Error: no status doc for project '{project}' at {path}", file=sys.stderr)
        print("Run: mp-status.py init <project> [dag.json]", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return f.read()


def save_status(project, content):
    path = status_path(project)
    with open(path, "w") as f:
        f.write(content)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_init(args):
    if len(args) < 3:
        print("Error: init requires <project>", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    project = args[2]
    dag_file = args[3] if len(args) > 3 else None
    dag = load_dag_from_file_or_stdin(dag_file)

    nodes = dag.get("nodes", [])
    if not nodes:
        print("Error: DAG has no nodes", file=sys.stderr)
        sys.exit(1)

    created_at = now_iso()
    lines = [
        f"# Status: {project}",
        f"",
        f"Created: {created_at}",
        f"Project: {project}",
        f"Nodes: {len(nodes)}",
        f"",
        f"<!-- mp-status-meta",
        f"project: {project}",
        f"created_at: {created_at}",
        f"-->",
        f"",
        f"## Node Status",
        f"",
        f"| Node | Name | Status | Done At | Artifact |",
        f"|------|------|--------|---------|----------|",
    ]
    for n in nodes:
        nid = n["id"]
        name = n.get("name", "")
        lines.append(f"| {nid} | {name} | TODO | — | — |")

    lines += [
        f"",
        f"## DORA Metrics",
        f"",
        f"| Metric | Value | Notes |",
        f"|--------|-------|-------|",
        f"| Deployment Frequency | — | complete DAG executions/day |",
        f"| Lead Time (median) | — | pending→artifact median minutes |",
        f"| Change Failure Rate | 0% | node rework % |",
        f"| MTTR | — | failure→recovery minutes |",
        f"| Reliability | — | quality score variance |",
        f"",
        f"<!-- dora-events",
        f"-->",
        f"",
        f"## Event Log",
        f"",
        f"| Time | Event |",
        f"|------|-------|",
        f"| {created_at} | project initialized with {len(nodes)} nodes |",
    ]

    content = "\n".join(lines) + "\n"
    save_status(project, content)
    print(f"✓ Status doc created: {status_path(project)}")
    print(f"  {len(nodes)} nodes set to TODO")


def cmd_done(args):
    if len(args) < 5:
        print("Error: done requires <project> <node_id> <artifact_path>", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    project = args[2]
    node_id = args[3]
    artifact = args[4]

    content = load_status(project)
    done_at = now_iso()

    # Find the node row and update it
    pattern = re.compile(
        r"(\|\s*" + re.escape(node_id) + r"\s*\|[^|]*\|)\s*TODO\s*(\|[^|]*\|[^|]*\|)"
    )
    replacement = f"\\g<1> DONE | {done_at} | {artifact} |"
    updated, count = pattern.subn(replacement, content)

    if count == 0:
        if node_id not in content:
            print(f"Error: node '{node_id}' not found in status doc for '{project}'", file=sys.stderr)
            sys.exit(1)
        if re.search(r"\|\s*" + re.escape(node_id) + r"\s*\|[^|]*\|\s*DONE\s*\|", content):
            print(f"Warning: node '{node_id}' is already DONE", file=sys.stderr)
        else:
            print(f"Error: could not update node '{node_id}' — unexpected format", file=sys.stderr)
            sys.exit(1)
        return

    # Append event to event log
    event_line = f"| {done_at} | node {node_id} marked DONE → {artifact} |"
    updated = updated.rstrip("\n") + "\n" + event_line + "\n"

    # Recalculate DORA metrics
    updated = recalculate_dora(updated, project)

    save_status(project, updated)
    print(f"✓ Node {node_id} marked DONE")
    print(f"  Artifact: {artifact}")
    print(f"  At: {done_at}")


def parse_node_counts(content):
    """Parse the node status table and return (total, done) counts."""
    total = 0
    done = 0
    in_node_table = False
    for line in content.split("\n"):
        if line.startswith("| Node ") or line.startswith("|------|"):
            in_node_table = True
            continue
        if in_node_table:
            if line.startswith("## ") or line.strip() == "":
                in_node_table = False
                continue
            m = re.match(r"\|\s*(\S+)\s*\|\s*([^|]*)\|\s*(TODO|DONE)\s*\|", line)
            if m:
                total += 1
                if m.group(3).strip() == "DONE":
                    done += 1
    return total, done


def parse_done_timestamps(content):
    """Extract done_at ISO strings from DONE rows in the node table."""
    stamps = []
    in_node_table = False
    for line in content.split("\n"):
        if line.startswith("| Node ") or line.startswith("|------|"):
            in_node_table = True
            continue
        if in_node_table:
            if line.startswith("## ") or line.strip() == "":
                in_node_table = False
                continue
            m = re.match(
                r"\|\s*\S+\s*\|\s*[^|]*\|\s*DONE\s*\|\s*([^|]+)\|",
                line,
            )
            if m:
                ts = m.group(1).strip()
                if ts and ts != "—":
                    stamps.append(ts)
    return stamps


def parse_created_at(content):
    """Extract created_at from the meta block."""
    m = re.search(r"created_at:\s*(\S+)", content)
    return m.group(1).strip() if m else None


def _parse_iso_z(s):
    """Parse ISO8601 with trailing Z. Returns datetime or None."""
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def compute_lead_time_minutes(content):
    """
    Compute median per-node lead time in minutes (decimal).
    Definition: time between status-doc creation and first DONE, then
    between consecutive DONE timestamps. Median of those deltas.
    Returns None if not enough data.
    """
    created = parse_created_at(content)
    stamps = parse_done_timestamps(content)
    if not created or not stamps:
        return None

    t0 = _parse_iso_z(created)
    times = [_parse_iso_z(s) for s in stamps]
    times = [t for t in times if t is not None]
    if t0 is None or not times:
        return None

    times.sort()
    deltas_s = []
    prev = t0
    for t in times:
        d = (t - prev).total_seconds()
        if d >= 0:
            deltas_s.append(d)
        prev = t
    if not deltas_s:
        return None

    deltas_s.sort()
    n = len(deltas_s)
    if n % 2:
        median_s = deltas_s[n // 2]
    else:
        median_s = (deltas_s[n // 2 - 1] + deltas_s[n // 2]) / 2.0
    return median_s / 60.0


def recalculate_dora(content, project):
    """Update DORA section based on current node states."""
    total, done = parse_node_counts(content)

    if total == 0:
        return content

    cfr = 0.0
    completion_pct = int(done / total * 100)

    lt = compute_lead_time_minutes(content)
    if lt is None:
        lead_time_str = "—"
    elif lt < 0.01:
        lead_time_str = "<0.01 min"
    else:
        lead_time_str = f"{lt:.2f} min"

    dora_block = f"""## DORA Metrics

| Metric | Value | Notes |
|--------|-------|-------|
| Deployment Frequency | — | complete DAG executions/day |
| Lead Time (median) | {lead_time_str} | pending→artifact median minutes |
| Change Failure Rate | {cfr:.0f}% | node rework % |
| MTTR | — | failure→recovery minutes |
| Reliability | — | quality score variance |
| Completion | {completion_pct}% | {done}/{total} nodes DONE |"""

    content = re.sub(
        r"## DORA Metrics\n.*?(?=\n<!-- dora-events|\n## )",
        dora_block + "\n",
        content,
        flags=re.DOTALL
    )
    return content


def cmd_dora(args):
    if len(args) < 3:
        print("Error: dora requires <project>", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    project = args[2]
    content = load_status(project)

    in_dora = False
    lines_out = []
    for line in content.split("\n"):
        if line.startswith("## DORA"):
            in_dora = True
        elif line.startswith("## ") and in_dora:
            break
        if in_dora:
            lines_out.append(line)

    if not lines_out:
        print(f"No DORA section found in status doc for '{project}'", file=sys.stderr)
        sys.exit(1)

    total, done = parse_node_counts(content)

    print(f"=== DORA Dashboard: {project} ===")
    print("\n".join(lines_out))
    if total > 0:
        print(f"\nNode completion: {done}/{total} ({int(done/total*100)}%)")


def build_summary_line(content):
    """
    Build a one-line SUMMARY for cmd_show:
    SUMMARY: 3/7 nodes DONE (43%) | Remaining: 4 | Lead Time: — avg | CFR: 0% | Reliability: —
    """
    total, done = parse_node_counts(content)

    if total == 0:
        return "SUMMARY: no nodes found"

    pct = int(done / total * 100)
    remaining = total - done

    # Extract CFR from DORA table if present
    cfr = "0%"
    m = re.search(r"\|\s*Change Failure Rate\s*\|\s*([^|]+)\|", content)
    if m:
        cfr = m.group(1).strip()

    # Extract Lead Time if present
    lead_time = "—"
    m = re.search(r"\|\s*Lead Time[^|]*\|\s*([^|]+)\|", content)
    if m:
        val = m.group(1).strip()
        if val not in ("—", "-", ""):
            lead_time = val

    # Extract Reliability if present
    reliability = "—"
    m = re.search(r"\|\s*Reliability\s*\|\s*([^|]+)\|", content)
    if m:
        val = m.group(1).strip()
        if val not in ("—", "-", ""):
            reliability = val

    return (
        f"SUMMARY: {done}/{total} nodes DONE ({pct}%) | "
        f"Remaining: {remaining} | "
        f"Lead Time: {lead_time} avg | "
        f"CFR: {cfr} | "
        f"Reliability: {reliability}"
    )


def cmd_show(args):
    if len(args) < 3:
        print("Error: show requires <project>", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    project = args[2]
    content = load_status(project)

    # Compact terminal output: summary + node table only
    summary = build_summary_line(content)
    print(summary)

    # Extract and print node table (lines between ## Node Status header and next ##)
    lines = content.split("\n")
    in_nodes = False
    for line in lines:
        if line.startswith("## Node Status"):
            in_nodes = True
            continue
        if in_nodes and line.startswith("##"):
            break
        if in_nodes:
            print(line)

    print(f"\nFull doc: {status_path(project)}")


def main():
    args = sys.argv

    # Handle --help / -h anywhere in argv
    for arg in args[1:]:
        if arg in ("-h", "--help"):
            print(USAGE)
            sys.exit(0)

    if len(args) < 2:
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    subcmd = args[1]

    try:
        if subcmd == "init":
            cmd_init(args)
        elif subcmd == "done":
            cmd_done(args)
        elif subcmd == "dora":
            cmd_dora(args)
        elif subcmd == "show":
            cmd_show(args)
        else:
            print(f"Error: unknown subcommand '{subcmd}'", file=sys.stderr)
            print(USAGE, file=sys.stderr)
            sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
