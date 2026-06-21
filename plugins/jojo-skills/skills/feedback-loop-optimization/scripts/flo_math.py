#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy>=1.26",
# ]
# ///
"""
flo_math.py — FLO (Feedback Loop Optimization) math helpers.

Commands:
  score  CRITERION:SCORE:WEIGHT...  Weighted FLO score
  beta   ALPHA BETA_V [SAMPLES]     Beta distribution posterior + Thompson Sampling
  ucb1   SCORE MAX_SCORE VISITS OFFSPRING  UCB1 for MAP-Elites cell selection
  ts_arms NAME:ALPHA:BETA...        Thompson Sampling arm comparison
  gain   BASELINE CURRENT           Percent improvement over baseline

Scoring formula:  weighted_score = Σ(score_i / 10 × weight_i)
  Scores are on 0–10 scale; weights should sum to 100 (or are auto-normalized).

UCB1 formula: UCB1 = score/max_score + C * sqrt(ln(total_visits) / offspring)
  C (exploration constant) defaults to sqrt(2) ≈ 1.414.

Examples:
  uv run flo_math.py score "correctness:8:40" "coverage:7:30" "quality:9:20" "uv:10:10"
  uv run flo_math.py beta 3 1
  uv run flo_math.py beta 3 1 1000
  uv run flo_math.py ucb1 85 90 7 2
  uv run flo_math.py ts_arms "mutation:3:1" "crossover:2:2" "explorer:2:3"
  uv run flo_math.py gain 65 82
"""

import argparse
import math
import sys

import numpy as np


# ── Helpers ──────────────────────────────────────────────────────────────────

def parse_triplet(s: str, sep: str = ":", expect_name: bool = True):
    """Parse 'name:a:b' or 'a:b' triplet/pair."""
    parts = s.split(sep)
    if expect_name:
        if len(parts) != 3:
            sys.exit(f"Expected NAME:A:B, got {s!r}")
        name = parts[0].strip()
        try:
            a = float(parts[1])
            b = float(parts[2])
        except ValueError:
            sys.exit(f"Could not parse numbers in {s!r}")
        return name, a, b
    else:
        if len(parts) != 3:
            sys.exit(f"Expected CRITERION:SCORE:WEIGHT, got {s!r}")
        crit = parts[0].strip()
        try:
            score = float(parts[1])
            weight = float(parts[2])
        except ValueError:
            sys.exit(f"Could not parse numbers in {s!r}")
        return crit, score, weight


def beta_mean(alpha: float, beta_v: float) -> float:
    return alpha / (alpha + beta_v)


def beta_variance(alpha: float, beta_v: float) -> float:
    s = alpha + beta_v
    return (alpha * beta_v) / (s * s * (s + 1))


def beta_mode(alpha: float, beta_v: float) -> float | None:
    """Return the mode of Beta(alpha, beta_v), or None if undefined.

    Defined cases:
      alpha > 1, beta_v > 1  →  (alpha-1) / (alpha+beta_v-2)  (interior mode)
      alpha > 1, beta_v == 1 →  1.0  (mode at right boundary)
      alpha == 1, beta_v > 1 →  0.0  (mode at left boundary)
      alpha == 1, beta_v == 1 →  None (uniform, no unique mode)
      alpha < 1 or beta_v < 1 →  None (U-shaped or improper)
    """
    if alpha > 1 and beta_v > 1:
        return (alpha - 1) / (alpha + beta_v - 2)
    if alpha > 1 and beta_v == 1:
        return 1.0
    if alpha == 1 and beta_v > 1:
        return 0.0
    return None


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_score(args):
    if not args.criteria:
        sys.exit("Provide at least one CRITERION:SCORE:WEIGHT triplet")

    parsed = []
    for s in args.criteria:
        parsed.append(parse_triplet(s, expect_name=False))

    # Validate score ranges
    for crit, score, weight in parsed:
        if not (0.0 <= score <= 10.0):
            print(f"  Warning: score for '{crit}' is {score}, expected 0–10")
        if weight < 0:
            sys.exit(f"Weight for '{crit}' must be non-negative")

    # Warn on duplicate criterion names (they are allowed but may be surprising)
    seen_names: dict[str, int] = {}
    for idx, (crit, _, _) in enumerate(parsed):
        if crit in seen_names:
            print(f"  Warning: duplicate criterion name '{crit}' — treating as separate entries")
        else:
            seen_names[crit] = idx

    total_weight = sum(w for _, _, w in parsed)
    if total_weight == 0:
        sys.exit("Total weight is 0")

    # Normalize weights if they don't sum to 100 (allow flexibility)
    normalized = [(c, s, w / total_weight * 100) for c, s, w in parsed]

    # Print table header
    cw = max(len(c) for c, _, _ in parsed) + 2
    print(f"{'Criterion':<{cw}}  {'Score':>6}  {'Weight':>8}  {'Contribution':>12}")
    print("─" * (cw + 32))

    weighted_sum = 0.0
    # Use zip to pair each parsed entry with its own normalized entry by position,
    # so duplicate criterion names each get their correct individual normalized weight.
    for (crit, score, _raw_w), (_c, _s, norm_w) in zip(parsed, normalized):
        contribution = score / 10.0 * norm_w
        weighted_sum += contribution
        print(f"{crit:<{cw}}  {score:>6.1f}  {norm_w:>7.2f}%  {contribution:>11.4f}")

    print("─" * (cw + 32))
    if abs(total_weight - 100.0) > 0.01:
        print(f"  (Weights normalized from {total_weight:.2f} to 100.00)")
    print(f"\nWeighted FLO Score = {weighted_sum:.2f} / 100")

    # Grade interpretation
    if weighted_sum >= 95:
        grade = "S (outstanding)"
    elif weighted_sum >= 85:
        grade = "A (excellent)"
    elif weighted_sum >= 75:
        grade = "B (good)"
    elif weighted_sum >= 65:
        grade = "C (acceptable)"
    elif weighted_sum >= 50:
        grade = "D (needs improvement)"
    else:
        grade = "F (failing)"
    print(f"Grade: {grade}")


def cmd_beta(args):
    try:
        alpha = float(args.alpha)
        beta_v = float(args.beta_v)
    except ValueError as e:
        sys.exit(f"Error parsing ALPHA/BETA: {e}")

    if alpha <= 0 or beta_v <= 0:
        sys.exit("ALPHA and BETA must be positive (> 0)")

    samples = None
    if args.samples is not None:
        try:
            samples = int(args.samples)
        except ValueError:
            sys.exit("SAMPLES must be an integer")

    mean = beta_mean(alpha, beta_v)
    var = beta_variance(alpha, beta_v)
    std = math.sqrt(var)
    mode = beta_mode(alpha, beta_v)
    n_obs = alpha + beta_v - 2  # implied successes + failures from prior-free perspective

    print(f"Beta(α={alpha}, β={beta_v})")
    print(f"  Posterior mean       = {mean:.6f}  ({mean*100:.2f}%)")
    print(f"  Posterior mode       = {mode:.6f}  ({mode*100:.2f}%)" if mode is not None else "  Posterior mode       = undefined (uniform: α=β=1, or α<1/β<1)")
    print(f"  Std deviation        = {std:.6f}")
    print(f"  95% credible interval: ~[{max(0, mean - 2*std):.4f}, {min(1, mean + 2*std):.4f}]")
    print(f"  Effective observations: α+β-2 = {alpha + beta_v - 2:.1f}")

    # Thompson Sampling recommendation
    print()
    if mean >= 0.75:
        recommendation = "exploit (high confidence)"
    elif mean >= 0.5:
        recommendation = "exploit with caution"
    elif mean >= 0.25:
        recommendation = "explore (low confidence)"
    else:
        recommendation = "explore (very low, consider retiring)"

    print(f"Thompson Sampling: mean={mean:.4f}  →  suggest: {recommendation}")

    # Optional: draw samples and show empirical mean
    if samples is not None and samples > 0:
        rng = np.random.default_rng(seed=42)
        drawn = rng.beta(alpha, beta_v, size=samples)
        emp_mean = float(np.mean(drawn))
        best = float(np.max(drawn))
        print(f"\nMonte Carlo ({samples:,} samples):")
        print(f"  Empirical mean  = {emp_mean:.6f}")
        print(f"  Best sample     = {best:.6f}")
        print(f"  P(θ > 0.5)      = {float(np.mean(drawn > 0.5)):.4f}")
        print(f"  P(θ > 0.75)     = {float(np.mean(drawn > 0.75)):.4f}")
        print(f"  P(θ > 0.9)      = {float(np.mean(drawn > 0.9)):.4f}")


def cmd_ucb1(args):
    try:
        score = float(args.score)
        max_score = float(args.max_score)
        visits = int(args.map_visits)
        offspring = int(args.offspring_count)
    except ValueError as e:
        sys.exit(f"Error parsing arguments: {e}")

    if max_score <= 0:
        sys.exit("MAX_SCORE must be positive")
    if visits < 1:
        sys.exit("MAP_VISITS must be >= 1")
    if offspring < 1:
        sys.exit("OFFSPRING_COUNT must be >= 1")
    if score > max_score:
        print(f"  Warning: SCORE ({score}) > MAX_SCORE ({max_score})")

    C = math.sqrt(2)  # standard UCB1 exploration constant

    exploitation = score / max_score
    exploration = C * math.sqrt(math.log(visits) / offspring)
    ucb1_value = exploitation + exploration

    print(f"UCB1 = {exploitation:.4f} + {exploration:.4f} = {ucb1_value:.4f}")
    print()
    print(f"  Exploitation term  score/max  = {score}/{max_score} = {exploitation:.4f}")
    print(f"  Exploration term   C√(ln(N)/n) = {C:.4f}·√(ln({visits})/{offspring}) = {exploration:.4f}")
    print(f"  C (exploration constant)       = √2 ≈ {C:.4f}")
    print()

    # Interpretation
    if ucb1_value > 2.0:
        strength = "very strong candidate (high score + under-explored)"
    elif ucb1_value > 1.5:
        strength = "strong candidate"
    elif ucb1_value > 1.0:
        strength = "moderate candidate"
    else:
        strength = "weak candidate (low score or over-explored)"
    print(f"  Interpretation: {strength}")


def cmd_ts_arms(args):
    if not args.arms:
        sys.exit("Provide at least one NAME:ALPHA:BETA triplet")

    parsed = []
    for s in args.arms:
        name, alpha, beta_v = parse_triplet(s, expect_name=True)
        if alpha <= 0 or beta_v <= 0:
            sys.exit(f"ALPHA and BETA for '{name}' must be positive")
        parsed.append((name, alpha, beta_v))

    # Draw Thompson Sampling estimates (use many samples for accuracy)
    rng = np.random.default_rng(seed=42)
    N_SAMPLES = 50_000

    results = []
    for name, alpha, beta_v in parsed:
        samples = rng.beta(alpha, beta_v, size=N_SAMPLES)
        mean = float(np.mean(samples))
        std = float(np.std(samples))
        p_best_raw = 0.0  # will compute below
        results.append({
            "name": name,
            "alpha": alpha,
            "beta": beta_v,
            "mean": mean,
            "std": std,
            "samples": samples,
        })

    # P(arm_i is best) = fraction of draws where arm_i has highest sample
    all_samples = np.stack([r["samples"] for r in results], axis=1)  # (N, K)
    best_arm_idx = np.argmax(all_samples, axis=1)  # (N,)
    for i, r in enumerate(results):
        r["p_best"] = float(np.mean(best_arm_idx == i))

    # Sort by mean descending
    results.sort(key=lambda x: x["mean"], reverse=True)

    # Display table
    nw = max(len(r["name"]) for r in results) + 2
    print(f"{'Arm':<{nw}}  {'α':>5}  {'β':>5}  {'Mean':>8}  {'Std':>8}  {'P(best)':>9}  {'Rank'}")
    print("─" * (nw + 52))
    for rank, r in enumerate(results, 1):
        mark = " ← WINNER" if rank == 1 else ""
        print(
            f"{r['name']:<{nw}}  {r['alpha']:>5.1f}  {r['beta']:>5.1f}  "
            f"{r['mean']:>8.4f}  {r['std']:>8.4f}  {r['p_best']:>8.2%}  #{rank}{mark}"
        )

    winner = results[0]
    print(f"\nBest arm: {winner['name']}  (mean={winner['mean']:.4f}, P(best)={winner['p_best']:.2%})")

    # Explore/exploit recommendation
    if winner["p_best"] > 0.80:
        rec = "exploit this arm confidently"
    elif winner["p_best"] > 0.60:
        rec = "lean towards this arm, but keep exploring"
    else:
        rec = "explore more — no clear winner yet"
    print(f"Recommendation: {rec}")


def cmd_gain(args):
    try:
        baseline = float(args.baseline)
        current = float(args.current)
    except ValueError as e:
        sys.exit(f"Error parsing values: {e}")

    if baseline == 0:
        sys.exit("BASELINE cannot be 0 (division by zero)")

    delta = current - baseline
    pct = delta / abs(baseline) * 100

    sign = "+" if delta >= 0 else ""
    direction = "improvement" if delta >= 0 else "regression"

    print(f"Baseline : {baseline:.4g}")
    print(f"Current  : {current:.4g}")
    print(f"Delta    : {sign}{delta:.4g}")
    print(f"Gain     : {sign}{pct:.2f}%  ({direction})")

    # Qualitative label
    abs_pct = abs(pct)
    if abs_pct >= 50:
        label = "massive"
    elif abs_pct >= 20:
        label = "large"
    elif abs_pct >= 10:
        label = "moderate"
    elif abs_pct >= 5:
        label = "small"
    elif abs_pct >= 1:
        label = "marginal"
    else:
        label = "negligible"

    if delta >= 0:
        print(f"         → {label} improvement")
    else:
        print(f"         → {label} regression")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="flo_math.py",
        description="FLO (Feedback Loop Optimization) math helpers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # score
    p_score = sub.add_parser(
        "score",
        help="Compute weighted FLO score from CRITERION:SCORE:WEIGHT triplets",
    )
    p_score.add_argument(
        "criteria",
        nargs="+",
        metavar="CRITERION:SCORE:WEIGHT",
        help="e.g. 'correctness:8:40' (score 0–10, weight in any unit)",
    )
    p_score.set_defaults(func=cmd_score)

    # beta
    p_beta = sub.add_parser(
        "beta",
        help="Beta distribution posterior mean + Thompson Sampling advice",
    )
    p_beta.add_argument("alpha", help="Alpha (successes + 1)")
    p_beta.add_argument("beta_v", metavar="BETA", help="Beta (failures + 1)")
    p_beta.add_argument("samples", nargs="?", default=None, help="Optional: number of Monte Carlo samples")
    p_beta.set_defaults(func=cmd_beta)

    # ucb1
    p_ucb1 = sub.add_parser(
        "ucb1",
        help="UCB1 value for MAP-Elites cell selection",
    )
    p_ucb1.add_argument("score", help="Cell score")
    p_ucb1.add_argument("max_score", metavar="MAX_SCORE", help="Maximum possible score")
    p_ucb1.add_argument("map_visits", metavar="MAP_VISITS", help="Total MAP visits (N)")
    p_ucb1.add_argument("offspring_count", metavar="OFFSPRING_COUNT", help="Offspring from this cell (n)")
    p_ucb1.set_defaults(func=cmd_ucb1)

    # ts_arms
    p_ts = sub.add_parser(
        "ts_arms",
        help="Thompson Sampling arm comparison — rank arms and pick winner",
    )
    p_ts.add_argument(
        "arms",
        nargs="+",
        metavar="NAME:ALPHA:BETA",
        help="e.g. 'mutation:3:1' (Beta(3,1) posterior for this arm)",
    )
    p_ts.set_defaults(func=cmd_ts_arms)

    # gain
    p_gain = sub.add_parser(
        "gain",
        help="Percent improvement (or regression) of CURRENT over BASELINE",
    )
    p_gain.add_argument("baseline", help="Baseline score/metric")
    p_gain.add_argument("current", help="Current score/metric")
    p_gain.set_defaults(func=cmd_gain)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
