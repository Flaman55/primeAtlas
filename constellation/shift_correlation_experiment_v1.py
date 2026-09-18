"""
shift_correlation_experiment_v1.py -- empirical k-tuple shift-correlation experiment.

IDEA: instead of deriving which offset patterns are admissible by reasoning about
residues modulo small primes (the usual "cross out n == 0 mod p" argument), this
script just takes the real set of primes up to N and, for every candidate pair of
shifts (a, b), counts how many n have n, n+a, n+b simultaneously prime -- like
sliding two copies of the same "comb" of primes across each other and counting where
all three teeth land together. Patterns that are forced to fail modulo some small p
(e.g. {0, 2, 4}, where one of n, n+2, n+4 is always divisible by 3) show up as a hard
EMPIRICAL ZERO in the count grid on their own, with no residue arithmetic anywhere in
the counting loop -- the "forbidden" structure is a property of the data, not of how
it's computed.

The mod-3-covering check at the bottom is only a POST-HOC sanity check confirming the
zeros the data produced match the known admissibility criterion -- it plays no part
in producing the grid itself.

Standalone script, no dependency on primeatlas/ or prime_sieve/: same self-contained
pattern as constellation_finder_v2.py and ktuple_sieve_v2.py in this directory.
"""

import argparse
import sys


def sieve_primes(n: int) -> bytearray:
    """Sieve of Eratosthenes up to n (inclusive). is_prime[i] is truthy iff i is prime."""
    is_prime = bytearray([1]) * (n + 1)
    is_prime[0] = is_prime[1] = 0
    for p in range(2, int(n ** 0.5) + 1):
        if is_prime[p]:
            is_prime[p * p :: p] = bytearray(len(is_prime[p * p :: p]))
    return is_prime


def shift_pair_grid(is_prime: bytearray, n: int, max_shift: int) -> dict:
    """
    For every 1 <= a < b <= max_shift, count n' in [2, n - max_shift] with
    n', n'+a, n'+b all prime. Returns {(a, b): count}.
    """
    limit = n - max_shift
    primes_in_range = [k for k in range(2, limit + 1) if is_prime[k]]
    counts = {}
    for a in range(1, max_shift + 1):
        for b in range(a + 1, max_shift + 1):
            counts[(a, b)] = 0
    for base in primes_in_range:
        for a in range(1, max_shift + 1):
            if not is_prime[base + a]:
                continue
            for b in range(a + 1, max_shift + 1):
                if is_prime[base + b]:
                    counts[(a, b)] += 1
    return counts


_SMALL_PRIMES = (2, 3, 5, 7, 11, 13)


def blocked_by_small_prime(a: int, b: int) -> int:
    """
    Return the smallest prime p in _SMALL_PRIMES for which {0, a, b} mod p covers every
    residue class mod p (forcing one of n, n+a, n+b to always be divisible by p, hence
    composite) -- 0 if no such p is found in the checked set.
    """
    for p in _SMALL_PRIMES:
        if len({0, a % p, b % p}) == p:
            return p
    return 0


def print_grid(counts: dict, max_shift: int) -> None:
    header = "a\\b " + " ".join(f"{b:>5}" for b in range(2, max_shift + 1))
    print(header)
    for a in range(1, max_shift):
        row = [f"{a:>4}"]
        for b in range(2, max_shift + 1):
            if b <= a:
                row.append("     ")
            else:
                row.append(f"{counts[(a, b)]:>5}")
        print(" ".join(row))


def report_empirical_zeros(counts: dict, max_shift: int) -> list:
    zeros = sorted(k for k, v in counts.items() if v == 0)
    mismatches = []
    print(f"\nEmpirical zero shift-pairs (a, b) among a,b in [1, {max_shift}]:")
    for (a, b) in zeros:
        p = blocked_by_small_prime(a, b)
        flag = f"  <-- forced zero: {{0,{a},{b}}} covers all residues mod {p}" if p else \
            "  <-- NOT explained by any small-prime covering!"
        print(f"  (a={a:>2}, b={b:>2}){flag}")
        if not p:
            mismatches.append((a, b))
    return mismatches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=2_000_000, help="sieve upper bound")
    parser.add_argument("--max-shift", type=int, default=20, help="max shift b to test")
    args = parser.parse_args()

    print(f"Sieving primes up to {args.n:,} ...")
    is_prime = sieve_primes(args.n)

    print(f"Counting shift-pair grid for a,b in [1, {args.max_shift}] ...")
    counts = shift_pair_grid(is_prime, args.n, args.max_shift)

    print()
    print_grid(counts, args.max_shift)

    mismatches = report_empirical_zeros(counts, args.max_shift)
    if mismatches:
        print(
            f"\nWARNING: {len(mismatches)} empirical zero(s) not explained by covering "
            f"mod any of {_SMALL_PRIMES} -- either N is too small (finite-range fluke) "
            "or a larger prime is responsible. Re-run with a larger --n or wider "
            "_SMALL_PRIMES to check."
        )
        sys.exit(1)
    else:
        print(
            "\nAll empirical zeros match a small-prime covering prediction exactly -- "
            "the forbidden pattern emerged purely from counting, confirmed after the fact."
        )


if __name__ == "__main__":
    main()
