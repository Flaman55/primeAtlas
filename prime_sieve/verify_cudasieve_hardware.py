"""
verify_cudasieve_hardware.py -- one-shot, real-hardware verification script for the three
TODO(needs real hardware) items left open in prime_sieve_cudasieve.py after the cudasieve-v2
branch was built and tested in a sandbox with no CUDA Toolkit and no Nvidia GPU (see that
file's module header and cmd_build()'s own docstring for the full background).

Run this ONCE, by hand, on the actual WSL2 + Nvidia GPU + CUDA Toolkit machine, AFTER the
`cudasieve` binary is built and working (Settings tab > Aktualizacje > CUDASieve installer,
or prime_sieve_cudasieve.py --fetch-license / --build directly). It is intentionally NOT part
of unitTests/ or tests/smoke_test.py -- both of those run in the sandbox on every change and
must stay runnable there; this script requires hardware neither of them can assume.

What it checks (each one maps to one of the three TODO(needs real hardware) comments in
prime_sieve_cudasieve.py):

  1. Boundary/format at 2**40 -- generate_primes_in_range()'s own stdout parsing was written
     against CUDASieve's documented CLI/source, never against real output. This compares its
     result for [2**40, 2**40 + 10**6) against prime_sieve_primesieve.py's own
     generate_primes_in_range() for the IDENTICAL range (libprimesieve is well-established,
     already in production use in this project for every floor from 13 upward -- see
     README.md's "The primesieve mode" section -- so it is the trustworthy reference here).
     A mismatch means either a parsing bug in prime_sieve_cudasieve.py, or a real correctness
     issue in CUDASieve itself for this range.

  2. Whether cudasieve's own `-s` (silent) flag actually suppresses every diagnostic line in
     `-p` (print) mode. generate_primes_in_range() already prints a WARNING line and drops any
     non-numeric stdout line rather than crashing, so this doesn't need special handling here
     -- just watch this script's own console output for that warning. Zero warnings across
     both ranges below is the expected/desired real-hardware result.

  3. The documented ~1-in-20,000 chance of an off-by-one prime count under concurrent GPU load
     (CUDASieve's own README, "Correctness" section) -- generate_primes_in_range() already
     raises if its output isn't strictly increasing, which catches gross corruption but not a
     single missing/duplicated prime. The exact-set comparison against primesieve below (not
     just a count comparison) is what actually catches that specific failure mode, for this
     one sample range. It is a real, documented, low-probability event upstream -- if this
     script ever reports a set mismatch, re-run it once before assuming a bug in this project's
     own code (see CUDASieve's own README for that documented risk).

Usage (inside WSL2, from this repo's prime_sieve/ folder):
    python3 verify_cudasieve_hardware.py

Optional: pass a different range size (default 10**6) as the sole argument, e.g. to try a
bigger sample once the default range passes cleanly:
    python3 verify_cudasieve_hardware.py 10000000

Exits 0 if every check passes, 1 otherwise -- safe to wire into a shell `&&` chain.
"""
import sys
import time

import prime_sieve_cudasieve as cuda_engine
import prime_sieve_primesieve as cpu_engine

MIN_PRINTABLE_TOP = cuda_engine.MIN_PRINTABLE_TOP  # 2**40 -- see that module's own
                                                    # "KNOWN LIMITATION" header comment.

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def run_one_range(lo, hi, label):
    print(f"\n--- {label}: [{lo:,}, {hi:,})  size={hi - lo:,} ---")

    print("[*] Locating cudasieve binary...")
    binary = cuda_engine.find_cudasieve_binary()
    check(binary is not None, "cudasieve binary must be found on this machine "
                               "(checked $CUDASIEVE_BIN, $PATH, and the installer's default "
                               "install dir -- see find_cudasieve_binary() in "
                               "prime_sieve_cudasieve.py) -- if this fails, run the Settings "
                               "tab installer (Aktualizacje > CUDASieve) first")
    if binary is None:
        return None, None
    print(f"    -> {binary}")

    print("[*] Running cudasieve (GPU)...")
    t0 = time.perf_counter()
    cuda_primes = cuda_engine.generate_primes_in_range(lo, hi)
    t_cuda = time.perf_counter() - t0
    print(f"    -> {len(cuda_primes):,} primes in {t_cuda:.3f}s "
          f"({len(cuda_primes) / t_cuda:,.0f} primes/s)")
    check(len(cuda_primes) > 0, f"{label}: cudasieve must find at least one prime in a "
                                 f"1e6-wide range this high up (a real prime desert this wide "
                                 f"would be extraordinary -- 0 results almost certainly means "
                                 f"stdout parsing silently dropped everything)")

    print("[*] Running primesieve (CPU, reference)...")
    t0 = time.perf_counter()
    cpu_primes = cpu_engine.generate_primes_in_range(lo, hi)
    t_cpu = time.perf_counter() - t0
    print(f"    -> {len(cpu_primes):,} primes in {t_cpu:.3f}s")

    check(len(cuda_primes) == len(cpu_primes),
          f"{label}: prime COUNT must match exactly (cudasieve={len(cuda_primes):,}, "
          f"primesieve={len(cpu_primes):,}) -- see this script's own module docstring, "
          f"item 3, for CUDASieve's documented ~1-in-20000 off-by-one risk under concurrent "
          f"GPU load; re-run once before assuming a bug in this project's own code")

    cuda_set = set(cuda_primes)
    cpu_set = set(cpu_primes)
    check(cuda_set == cpu_set,
          f"{label}: prime SETS must be identical, not just counts -- "
          f"only-in-cudasieve={sorted(cuda_set - cpu_set)[:10]} "
          f"only-in-primesieve={sorted(cpu_set - cuda_set)[:10]} (each list truncated to 10)")

    if cuda_primes:
        check(cuda_primes[0] == cpu_primes[0] if cpu_primes else False,
              f"{label}: first prime at/after the range start must match exactly "
              f"(cudasieve={cuda_primes[0]:,}, "
              f"primesieve={cpu_primes[0] if cpu_primes else 'N/A'}) -- this is the specific "
              f"'exact boundary behavior AT 2**40' this script's item 1 exists to check")

    return cuda_primes, cpu_primes


def main():
    range_width = int(sys.argv[1]) if len(sys.argv) > 1 else 10 ** 6

    print("=" * 78)
    print("verify_cudasieve_hardware.py -- real-hardware validation of the 3 "
          "TODO(needs real hardware) items in prime_sieve_cudasieve.py")
    print("=" * 78)

    # Range 1: starts EXACTLY at MIN_PRINTABLE_TOP (2**40) -- the documented boundary itself.
    run_one_range(MIN_PRINTABLE_TOP, MIN_PRINTABLE_TOP + range_width,
                  "Range A (starts exactly at 2**40)")

    # Range 2: a second, unrelated sample further up (10**13-ish) -- catches a bug that
    # happens to be masked at the exact boundary value but not elsewhere.
    lo2 = 10 ** 13
    run_one_range(lo2, lo2 + range_width, "Range B (10**13, unrelated sample)")

    # Sanity check: MIN_PRINTABLE_TOP itself must still be correctly enforced (this part
    # already has sandbox test coverage in unitTests/test_cudasieve_integration.py -- this is
    # just a real-hardware smoke check that the guard didn't get bypassed by anything above).
    print(f"\n--- Guard check: below-floor range must still be refused ---")
    try:
        cuda_engine.generate_primes_in_range(MIN_PRINTABLE_TOP - 100, MIN_PRINTABLE_TOP)
        check(False, "a range entirely BELOW 2**40 must raise RuntimeError, not run")
    except RuntimeError:
        check(True, "a range entirely BELOW 2**40 correctly raises RuntimeError")

    print("\n" + "=" * 78)
    if failures:
        print(f"{len(failures)} FAILURE(S) -- see FAIL lines above")
        return 1
    print("ALL CHECKS PASSED -- prime_sieve_cudasieve.py's parsing/boundary/correctness "
          "assumptions hold on this machine. You can remove the three "
          "TODO(needs real hardware) comments in that file's module header, "
          "generate_primes_in_range(), and cmd_build()'s own header block.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
