import sys
import json

# ==========================================================================================
# primecount_query.py -- one-shot CLI calculator for libprimecount's public API (exact
# pi(x) via combinatorial algorithms, no sieve needed), launched by PrimeAtlas's Badania ->
# Przyblizenia pi(x) sub-tab's "primecount" data-source mode. Mirrors primesieve_query.py's
# own shape exactly (same folder, same reasoning) -- see that file's own module header for
# the split rationale (a single quick query and exit, nothing written to storage).
#
# Reuses prime_count_primecount.py's ctypes bindings by importing it as a plain Python
# module -- both files live in this same prime_sieve/ folder and only ever run inside WSL.
#
# Usage (WSL):
#   python3 primecount_query.py pi <x>            count of primes <= x (single value)
#   python3 primecount_query.py pi_batch <x1> [x2 x3 ...]
#                                                  count of primes <= x for EACH x given,
#                                                  in ONE process/library-load -- this is
#                                                  the op the pi(x) approximations tab
#                                                  actually uses (one row per checkpoint,
#                                                  one wsl.exe round trip per PAGE instead
#                                                  of one per row)
#   python3 primecount_query.py nth <n>           the n-th prime (1-indexed, n=1 -> 2)
#   python3 primecount_query.py version           libprimecount's own version string --
#                                                  used purely as a cheap "is it actually
#                                                  installed?" probe (Settings ->
#                                                  Aktualizacje's primecount status check),
#                                                  no prime-counting cost at all
#
# Prints EXACTLY one line of JSON to stdout:
#   success: {"ok": true, "result": <int>}                (pi, nth)
#            {"ok": true, "result": [<int>, <int>, ...]}   (pi_batch, same order as input)
#            {"ok": true, "result": "<version string>"}    (version)
#   failure: {"ok": false, "error": "<message>"}, exit code 1 -- additionally carries
#            "error_kind": "not_installed" when the failure is specifically libprimecount
#            itself not being loadable (prime_count_primecount.PrimecountNotInstalledError)
#            -- lets a caller offer an "install it now?" prompt instead of a generic error.
# Same "never an uncaught traceback on stderr" contract as primesieve_query.py -- every
# bad-input or libprimecount-side error is caught and reported this way, so the GUI side
# can always just parse stdout as JSON.
# ==========================================================================================

import prime_count_primecount as pc


def main(argv):
    if len(argv) < 2:
        print(json.dumps({"ok": False, "error": "no operation given"}))
        return 1
    op = argv[1]
    try:
        if op == "pi":
            if len(argv) != 3:
                raise ValueError("pi needs exactly 1 argument: <x>")
            result = pc.pi(int(argv[2]))
        elif op == "pi_batch":
            if len(argv) < 3:
                raise ValueError("pi_batch needs at least 1 argument: <x1> [x2 x3 ...]")
            result = [pc.pi(int(x)) for x in argv[2:]]
        elif op == "nth":
            if len(argv) != 3:
                raise ValueError("nth needs exactly 1 argument: <n>")
            result = pc.nth_prime(int(argv[2]))
        elif op == "version":
            result = pc.primecount_lib_version()
        else:
            raise ValueError(f"unknown operation: {op!r} (expected pi/pi_batch/nth/version)")
    except pc.PrimecountNotInstalledError as e:
        print(json.dumps({"ok": False, "error": str(e), "error_kind": "not_installed"}))
        return 1
    except (ValueError, RuntimeError) as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    print(json.dumps({"ok": True, "result": result}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
