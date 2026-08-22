import sys
import json

# ==========================================================================================
# primesieve_query.py -- one-shot CLI calculator for libprimesieve's public API (count
# primes in a range, nth prime, next/prev prime), launched by PrimeAtlas's 'primesieve'
# calculator sub-tab (Liczby pierwsze -> primesieve). Deliberately SEPARATE from
# prime_sieve_primesieve.py's own __main__ (a long-running window-GENERATION CLI with its
# own positional-argument contract, benchmark logging, PGS2 file writes) -- this script
# answers a SINGLE quick query and exits. No window files, no benchmark log row, nothing
# written to storage at all -- CONSTELLATION_PORTAL_DIR / PORTAL_FOLDER never come up here.
#
# Reuses prime_sieve_primesieve.py's ctypes bindings by importing it as a plain Python
# module -- both files live in this same prime_sieve/ folder and only ever run inside WSL,
# where that import is cheap and always available. This is the ONE deliberate exception to
# this folder's "no cross-imports between engine files" convention (see that file's own
# module header) -- this script isn't a scanner engine itself, just a thin CLI wrapper
# around bindings that already exist there.
#
# Usage (WSL):
#   python3 primesieve_query.py count <lo> <hi>   primes in [lo, hi), EXCLUSIVE (this
#                                                  project's convention -- see
#                                                  prime_sieve_primesieve.py's own header
#                                                  comment on the boundary conversion)
#   python3 primesieve_query.py nth <n> [start]   the n-th prime after `start` (default 0),
#                                                  n must be a positive integer
#   python3 primesieve_query.py next <x>          smallest prime strictly greater than x
#   python3 primesieve_query.py prev <x>          largest prime strictly less than x
#
# Prints EXACTLY one line of JSON to stdout:
#   success: {"ok": true, "result": <int>}
#   failure: {"ok": false, "error": "<message>"}, exit code 1
# Ordinary bad-input cases (n<=0, x<=2 for prev, unknown operation, non-integer argument,
# a genuine libprimesieve error) are all caught and reported this way -- never an uncaught
# traceback on stderr -- so the GUI side can always just parse stdout as JSON and show
# `error` in a dialog rather than a raw Python traceback.
# ==========================================================================================

import prime_sieve_primesieve as ps


def main(argv):
    if len(argv) < 2:
        print(json.dumps({"ok": False, "error": "no operation given"}))
        return 1
    op = argv[1]
    try:
        if op == "count":
            if len(argv) != 4:
                raise ValueError("count needs exactly 2 arguments: <lo> <hi>")
            lo, hi = int(argv[2]), int(argv[3])
            result = ps.count_primes_in_range(lo, hi)
        elif op == "nth":
            if len(argv) not in (3, 4):
                raise ValueError("nth needs 1 or 2 arguments: <n> [start]")
            n = int(argv[2])
            start = int(argv[3]) if len(argv) == 4 else 0
            result = ps.nth_prime(n, start)
        elif op == "next":
            if len(argv) != 3:
                raise ValueError("next needs exactly 1 argument: <x>")
            result = ps.next_prime(int(argv[2]))
        elif op == "prev":
            if len(argv) != 3:
                raise ValueError("prev needs exactly 1 argument: <x>")
            result = ps.prev_prime(int(argv[2]))
        else:
            raise ValueError(f"unknown operation: {op!r} (expected count/nth/next/prev)")
    except (ValueError, RuntimeError) as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    print(json.dumps({"ok": True, "result": result}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
