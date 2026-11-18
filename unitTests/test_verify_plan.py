"""
test_verify_plan.py -- primeatlas/generation/verify_plan.py: the Generation tab's Section D
fields turned into the store verifiers' arguments (the island and the window width:
test_verify_width.py). A typed number in any notation; the Threads field resolves Auto, Max
and numbers and refuses everything else; the estimates (verify_estimate.py) price the proof
by the last pt1_verify row and each pass by the v7.2 row of that floor nearest in width, and
say nothing without such a row.

Usage:
    python unitTests/test_verify_plan.py
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.generation import verify_estimate, verify_plan  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_parse_int():
    check(verify_plan.parse_int(" 29 ", 0) == 29, "parse_int trims spaces")
    check(verify_plan.parse_int("0", 0) == 0, "parse_int: 0 allowed with minimum 0")
    for text in ("", None, "x", "-1", "2.5", "1,5", "3,000"):
        check(verify_plan.parse_int(text, 0) is None, f"parse_int refuses {text!r}")
    for text, want in (("1e3", 1000), ("1 000", 1000), ("10^3", 1000)):
        check(verify_plan.parse_int(text, 0) == want,
              f"parse_int reads {text!r} in any notation as {want}")
    check(verify_plan.parse_int("0", 1) is None, "parse_int: 0 refused with minimum 1")


def _test_resolve_threads():
    resolve = verify_plan.resolve_threads
    check(resolve("Auto", "24", None) == 24, "Auto -> the pipeline form's workers")
    check(resolve(" auto ", "8", 32) == 8, "Auto ignores the CPU count, any case")
    check(resolve("Auto", "x", 32) is None, "Auto with an invalid workers field -> None")
    check(resolve("Auto", "0", 32) is None, "Auto with 0 workers -> None")
    check(resolve("Max", "24", 16) == 16, "Max -> the WSL CPU count")
    check(resolve("MAX", "24", 1000) == verify_plan.THREADS_CAP, "Max capped at THREADS_CAP")
    check(resolve("Max", "24", None) is None, "Max without a CPU probe -> None")
    check(resolve("12", "24", None) == 12, "a number as typed")
    check(resolve(str(verify_plan.THREADS_CAP), "24", None) == verify_plan.THREADS_CAP,
          "THREADS_CAP itself allowed")
    for text in ("0", "257", "", "x", "-4"):
        check(resolve(text, "24", 32) is None, f"Threads refuses {text!r}")


def _row(engine, floor=29, numbers="", sieve="", verify="", version=""):
    return {"engine": engine, "engine_version": version, "base_exponent": str(floor),
            "numbers_processed": str(numbers), "sieve_seconds": str(sieve),
            "verify_seconds": str(verify)}


def _test_estimates():
    proof = verify_estimate.proof_seconds
    rows = [_row("pt1_verify", numbers=10 ** 9, verify=100),
            _row("pt1_verify", floor=31, numbers=10 ** 9, verify=50),
            _row("pt1_verify", numbers=10 ** 9, verify="")]
    check(proof(rows, 10 ** 10) == 500, "proof: the last pt1_verify row with a time, any floor")
    check(proof([_row("v7", numbers=10 ** 9, sieve=5, version="v7.2")], 10 ** 9) is None,
          "proof: no pt1_verify row -> None")
    check(proof(rows, 0) is None, "proof: nothing to verify -> None")
    sieve = verify_estimate.sieve_seconds
    rows = [_row("v7", numbers=10 ** 9, sieve=300, version="v7.2"),
            _row("v7", numbers=10 ** 11, sieve=400, version="v7.2"),
            _row("v7", floor=31, numbers=10 ** 11, sieve=1800, version="v7.2"),
            _row("v7", numbers=10 ** 10, sieve=999, version="v7.1"),
            _row("v7", numbers=10 ** 10, sieve="", version="v7.2"),
            _row("pt1", numbers=10 ** 10, sieve=60)]
    check(sieve(rows, 29, [10 ** 11, 10 ** 11]) == 800,
          "sieve: each pass priced by the floor's v7.2 row of its width")
    check(sieve(rows, 29, [10 ** 11, 2 * 10 ** 9]) == 700,
          "sieve: a narrow pass takes the nearest width (10^9, not v7.1's 10^10)")
    check(sieve(rows, 31, [10 ** 10]) == 1800, "sieve: floor 31 has its own row")
    check(sieve(rows, 33, [10 ** 11]) is None, "sieve: a floor without a v7.2 row -> None")
    check(sieve(rows, 29, []) is None, "sieve: no pass -> None")
    check(verify_estimate.duration_text(None) == "?" and
          verify_estimate.duration_text(42) == "42 s" and
          verify_estimate.duration_text(4000) == "1.1 h" and
          verify_estimate.duration_text(600) == "10 min",
          "duration text: ?, seconds, minutes, hours")


def main():
    _test_estimates()
    _test_parse_int()
    _test_resolve_threads()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
