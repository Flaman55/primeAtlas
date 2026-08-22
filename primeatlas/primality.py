"""
primality.py -- pure-Python probabilistic primality testing (Miller-Rabin, Fermat,
Solovay-Strassen) and integer factorization (trial division + Pollard's rho), for the
Testy pierwszosci sub-tab (Liczby pierwsze -> Testy pierwszosci). No external
dependencies required for any of this -- consistent with the app's zero-extra-installs
promise (see the PDF-writer module's own header comment in prime_atlas_v1.py) -- but
factorize() will use sympy.factorint() INSTEAD whenever sympy happens to be importable
in this same Python environment (materially faster and complete for numbers the
pure-Python path might time out on), via the optional-library installer in the
Settings tab (see settings_tab.py's own "opcjonalne biblioteki" section). Nothing here
needs tkinter -- this module runs in the same native-Windows Python process the GUI
itself does (unlike the primesieve calculator, which has to cross into WSL because
libprimesieve is a Linux shared library -- see prime_sieve_primesieve.py's own module
header); Miller-Rabin/Fermat/Solovay-Strassen/Pollard's rho are all ordinary Python
big-int arithmetic, native ints already have arbitrary precision, nothing OS-specific
about any of it.
"""
import math
import random
import time


def try_import_sympy():
    """Returns the sympy module if it's importable in this Python environment, else
    None -- never raises. Checked FRESH on every call (not cached at module import
    time) so a library installed later via the Settings tab's installer (Faza 2b) is
    picked up the next time this is called, without necessarily needing an app
    restart -- pip installing into site-packages while the process is already running
    is visible to a later plain `import sympy` in most cases (failed imports aren't
    cached in sys.modules the way successful ones are); the Settings tab's own
    restart-advisory dialog is a safety net for the cases where it doesn't (e.g. a
    .pth file that only gets picked up at interpreter startup), not a requirement."""
    try:
        import sympy
        return sympy
    except ImportError:
        return None


# ------------------------------------------------------------------------------------------
# Small-prime trial-division fast path -- shared by every test below so a tiny/obviously
# composite input never pays for a full Miller-Rabin/Fermat/Solovay-Strassen round, and so
# every method AGREES on the easy cases instead of each re-implementing (and potentially
# disagreeing on) the n<2/even/small-prime edge cases independently.
# ------------------------------------------------------------------------------------------

_SMALL_PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]


def _trial_division_quick(n):
    """Returns True/False if n's primality can be decided outright against the small
    fixed prime list above (n IS one of them, n is divisible by one of them, or n is
    small enough that "no factor <= 37" already proves primality), else None
    (undecided -- caller falls through to a real test)."""
    if n < 2:
        return False
    for p in _SMALL_PRIMES:
        if n == p:
            return True
        if n % p == 0:
            return False
    if n < _SMALL_PRIMES[-1] ** 2:
        return True  # no factor <= 37 found, and n < 37**2 -- must be prime
    return None


# ------------------------------------------------------------------------------------------
# Miller-Rabin
# ------------------------------------------------------------------------------------------

# Deterministic for every n < 3,317,044,064,679,887,385,961,981 (~3.3*10**24) when tested
# against EXACTLY this witness set -- a published result (Jaeschke / Feitsma / Galway; see
# e.g. https://miller-rabin.appspot.com/ for the exact reference), not a rule of thumb --
# using MORE witnesses below this threshold buys no extra certainty, they're already
# exhaustive there. Above it, this module falls back to `rounds` random-witness rounds
# instead (see miller_rabin_test()'s own docstring).
_MR_DETERMINISTIC_WITNESSES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]
_MR_DETERMINISTIC_LIMIT = 3317044064679887385961981


def _miller_rabin_round(n, a, d, r):
    x = pow(a, d, n)
    if x == 1 or x == n - 1:
        return True
    for _ in range(r - 1):
        x = pow(x, 2, n)
        if x == n - 1:
            return True
    return False


def miller_rabin_test(n, rounds=40):
    """Returns (is_probably_prime, certainty) -- certainty is one of "trial division"
    (decided by _trial_division_quick), "deterministic" (n fell within the proven
    witness-set range, so this is a MATHEMATICAL CERTAINTY, not a probability), or
    "probabilistic ({rounds} rounds)" above that range."""
    quick = _trial_division_quick(n)
    if quick is not None:
        return quick, "trial division"
    if n % 2 == 0:
        return False, "trial division"
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
                return False, "deterministic"
        return True, "deterministic"
    for _ in range(rounds):
        a = random.randrange(2, n - 1)
        if not _miller_rabin_round(n, a, d, r):
            return False, f"probabilistic ({rounds} rounds)"
    return True, f"probabilistic ({rounds} rounds)"


# ------------------------------------------------------------------------------------------
# Fermat primality test -- shown alongside Miller-Rabin deliberately, not as this app's
# primality DECISION anywhere else: Fermat's test is materially weaker (Carmichael numbers
# -- e.g. 561, 41041, 825265 -- pass EVERY Fermat round for EVERY witness coprime to them,
# no matter how many rounds are run), so showing it next to Miller-Rabin/Solovay-Strassen in
# the same results table makes that weakness visible in exactly the case where it matters,
# instead of silently hiding it behind a single pass/fail verdict.
# ------------------------------------------------------------------------------------------

def fermat_test(n, rounds=40):
    """Returns (is_probably_prime, certainty) -- same two-tuple shape as
    miller_rabin_test(), so the results table can show every method uniformly. A witness
    NOT coprime to n (gcd(a, n) != 1) is itself proof of compositeness (a shared factor),
    reported the same way a failed a**(n-1) === 1 (mod n) check would be, not treated as
    an error."""
    quick = _trial_division_quick(n)
    if quick is not None:
        return quick, "trial division"
    if n % 2 == 0:
        return False, "trial division"
    for _ in range(rounds):
        a = random.randrange(2, n - 1)
        if math.gcd(a, n) != 1:
            return False, f"probabilistic ({rounds} rounds)"
        if pow(a, n - 1, n) != 1:
            return False, f"probabilistic ({rounds} rounds)"
    return True, f"probabilistic ({rounds} rounds)"


# ------------------------------------------------------------------------------------------
# Solovay-Strassen -- Euler-criterion-based test, stronger than plain Fermat (no Carmichael-
# style unconditional failure mode -- at least half of all witnesses coprime to a composite
# n expose it, vs. Fermat's witnesses that can ALL agree with a Carmichael number), still
# weaker than Miller-Rabin (which this module still treats as the primary/most trustworthy
# of the three -- see its own module-level comment on the deterministic witness range).
# ------------------------------------------------------------------------------------------

def _jacobi_symbol(a, n):
    """Standard Jacobi symbol (a/n) via quadratic reciprocity, n a positive odd integer."""
    if n <= 0 or n % 2 == 0:
        raise ValueError("n must be a positive odd integer")
    a %= n
    result = 1
    while a != 0:
        while a % 2 == 0:
            a //= 2
            if n % 8 in (3, 5):
                result = -result
        a, n = n, a
        if a % 4 == 3 and n % 4 == 3:
            result = -result
        a %= n
    return result if n == 1 else 0


def solovay_strassen_test(n, rounds=40):
    """Returns (is_probably_prime, certainty) -- same shape as the other two tests."""
    quick = _trial_division_quick(n)
    if quick is not None:
        return quick, "trial division"
    if n % 2 == 0:
        return False, "trial division"
    for _ in range(rounds):
        a = random.randrange(2, n - 1)
        if math.gcd(a, n) != 1:
            return False, f"probabilistic ({rounds} rounds)"
        jacobi = _jacobi_symbol(a, n) % n
        modexp = pow(a, (n - 1) // 2, n)
        if jacobi != modexp:
            return False, f"probabilistic ({rounds} rounds)"
    return True, f"probabilistic ({rounds} rounds)"


def run_all_tests(n, rounds=40):
    """Runs all three tests above against the SAME n, timing each individually. Returns
    a list of dicts (one per method, in a fixed display order):
    {"method": "Miller-Rabin"|"Fermat"|"Solovay-Strassen", "is_prime": bool,
    "certainty": str, "seconds": float} -- exactly what the Testy pierwszosci tab's
    results table needs, one row per method, no further transformation."""
    rows = []
    for method_name, fn in (
        ("Miller-Rabin", miller_rabin_test),
        ("Fermat", fermat_test),
        ("Solovay-Strassen", solovay_strassen_test),
    ):
        t0 = time.perf_counter()
        is_prime, certainty = fn(n, rounds=rounds)
        seconds = time.perf_counter() - t0
        rows.append({"method": method_name, "is_prime": is_prime, "certainty": certainty,
                     "seconds": seconds})
    return rows


# ------------------------------------------------------------------------------------------
# Factorization -- trial division (strips every small factor fast) + Pollard's rho (for
# whatever's left) as the built-in, zero-install default; sympy.factorint() used instead
# when available (see try_import_sympy()) since it is both faster and materially more
# complete (adds Pollard p-1 and a small ECM stage on top of its own rho) for anything the
# pure-Python path might struggle with.
# ------------------------------------------------------------------------------------------

def _pollard_rho(n):
    """Brent's cycle-detection variant of Pollard's rho. Returns a single non-trivial
    factor of n (not necessarily prime -- factorize_pure_python() recurses on whatever
    this returns), or None on the (uncommon) failure case where this particular random
    (x0, c) choice degenerates -- factorize_pure_python() just retries with a fresh
    random choice when that happens."""
    if n % 2 == 0:
        return 2
    if n % 3 == 0:
        return 3
    y = random.randrange(1, n)
    c = random.randrange(1, n)
    m = 128
    g = r = q = 1
    x = ys = 0
    while g == 1:
        x = y
        for _ in range(r):
            y = (y * y + c) % n
        k = 0
        while k < r and g == 1:
            ys = y
            for _ in range(min(m, r - k)):
                y = (y * y + c) % n
                q = (q * abs(x - y)) % n
            g = math.gcd(q, n)
            k += m
        r *= 2
    if g == n:
        while True:
            ys = (ys * ys + c) % n
            g = math.gcd(abs(x - ys), n)
            if g > 1:
                break
    return None if g == n else g


def factorize_pure_python(n, trial_limit=100_000, time_budget=10.0):
    """Returns (factors, complete) -- factors is a sorted list of prime factors WITH
    multiplicity (e.g. 12 -> [2, 2, 3]), complete is False only if time_budget (wall-
    clock seconds, Pollard's rho phase only -- trial division always runs to
    completion first, it's cheap) ran out with an un-factored remainder still > 1
    still stuck on the end of the list AS-IS (not necessarily prime) -- this is a GUI
    calculator, not a batch job, so a pathological input (e.g. two huge close-together
    prime factors, Pollard's rho's known weak case) times out gracefully rather than
    hanging the UI indefinitely. n must be >= 2."""
    if n < 2:
        raise ValueError("n must be >= 2")
    factors = []
    for p in range(2, min(trial_limit, math.isqrt(n)) + 1):
        while n % p == 0:
            factors.append(p)
            n //= p
        if p * p > n:
            break
    if n == 1:
        return sorted(factors), True

    deadline = time.perf_counter() + time_budget
    stack = [n]
    complete = True
    while stack:
        m = stack.pop()
        if m == 1:
            continue
        quick = _trial_division_quick(m)
        if quick is True:
            factors.append(m)
            continue
        if time.perf_counter() > deadline:
            factors.append(m)  # un-factored remainder, appended as-is
            complete = False
            continue
        is_prime, _certainty = miller_rabin_test(m)
        if is_prime:
            factors.append(m)
            continue
        d = None
        while d is None and time.perf_counter() <= deadline:
            d = _pollard_rho(m)
        if d is None:
            factors.append(m)  # rho kept degenerating and the budget ran out
            complete = False
            continue
        stack.append(d)
        stack.append(m // d)
    return sorted(factors), complete


def _to_factor_pairs(factors):
    """[2, 2, 3, 5, 5] -> [(2, 2), (3, 1), (5, 2)] -- (prime, exponent) pairs, the shape
    the results display actually wants (2^2 x 3 x 5^2) rather than a flat repeated
    list."""
    pairs = []
    for f in sorted(factors):
        if pairs and pairs[-1][0] == f:
            pairs[-1] = (f, pairs[-1][1] + 1)
        else:
            pairs.append((f, 1))
    return pairs


def factorize(n, use_sympy=True, trial_limit=100_000, time_budget=10.0):
    """Top-level factorization entry point for the Testy pierwszosci tab. Returns
    {"pairs": [(prime, exponent), ...], "method": "sympy"|"pure_python",
    "complete": bool, "seconds": float}.

    Tries sympy.factorint() first when use_sympy=True AND sympy is actually importable
    (see try_import_sympy()) -- falls back to factorize_pure_python() either when sympy
    isn't installed, or if it raises for any reason (defensive -- an installed-but-
    broken sympy should degrade to the built-in path, not crash the calculator).
    "complete" is always True on the sympy path (factorint() doesn't have a partial-
    result failure mode the way the time-budgeted pure-Python path does)."""
    if n < 2:
        raise ValueError("n must be >= 2")
    t0 = time.perf_counter()
    if use_sympy:
        sympy = try_import_sympy()
        if sympy is not None:
            try:
                factor_map = sympy.factorint(n)
                pairs = sorted(factor_map.items())
                return {"pairs": pairs, "method": "sympy", "complete": True,
                        "seconds": time.perf_counter() - t0}
            except Exception:  # noqa: BLE001 -- fall through to pure-python on ANY
                                # sympy-side failure, never let this crash the calculator
                pass
    factors, complete = factorize_pure_python(n, trial_limit=trial_limit,
                                               time_budget=time_budget)
    return {"pairs": _to_factor_pairs(factors), "method": "pure_python",
            "complete": complete, "seconds": time.perf_counter() - t0}
