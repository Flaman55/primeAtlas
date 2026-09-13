import ctypes
import ctypes.util

# ==========================================================================================
# prime_count_primecount.py -- ctypes binding to libprimecount, Kim Walisch's companion
# library to primesieve (see prime_sieve_primesieve.py in this same folder for that one's
# own binding, which this file mirrors closely).
#
# Unlike every engine in this folder (including primesieve mode), this file does not
# enumerate or write any primes at all -- primecount answers "how many primes are there
# below x?" (and its inverse, "what is the n-th prime?") directly, via combinatorial
# algorithms (Meissel/Lehmer/LMO/Deleglise-Rivat/Gourdon, depending on x and library
# version) that never need to sieve every integer up to x. That is the whole reason this
# binding exists alongside primesieve mode: a fresh (or primesieve-generated) sieve is
# O(x) time and memory, capped in this project at MAX_SIEVE_BOUND (~2*10**8) in every pure-
# Python conjecture module (squares_window.py, gaps_window.py, pi_approx_window.py, ...);
# primecount_pi(x) runs in O(x^(2/3) / (log x)^2) time and O(x^(1/3) * (log x)^3) memory,
# reaching x in the range of 10^12-10^15+ (hardware/thread-count dependent) without ever
# holding a single bit of sieve state for the whole range.
#
# Only the 64-bit C API is bound here (primecount_pi/primecount_nth_prime/primecount_phi,
# all int64_t) -- primecount.h also exposes 128-bit variants (primecount_pi_128/
# primecount_nth_prime_128, via a pc_int128_t {lo: uint64, hi: int64} struct) for x up to
# 10**31, but those exist for astronomically large x that would take primecount itself far
# longer to compute than anyone would wait for in an interactive GUI -- int64_t alone
# already covers x up to 2**63-1 (~9.22*10**18), several orders of magnitude past what's
# practical here. Skipped for now, not because it's hard to bind, but because there is no
# realistic caller yet -- add it if a future need for x > 2**63-1 actually shows up.
#
# ATTRIBUTION: this file calls into libprimecount, an independent, third-party, open-source
# project by Kim Walisch -- NOT authored by, or part of, this project.
#   Source:  https://github.com/kimwalisch/primecount
#   License: BSD (see that repository's own LICENSE file for the exact text)
#   This file only binds (via ctypes) to the SYSTEM-installed libprimecount shared library
#   and calls its public C API (primecount.h / doc/API.md in that repository) -- no
#   primecount source code is copied into this file or this project.
# ==========================================================================================

_lib = None


class PrimecountNotInstalledError(RuntimeError):
    """Raised specifically when libprimecount itself could not be loaded (as opposed to
    any other RuntimeError this module raises for a genuine libprimecount-side compute
    error) -- a distinct type so a caller several layers up (primecount_query.py's own
    JSON error_kind field, then research_pi_approx_tab.py's "primecount" data-source
    mode) can tell "please install it" apart from "it's installed but something else
    went wrong" without parsing this exception's own message text."""


def _load_lib():
    global _lib
    if _lib is None:
        lib_path = ctypes.util.find_library("primecount")
        if not lib_path:
            # Same find_library() fallback reasoning as prime_sieve_primesieve.py's own
            # _load_lib() -- an SONAME-versioned .so can fail to resolve by name on some
            # distros even when genuinely installed; fall back to the plain unversioned
            # name a -dev package's linker script normally provides.
            lib_path = "libprimecount.so"
        try:
            lib = ctypes.CDLL(lib_path, use_errno=True)
        except OSError as e:
            raise PrimecountNotInstalledError(
                f"Could not load libprimecount ({lib_path}): {e}. Install it first (e.g. "
                f"'apt install primecount libprimecount8 libprimecount-dev "
                f"libprimecount-dev-common', or build from "
                f"https://github.com/kimwalisch/primecount).") from e
        lib.primecount_pi.argtypes = [ctypes.c_int64]
        lib.primecount_pi.restype = ctypes.c_int64
        lib.primecount_nth_prime.argtypes = [ctypes.c_int64]
        lib.primecount_nth_prime.restype = ctypes.c_int64
        lib.primecount_phi.argtypes = [ctypes.c_int64, ctypes.c_int64]
        lib.primecount_phi.restype = ctypes.c_int64
        lib.primecount_get_num_threads.argtypes = []
        lib.primecount_get_num_threads.restype = ctypes.c_int
        lib.primecount_set_num_threads.argtypes = [ctypes.c_int]
        lib.primecount_set_num_threads.restype = None
        lib.primecount_version.argtypes = []
        lib.primecount_version.restype = ctypes.c_char_p
        _lib = lib
    return _lib


def primecount_lib_version():
    return _load_lib().primecount_version().decode("ascii")


def get_num_threads():
    return int(_load_lib().primecount_get_num_threads())


def set_num_threads(num_threads):
    """0 (or any value <= 0) means 'let primecount decide' in the C API's own convention
    (it defaults to all available CPU cores) -- passed straight through, no clamping here."""
    _load_lib().primecount_set_num_threads(int(num_threads))


def pi(x):
    """Count of primes <= x, via Xavier Gourdon's algorithm (primecount's fastest, used by
    primecount_pi() regardless of which of the library's several combinatorial algorithms
    it's internally named after -- see this file's own module docstring). Uses every CPU
    core by default; call set_num_threads() first to change that.

    Returns -1 on error per the C API's own contract, which this wrapper turns into a
    raised RuntimeError instead -- silently returning -1 as if it were a real (impossible,
    since pi(x) is never negative) count would be worse than raising for every caller in
    this project (see e.g. squares_window.py's own "never silently truncate" contracts)."""
    if x < 0:
        raise ValueError("x must be >= 0")
    lib = _load_lib()
    ctypes.set_errno(0)
    result = int(lib.primecount_pi(x))
    if result < 0:
        raise RuntimeError(f"primecount_pi({x}) failed (errno={ctypes.get_errno()})")
    return result


def nth_prime(n):
    """The n-th prime (1-indexed, nth_prime(1) == 2), via a combination of primecount's
    own counting function and a final sieve pass to locate the exact prime -- same
    "count first, then search" idea any Meissel-Lehmer-style nth-prime implementation
    uses. Returns -1 on error per the C API; raised as RuntimeError here, same reasoning
    as pi()'s own docstring."""
    if n <= 0:
        raise ValueError("n must be a positive integer")
    lib = _load_lib()
    ctypes.set_errno(0)
    result = int(lib.primecount_nth_prime(n))
    if result < 0:
        raise RuntimeError(f"primecount_nth_prime({n}) failed (errno={ctypes.get_errno()})")
    return result


def phi(x, a):
    """Legendre's partial sieve function phi(x, a): counts the integers in [1, x] not
    divisible by any of the first `a` primes. The building block primecount's own pi(x)
    implementations are built from internally -- exposed here mainly for completeness
    (mirrors primecount.h's own public C API 1:1) and any future feature that might want
    it directly; nothing in this project's pi(x) tab calls it yet."""
    lib = _load_lib()
    ctypes.set_errno(0)
    result = int(lib.primecount_phi(x, a))
    if result < 0:
        raise RuntimeError(f"primecount_phi({x}, {a}) failed (errno={ctypes.get_errno()})")
    return result
