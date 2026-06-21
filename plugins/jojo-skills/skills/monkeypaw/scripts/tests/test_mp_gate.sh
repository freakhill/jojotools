#!/usr/bin/env bash
# Tests for mp-gate.py: ledger I/O, idempotency, artifact parsers, gate
# evaluation, edge-trigger, report export. Run: bash test_mp_gate.sh
set -e

SCRIPTS="$(cd "$(dirname "$0")/.." && pwd)"
MP="$SCRIPTS/mp-gate.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export MP_GATE_HOME="$TMP/home"          # isolate ledger from real ~/.monkeypaw

# ---------- Test 1: log a single args-only run, then check ----------
OUT=$(uv run "$MP" log --project demo --archetype code --scale standard --score 90 \
    --preflight "$TMP/none.md" --topology "$TMP/none.md" \
    --sweep-summary "$TMP/none.md" --folds-dir "$TMP/nofolds" 2>&1)
echo "$OUT" | grep -q "logged run demo-" || { echo "FAIL T1: log did not confirm"; echo "$OUT"; exit 1; }
test -f "$MP_GATE_HOME/gate_telemetry.jsonl" || { echo "FAIL T1: ledger not created"; exit 1; }
LINES=$(wc -l < "$MP_GATE_HOME/gate_telemetry.jsonl")
[ "$LINES" -eq 1 ] || { echo "FAIL T1: expected 1 ledger row, got $LINES"; exit 1; }

OUT=$(uv run "$MP" check 2>&1)
echo "$OUT" | grep -q "Gate status over 1 runs" || { echo "FAIL T1: check header wrong"; echo "$OUT"; exit 1; }
echo "$OUT" | grep -qE '\| T2-3 \|' || { echo "FAIL T1: check missing T2-3 row"; echo "$OUT"; exit 1; }

# ---------- Test 2: log is idempotent on run_id ----------
for i in 1 2; do
  uv run "$MP" log --project idem --archetype data --scale tiny --score 80 \
    --run-id idem-FIXED --preflight "$TMP/none.md" --topology "$TMP/none.md" \
    --sweep-summary "$TMP/none.md" --folds-dir "$TMP/nofolds" >/dev/null 2>&1
done
COUNT=$(grep -c '"run_id": "idem-FIXED"' "$MP_GATE_HOME/gate_telemetry.jsonl")
[ "$COUNT" -eq 1 ] || { echo "FAIL T2: expected 1 row for fixed run_id, got $COUNT"; exit 1; }

# ---------- Test 3: convention-read parsers populate the row ----------
cat > "$TMP/mp_preflight_pp.md" <<'EOF'
# mp-preflight: pp

Generated: 2026-06-03 10:00:00
Engine: z3
Result: **PASS**

## Detail

satisfiable schedule exists

## DAG Summary

- Nodes: 15
- Resources: none
- Worker limit: unset
EOF
cat > "$TMP/mp_topology_pp.md" <<'EOF'
# mp-topology: pp

Generated: 2026-06-03 10:00:00

## Metrics

| Metric   | Value |
|----------|-------|
| Width    | 7 |
| Depth    | 8 |
| Coupling | 0.20 |

## Selected Topology

**Hybrid**

Rationale: mixed structure
EOF
cat > "$TMP/sweep_summary_pp.md" <<'EOF'
# sweep_summary: pp

<!-- sweep-summary
project: pp
completed_at: 2026-06-03T10:30:00Z
-->

| field | value |
|-------|-------|
| total_nodes        | 15 |
| visited_nodes      | 15 |
| refine_count       | 2 |
| mean_delta         | +1.5 |
| max_delta          | +13.5 |
| budget_used        | 4 |
| budget_total       | 30 |
| converged          | no |
| terminated_reason  | all_visited |
EOF
mkdir -p "$TMP/folds_pp"
printf 'x\n' > "$TMP/folds_pp/architecture.md"
printf 'x\n' > "$TMP/folds_pp/decisions.md"
printf 'x\n' > "$TMP/folds_pp/_meta.yaml"

uv run "$MP" log --project pp --archetype code --scale large --score 96.5 \
  --preflight "$TMP/mp_preflight_pp.md" --topology "$TMP/mp_topology_pp.md" \
  --sweep-summary "$TMP/sweep_summary_pp.md" --folds-dir "$TMP/folds_pp" \
  --run-id pp-FIXED >/dev/null 2>&1

ROW=$(grep '"run_id": "pp-FIXED"' "$MP_GATE_HOME/gate_telemetry.jsonl")
echo "$ROW" | python3 -c '
import json,sys
r=json.loads(sys.stdin.read())
assert r["preflight"]["schedulable"] is True, r["preflight"]
assert r["preflight"]["method"]=="z3", r["preflight"]
assert r["topology"]["pattern"]=="Hybrid", r["topology"]
assert r["topology"]["width"]==7 and r["topology"]["depth"]==8, r["topology"]
assert abs(r["topology"]["coupling"]-0.20)<1e-9, r["topology"]
assert r["sweep"]["ran"] is True and r["sweep"]["nodes_refined"]==2, r["sweep"]
assert abs(r["sweep"]["max_flo_delta"]-13.5)<1e-9, r["sweep"]
assert r["context"]["folds"]==2, r["context"]   # _meta.yaml excluded
assert r["nodes"]==15, r["nodes"]               # read from preflight DAG Summary
print("T3 row OK")
' || { echo "FAIL T3: parsed row fields wrong"; echo "$ROW"; exit 1; }

# ---------- Test 4: gate evaluation boundaries ----------
seed_ledger() { mkdir -p "$MP_GATE_HOME"; printf '%s\n' "$@" > "$MP_GATE_HOME/gate_telemetry.jsonl"; }
row() { python3 -c '
import json,sys
base={"run_id":sys.argv[1],"ts":"t","project":"p","archetype":sys.argv[2],"scale":"standard","nodes":5,
"topology":{"pattern":None,"width":None,"depth":None,"coupling":None,"misroute":json.loads(sys.argv[3])},
"preflight":{"method":None,"schedulable":json.loads(sys.argv[4]),"manual_resolution":False},
"context":{"max_governor_state":sys.argv[5],"folds":0,"handoff_recovered":json.loads(sys.argv[6])},
"sweep":{"ran":True,"nodes_visited":5,"nodes_refined":0,"max_flo_delta":0.0,"nodes_unrecovered":int(sys.argv[7])},
"resources":{"saturated":json.loads(sys.argv[8])},
"score":{"kind":sys.argv[9],"value":(None if sys.argv[10]=="null" else float(sys.argv[10])),"baseline":None,"delta":(None if sys.argv[11]=="null" else float(sys.argv[11]))}}
print(json.dumps(base))
' "$@"; }

# row() positional arg order (11): run_id archetype misroute schedulable governor
#                                  handoff unrecovered saturated kind value delta
#   bool/null args are parsed as JSON ('true'/'false'/'null'); value/delta 'null' => None.

# T2-1: 1 unschedulable run -> UNMET; 2 -> MET   (schedulable=false)
seed_ledger \
  "$(row r1 code false false NORMAL null 0 false oracle 90 null)" \
  "$(row r2 code false false NORMAL null 0 false oracle 90 null)"
uv run "$MP" check 2>&1 | grep -qE '\| T2-1 \|.*\| MET \|' || { echo "FAIL T4: T2-1 should be MET at 2 unschedulable"; exit 1; }

seed_ledger "$(row r1 code false false NORMAL null 0 false oracle 90 null)"
uv run "$MP" check 2>&1 | grep -qE '\| T2-1 \|.*\| — \|' || { echo "FAIL T4: T2-1 should be UNMET at 1"; exit 1; }

# T2-2: EMERGENCY + handoff not recovered -> MET   (schedulable=true, governor=EMERGENCY, handoff=false)
seed_ledger "$(row r1 code false true EMERGENCY false 0 false oracle 90 null)"
uv run "$MP" check 2>&1 | grep -qE '\| T2-2 \|.*\| MET \|' || { echo "FAIL T4: T2-2 should be MET"; exit 1; }

# T2-4: nodes_unrecovered sums to 3 -> MET   (unrecovered 2 + 1)
seed_ledger \
  "$(row r1 code false true NORMAL null 2 false oracle 90 null)" \
  "$(row r2 code false true NORMAL null 1 false oracle 90 null)"
uv run "$MP" check 2>&1 | grep -qE '\| T2-4 \|.*\| MET \|' || { echo "FAIL T4: T2-4 should be MET at sum 3"; exit 1; }

# T1-1 UNMET baseline (nothing flagged) ; T1-2 MET (saturated=true)
seed_ledger "$(row r1 code false true NORMAL null 0 false oracle 90 null)"
uv run "$MP" check 2>&1 | grep -qE '\| T1-1 \|.*\| — \|' || { echo "FAIL T4: T1-1 should be UNMET"; exit 1; }
seed_ledger "$(row r1 code false true NORMAL null 0 true oracle 90 null)"
uv run "$MP" check 2>&1 | grep -qE '\| T1-2 \|.*\| MET \|' || { echo "FAIL T4: T1-2 should be MET"; exit 1; }

# T2-3: 5 code/oracle runs, sigma>5 -> MET ; sigma<5 -> UNMET   (schedulable=true)
seed_ledger \
  "$(row a code false true NORMAL null 0 false oracle 80 null)" \
  "$(row b code false true NORMAL null 0 false oracle 95 null)" \
  "$(row c code false true NORMAL null 0 false oracle 70 null)" \
  "$(row d code false true NORMAL null 0 false oracle 90 null)" \
  "$(row e code false true NORMAL null 0 false oracle 100 null)"
uv run "$MP" check 2>&1 | grep -qE '\| T2-3 \|.*\| MET \|' || { echo "FAIL T4: T2-3 should be MET (sigma>5,n=5)"; exit 1; }
seed_ledger \
  "$(row a code false true NORMAL null 0 false oracle 90 null)" \
  "$(row b code false true NORMAL null 0 false oracle 91 null)" \
  "$(row c code false true NORMAL null 0 false oracle 90 null)" \
  "$(row d code false true NORMAL null 0 false oracle 89 null)" \
  "$(row e code false true NORMAL null 0 false oracle 90 null)"
uv run "$MP" check 2>&1 | grep -qE '\| T2-3 \|.*\| — \|' || { echo "FAIL T4: T2-3 should be UNMET (sigma<5)"; exit 1; }

rm -f "$MP_GATE_HOME/gate_telemetry.jsonl"   # reset for later tests

# ---------- Test 5: edge-triggered nudge fires once on crossing ----------
rm -f "$MP_GATE_HOME/gate_telemetry.jsonl" "$MP_GATE_HOME/gate_state.json"
log_t12() { uv run "$MP" log --project edge --archetype code --scale standard --score 90 \
  --resource-saturated --run-id "$1" \
  --preflight "$TMP/none.md" --topology "$TMP/none.md" \
  --sweep-summary "$TMP/none.md" --folds-dir "$TMP/nofolds" 2>&1; }

OUT=$(log_t12 edge-1)
echo "$OUT" | grep -q "GATE MET — T1-2" || { echo "FAIL T5: first crossing should nudge"; echo "$OUT"; exit 1; }

OUT=$(log_t12 edge-2)
echo "$OUT" | grep -q "GATE MET — T1-2" && { echo "FAIL T5: nudge should NOT refire on already-MET gate"; echo "$OUT"; exit 1; }
test -f "$MP_GATE_HOME/gate_state.json" || { echo "FAIL T5: gate_state.json not written"; exit 1; }
grep -q '"T1-2": "MET"' "$MP_GATE_HOME/gate_state.json" || { echo "FAIL T5: state not persisted MET"; exit 1; }
rm -f "$MP_GATE_HOME/gate_telemetry.jsonl" "$MP_GATE_HOME/gate_state.json"

# ---------- Test 6: report emits markdown + json snapshot ----------
rm -f "$MP_GATE_HOME/gate_telemetry.jsonl" "$MP_GATE_HOME/gate_state.json"
uv run "$MP" log --project rep --archetype data --scale standard --score 88 \
  --run-id rep-1 --preflight "$TMP/none.md" --topology "$TMP/none.md" \
  --sweep-summary "$TMP/none.md" --folds-dir "$TMP/nofolds" >/dev/null 2>&1
OUT=$(uv run "$MP" report --out-dir "$TMP/export" 2>&1)
MD=$(ls "$TMP/export"/gate_report_*.md 2>/dev/null | head -1)
test -n "$MD" || { echo "FAIL T6: gate_report markdown not written"; echo "$OUT"; exit 1; }
test -f "$TMP/export/corpus_snapshot.json" || { echo "FAIL T6: corpus_snapshot.json not written"; exit 1; }
grep -q "## Gate status" "$MD" || { echo "FAIL T6: report missing Gate status section"; exit 1; }
grep -q "## Score distribution" "$MD" || { echo "FAIL T6: report missing Score distribution section"; exit 1; }
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert isinstance(d,list) and d[0]["run_id"]=="rep-1"' "$TMP/export/corpus_snapshot.json" \
  || { echo "FAIL T6: snapshot JSON malformed"; exit 1; }
rm -f "$MP_GATE_HOME/gate_telemetry.jsonl" "$MP_GATE_HOME/gate_state.json"

# ---------- Test 7: integration — 6 code runs flip T2-3 via the public log path ----------
rm -f "$MP_GATE_HOME/gate_telemetry.jsonl" "$MP_GATE_HOME/gate_state.json"
i=0; SAW_NUDGE=0
for sc in 80 95 70 90 100 60; do
  i=$((i+1))
  OUT=$(uv run "$MP" log --project intg --archetype code --scale standard --score "$sc" \
    --score-kind flo --run-id "intg-$i" \
    --preflight "$TMP/none.md" --topology "$TMP/none.md" \
    --sweep-summary "$TMP/none.md" --folds-dir "$TMP/nofolds" 2>&1)
  echo "$OUT" | grep -q "GATE MET — T2-3" && SAW_NUDGE=1
done
[ "$SAW_NUDGE" -eq 1 ] || { echo "FAIL T7: T2-3 nudge never fired across 6 high-variance runs"; exit 1; }
uv run "$MP" check 2>&1 | grep -qE '\| T2-3 \|.*\| MET \|' || { echo "FAIL T7: T2-3 not MET after 6 runs"; exit 1; }
rm -f "$MP_GATE_HOME/gate_telemetry.jsonl" "$MP_GATE_HOME/gate_state.json"

echo "PASS: all mp-gate tests (7/7)"
