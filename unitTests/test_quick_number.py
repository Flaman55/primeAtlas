"""The parser of every numeric field (primeatlas/generation/quick_number.py).

Rules checked:
  - "^" is a power everywhere in an expression, as in the app's own texts ("10^N"): never
    Python's XOR ("5^3" = 125, not 6); it binds like "**" (right to left, above * and +);
  - exact integers at storage-floor scale, with or without an added term;
  - plain integers with space or comma grouping, "a*10**b", scientific notation;
  - blank or broken input gives None.
    python unitTests/test_quick_number.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


CASES = (
    ("10^25+3", 10 ** 25 + 3),
    ("10^25 - 1", 10 ** 25 - 1),
    ("5^3", 125),
    ("2^10", 1024),
    ("10^2^2", 10 ** 4),
    ("3*10^24+5", 3 * 10 ** 24 + 5),
    ("(10^7)*3", 3 * 10 ** 7),
    ("10^25+10^7", 10 ** 25 + 10 ** 7),
    ("10^30+12345678901234567", 10 ** 30 + 12345678901234567),
    ("10^25", 10 ** 25),
    ("3*10^24", 3 * 10 ** 24),
    ("10**25+3", 10 ** 25 + 3),
    ("10**2**2", 10 ** 4),
    ("23 081 664 151", 23081664151),
    ("23,081,664,151", 23081664151),
    ("1e3", 1000),
    ("42", 42),
)

BROKEN = ("", "   ", "abc", "10^", "^5", "10^^2", "1e", None)


def main():
    from primeatlas.generation.quick_number import _eval_quick_number
    passed = True
    for text, want in CASES:
        got = _eval_quick_number(text)
        passed &= check(got == want, f"{text!r} -> {want} (got {got})")
    for text in BROKEN:
        got = _eval_quick_number(text)
        passed &= check(got is None, f"{text!r} -> None (got {got})")
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
