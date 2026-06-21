#!/usr/bin/env bash
# Tests for mp-validate.py covering: sweep_metrics schema, sweep_summary schema,
# compare block emission, aggregate gate decision.
#
# Run from anywhere: bash test_mp_validate.sh
set -e

SCRIPTS="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

MP="$SCRIPTS/mp-validate.py"

# ---------- Fixture: valid sweep_metrics.md ----------
cat > "$TMP/sweep_metrics.md" <<'EOF'
# sweep_metrics: testproj

<!-- sweep-meta
project: testproj
started_at: 2026-05-24T10:00:00Z
budget_total: 30
-->

| node_id | baseline_score | new_score | delta | refine | budget_remaining | timestamp |
|---------|----------------|-----------|-------|--------|------------------|-----------|
| N18 | 82 | 89 | +7.0 | yes | 29 | 2026-05-24T10:01:00Z |
| N17 | 91 | 91 | +0.0 | no | 28 | 2026-05-24T10:02:00Z |
| N16 | 75 | 71 | -4.0 | no | 27 | 2026-05-24T10:03:00Z |
| N15 | 80 | 83 | +3.0 | yes | 26 | 2026-05-24T10:04:00Z |
EOF

# ---------- Fixture: valid sweep_summary.md ----------
cat > "$TMP/sweep_summary.md" <<'EOF'
# sweep_summary: testproj

<!-- sweep-summary
project: testproj
completed_at: 2026-05-24T10:30:00Z
-->

| field | value |
|-------|-------|
| total_nodes        | 18    |
| visited_nodes      | 4     |
| refine_count       | 2     |
| mean_delta         | +1.5  |
| max_delta          | +7.0  |
| budget_used        | 4     |
| budget_total       | 30    |
| converged          | no    |
| terminated_reason  | all_visited |

## [REFINE] nodes (forward execution order)
- N15, N18
EOF

# ---------- Test 1: parse-metrics on valid file ----------
OUT=$(uv run "$MP" parse-metrics "$TMP/sweep_metrics.md" 2>&1)
echo "$OUT" | grep -q "schema OK" || { echo "FAIL T1: parse-metrics did not report OK"; echo "$OUT"; exit 1; }
echo "$OUT" | grep -q "visited: 4 nodes" || { echo "FAIL T1: visited count wrong"; echo "$OUT"; exit 1; }
echo "$OUT" | grep -q "refine: 2" || { echo "FAIL T1: refine count wrong"; echo "$OUT"; exit 1; }
echo "$OUT" | grep -q "regressions: N16" || { echo "FAIL T1: regression N16 not flagged"; echo "$OUT"; exit 1; }

# ---------- Test 2: parse-summary on valid file ----------
OUT=$(uv run "$MP" parse-summary "$TMP/sweep_summary.md" 2>&1)
echo "$OUT" | grep -q "schema OK" || { echo "FAIL T2: parse-summary did not report OK"; echo "$OUT"; exit 1; }
echo "$OUT" | grep -q "refine_count: 2" || { echo "FAIL T2: refine_count wrong"; echo "$OUT"; exit 1; }
echo "$OUT" | grep -q "REFINE nodes: N15, N18" || { echo "FAIL T2: refine nodes wrong"; echo "$OUT"; exit 1; }

# ---------- Test 3: parse-metrics on malformed file (missing meta) ----------
cat > "$TMP/bad_metrics.md" <<'EOF'
| node_id | baseline_score | new_score | delta | refine | budget_remaining | timestamp |
|---|---|---|---|---|---|---|
| N1 | 80 | 85 | +5.0 | yes | 10 | 2026-05-24T10:00:00Z |
EOF

if uv run "$MP" parse-metrics "$TMP/bad_metrics.md" 2>/dev/null; then
    echo "FAIL T3: parse-metrics should reject file missing sweep-meta"; exit 1
fi

# ---------- Test 4: parse-summary on file missing required field ----------
cat > "$TMP/bad_summary.md" <<'EOF'
# sweep_summary: testproj

<!-- sweep-summary
project: testproj
completed_at: 2026-05-24T10:30:00Z
-->

| field | value |
|-------|-------|
| total_nodes        | 18    |
| visited_nodes      | 4     |
| refine_count       | 2     |
| mean_delta         | +1.5  |
| max_delta          | +7.0  |
| budget_used        | 4     |
| budget_total       | 30    |
| converged          | no    |
EOF

if uv run "$MP" parse-summary "$TMP/bad_summary.md" 2>/dev/null; then
    echo "FAIL T4: parse-summary should reject file missing terminated_reason"; exit 1
fi

# ---------- Test 5: parse-summary on invalid terminated_reason ----------
cat > "$TMP/bad_summary2.md" <<'EOF'
# sweep_summary: testproj

<!-- sweep-summary
project: testproj
completed_at: 2026-05-24T10:30:00Z
-->

| field | value |
|-------|-------|
| total_nodes        | 18    |
| visited_nodes      | 4     |
| refine_count       | 2     |
| mean_delta         | +1.5  |
| max_delta          | +7.0  |
| budget_used        | 4     |
| budget_total       | 30    |
| converged          | no    |
| terminated_reason  | something_invalid |
EOF

if uv run "$MP" parse-summary "$TMP/bad_summary2.md" 2>/dev/null; then
    echo "FAIL T5: parse-summary should reject invalid terminated_reason"; exit 1
fi

# ---------- Test 6: compare emits valid block + JSON sidecar ----------
cat > "$TMP/baseline.json" <<'EOF'
{"oracle_pass_rate": 32.0, "coverage": 18.0, "code_quality": 12.0, "documentation": 8.0, "reproducibility": 10.0, "reconciliation": 5.0}
EOF

cat > "$TMP/sweep.json" <<'EOF'
{"oracle_pass_rate": 36.0, "coverage": 18.0, "code_quality": 13.0, "documentation": 9.0, "reproducibility": 10.0, "reconciliation": 5.0}
EOF

OUT=$(uv run "$MP" compare --task P2 \
    --baseline-scores "$TMP/baseline.json" --sweep-scores "$TMP/sweep.json" \
    --sweep-summary "$TMP/sweep_summary.md" --sweep-metrics "$TMP/sweep_metrics.md" \
    --wall-clock-base-min 120 --wall-clock-sweep-min 145 \
    --json-out "$TMP/p2_result.json" 2>&1)

echo "$OUT" | grep -q '#### P2 — ' || { echo "FAIL T6: compare header missing"; echo "$OUT"; exit 1; }
echo "$OUT" | grep -qF '**TOTAL** | 100 | 85.0 | 91.0 | **+6.0**' \
    || { echo "FAIL T6: total delta wrong (expected +6.0)"; echo "$OUT"; exit 1; }
echo "$OUT" | grep -q 'regressions (per-node delta < -1): N16' \
    || { echo "FAIL T6: regression flag missing"; echo "$OUT"; exit 1; }

test -f "$TMP/p2_result.json" || { echo "FAIL T6: sidecar JSON not written"; exit 1; }

# Validate sidecar JSON contents
PYRESULT=$(python3 -c "import json; d=json.load(open('$TMP/p2_result.json')); print(d['task_id'], d['baseline_total'], d['sweep_total'], d['refine_count'], ','.join(d['regressions']))")
[ "$PYRESULT" = "P2 85.0 91.0 2 N16" ] || { echo "FAIL T6: sidecar contents wrong: $PYRESULT"; exit 1; }

# ---------- Test 7: aggregate with 5 task sidecars triggers gate evaluation ----------
for tid in P2 D2 X1 N1 P3; do
    delta_idx=$((RANDOM % 100))  # not used; deterministic below
done

# Build 5 task sidecars: 4 pass (Δ≥+2), 1 borderline; should authorize
cat > "$TMP/r_P2.json" <<'EOF'
{"task_id":"P2","baseline_total":78.0,"sweep_total":83.0,"regressions":[],"refine_count":3,"wall_clock_base_min":120,"wall_clock_sweep_min":145}
EOF
cat > "$TMP/r_D2.json" <<'EOF'
{"task_id":"D2","baseline_total":76.5,"sweep_total":80.0,"regressions":[],"refine_count":4,"wall_clock_base_min":140,"wall_clock_sweep_min":175}
EOF
cat > "$TMP/r_X1.json" <<'EOF'
{"task_id":"X1","baseline_total":82.0,"sweep_total":84.5,"regressions":[],"refine_count":2,"wall_clock_base_min":110,"wall_clock_sweep_min":130}
EOF
cat > "$TMP/r_N1.json" <<'EOF'
{"task_id":"N1","baseline_total":88.0,"sweep_total":90.5,"regressions":[],"refine_count":1,"wall_clock_base_min":90,"wall_clock_sweep_min":100}
EOF
cat > "$TMP/r_P3.json" <<'EOF'
{"task_id":"P3","baseline_total":80.0,"sweep_total":82.0,"regressions":[],"refine_count":2,"wall_clock_base_min":100,"wall_clock_sweep_min":118}
EOF

OUT=$(uv run "$MP" aggregate "$TMP/r_P2.json" "$TMP/r_D2.json" "$TMP/r_X1.json" "$TMP/r_N1.json" "$TMP/r_P3.json")
echo "$OUT" | grep -qE 'Phase B authorized:\** YES' \
    || { echo "FAIL T7: gate should authorize Phase B"; echo "$OUT"; exit 1; }
echo "$OUT" | grep -q 'Mean Δ across 5 tasks' \
    || { echo "FAIL T7: aggregate report missing mean Δ line"; echo "$OUT"; exit 1; }

# ---------- Test 8: aggregate with one regression denies Phase B ----------
cat > "$TMP/r_P2_reg.json" <<'EOF'
{"task_id":"P2","baseline_total":78.0,"sweep_total":75.0,"regressions":["N03","N07"],"refine_count":3,"wall_clock_base_min":120,"wall_clock_sweep_min":145}
EOF

OUT=$(uv run "$MP" aggregate "$TMP/r_P2_reg.json" "$TMP/r_D2.json" "$TMP/r_X1.json" "$TMP/r_N1.json" "$TMP/r_P3.json")
echo "$OUT" | grep -qE 'Phase B authorized:\** NO' \
    || { echo "FAIL T8: gate should deny Phase B when one task regresses >1 pt"; echo "$OUT"; exit 1; }

# ---------- Test 9: aggregate with mean Δ below threshold denies Phase B ----------
cat > "$TMP/r_low_a.json" <<'EOF'
{"task_id":"A","baseline_total":80.0,"sweep_total":80.5,"regressions":[],"refine_count":1}
EOF
cat > "$TMP/r_low_b.json" <<'EOF'
{"task_id":"B","baseline_total":80.0,"sweep_total":80.5,"regressions":[],"refine_count":1}
EOF
cat > "$TMP/r_low_c.json" <<'EOF'
{"task_id":"C","baseline_total":80.0,"sweep_total":80.5,"regressions":[],"refine_count":1}
EOF

OUT=$(uv run "$MP" aggregate "$TMP/r_low_a.json" "$TMP/r_low_b.json" "$TMP/r_low_c.json")
echo "$OUT" | grep -qE 'Phase B authorized:\** NO' \
    || { echo "FAIL T9: gate should deny when mean Δ < 2.0"; echo "$OUT"; exit 1; }

echo "PASS: all mp-validate tests (9/9)"
