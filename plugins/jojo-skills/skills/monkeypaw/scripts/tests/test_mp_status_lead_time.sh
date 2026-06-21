#!/usr/bin/env bash
# Regression test for mp-status Lead Time computation (G10).
#
# Bug: Lead Time (median) in DORA section stayed "—" because
# recalculate_dora() hardcoded the cell. Fixed by computing median
# of (created→first_done) + (consecutive done→done) intervals.
#
# Run from anywhere: bash test_mp_status_lead_time.sh
set -e

SCRIPTS="$(cd "$(dirname "$0")/.." && pwd)"
PROJ="lt_test_$$"
STATUS_FILE="/tmp/mp_status_${PROJ}.md"
trap 'rm -f "$STATUS_FILE"' EXIT

# --- Test 1: 5 nodes init, no DONE → Lead Time should remain "—" ---
echo '{"project":"'"$PROJ"'","nodes":[{"id":"N01","name":"a"},{"id":"N02","name":"b"},{"id":"N03","name":"c"},{"id":"N04","name":"d"},{"id":"N05","name":"e"}]}' \
    | uv run "$SCRIPTS/mp-status.py" init "$PROJ" > /dev/null

if ! grep -q "| Lead Time (median) | — |" "$STATUS_FILE"; then
    echo "FAIL T1: Lead Time should be '—' before any DONE"; exit 1
fi

# --- Test 2: 4 DONE in burst → Lead Time becomes numeric (not "—") ---
uv run "$SCRIPTS/mp-status.py" done "$PROJ" N01 /tmp/a > /dev/null
uv run "$SCRIPTS/mp-status.py" done "$PROJ" N02 /tmp/b > /dev/null
uv run "$SCRIPTS/mp-status.py" done "$PROJ" N03 /tmp/c > /dev/null
uv run "$SCRIPTS/mp-status.py" done "$PROJ" N04 /tmp/d > /dev/null

LEAD=$(grep "Lead Time" "$STATUS_FILE" | head -1)
if echo "$LEAD" | grep -q "| — |"; then
    echo "FAIL T2: Lead Time still '—' after 4 burst completions"; echo "  $LEAD"; exit 1
fi

# Should match either "<0.01 min" or "N.NN min"
if ! echo "$LEAD" | grep -qE "(<0\.01 min|[0-9]+\.[0-9]+ min)"; then
    echo "FAIL T2: Lead Time format unexpected"; echo "  $LEAD"; exit 1
fi

# --- Test 3: show subcommand reflects the value in SUMMARY ---
SUM=$(uv run "$SCRIPTS/mp-status.py" show "$PROJ" | grep SUMMARY)
if echo "$SUM" | grep -q "Lead Time: — avg"; then
    echo "FAIL T3: SUMMARY still shows 'Lead Time: — avg'"; echo "  $SUM"; exit 1
fi

# --- Test 4: dora subcommand reflects the value ---
DORA=$(uv run "$SCRIPTS/mp-status.py" dora "$PROJ" | grep "Lead Time")
if echo "$DORA" | grep -q "| — |"; then
    echo "FAIL T4: dora dashboard still shows '—'"; echo "  $DORA"; exit 1
fi

echo "PASS: all G10 regression tests (4/4)"
