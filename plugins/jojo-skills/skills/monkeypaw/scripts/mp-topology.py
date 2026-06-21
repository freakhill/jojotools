#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
mp-topology.py — Compute DAG metrics and select topology

Usage:
  mp-topology.py [dag.json]       # file argument
  echo '{...}' | mp-topology.py  # stdin

Options:
  -h, --help  Show this help message and exit

Metrics computed:
  Width    = max nodes in any single BFS layer
  Depth    = number of layers (longest path in hops)
  Coupling = fraction of nodes with >1 incoming OR >1 outgoing edge

Topology selection:
  Width>3, Depth<=4, Coupling<0.3  → Parallel
  Depth>8                          → Hierarchical
  Width<=2, Depth<=6               → Sequential
  else                             → Hybrid

Output: /tmp/mp_topology_<project>.md
"""

import json
import sys
from collections import defaultdict, deque
from datetime import datetime

USAGE = """\
Usage:
  mp-topology.py [dag.json]       # file argument
  echo '{...}' | mp-topology.py  # stdin

Options:
  -h, --help  Show this help message and exit

Metrics:
  Width    = max nodes in any single BFS layer
  Depth    = number of layers (longest path in hops)
  Coupling = fraction of nodes with >1 incoming OR >1 outgoing edge

Topology selection:
  Width>3, Depth<=4, Coupling<0.3  → Parallel
  Depth>8                          → Hierarchical
  Width<=2, Depth<=6               → Sequential
  else                             → Hybrid

Output: /tmp/mp_topology_<project>.md

Example:
  echo '{"project":"demo","nodes":[{"id":"A"},{"id":"B","depends_on":["A"]}]}' | mp-topology.py
"""


def load_dag(args):
    # Handle --help / -h first
    for arg in args[1:]:
        if arg in ("-h", "--help"):
            print(USAGE)
            sys.exit(0)

    positional = [a for a in args[1:] if not a.startswith("-")]
    flags = [a for a in args[1:] if a.startswith("-")]
    for flag in flags:
        print(f"Error: unknown option '{flag}'", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    if positional:
        path = positional[0]
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


def build_graph(nodes):
    node_ids = {n["id"] for n in nodes}
    adj = defaultdict(list)   # forward edges
    radj = defaultdict(list)  # reverse edges (predecessors)
    in_deg = {n["id"]: 0 for n in nodes}
    out_deg = {n["id"]: 0 for n in nodes}

    for n in nodes:
        nid = n["id"]
        for dep in n.get("depends_on", []):
            if dep not in node_ids:
                print(f"Warning: node '{nid}' depends on unknown '{dep}' — ignored", file=sys.stderr)
                continue
            adj[dep].append(nid)
            radj[nid].append(dep)
            in_deg[nid] += 1
            out_deg[dep] += 1

    return adj, radj, in_deg, out_deg


def compute_bfs_layers(nodes, adj, in_deg):
    """
    BFS from all source nodes (in_deg=0) to assign layers.
    Layer = longest path from any source to this node.
    Returns list of layers, each a list of node ids.
    """
    node_ids = [n["id"] for n in nodes]
    layer = {nid: 0 for nid in node_ids}

    in_rem = dict(in_deg)
    q = deque(sorted(nid for nid in node_ids if in_rem[nid] == 0))
    topo_order = []
    while q:
        nid = q.popleft()
        topo_order.append(nid)
        for succ in adj[nid]:
            layer[succ] = max(layer[succ], layer[nid] + 1)
            in_rem[succ] -= 1
            if in_rem[succ] == 0:
                q.append(succ)

    if len(topo_order) < len(node_ids):
        # Cycle present — assign remaining nodes to last layer
        max_layer = max(layer.values()) if layer else 0
        topo_set = set(topo_order)
        for nid in node_ids:
            if nid not in topo_set:
                layer[nid] = max_layer + 1

    max_l = max(layer.values()) if layer else 0
    layers = [[] for _ in range(max_l + 1)]
    for nid, l in layer.items():
        layers[l].append(nid)

    return layers


def compute_metrics(nodes, adj, in_deg, out_deg):
    layers = compute_bfs_layers(nodes, adj, in_deg)
    depth = len(layers)
    width = max(len(layer) for layer in layers) if layers else 0

    n = len(nodes)
    if n == 0:
        coupling = 0.0
    else:
        coupled_count = sum(
            1 for nid in (node["id"] for node in nodes)
            if in_deg[nid] > 1 or out_deg[nid] > 1
        )
        coupling = coupled_count / n

    return width, depth, coupling, layers


def select_topology(width, depth, coupling):
    if width > 3 and depth <= 4 and coupling < 0.3:
        return "Parallel"
    elif depth > 8:
        return "Hierarchical"
    elif width <= 2 and depth <= 6:
        return "Sequential"
    else:
        return "Hybrid"


def topology_rationale(topology, width, depth, coupling):
    if topology == "Parallel":
        return f"Width={width}>3, Depth={depth}<=4, Coupling={coupling:.2f}<0.3 → broad, loosely-coupled graph suits parallel execution"
    elif topology == "Hierarchical":
        return f"Depth={depth}>8 → deep critical path requires layered hierarchical orchestration"
    elif topology == "Sequential":
        return f"Width={width}<=2, Depth={depth}<=6 → narrow linear graph suits sequential execution"
    else:
        return f"Width={width}, Depth={depth}, Coupling={coupling:.2f} → mixed structure; Hybrid recommended"


def write_report(project, width, depth, coupling, topology, rationale, layers, output_path):
    lines = [
        f"# mp-topology: {project}",
        f"",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"## Metrics",
        f"",
        f"| Metric   | Value |",
        f"|----------|-------|",
        f"| Width    | {width} |",
        f"| Depth    | {depth} |",
        f"| Coupling | {coupling:.2f} |",
        f"",
        f"## Selected Topology",
        f"",
        f"**{topology}**",
        f"",
        f"Rationale: {rationale}",
        f"",
        f"## BFS Layers",
        f"",
    ]
    for i, layer in enumerate(layers):
        lines.append(f"Layer {i}: {', '.join(sorted(layer))}")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    try:
        dag = load_dag(sys.argv)

        project = dag.get("project", "unknown")
        nodes = dag.get("nodes", [])

        if not nodes:
            print("Error: DAG has no nodes", file=sys.stderr)
            sys.exit(1)

        output_path = f"/tmp/mp_topology_{project}.md"

        adj, radj, in_deg, out_deg = build_graph(nodes)
        width, depth, coupling, layers = compute_metrics(nodes, adj, in_deg, out_deg)
        topology = select_topology(width, depth, coupling)
        rationale = topology_rationale(topology, width, depth, coupling)

        write_report(project, width, depth, coupling, topology, rationale, layers, output_path)

        print(f"Width={width}  Depth={depth}  Coupling={coupling:.2f}")
        print(f"Topology → {topology}")
        print(f"Rationale: {rationale}")
        print(f"Report: {output_path}")

    except SystemExit:
        raise
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
