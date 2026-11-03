"""
ktuple_wheel_v2_1.py -- the arithmetic of ktuple_sieve_v2_1.py: Miller-Rabin, a small
prime sieve, the CRT residue wheel for a pattern's offsets, per-window candidate
extraction and verification, and the Hardy-Littlewood density used to size a
search fragment. No file I/O and no dependency outside the standard library.
"""
import math
import random


# ------------------------------------------------------------------------------------------
# Miller-Rabin -- minimal standalone copy of primeatlas/primality.py's own
# miller_rabin_test(), trimmed to just the True/False verdict (no certainty label needed
# here). See ktuple_sieve_v2_1.py's module docstring for why it's duplicated rather
# than imported.
# ------------------------------------------------------------------------------------------

_MR_DETERMINISTIC_WITNESSES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]
_MR_DETERMINISTIC_LIMIT = 3317044064679887385961981  # ~3.3e24 -- see primality.py


def _miller_rabin_round(n, a, d, r):
    x = pow(a, d, n)
    if x == 1 or x == n - 1:
        return True
    for _ in range(r - 1):
        x = pow(x, 2, n)
        if x == n - 1:
            return True
    return False


def is_probable_prime(n, rounds=40):
    if n < 2:
        return False
    for p in _MR_DETERMINISTIC_WITNESSES:
        if n == p:
            return True
        if n % p == 0:
            return False
    d = n - 1
    r = 0
    while d % 2 == 0:
        d //= 2
        r += 1
    if n < _MR_DETERMINISTIC_LIMIT:
        for a in _MR_DETERMINISTIC_WITNESSES:
            if a >= n:
                continue
            if not _miller_rabin_round(n, a, d, r):
                return False
        return True
    for _ in range(rounds):
        a = random.randrange(2, n - 1)
        if not _miller_rabin_round(n, a, d, r):
            return False
    return True


# ------------------------------------------------------------------------------------------
# Small prime generation (pure Python sieve -- deep_prime_limit is at most a few million,
# instant either way, no external dependency needed).
# ------------------------------------------------------------------------------------------

def primes_upto(limit):
    """Simple sieve of Eratosthenes, ascending list of primes <= limit."""
    if limit < 2:
        return []
    sieve = bytearray([1]) * (limit + 1)
    sieve[0] = sieve[1] = 0
    for p in range(2, math.isqrt(limit) + 1):
        if sieve[p]:
            sieve[p * p::p] = bytearray(len(sieve[p * p::p]))
    return [i for i, is_p in enumerate(sieve) if is_p]


# ------------------------------------------------------------------------------------------
# Wheel construction (CRT over a handful of small primes).
# ------------------------------------------------------------------------------------------

def _crt_pair(r1, m1, r2, m2):
    """x == r1 (mod m1), x == r2 (mod m2), 0 <= x < m1*m2 -- m1, m2 coprime."""
    m1_inv = pow(m1, -1, m2)
    return (r1 + m1 * ((r2 - r1) * m1_inv % m2)) % (m1 * m2)


def build_wheel(offsets, wheel_primes):
    """For each wheel prime p, a residue r (mod p) is BAD if some offset d makes
    (r + d) % p == 0 -- i.e. starting at n === r (mod p) forces member n+d divisible by
    p. Since k=15-style patterns already span most residues mod small p (their offsets
    are spread across [0, 56] -- for p > 56 every offset is automatically distinct mod
    p, and even for p <= 56 most are), only a small fraction of residues mod p survive.
    Combining survivors across several small primes via CRT compounds this fast (e.g.
    for k15 variant 4: mod 2 alone already halves the space, mod 2*3*5*7*11*13=30030
    leaves ~1 in 30030). Returns (M, sorted_surviving_residues)."""
    M = 1
    residues = [0]
    for p in wheel_primes:
        bad = set((-d) % p for d in offsets)
        good_mod_p = [r for r in range(p) if r not in bad]
        new_residues = [_crt_pair(r, M, gp, p) for r in residues for gp in good_mod_p]
        residues = new_residues
        M *= p
    residues.sort()
    return M, residues


def default_wheel_primes(offsets, max_M=100_000):
    """Greedily picks small primes (2, 3, 5, 7, ...) to include in the explicit wheel,
    stopping just before the combined modulus M would exceed max_M -- keeps the
    surviving-residue table (len(residues), used to stride every window) small enough
    to build/iterate cheaply, while still capturing most of the wheel's benefit (see
    build_wheel()'s own docstring -- returns diminish fast past the first several
    primes, per Mertens' theorem)."""
    chosen = []
    M = 1
    for p in primes_upto(97):
        if M * p > max_M:
            break
        chosen.append(p)
        M *= p
    return chosen


# ------------------------------------------------------------------------------------------
# Per-window candidate extraction.
# ------------------------------------------------------------------------------------------

def _survives_trial_division(n, offsets, deep_primes):
    for p in deep_primes:
        r = n % p
        for d in offsets:
            if (r + d) % p == 0 and n + d != p:  # n+d==p guard: trivial, never hit at the
                return False                      # magnitudes this module targets, kept
                                                    # for correctness at any scale anyway
    return True


def scan_window_for_candidates(base, window_m, offsets, wheel_M, wheel_residues, deep_primes):
    """Scans [base, base+window_m) for positions n surviving both the wheel and the
    deep-prime trial-division filter. Returns a list of surviving n (still need real
    primality verification of all k members -- see verify_candidates())."""
    candidates = []
    for r in wheel_residues:
        n = base + ((r - base) % wheel_M)
        while n < base + window_m:
            if _survives_trial_division(n, offsets, deep_primes):
                candidates.append(n)
            n += wheel_M
    candidates.sort()
    return candidates


def verify_candidates(candidates, offsets, rounds=40):
    """Real primality verification of survivors -- returns the sorted subset of
    `candidates` for which EVERY member (n+d for d in offsets) is prime."""
    hits = []
    for n in candidates:
        if all(is_probable_prime(n + d, rounds=rounds) for d in offsets):
            hits.append(n)
    return hits


# ------------------------------------------------------------------------------------------
# Hardy-Littlewood density -- used only to size a SUGGESTED fragment for the
# "concentrated" location strategy (step_for_concentrated() in
# ktuple_locations_v2_1.py); never affects
# correctness of the sieve itself, only how wide a slice is worth searching for a
# reasonable chance of a hit.
# ------------------------------------------------------------------------------------------

def singular_series_constant(offsets, k, limit=200_000):
    """C_k for this specific pattern: product over primes p of
    (1 - w(p)/p) / (1 - 1/p)**k, where w(p) = number of distinct residues the offsets
    occupy mod p. Converges quickly (grows/shrinks by ever-smaller factors past the
    first few hundred primes) -- limit=200_000 is already good to ~4-5 significant
    figures for k=15-sized patterns; raise it for more precision at real compute cost
    (primes_upto() is O(limit), one-off, cheap even at limit=2_000_000)."""
    log_c = 0.0
    for p in primes_upto(limit):
        w = len(set(o % p for o in offsets))
        if w >= p:
            return 0.0  # inadmissible pattern -- every residue mod p is bad
        log_c += math.log((1 - w / p) / (1 - 1 / p) ** k)
    return math.exp(log_c)


def recommended_fragment_width(offsets, k, floor_exponent, target_expected=1.0, limit=200_000):
    """Width W (as an int) such that the Hardy-Littlewood expected count of this
    pattern with its base in a W-wide slice near 10**floor_exponent is approximately
    target_expected. Uses ln(10**floor_exponent) as a single representative log(x) --
    good enough for sizing a search fragment (not a precision research estimate) since
    ln(x) barely moves across even a couple of orders of magnitude at these depths."""
    C_k = singular_series_constant(offsets, k, limit=limit)
    if C_k <= 0:
        raise ValueError("pattern is inadmissible (or C_k underflowed to 0) -- cannot size a fragment")
    ln_x = floor_exponent * math.log(10)
    density = C_k / ln_x ** k
    return max(1, round(target_expected / density))
