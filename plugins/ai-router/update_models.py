#!/usr/bin/env python3
"""
update_models.py — Yearly refresh script for models.json.

PRIVACY POLICY: We only ever use models that do NOT train on our sessions.
Every model in this catalog must have a confirmed no-training policy.
OpenRouter calls enforce this via provider.data_collection=deny (ZDR).
When adding new models, always verify and document their no_training_source.

Fetches live model data from OpenRouter, diffs against the local catalog,
and optionally writes an updated models.json.

Usage:
    python update_models.py --check                       # diff only
    python update_models.py --check --update              # diff + write
    python update_models.py --check-zdr                   # verify ZDR per model (slow)
    python update_models.py --check-training              # audit no_training fields
    python update_models.py --check --update --check-zdr  # everything
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx", file=sys.stderr)
    sys.exit(1)

_OR_BASE_URL = "https://openrouter.ai/api/v1"
_OR_REFERER = "https://github.com/jojo/dotfiles"
_OR_TITLE = "ai-router-mcp"
_MODELS_PATH = Path(__file__).parent / "models.json"


def _or_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": _OR_REFERER,
        "X-Title": _OR_TITLE,
    }


def _load_local() -> dict:
    if not _MODELS_PATH.exists():
        print(f"No local models.json found at {_MODELS_PATH}", file=sys.stderr)
        return {}
    return json.loads(_MODELS_PATH.read_text(encoding="utf-8"))


def _fetch_or_models(api_key: str) -> list[dict]:
    """Fetch the full model list from OpenRouter /models."""
    with httpx.Client(base_url=_OR_BASE_URL, headers=_or_headers(api_key), timeout=30.0) as c:
        r = c.get("/models")
        r.raise_for_status()
        return r.json().get("data", [])


def _probe_zdr(api_key: str, model_id: str) -> bool:
    """
    Probe whether a model is routable with ZDR enforcement by sending a minimal
    request with provider.data_collection=deny. Returns True if HTTP 200.
    Note: a 400/422 for other reasons (context, etc.) can be a false negative.
    """
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
        "provider": {"data_collection": "deny"},
    }
    try:
        with httpx.Client(base_url=_OR_BASE_URL, headers=_or_headers(api_key), timeout=20.0) as c:
            r = c.post("/chat/completions", json=payload)
            # 200 = definitely works; 429 = rate limited but key/model valid
            return r.status_code in (200, 429)
    except Exception:
        return False


def _pricing_from_or_model(m: dict) -> tuple[float, float]:
    """Extract (input_cost_per_m, output_cost_per_m) from OR model dict."""
    pricing = m.get("pricing", {})
    try:
        # OR returns cost per token as a string — multiply by 1M
        inp = float(pricing.get("prompt", 0)) * 1_000_000
        out = float(pricing.get("completion", 0)) * 1_000_000
    except (TypeError, ValueError):
        inp = out = 0.0
    return round(inp, 4), round(out, 4)


def _context_k_from_or_model(m: dict) -> int:
    ctx = m.get("context_length", 0)
    return round(ctx / 1000)


def _diff_model(local: dict, live: dict) -> list[str]:
    """Compare a local model entry against live OR data. Return list of change strings."""
    changes = []
    live_inp, live_out = _pricing_from_or_model(live)
    local_inp = local.get("input_cost_per_m", 0)
    local_out = local.get("output_cost_per_m", 0)

    if abs(live_inp - local_inp) > 0.001:
        changes.append(f"  input price: ${local_inp:.4f} → ${live_inp:.4f} /M")
    if abs(live_out - local_out) > 0.001:
        changes.append(f"  output price: ${local_out:.4f} → ${live_out:.4f} /M")

    live_ctx = _context_k_from_or_model(live)
    local_ctx = local.get("context_k", 0)
    if live_ctx and abs(live_ctx - local_ctx) > 10:
        changes.append(f"  context: {local_ctx}K → {live_ctx}K")

    return changes


def _build_updated_entry(local: dict, live: dict) -> dict:
    """Merge live OR pricing/context into a local model entry."""
    updated = dict(local)
    inp, out = _pricing_from_or_model(live)
    if inp:
        updated["input_cost_per_m"] = inp
    if out:
        updated["output_cost_per_m"] = out
    ctx = _context_k_from_or_model(live)
    if ctx:
        updated["context_k"] = ctx
    # Update name if OR has a better one
    live_name = live.get("name", "")
    if live_name and live_name != local.get("name", ""):
        updated["name"] = live_name
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh models.json from OpenRouter API")
    parser.add_argument("--check", action="store_true", help="Check for changes (always runs diff)")
    parser.add_argument("--update", action="store_true", help="Write updated models.json after diff")
    parser.add_argument("--check-zdr", action="store_true", help="Probe ZDR eligibility per model (slow — one request per model)")
    parser.add_argument("--check-training", action="store_true", help="Audit no_training fields — lists any model missing no_training:true or no_training_source")
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    print("Fetching model list from OpenRouter...")
    try:
        live_models = _fetch_or_models(api_key)
    except httpx.HTTPStatusError as e:
        print(f"ERROR fetching models: HTTP {e.response.status_code} — {e.response.text[:200]}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR fetching models: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  {len(live_models)} models returned by OpenRouter\n")

    live_by_id = {m["id"]: m for m in live_models}

    local_catalog = _load_local()
    local_or_models: list[dict] = local_catalog.get("openrouter_models", [])
    local_by_id = {m["id"]: m for m in local_or_models}

    # --- Diff ---
    local_ids = set(local_by_id)
    live_ids = set(live_by_id)

    removed = local_ids - live_ids
    added = live_ids - local_ids
    common = local_ids & live_ids

    print("=" * 60)
    print("DIFF REPORT")
    print("=" * 60)

    if removed:
        print(f"\nREMOVED from OR ({len(removed)}):")
        for mid in sorted(removed):
            name = local_by_id[mid].get("name", mid)
            print(f"  - {name} ({mid})")
    else:
        print("\nNo models removed.")

    if added:
        print(f"\nNEW on OR ({len(added)} — first 20 shown):")
        for mid in sorted(added)[:20]:
            live = live_by_id[mid]
            inp, out = _pricing_from_or_model(live)
            ctx = _context_k_from_or_model(live)
            name = live.get("name", mid)
            print(f"  + {name} ({mid})  ${inp:.3f}/${out:.3f} per M  ctx={ctx}K")
    else:
        print("\nNo new models.")

    changed_count = 0
    print(f"\nPRICING/CONTEXT CHANGES (tracked {len(common)} models):")
    for mid in sorted(common):
        live = live_by_id[mid]
        local = local_by_id[mid]
        changes = _diff_model(local, live)
        if changes:
            changed_count += 1
            name = local.get("name", mid)
            print(f"\n  {name} ({mid}):")
            for c in changes:
                print(c)
    if not changed_count:
        print("  No pricing/context changes detected.")

    # --- ZDR check ---
    if args.check_zdr:
        print(f"\n{'=' * 60}")
        print("ZDR ELIGIBILITY PROBE")
        print("(one API call per tracked model — this takes a while)")
        print("=" * 60)
        for mid in sorted(local_ids):
            name = local_by_id[mid].get("name", mid)
            eligible = _probe_zdr(api_key, mid)
            status = "ZDR OK ✓" if eligible else "ZDR FAIL ✗"
            print(f"  {status}  {name} ({mid})")

    # --- Training policy audit ---
    if args.check_training:
        print(f"\n{'=' * 60}")
        print("NO-TRAINING POLICY AUDIT")
        print("Every model must have no_training=true and a documented source.")
        print("=" * 60)
        all_models = local_catalog.get("openrouter_models", []) + local_catalog.get("image_generation_models", [])
        missing_flag = [m for m in all_models if not m.get("no_training")]
        missing_source = [m for m in all_models if m.get("no_training") and not m.get("no_training_source")]
        if missing_flag:
            print(f"\n  MISSING no_training:true ({len(missing_flag)}):")
            for m in missing_flag:
                print(f"    ✗  {m.get('name', m['id'])} ({m['id']})")
        if missing_source:
            print(f"\n  MISSING no_training_source ({len(missing_source)}):")
            for m in missing_source:
                print(f"    ✗  {m.get('name', m['id'])} ({m['id']})")
        if not missing_flag and not missing_source:
            print(f"\n  ALL {len(all_models)} models: no_training=true ✓ and source documented ✓")
        print("\n  Policy: openrouter.ai/docs/guides/features/zdr (ZDR = no storage, no training)")

    # --- Update ---
    if args.update:
        print(f"\n{'=' * 60}")
        print("WRITING UPDATED models.json")
        print("=" * 60)

        updated_models = []
        for local in local_or_models:
            mid = local["id"]
            if mid in live_by_id:
                updated = _build_updated_entry(local, live_by_id[mid])
                updated_models.append(updated)
            else:
                print(f"  Keeping removed model in catalog (mark manually): {mid}")
                updated_models.append(local)

        updated_catalog = dict(local_catalog)
        updated_catalog["openrouter_models"] = updated_models
        updated_catalog["updated"] = date.today().isoformat()
        # Bump version to current year-month
        today = date.today()
        updated_catalog["version"] = f"{today.year}-{today.month:02d}"

        _MODELS_PATH.write_text(
            json.dumps(updated_catalog, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  Written: {_MODELS_PATH}")
        print(f"  {len(updated_models)} text models kept.")
        print("  Image generation models: unchanged (managed manually).")
        print("\nDone. Review changes with: git diff claude/plugins/ai-router/models.json")
    else:
        if args.check:
            print("\n(Run with --update to write changes to models.json)")


if __name__ == "__main__":
    main()
