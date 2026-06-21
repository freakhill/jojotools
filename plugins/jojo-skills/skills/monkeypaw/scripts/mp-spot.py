#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
mp-spot.py — Random SPOT node selection (~20% of nodes, reproducible)

Usage:
  mp-spot.py [dag.json] [--seed N] [--pct N]
  echo '{...}' | mp-spot.py [--seed N] [--pct N]

Options:
  --seed N    Random seed for reproducibility (default: random)
  --pct N     Percentage of nodes to select (default: 20)
  -h, --help  Show this help message and exit

Output:
  Prints selected node IDs, one per line.
  Writes report to /tmp/mp_spot_<project>.md
"""

import json
import sys
import random
import math
from datetime import datetime

USAGE = """\
Usage:
  mp-spot.py [dag.json] [--seed N] [--pct N]
  echo '{...}' | mp-spot.py [--seed N] [--pct N]

Options:
  --seed N    Random seed for reproducibility (default: random)
  --pct N     Percentage of nodes to select (default: 20)
  -h, --help  Show this help message and exit

Output:
  Prints selected node IDs, one per line.
  Writes report to /tmp/mp_spot_<project>.md

Example:
  echo '{"project":"demo","nodes":[{"id":"A"},{"id":"B"},{"id":"C"}]}' | mp-spot.py --pct 50 --seed 42
"""


def parse_args(argv):
    # Handle --help / -h first
    for arg in argv[1:]:
        if arg in ("-h", "--help"):
            print(USAGE)
            sys.exit(0)

    args = argv[1:]
    seed = None
    pct = 20
    dag_file = None

    i = 0
    while i < len(args):
        if args[i] == "--seed":
            if i + 1 >= len(args):
                print("Error: --seed requires a value", file=sys.stderr)
                sys.exit(1)
            try:
                seed = int(args[i + 1])
            except ValueError:
                print(f"Error: --seed value must be integer, got '{args[i+1]}'", file=sys.stderr)
                sys.exit(1)
            i += 2
        elif args[i] == "--pct":
            if i + 1 >= len(args):
                print("Error: --pct requires a value", file=sys.stderr)
                sys.exit(1)
            try:
                pct = int(args[i + 1])
                if not (1 <= pct <= 100):
                    raise ValueError
            except ValueError:
                print(f"Error: --pct must be 1-100, got '{args[i+1]}'", file=sys.stderr)
                sys.exit(1)
            i += 2
        elif args[i].startswith("--"):
            print(f"Error: unknown option '{args[i]}'", file=sys.stderr)
            print(USAGE, file=sys.stderr)
            sys.exit(1)
        else:
            if dag_file is not None:
                print(f"Error: unexpected argument '{args[i]}'", file=sys.stderr)
                sys.exit(1)
            dag_file = args[i]
            i += 1

    return dag_file, seed, pct


def load_dag(dag_file):
    if dag_file:
        try:
            with open(dag_file) as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"Error: file not found: {dag_file}", file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON in {dag_file}: {e}", file=sys.stderr)
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


def write_report(project, selected, all_nodes, seed, pct, output_path):
    selected_set = set(selected)
    lines = [
        f"# mp-spot: {project}",
        f"",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Seed: {seed if seed is not None else 'random'}",
        f"Percentage: {pct}%",
        f"Selected: {len(selected)} / {len(all_nodes)} nodes",
        f"",
        f"## Selected Nodes [SPOT]",
        f"",
    ]
    for nid in selected:
        lines.append(f"- `{nid}` [SPOT]")

    lines += [
        f"",
        f"## All Nodes",
        f"",
    ]
    for n in all_nodes:
        nid = n["id"]
        marker = " **[SPOT]**" if nid in selected_set else ""
        name = n.get("name", "")
        name_str = f" — {name}" if name else ""
        lines.append(f"- `{nid}`{name_str}{marker}")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    try:
        dag_file, seed, pct = parse_args(sys.argv)
        dag = load_dag(dag_file)

        project = dag.get("project", "unknown")
        nodes = dag.get("nodes", [])

        if not nodes:
            print("Error: DAG has no nodes", file=sys.stderr)
            sys.exit(1)

        output_path = f"/tmp/mp_spot_{project}.md"

        node_ids = [n["id"] for n in nodes]
        k = max(1, math.ceil(len(node_ids) * pct / 100))

        rng = random.Random(seed)
        selected = sorted(rng.sample(node_ids, min(k, len(node_ids))))

        write_report(project, selected, nodes, seed, pct, output_path)

        for nid in selected:
            print(nid)

        print(f"# {len(selected)}/{len(node_ids)} nodes selected ({pct}%, seed={seed})", file=sys.stderr)
        print(f"# Report: {output_path}", file=sys.stderr)

    except SystemExit:
        raise
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
