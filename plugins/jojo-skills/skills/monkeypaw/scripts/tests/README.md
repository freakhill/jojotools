# monkeypaw scripts — regression tests

Bash tests, one per fixed bug. Run individually or as a suite:

```bash
for t in test_*.sh; do   # run from this tests/ directory
    echo "=== $(basename $t) ==="
    bash "$t" || break
done
```

Convention: each test self-cleans via `trap` (no leftover /tmp files).

## Index

| Test | Covers gap | Confirms |
|---|---|---|
| test_mp_status_lead_time.sh | G10 (P1 run, 2026-05-23) | Lead Time computed from done timestamps; sub-second renders as "<0.01 min" |
| test_mp_validate.sh | Phase A validation infra (2026-05-24) | sweep_metrics/sweep_summary schemas enforced; compare emits per-task block; aggregate gate decision logic |
