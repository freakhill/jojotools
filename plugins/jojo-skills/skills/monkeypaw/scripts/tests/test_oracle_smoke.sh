#!/usr/bin/env bash
# Pre-Phase-A smoke test for all 5 corpus oracles.
#
# Verifies that each oracle.{sh,py} can:
#   1. be invoked with no args → exit non-zero with a usage message
#   2. be invoked with a nonexistent directory → exit non-zero with a clear error
#
# Does NOT actually exercise the monkeypaw-produced project — that takes hours
# (some oracles run `pip install -e <project>` which hangs on bad inputs).
# This is the ~5-second pre-flight before a Phase A run, catching only the
# most basic packaging mistakes (missing shebang, broken arg parsing).

set -u
SKILL_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
FIXTURES_DIR="$SKILL_DIR/corpus/fixtures"
PASSED=0
FAILED=0

for task in X1 P2 P3 D2 N1; do
  echo ""
  echo "=== $task ==="
  if [[ "$task" == "N1" ]]; then
    ORACLE="$FIXTURES_DIR/$task/oracle.py"
    INVOKE=(python3 "$ORACLE")
  else
    ORACLE="$FIXTURES_DIR/$task/oracle.sh"
    INVOKE=(bash "$ORACLE")
  fi

  if [[ ! -f "$ORACLE" ]]; then
    echo "  [FAIL] $ORACLE not found"
    FAILED=$((FAILED+1))
    continue
  fi
  if [[ ! -x "$ORACLE" ]]; then
    echo "  [WARN] $ORACLE is not executable; chmod +x recommended"
  fi

  # Probe 1: no args should exit non-zero with usage
  OUT="$("${INVOKE[@]}" 2>&1)"; RC=$?
  if [[ "$RC" != "0" ]] && [[ "$OUT" == *"usage"* || "$OUT" == *"Usage"* ]]; then
    echo "  [PASS] no-args → usage + non-zero exit"
    PASSED=$((PASSED+1))
  else
    echo "  [FAIL] no-args expected usage+non-zero, got rc=$RC out=$(echo "$OUT" | head -c 100)"
    FAILED=$((FAILED+1))
  fi

  # Probe 2: nonexistent directory
  OUT="$("${INVOKE[@]}" /nonexistent/path/${RANDOM}_$$ 2>&1)"; RC=$?
  if [[ "$RC" != "0" ]]; then
    echo "  [PASS] nonexistent-dir → non-zero exit (rc=$RC)"
    PASSED=$((PASSED+1))
  else
    echo "  [FAIL] nonexistent-dir expected non-zero, got rc=0"
    FAILED=$((FAILED+1))
  fi

done

echo ""
echo "=== Summary ==="
echo "  passed: $PASSED"
echo "  failed: $FAILED"

if [[ "$FAILED" == "0" ]]; then
  echo "SMOKE OK — all oracles handle bad inputs gracefully."
  exit 0
else
  echo "SMOKE FAIL — fix the $FAILED issues above before running Phase A."
  exit 1
fi
