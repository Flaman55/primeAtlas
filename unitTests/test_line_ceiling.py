"""
test_line_ceiling.py -- every .py file git tracks stays under the 1000-line ceiling
(a ceiling, not a target). Frozen numbered versions, which are never edited in place,
are the only exceptions; each one must still exist and still be over the ceiling, so
the list cannot go stale.

Run:
    python unitTests\test_line_ceiling.py
"""
import os
import subprocess
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
MAX_LINES = 1000
FROZEN_EXCEPTIONS = (
    "constellation/constellation_finder_v2.py",
    "constellation/constellation_finder_v2_1.py",
    "constellation/ktuple_sieve_v2.py",
)

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def main():
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=_REPO_ROOT, capture_output=True,
                         text=True, timeout=60)
    if out.returncode != 0:
        print(f"SKIPPED (not a git checkout: {out.stderr.strip()})")
        return 0
    paths = [p for p in out.stdout.splitlines() if p]
    check(len(paths) > 100, f"git lists the repo's Python files ({len(paths)})")
    over = {}
    for rel in paths:
        full = os.path.join(_REPO_ROOT, rel)
        if not os.path.isfile(full):
            continue
        with open(full, encoding="utf-8", errors="replace") as f:
            n = f.read().count("\n")
        if n > MAX_LINES:
            over[rel] = n
    unexpected = {p: n for p, n in over.items() if p not in FROZEN_EXCEPTIONS}
    check(not unexpected, f"no file over {MAX_LINES} lines outside the frozen versions "
                          f"(found {unexpected})")
    for rel in FROZEN_EXCEPTIONS:
        check(rel in over, f"{rel} is still a frozen file over the ceiling (else drop it here)")

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
