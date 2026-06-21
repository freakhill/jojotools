#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["z3-solver"]
# ///
"""
mp-preflight.py — DAG schedulability pre-flight check (Z3 or manual fallback)

Usage:
  mp-preflight.py [dag.json]        # file argument
  echo '{...}' | mp-preflight.py   # stdin

Options:
  -h, --help    Show this help message and exit

Exit codes: 0 = PASS, 1 = FAIL or error
Output: /tmp/mp_preflight_<project>.md
"""

import json
import sys
import os
from collections import defaultdict, deque
from datetime import datetime

USAGE = """\
Usage:
  mp-preflight.py [dag.json]        # file argument
  echo '{...}' | mp-preflight.py   # stdin

Options:
  -h, --help    Show this help message and exit

Exit codes: 0 = PASS, 1 = FAIL or error
Output: /tmp/mp_preflight_<project>.md

Example:
  echo '{"project":"demo","nodes":[{"id":"A"},{"id":"B","depends_on":["A"]}]}' | mp-preflight.py
"""


def load_dag(args):
    # Handle --help / -h before anything else
    for arg in args[1:]:
        if arg in ("-h", "--help"):
            print(USAGE)
            sys.exit(0)

    # Filter out unknown flags to give clean error messages
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
    """Return node_ids, adjacency list, and reverse adjacency."""
    node_ids = {n["id"] for n in nodes}
    adj = defaultdict(list)       # id -> [successors]
    radj = defaultdict(list)      # id -> [predecessors]
    for n in nodes:
        nid = n["id"]
        for dep in n.get("depends_on", []):
            if dep not in node_ids:
                raise ValueError(f"Node {nid} depends on unknown node {dep}")
            adj[dep].append(nid)
            radj[nid].append(dep)
    return node_ids, adj, radj


def topo_sort(node_ids, radj):
    """Kahn's algorithm. Returns (sorted_list, cycle_nodes)."""
    adj = defaultdict(list)
    for node, preds in radj.items():
        for p in preds:
            adj[p].append(node)

    in_deg = {n: len(radj[n]) for n in node_ids}
    queue = deque(sorted(n for n in node_ids if in_deg[n] == 0))
    order = []
    while queue:
        n = queue.popleft()
        order.append(n)
        for succ in adj[n]:
            in_deg[succ] -= 1
            if in_deg[succ] == 0:
                queue.append(succ)
    cycle_nodes = node_ids - set(order)
    return order, cycle_nodes


def find_cycle_description(cycle_nodes, radj):
    """Find a short cycle path to display."""
    if not cycle_nodes:
        return ""
    start = next(iter(cycle_nodes))
    visited = {}
    path = []

    def dfs(node, depth=0):
        if depth > len(cycle_nodes) + 1:
            return None
        if node in visited:
            idx = visited[node]
            return path[idx:]
        visited[node] = len(path)
        path.append(node)
        for pred in radj.get(node, []):
            if pred in cycle_nodes:
                result = dfs(pred, depth + 1)
                if result:
                    return result
        path.pop()
        del visited[node]
        return None

    cycle = dfs(start)
    if cycle:
        return "→".join(cycle + [cycle[0]])
    return "→".join(sorted(cycle_nodes))


def build_reachability(node_ids, adj):
    """
    Compute transitive closure: reachable[a] = set of nodes reachable from a
    via forward edges. Processes in reverse topological order.
    """
    in_rem = defaultdict(int)
    for src, dsts in adj.items():
        for dst in dsts:
            in_rem[dst] += 1
    for nid in node_ids:
        if nid not in in_rem:
            in_rem[nid] = 0

    q = deque(sorted(nid for nid in node_ids if in_rem[nid] == 0))
    topo = []
    while q:
        nid = q.popleft()
        topo.append(nid)
        for succ in adj.get(nid, []):
            in_rem[succ] -= 1
            if in_rem[succ] == 0:
                q.append(succ)

    reachable = {nid: set() for nid in node_ids}
    for nid in reversed(topo):
        for succ in adj.get(nid, []):
            reachable[nid].add(succ)
            reachable[nid].update(reachable[succ])

    return reachable


def detect_parallel_resource_conflicts(nodes, resources, adj):
    """
    Pre-check BEFORE Z3/manual: detect nodes where:
      - parallel=true
      - they share the same resource
      - no ordering between them (neither is reachable from the other)

    Returns list of conflict descriptions naming the conflicting nodes.
    Exit 1 with a specific message if any conflicts found.
    """
    if not resources:
        return []

    node_ids = {n["id"] for n in nodes}
    reachable = build_reachability(node_ids, adj)

    # Group parallel=true nodes by resource
    resource_parallel_nodes = defaultdict(list)
    for n in nodes:
        if n.get("parallel") is True:
            res = n.get("resource")
            if res and res in resources:
                resource_parallel_nodes[res].append(n["id"])

    conflicts = []
    for res, parallel_nodes in resource_parallel_nodes.items():
        limit = resources.get(res, 1)
        if len(parallel_nodes) <= limit:
            continue
        # Find pairs with no ordering between them
        unordered_pairs = []
        for i in range(len(parallel_nodes)):
            for j in range(i + 1, len(parallel_nodes)):
                a, b = parallel_nodes[i], parallel_nodes[j]
                a_reaches_b = b in reachable.get(a, set())
                b_reaches_a = a in reachable.get(b, set())
                if not a_reaches_b and not b_reaches_a:
                    unordered_pairs.append((a, b))
        if unordered_pairs:
            pair_strs = [f"{a}↔{b}" for a, b in unordered_pairs]
            conflicts.append(
                f"parallel resource conflict on '{res}' (limit={limit}): "
                f"nodes {', '.join(sorted(parallel_nodes))} — unordered parallel pairs: "
                f"{', '.join(pair_strs)}"
            )
    return conflicts


def check_resource_conflicts(nodes, resources, order):
    """
    Check exclusive resources: if a resource has limit=1,
    more nodes than limit → flag conflict.
    Returns list of conflict descriptions.
    """
    if not resources:
        return []
    conflicts = []
    resource_nodes = defaultdict(list)
    for n in nodes:
        res = n.get("resource")
        if res and res in resources:
            resource_nodes[res].append(n["id"])

    for res, limit in resources.items():
        using = resource_nodes[res]
        if len(using) > limit:
            conflicts.append(
                f"resource '{res}' (limit={limit}) has {len(using)} nodes: {', '.join(using)}"
            )
    return conflicts


def preflight_z3(nodes, resources, worker_limit):
    """
    Z3-based schedulability check.
    Returns (passed: bool, detail: str, engine: str)
    """
    try:
        from z3 import Solver, Int, Or, sat, unsat
    except ImportError:
        return None, "z3 not available", "z3"

    node_ids_list = [n["id"] for n in nodes]

    s = Solver()
    start_t = {nid: Int(f"start_{nid}") for nid in node_ids_list}
    end_t   = {nid: Int(f"end_{nid}")   for nid in node_ids_list}

    for nid in node_ids_list:
        s.add(start_t[nid] >= 0)
        s.add(end_t[nid] == start_t[nid] + 1)

    for n in nodes:
        nid = n["id"]
        for dep in n.get("depends_on", []):
            if dep in start_t:
                s.add(start_t[nid] >= end_t[dep])

    resource_nodes = defaultdict(list)
    for n in nodes:
        res = n.get("resource")
        if res and resources and res in resources:
            resource_nodes[res].append(n["id"])

    for res, limit in (resources or {}).items():
        using = resource_nodes[res]
        if limit == 1 and len(using) > 1:
            for i in range(len(using)):
                for j in range(i + 1, len(using)):
                    a, b = using[i], using[j]
                    s.add(Or(end_t[a] <= start_t[b], end_t[b] <= start_t[a]))

    result = s.check()
    if result == sat:
        return True, "satisfiable schedule exists", "z3"
    elif result == unsat:
        s2 = Solver()
        for nid in node_ids_list:
            s2.add(start_t[nid] >= 0)
            s2.add(end_t[nid] == start_t[nid] + 1)
        for n in nodes:
            nid = n["id"]
            for dep in n.get("depends_on", []):
                if dep in start_t:
                    s2.add(start_t[nid] >= end_t[dep])
        if s2.check() == unsat:
            return False, "dependency cycle detected (Z3 unsat on ordering constraints)", "z3"
        else:
            return False, "resource over-allocation: no valid schedule within resource limits", "z3"
    else:
        return False, f"Z3 returned unknown result: {result}", "z3"


def preflight_manual(nodes, resources):
    """
    Manual topological sort + cycle detection fallback.
    Returns (passed: bool, detail: str, engine: str)
    """
    node_ids_list = [n["id"] for n in nodes]
    node_ids = set(node_ids_list)

    for n in nodes:
        for dep in n.get("depends_on", []):
            if dep not in node_ids:
                return False, f"node '{n['id']}' depends on unknown node '{dep}'", "manual"

    try:
        _, adj, radj = build_graph(nodes)
    except ValueError as e:
        return False, str(e), "manual"

    order, cycle_nodes = topo_sort(node_ids, radj)

    if cycle_nodes:
        cycle_desc = find_cycle_description(cycle_nodes, radj)
        return False, f"cycle involving {cycle_desc}", "manual"

    conflicts = check_resource_conflicts(nodes, resources or {}, order)
    if conflicts:
        return False, "; ".join(conflicts), "manual"

    if len(order) < len(node_ids):
        missing = node_ids - set(order)
        return False, f"unreachable nodes: {', '.join(sorted(missing))}", "manual"

    return True, "topological sort valid, no cycles, no resource conflicts", "manual"


def write_report(project, passed, detail, engine, nodes, resources, worker_limit, output_path):
    status_icon = "PASS" if passed else "FAIL"
    lines = [
        f"# mp-preflight: {project}",
        f"",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Engine: {engine}",
        f"Result: **{status_icon}**",
        f"",
        f"## Detail",
        f"",
        f"{detail}",
        f"",
        f"## DAG Summary",
        f"",
        f"- Nodes: {len(nodes)}",
        f"- Resources: {json.dumps(resources) if resources else 'none'}",
        f"- Worker limit: {worker_limit if worker_limit else 'unset'}",
        f"",
        f"## Node List",
        f"",
    ]
    for n in nodes:
        deps = n.get("depends_on", [])
        res = n.get("resource", "")
        parallel_flag = " [parallel]" if n.get("parallel") else ""
        dep_str = f" <- {', '.join(deps)}" if deps else ""
        res_str = f" [{res}]" if res else ""
        lines.append(f"- `{n['id']}` {n.get('name', '')}{dep_str}{res_str}{parallel_flag}")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    try:
        dag = load_dag(sys.argv)

        project = dag.get("project", "unknown")
        nodes = dag.get("nodes", [])
        resources = dag.get("resources", {})
        worker_limit = dag.get("worker_limit")

        if not nodes:
            print("Error: DAG has no nodes", file=sys.stderr)
            sys.exit(1)

        output_path = f"/tmp/mp_preflight_{project}.md"

        # Build forward adjacency for reachability analysis
        node_ids = {n["id"] for n in nodes}
        adj = defaultdict(list)
        for n in nodes:
            for dep in n.get("depends_on", []):
                if dep in node_ids:
                    adj[dep].append(n["id"])

        # Step 1: parallel resource conflict pre-check (before Z3/manual)
        parallel_conflicts = detect_parallel_resource_conflicts(nodes, resources, adj)
        if parallel_conflicts:
            detail = "PARALLEL RESOURCE CONFLICT — " + "; ".join(parallel_conflicts)
            write_report(project, False, detail, "pre-check", nodes, resources, worker_limit, output_path)
            print(f"✗ PRE-FLIGHT FAIL: {detail}")
            sys.exit(1)

        # Step 2: Z3 first, manual fallback
        passed, detail, engine = preflight_z3(nodes, resources, worker_limit)

        if passed is None:
            passed, detail, engine = preflight_manual(nodes, resources)

        write_report(project, passed, detail, engine, nodes, resources, worker_limit, output_path)

        if passed:
            print(f"✓ PRE-FLIGHT PASS ({engine})")
        else:
            print(f"✗ PRE-FLIGHT FAIL: {detail}")

        sys.exit(0 if passed else 1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
