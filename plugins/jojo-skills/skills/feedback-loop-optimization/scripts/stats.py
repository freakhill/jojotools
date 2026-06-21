#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy>=1.26",
#   "scipy>=1.11",
# ]
# ///
"""
stats.py — Statistical analysis via NumPy and SciPy.

Commands:
  describe NUMS...         Summary statistics
  corr LIST_A LIST_B       Pearson correlation (comma-separated lists)
  dist DIST ACTION VALUE   Distribution CDF/PDF/quantile
  zscore NUMS...           Z-scores for each value

Distribution names: normal, t, chi2, exponential, gamma
Distribution actions: cdf, pdf, quantile (alias: ppf)

For 'dist t' and 'dist chi2', pass degrees-of-freedom as last arg:
  uv run stats.py dist t cdf 1.96 --df 10

For 'dist exponential', optionally pass --scale (default 1.0):
  uv run stats.py dist exponential cdf 2.0 --scale 1.5

For 'dist gamma', pass --shape (required) and optionally --scale (default 1.0):
  uv run stats.py dist gamma cdf 3.0 --shape 2.0 --scale 1.0

Examples:
  uv run stats.py describe 1 2 3 4 5
  uv run stats.py corr "1,2,3,4" "2,4,5,4"
  uv run stats.py dist normal cdf 1.96
  uv run stats.py dist t quantile 0.975 --df 10
  uv run stats.py dist exponential cdf 2.0 --scale 1.5
  uv run stats.py dist gamma pdf 3.0 --shape 2.0 --scale 1.0
  uv run stats.py zscore 10 20 30 40 50
"""

import argparse
import sys

import numpy as np
from scipy import stats as sp_stats


def parse_nums(args_list: list[str]) -> np.ndarray:
    try:
        return np.array([float(x) for x in args_list])
    except ValueError as e:
        sys.exit(f"Error parsing numbers: {e}")


def parse_csv(s: str) -> np.ndarray:
    try:
        return np.array([float(x.strip()) for x in s.split(",")])
    except ValueError as e:
        sys.exit(f"Error parsing comma-separated numbers: {e}")


def cmd_describe(args):
    data = parse_nums(args.nums)
    ddof = args.ddof
    if ddof not in (0, 1):
        sys.exit(f"--ddof must be 0 or 1, got {ddof}")
    n = len(data)
    mean = np.mean(data)
    median = np.median(data)
    std = np.std(data, ddof=ddof) if n > 1 else 0.0
    se = std / np.sqrt(n) if n > 1 else 0.0
    mn, mx = np.min(data), np.max(data)
    q1, q3 = np.percentile(data, 25), np.percentile(data, 75)
    iqr = q3 - q1
    rng = mx - mn
    skewness = float(sp_stats.skew(data))
    kurtosis = float(sp_stats.kurtosis(data, fisher=True))  # excess kurtosis (Fisher)

    std_label = f"std (sample, ddof=1)" if ddof == 1 else f"std (population, ddof=0)"
    col = 26
    print(f"{'n':<{col}} {n}")
    print(f"{'mean':<{col}} {mean:.6g}")
    print(f"{'median':<{col}} {median:.6g}")
    print(f"{std_label:<{col}} {std:.6g}")
    print(f"{'std error':<{col}} {se:.6g}")
    print(f"{'min':<{col}} {mn:.6g}")
    print(f"{'Q1 (25%)':<{col}} {q1:.6g}")
    print(f"{'Q3 (75%)':<{col}} {q3:.6g}")
    print(f"{'max':<{col}} {mx:.6g}")
    print(f"{'IQR':<{col}} {iqr:.6g}")
    print(f"{'range':<{col}} {rng:.6g}")
    print(f"{'skewness':<{col}} {skewness:.6g}")
    print(f"{'kurtosis (excess, Fisher)':<{col}} {kurtosis:.6g}")


def cmd_corr(args):
    a = parse_csv(args.list_a)
    b = parse_csv(args.list_b)
    if len(a) != len(b):
        sys.exit(f"Lists must have equal length ({len(a)} vs {len(b)})")
    if len(a) < 2:
        sys.exit("Need at least 2 data points for correlation")
    r, p = sp_stats.pearsonr(a, b)
    print(f"Pearson r  = {r:.6f}")
    print(f"p-value    = {p:.6g}")
    if p < 0.001:
        sig = "*** (p<0.001)"
    elif p < 0.01:
        sig = "** (p<0.01)"
    elif p < 0.05:
        sig = "* (p<0.05)"
    else:
        sig = "ns (not significant)"
    print(f"Significance: {sig}")


def cmd_dist(args):
    dist_name = args.dist.lower()
    action = args.action.lower()
    try:
        value = float(args.value)
    except ValueError:
        sys.exit(f"VALUE must be a number, got: {args.value!r}")

    df = args.df        # may be None
    scale = args.scale  # float, default 1.0
    shape = args.shape  # may be None

    dist_map = {
        "normal": sp_stats.norm,
        "t": sp_stats.t,
        "chi2": sp_stats.chi2,
        "exponential": sp_stats.expon,
        "gamma": sp_stats.gamma,
    }
    if dist_name not in dist_map:
        sys.exit(f"Unknown distribution: {dist_name!r}. Choose from: {', '.join(dist_map)}")

    d = dist_map[dist_name]

    # Build frozen distribution object
    if dist_name in ("t", "chi2"):
        if df is None:
            sys.exit(f"Distribution '{dist_name}' requires --df (degrees of freedom)")
        dist_obj = d(df=df)
        dist_label = f"{dist_name}(df={df})"
    elif dist_name == "exponential":
        dist_obj = d(scale=scale)
        dist_label = f"exponential(scale={scale})"
    elif dist_name == "gamma":
        if shape is None:
            sys.exit("Distribution 'gamma' requires --shape (shape parameter a > 0)")
        if shape <= 0:
            sys.exit(f"--shape must be > 0, got {shape}")
        dist_obj = d(a=shape, scale=scale)
        dist_label = f"gamma(shape={shape}, scale={scale})"
    else:
        dist_obj = d()
        dist_label = dist_name

    action_aliases = {"quantile": "ppf", "ppf": "ppf", "cdf": "cdf", "pdf": "pdf"}
    if action not in action_aliases:
        sys.exit(f"Unknown action: {action!r}. Choose from: cdf, pdf, quantile")
    method = action_aliases[action]

    try:
        result = getattr(dist_obj, method)(value)
    except Exception as e:
        sys.exit(f"Computation error: {e}")

    label_map = {"cdf": "CDF", "pdf": "PDF", "ppf": "Quantile (PPF)"}
    print(f"{dist_label} {label_map[method]}({value}) = {result:.8g}")


def cmd_zscore(args):
    data = parse_nums(args.nums)
    if len(data) < 2:
        sys.exit("Need at least 2 data points for z-scores")
    mean = np.mean(data)
    std = np.std(data, ddof=1)
    if std == 0:
        sys.exit("Standard deviation is 0 — all values are identical")
    zs = (data - mean) / std

    col_w = max(len(f"{v:.6g}") for v in data) + 2
    z_w = max(len(f"{z:.4f}") for z in zs) + 2
    print(f"{'Value':<{col_w}}  {'Z-score':<{z_w}}")
    print("-" * (col_w + z_w + 2))
    for v, z in zip(data, zs):
        print(f"{v:<{col_w}.6g}  {z:<{z_w}.4f}")
    print(f"\nmean={mean:.6g}  std={std:.6g}")


def main():
    parser = argparse.ArgumentParser(
        prog="stats.py",
        description="Statistical analysis via NumPy and SciPy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # describe
    p_desc = sub.add_parser("describe", help="Summary statistics for a list of numbers")
    p_desc.add_argument("nums", nargs="+", help="Numbers to describe")
    p_desc.add_argument(
        "--ddof",
        type=int,
        default=1,
        metavar="INT",
        help="Delta degrees of freedom for std: 1=sample (default), 0=population",
    )
    p_desc.set_defaults(func=cmd_describe)

    # corr
    p_corr = sub.add_parser("corr", help="Pearson correlation between two lists")
    p_corr.add_argument("list_a", help="First list, comma-separated (e.g. '1,2,3')")
    p_corr.add_argument("list_b", help="Second list, comma-separated")
    p_corr.set_defaults(func=cmd_corr)

    # dist
    p_dist = sub.add_parser("dist", help="Distribution queries (CDF/PDF/quantile)")
    p_dist.add_argument("dist", help="Distribution name: normal, t, chi2, exponential, gamma")
    p_dist.add_argument("action", help="Action: cdf, pdf, quantile")
    p_dist.add_argument("value", help="Input value")
    p_dist.add_argument("--df", type=float, default=None, help="Degrees of freedom (required for t, chi2)")
    p_dist.add_argument("--scale", type=float, default=1.0, metavar="FLOAT",
                        help="Scale parameter for exponential and gamma (default: 1.0)")
    p_dist.add_argument("--shape", type=float, default=None, metavar="FLOAT",
                        help="Shape parameter 'a' for gamma distribution (required for gamma, must be > 0)")
    p_dist.set_defaults(func=cmd_dist)

    # zscore
    p_z = sub.add_parser("zscore", help="Compute z-scores for each value in a dataset")
    p_z.add_argument("nums", nargs="+", help="Dataset values")
    p_z.set_defaults(func=cmd_zscore)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
