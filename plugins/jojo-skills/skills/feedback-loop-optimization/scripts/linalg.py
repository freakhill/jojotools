#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy>=1.26",
# ]
# ///
"""
linalg.py — Linear algebra via NumPy.

Matrix input format: JSON-style string, e.g. "[[1,2],[3,4]]"

Commands:
  solve A b       Solve linear system Ax = b
  eigen MATRIX    Eigenvalues and eigenvectors
  det MATRIX      Determinant
  inv MATRIX      Matrix inverse
  svd MATRIX      Singular value decomposition summary

Examples:
  uv run linalg.py det "[[1,2],[3,4]]"
  uv run linalg.py inv "[[1,2],[3,4]]"
  uv run linalg.py eigen "[[4,1],[2,3]]"
  uv run linalg.py solve "[[2,1],[-1,3]]" "[5,3]"
  uv run linalg.py svd "[[1,2,3],[4,5,6]]"
"""

import argparse
import json
import sys

import numpy as np


def parse_matrix(s: str) -> np.ndarray:
    """Parse JSON-style matrix string into numpy array."""
    try:
        data = json.loads(s)
        arr = np.array(data, dtype=float)
    except (json.JSONDecodeError, ValueError) as e:
        sys.exit(f"Error parsing matrix {s!r}: {e}\nExpected format: '[[1,2],[3,4]]'")
    if arr.ndim < 1:
        sys.exit("Matrix must be at least 1-dimensional")
    return arr


def parse_vector(s: str) -> np.ndarray:
    """Parse JSON-style vector or scalar string."""
    try:
        data = json.loads(s)
        arr = np.array(data, dtype=float)
        if arr.ndim == 0:
            arr = arr.reshape(1)
        return arr.flatten()
    except (json.JSONDecodeError, ValueError) as e:
        sys.exit(f"Error parsing vector {s!r}: {e}\nExpected format: '[1,2,3]'")


def fmt_matrix(m: np.ndarray, indent: int = 4) -> str:
    """Format a 2D matrix with aligned columns."""
    pad = " " * indent
    if m.ndim == 1:
        m = m.reshape(1, -1)
    col_widths = [max(len(f"{m[r, c]:.6g}") for r in range(m.shape[0])) for c in range(m.shape[1])]
    rows = []
    for r in range(m.shape[0]):
        row = "  ".join(f"{m[r, c]:{col_widths[c]}.6g}" for c in range(m.shape[1]))
        rows.append(pad + "[ " + row + " ]")
    return "\n".join(rows)


def cmd_solve(args):
    A = parse_matrix(args.A)
    b = parse_vector(args.b)

    if A.ndim != 2:
        sys.exit("A must be a 2D matrix")
    if A.shape[0] != A.shape[1]:
        sys.exit(f"A must be square (got {A.shape[0]}x{A.shape[1]}). For over/under-determined systems, use numpy.linalg.lstsq.")
    if A.shape[0] != len(b):
        sys.exit(f"Dimension mismatch: A is {A.shape[0]}x{A.shape[1]} but b has {len(b)} elements")

    try:
        x = np.linalg.solve(A, b)
    except np.linalg.LinAlgError as e:
        sys.exit(f"Could not solve system: {e}")

    print("Solution x (Ax = b):")
    for i, xi in enumerate(x):
        print(f"    x[{i}] = {xi:.8g}")

    residual = np.linalg.norm(A @ x - b)
    print(f"Verification: ||Ax - b|| = {residual:.6f}")


def cmd_eigen(args):
    M = parse_matrix(args.matrix)
    if M.ndim != 2 or M.shape[0] != M.shape[1]:
        sys.exit(f"Expected square matrix, got shape {M.shape}")

    try:
        eigenvalues, eigenvectors = np.linalg.eig(M)
    except np.linalg.LinAlgError as e:
        sys.exit(f"Eigendecomposition failed: {e}")

    print("Eigenvalues:")
    for i, ev in enumerate(eigenvalues):
        if np.iscomplex(ev):
            print(f"    λ[{i}] = {ev.real:.6g} + {ev.imag:.6g}i")
        else:
            print(f"    λ[{i}] = {ev.real:.6g}")

    print("\nEigenvectors (columns):")
    n = M.shape[0]
    for i in range(n):
        vec = eigenvectors[:, i]
        vec_str = "  ".join(f"{v.real:.6g}" for v in vec)
        print(f"    v[{i}] = [ {vec_str} ]")


def cmd_det(args):
    M = parse_matrix(args.matrix)
    if M.ndim != 2 or M.shape[0] != M.shape[1]:
        sys.exit(f"Expected square matrix, got shape {M.shape}")

    try:
        d = np.linalg.det(M)
    except np.linalg.LinAlgError as e:
        sys.exit(f"Determinant computation failed: {e}")

    print(f"{d:.8g}")


def cmd_inv(args):
    M = parse_matrix(args.matrix)
    if M.ndim != 2 or M.shape[0] != M.shape[1]:
        sys.exit(f"Expected square matrix, got shape {M.shape}")

    try:
        inv = np.linalg.inv(M)
    except np.linalg.LinAlgError as e:
        sys.exit(f"Matrix is singular (not invertible): {e}")

    print("Inverse matrix:")
    print(fmt_matrix(inv))

    # Condition number for info
    cond = np.linalg.cond(M)
    print(f"\nCondition number: {cond:.6g}")
    if cond > 1e10:
        print("  Warning: matrix is ill-conditioned — result may be inaccurate")


def cmd_svd(args):
    M = parse_matrix(args.matrix)
    if M.ndim != 2:
        sys.exit(f"Expected 2D matrix, got shape {M.shape}")

    try:
        U, s, Vt = np.linalg.svd(M, full_matrices=False)
    except np.linalg.LinAlgError as e:
        sys.exit(f"SVD failed: {e}")

    print(f"Shape: {M.shape[0]}×{M.shape[1]}")
    print(f"Rank:  {np.sum(s > 1e-10)}")
    print(f"\nSingular values:")
    for i, sv in enumerate(s):
        print(f"    σ[{i}] = {sv:.8g}")

    total = np.sum(s ** 2)
    print(f"\nVariance explained (σ²/Σσ²):")
    cumvar = 0.0
    for i, sv in enumerate(s):
        var = (sv ** 2) / total * 100
        cumvar += var
        print(f"    σ[{i}]: {var:6.2f}%  (cumulative: {cumvar:.2f}%)")

    print(f"\nU ({U.shape[0]}×{U.shape[1]}):")
    print(fmt_matrix(U))
    print(f"\nVᵀ ({Vt.shape[0]}×{Vt.shape[1]}):")
    print(fmt_matrix(Vt))


def main():
    parser = argparse.ArgumentParser(
        prog="linalg.py",
        description="Linear algebra via NumPy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # solve
    p_solve = sub.add_parser("solve", help="Solve linear system Ax = b")
    p_solve.add_argument("A", help="Coefficient matrix A, JSON format '[[1,2],[3,4]]'")
    p_solve.add_argument("b", help="Right-hand side vector b, JSON format '[1,2]'")
    p_solve.set_defaults(func=cmd_solve)

    # eigen
    p_eigen = sub.add_parser("eigen", help="Eigenvalues and eigenvectors")
    p_eigen.add_argument("matrix", help="Square matrix in JSON format")
    p_eigen.set_defaults(func=cmd_eigen)

    # det
    p_det = sub.add_parser("det", help="Determinant of a matrix")
    p_det.add_argument("matrix", help="Square matrix in JSON format")
    p_det.set_defaults(func=cmd_det)

    # inv
    p_inv = sub.add_parser("inv", help="Matrix inverse")
    p_inv.add_argument("matrix", help="Square matrix in JSON format")
    p_inv.set_defaults(func=cmd_inv)

    # svd
    p_svd = sub.add_parser("svd", help="Singular value decomposition summary")
    p_svd.add_argument("matrix", help="Matrix in JSON format (any shape)")
    p_svd.set_defaults(func=cmd_svd)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
