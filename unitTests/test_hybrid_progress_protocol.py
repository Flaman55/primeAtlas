"""Checks the stable stdout protocol shared by hybrid_sieve.py and GenerationTab.

Usage:
    python unitTests\\test_hybrid_progress_protocol.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

from primeatlas.generation import _GEN_HYBRID_DONE_RE, _GEN_HYBRID_STAGE_RE


def main():
    failures = []

    def check(value, message):
        print(("ok:   " if value else "FAIL: ") + message)
        if not value:
            failures.append(message)

    sample = ("[HYBRID] stage 2/5: [10,000,000, 20,000,000) MAIN<= 997; "
              "filter 1009..106693; tuples<= 2\n"
              "[HYBRID] stage tuples: 2: 2,536,441\n"
              "[HYBRID] done: 6,176,607 primes, 10 window(s), 1.213s\n")
    stages = _GEN_HYBRID_STAGE_RE.findall(sample)
    check(stages == [("2", "5")],
          f"Generation parser reads the real runner stage sample exactly (got {stages!r})")
    check(_GEN_HYBRID_DONE_RE.search(sample) is not None,
          "Generation parser recognizes the real runner completion sample")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
