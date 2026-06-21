#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "sympy>=1.12",
# ]
# ///
"""
numtheory.py — Number theory helpers (pure Python + SymPy).

Commands:
  prime N           Check if N is prime
  primes N          List all primes up to N
  factor N          Prime factorization
  gcd A B           Greatest common divisor
  lcm A B           Least common multiple
  fibonacci N       First N Fibonacci numbers
  modpow BASE EXP MOD  Modular exponentiation (BASE^EXP mod MOD)

Examples:
  uv run numtheory.py prime 17
  uv run numtheory.py primes 50
  uv run numtheory.py factor 360
  uv run numtheory.py gcd 48 18
  uv run numtheory.py lcm 12 15
  uv run numtheory.py fibonacci 10
  uv run numtheory.py modpow 2 10 1000
"""

import argparse
import sys
from math import gcd as math_gcd, lcm as math_lcm, isqrt

from sympy import isprime, primerange, factorint


def parse_int(s: str, name: str = "value") -> int:
    try:
        n = int(s)
        return n
    except ValueError:
        sys.exit(f"Error: {name!r} must be an integer, got {s!r}")


def cmd_prime(args):
    n = parse_int(args.n, "N")
    if n < 0:
        sys.exit("N must be a non-negative integer")
    result = isprime(n)
    if result:
        print(f"{n} is PRIME")
    else:
        print(f"{n} is NOT prime")


def cmd_primes(args):
    n = parse_int(args.n, "N")
    if n < 2:
        print("No primes up to", n)
        return
    if n > 10_000_000:
        sys.exit("N too large (max 10,000,000 to avoid memory issues)")
    p_list = list(primerange(2, n + 1))
    count = len(p_list)
    # Display compactly
    if count <= 200:
        # Show all on wrapped lines
        cols = 10
        for i in range(0, count, cols):
            chunk = p_list[i : i + cols]
            print("  " + "  ".join(f"{p:>8}" for p in chunk))
    else:
        # Show first/last 10 and count
        first10 = p_list[:10]
        last10 = p_list[-10:]
        print("First 10: " + ", ".join(str(p) for p in first10))
        print("Last  10: " + ", ".join(str(p) for p in last10))
    print(f"\nTotal: {count} primes up to {n}")


def cmd_factor(args):
    n = parse_int(args.n, "N")
    if n == 0:
        print("0 has no prime factorization")
        return
    if n < 0:
        # Factor the absolute value and show sign
        sign = "-1 × "
        n = -n
    else:
        sign = ""
    if n == 1:
        print(f"{sign}1 (unit, no prime factors)")
        return

    factors = factorint(n)  # returns {prime: exponent}
    parts = []
    for p in sorted(factors):
        exp = factors[p]
        if exp == 1:
            parts.append(str(p))
        else:
            parts.append(f"{p}^{exp}")
    print(f"{sign}" + " × ".join(parts))


def cmd_gcd(args):
    a = parse_int(args.a, "A")
    b = parse_int(args.b, "B")
    result = math_gcd(a, b)
    print(f"gcd({a}, {b}) = {result}")


def cmd_lcm(args):
    a = parse_int(args.a, "A")
    b = parse_int(args.b, "B")
    if a == 0 or b == 0:
        print(f"lcm({a}, {b}) = 0")
        return
    result = math_lcm(a, b)
    print(f"lcm({a}, {b}) = {result}")


def cmd_fibonacci(args):
    n = parse_int(args.n, "N")
    if n <= 0:
        sys.exit("N must be a positive integer")
    if n > 10_000:
        sys.exit("N too large (max 10,000 to keep output manageable)")

    fibs = []
    a, b = 0, 1
    for _ in range(n):
        fibs.append(a)
        a, b = b, a + b

    if n <= 20:
        print(", ".join(str(f) for f in fibs))
    else:
        # Show first 10 and last 5 with ellipsis
        first = ", ".join(str(f) for f in fibs[:10])
        last = ", ".join(str(f) for f in fibs[-5:])
        print(f"{first}, ..., {last}")
        print(f"\nF({n-1}) = {fibs[-1]}")
    print(f"\nTotal: {n} numbers  |  F({n-1}) = {fibs[-1]}")


def cmd_modpow(args):
    base = parse_int(args.base, "BASE")
    exp = parse_int(args.exp, "EXP")
    mod = parse_int(args.mod, "MOD")
    if mod == 0:
        sys.exit("MOD must be non-zero")
    if exp < 0:
        sys.exit("EXP must be non-negative (negative modular exponentiation not supported)")
    result = pow(base, exp, mod)
    print(f"{base}^{exp} mod {mod} = {result}")


def main():
    parser = argparse.ArgumentParser(
        prog="numtheory.py",
        description="Number theory helpers (pure Python + SymPy)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # prime
    p_prime = sub.add_parser("prime", help="Check if N is prime")
    p_prime.add_argument("n", help="Integer to test")
    p_prime.set_defaults(func=cmd_prime)

    # primes
    p_primes = sub.add_parser("primes", help="List all primes up to N")
    p_primes.add_argument("n", help="Upper bound (inclusive)")
    p_primes.set_defaults(func=cmd_primes)

    # factor
    p_factor = sub.add_parser("factor", help="Prime factorization of N")
    p_factor.add_argument("n", help="Integer to factorize")
    p_factor.set_defaults(func=cmd_factor)

    # gcd
    p_gcd = sub.add_parser("gcd", help="Greatest common divisor of A and B")
    p_gcd.add_argument("a", help="First integer")
    p_gcd.add_argument("b", help="Second integer")
    p_gcd.set_defaults(func=cmd_gcd)

    # lcm
    p_lcm = sub.add_parser("lcm", help="Least common multiple of A and B")
    p_lcm.add_argument("a", help="First integer")
    p_lcm.add_argument("b", help="Second integer")
    p_lcm.set_defaults(func=cmd_lcm)

    # fibonacci
    p_fib = sub.add_parser("fibonacci", help="First N Fibonacci numbers")
    p_fib.add_argument("n", help="Count of Fibonacci numbers to generate")
    p_fib.set_defaults(func=cmd_fibonacci)

    # modpow
    p_modpow = sub.add_parser("modpow", help="Modular exponentiation: BASE^EXP mod MOD")
    p_modpow.add_argument("base", help="Base")
    p_modpow.add_argument("exp", help="Exponent (non-negative)")
    p_modpow.add_argument("mod", help="Modulus")
    p_modpow.set_defaults(func=cmd_modpow)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
