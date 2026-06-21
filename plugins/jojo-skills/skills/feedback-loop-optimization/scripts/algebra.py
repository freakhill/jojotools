#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "sympy>=1.12",
# ]
# ///
"""
algebra.py — Symbolic math via SymPy.

Commands:
  solve EXPR [VAR]    Solve equation (set to zero if no '=')
  expand EXPR         Expand expression
  factor EXPR         Factor expression
  diff EXPR [VAR]     Differentiate
  integrate EXPR [VAR] Integrate (indefinite)
  simplify EXPR       Simplify expression

Examples:
  uv run algebra.py solve "x**2 - 4" x
  uv run algebra.py diff "x**3 + 2*x" x
  uv run algebra.py integrate "sin(x)" x
  uv run algebra.py factor "x**2 - 5*x + 6"
"""

import argparse
import sys

from sympy import (
    Symbol,
    symbols,
    sympify,
    solve,
    expand,
    factor,
    diff,
    integrate,
    simplify,
    latex,
    pretty,
    SympifyError,
)
from sympy.parsing.sympy_parser import parse_expr


def parse_expression(expr_str: str):
    """Parse a string into a SymPy expression, handling '=' as subtraction."""
    if "=" in expr_str:
        lhs, rhs = expr_str.split("=", 1)
        return parse_expr(lhs.strip()) - parse_expr(rhs.strip())
    return parse_expr(expr_str.strip())


def detect_var(expr) -> Symbol:
    """Auto-detect the free variable; error if ambiguous."""
    free = sorted(expr.free_symbols, key=str)
    if len(free) == 1:
        return free[0]
    if not free:
        return symbols("x")
    raise ValueError(
        f"Expression has multiple free variables: {[str(s) for s in free]}. "
        "Specify one with [VAR]."
    )


def cmd_solve(args):
    try:
        expr = parse_expression(args.expr)
    except (SympifyError, Exception) as e:
        sys.exit(f"Error parsing expression: {e}")

    if args.var:
        var = Symbol(args.var)
    else:
        try:
            var = detect_var(expr)
        except ValueError as e:
            sys.exit(str(e))

    try:
        solutions = solve(expr, var)
    except Exception as e:
        sys.exit(f"Could not solve: {e}")

    if not solutions:
        print(f"No solutions found for {var} in: {expr} = 0")
    else:
        sol_strs = [str(s) for s in solutions]
        print(f"{var} = [{', '.join(sol_strs)}]")


def cmd_expand(args):
    try:
        expr = parse_expression(args.expr)
        result = expand(expr)
        print(str(result))
    except Exception as e:
        sys.exit(f"Error: {e}")


def cmd_factor(args):
    try:
        expr = parse_expression(args.expr)
        result = factor(expr)
        print(str(result))
    except Exception as e:
        sys.exit(f"Error: {e}")


def cmd_diff(args):
    try:
        expr = parse_expression(args.expr)
    except Exception as e:
        sys.exit(f"Error parsing expression: {e}")

    if args.var:
        var = Symbol(args.var)
    else:
        try:
            var = detect_var(expr)
        except ValueError as e:
            sys.exit(str(e))

    try:
        result = diff(expr, var)
        print(f"d/d{var}({expr}) = {result}")
    except Exception as e:
        sys.exit(f"Error: {e}")


def cmd_integrate(args):
    try:
        expr = parse_expression(args.expr)
    except Exception as e:
        sys.exit(f"Error parsing expression: {e}")

    if args.var:
        var = Symbol(args.var)
    else:
        try:
            var = detect_var(expr)
        except ValueError as e:
            sys.exit(str(e))

    try:
        result = integrate(expr, var)
        print(f"∫({expr}) d{var} = {result} + C")
    except Exception as e:
        sys.exit(f"Error: {e}")


def cmd_simplify(args):
    try:
        expr = parse_expression(args.expr)
        result = simplify(expr)
        print(str(result))
    except Exception as e:
        sys.exit(f"Error: {e}")


def main():
    parser = argparse.ArgumentParser(
        prog="algebra.py",
        description="Symbolic math via SymPy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # solve
    p_solve = sub.add_parser("solve", help="Solve equation (= 0 or with explicit =)")
    p_solve.add_argument("expr", help="Expression or equation, e.g. 'x**2 - 4' or 'x**2 = 4'")
    p_solve.add_argument("var", nargs="?", default=None, help="Variable to solve for (auto-detected if omitted)")
    p_solve.set_defaults(func=cmd_solve)

    # expand
    p_expand = sub.add_parser("expand", help="Expand expression")
    p_expand.add_argument("expr", help="Expression to expand")
    p_expand.set_defaults(func=cmd_expand)

    # factor
    p_factor = sub.add_parser("factor", help="Factor expression")
    p_factor.add_argument("expr", help="Expression to factor")
    p_factor.set_defaults(func=cmd_factor)

    # diff
    p_diff = sub.add_parser("diff", help="Differentiate expression")
    p_diff.add_argument("expr", help="Expression to differentiate")
    p_diff.add_argument("var", nargs="?", default=None, help="Variable (auto-detected if omitted)")
    p_diff.set_defaults(func=cmd_diff)

    # integrate
    p_int = sub.add_parser("integrate", help="Integrate expression (indefinite)")
    p_int.add_argument("expr", help="Expression to integrate")
    p_int.add_argument("var", nargs="?", default=None, help="Variable (auto-detected if omitted)")
    p_int.set_defaults(func=cmd_integrate)

    # simplify
    p_simp = sub.add_parser("simplify", help="Simplify expression")
    p_simp.add_argument("expr", help="Expression to simplify")
    p_simp.set_defaults(func=cmd_simplify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
