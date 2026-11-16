"""The shared reader of number fields (primeatlas/core/number_text.py).

Rules checked:
  - digit grouping from any convention: spaces of any kind, apostrophes, underscores,
    commas or dots in groups of three, Indian lakh groups; mixed comma and dot (the last
    one is the decimal mark);
  - powers: "^", "**", superscript digits, LaTeX braces; scientific "e"/"E" with a sign;
    times signs "*", "x", "×", "·", "\\times"; minus signs "-", "−", "–";
  - exact arithmetic at storage-floor scale, "^" right to left and above unary minus;
  - one comma or dot before exactly three digits: both readings are tried and only whole
    results count ("1,500" is 1500, "3,000" is 3000 or 3, "1,5" is not whole);
  - ambiguous input lists its whole candidates; invalid input names its reason;
  - no evaluation of code and no hang: names, calls and attributes are rejected, a power
    too large is rejected at once;
  - 5000 random strings of digits, marks and operators: never an exception, never slow;
  - fraction fields (fraction=True) take non-whole values in the same notations ("1,5",
    "2.5e-1", "3/4"), still ambiguous for "1,500" (1500 or 1.5); words (words=("Auto",))
    are read case-insensitively as themselves;
  - plain_number gives the plain digits a reading stands for, or the stripped text when it
    is not ok, so code that reads plain integers keeps its own error messages;
  - _eval_quick_number returns the value only when the reading is unambiguous.
    python unitTests/test_number_text.py
"""
import os
import sys
import time
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


F25 = 10 ** 25

OK = (
    ("42", 42),
    ("  42  ", 42),
    ("-7", -7),
    ("+7", 7),
    ("1 000 000", 1_000_000),
    ("1 000 000", 1_000_000),
    ("1 000 000", 1_000_000),
    ("1 000 000", 1_000_000),
    ("1'000'000", 1_000_000),
    ("1’000’000", 1_000_000),
    ("1_000_000", 1_000_000),
    ("1,000,000", 1_000_000),
    ("1.000.000", 1_000_000),
    ("1,00,00,000", 10_000_000),
    ("1,234,567.0", 1_234_567),
    ("1.234.567,0", 1_234_567),
    ("1,500", 1500),
    ("1.500", 1500),
    ("12345,000", 12345),
    ("10^25", F25),
    ("10**25", F25),
    ("10²⁵", F25),
    ("10^{25}", F25),
    ("10^25+3", F25 + 3),
    ("10^25 - 1", F25 - 1),
    ("10^25 − 1", F25 - 1),
    ("10^25 – 1", F25 - 1),
    ("3*10^24", 3 * 10 ** 24),
    ("3 x 10^24", 3 * 10 ** 24),
    ("3X10^24", 3 * 10 ** 24),
    ("3×10^24", 3 * 10 ** 24),
    ("3 · 10^24", 3 * 10 ** 24),
    ("3 \\times 10^{24}", 3 * 10 ** 24),
    ("3\\cdot10^{24}", 3 * 10 ** 24),
    ("1.5×10²⁵", 15 * 10 ** 24),
    ("1,5·10^25", 15 * 10 ** 24),
    ("1e3", 1000),
    ("1E+25", F25),
    ("1.5E25", 15 * 10 ** 24),
    ("1,5E+25", 15 * 10 ** 24),
    ("2.5e1", 25),
    ("10^30+12345678901234567", 10 ** 30 + 12345678901234567),
    ("5^3", 125),
    ("2^3^2", 2 ** 9),
    ("-2^2", -4),
    ("(10^7)*3", 3 * 10 ** 7),
    ("10^5/2", 50_000),
    ("7*(2+3)", 35),
    ("10^7 + 10^7/2", 15_000_000),
)

AMBIGUOUS = (
    ("3,000", {3000, 3}),
    ("3.000", {3000, 3}),
    ("1,500e3", {1_500_000, 1500}),
)

INVALID = (
    ("1,5", "not_whole"),
    ("7/2", "not_whole"),
    ("10^-3", "not_whole"),
    ("abc", "syntax"),
    ("4,.,.", "syntax"),
    ("4,.", "syntax"),
    (",5", "syntax"),
    ("1..2", "syntax"),
    ("10^", "syntax"),
    ("^5", "syntax"),
    ("10^^2", "syntax"),
    ("1e", "syntax"),
    ("1,2,3", "syntax"),
    ("12,34,567,8", "syntax"),
    ("1.234,567.8", "syntax"),
    ("()", "syntax"),
    ("(1", "syntax"),
    ("0x1F", "syntax"),
    ("0x10", "syntax"),
    ("3 x 10", "syntax"),
    ("__import__('os')", "syntax"),
    ("len('ab')", "syntax"),
    ("1;2", "syntax"),
    ("10^10^10", "too_large"),
    ("2^1000000", "too_large"),
    ("10^(10^7)", "too_large"),
)


def main():
    from primeatlas.core import number_text as nt
    from primeatlas.generation.quick_number import _eval_quick_number
    passed = True
    for text, want in OK:
        r = nt.read_number(text)
        passed &= check(r.state == nt.OK and r.value == want,
                        f"{text!a} -> {want} ({r.state}, {r.value})")
    for text, want in AMBIGUOUS:
        r = nt.read_number(text)
        passed &= check(r.state == nt.AMBIGUOUS and set(r.candidates) == want
                        and r.value is None,
                        f"{text!a} -> ambiguous {sorted(want)} ({r.state}, {r.candidates})")
        passed &= check(_eval_quick_number(text) is None,
                        f"{text!a}: the field reader takes no value from ambiguous input")
    for text, reason in INVALID:
        t0 = time.perf_counter()
        r = nt.read_number(text)
        seconds = time.perf_counter() - t0
        passed &= check(r.state == nt.INVALID and r.reason == reason and r.value is None
                        and seconds < 0.5,
                        f"{text!a} -> invalid, {reason} ({r.state}, {r.reason}, {seconds:.3f} s)")
    for text in ("", "   ", None):
        r = nt.read_number(text)
        passed &= check(r.state == nt.EMPTY and r.value is None, f"{text!a} -> empty")
    import random
    rng = random.Random(11)
    alphabet = "0123456789.,' ^*/+-()eE×²⁻−x{}"
    worst, crashed = 0.0, []
    for _ in range(5000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randrange(1, 16)))
        t0 = time.perf_counter()
        try:
            r = nt.read_number(text)
            assert r.state in (nt.OK, nt.AMBIGUOUS, nt.INVALID, nt.EMPTY)
        except Exception as error:  # noqa: BLE001
            crashed.append((text, error))
        worst = max(worst, time.perf_counter() - t0)
    passed &= check(not crashed and worst < 0.5,
                    f"5000 random strings: no exception, slowest {worst:.3f} s "
                    f"({ascii(crashed[:3])})")
    for text, want in (("1,5", Fraction(3, 2)), ("2.5e-1", Fraction(1, 4)), ("3/4", Fraction(3, 4)),
                       ("1 234,5", Fraction(2469, 2)), ("-0,5", Fraction(-1, 2)), ("7", 7),
                       ("10^-3", Fraction(1, 1000))):
        r = nt.read_number(text, fraction=True)
        passed &= check(r.state == nt.OK and r.value == want and type(r.value) is type(want),
                        f"fraction {text!a} -> {want} ({r.state}, {r.value!r})")
    r = nt.read_number("1,500", fraction=True)
    passed &= check(r.state == nt.AMBIGUOUS and set(r.candidates) == {1500, Fraction(3, 2)},
                    f"fraction '1,500' -> 1500 or 1.5 ({r.candidates})")
    r = nt.read_number("abc", fraction=True)
    passed &= check(r.state == nt.INVALID and r.reason == nt.SYNTAX, "fraction 'abc' invalid")
    for text in ("Auto", "auto", " AUTO "):
        r = nt.read_number(text, words=("Auto", "Max"))
        passed &= check(r.state == nt.OK and r.value == "Auto", f"word {text!a} -> Auto")
    r = nt.read_number("Autos", words=("Auto",))
    passed &= check(r.state == nt.INVALID, "a word must match whole")
    for text, kw, want in (("1 000 000", {}, "1000000"), ("10^25+3", {}, str(F25 + 3)),
                           ("1,5", {}, "1,5"), ("3,000", {}, "3,000"), ("  abc ", {}, "abc"),
                           ("", {}, ""), ("1,5", {"fraction": True}, "1.5"),
                           ("1/3", {"fraction": True}, str(1 / 3)),
                           ("2,0", {"fraction": True}, "2"), ("auto", {"words": ("Auto",)}, "Auto")):
        got = nt.plain_number(text, **kw)
        passed &= check(got == want, f"plain_number({text!a}, {kw}) -> {want!a} (got {got!a})")
    passed &= check(nt.number_value("1 000") == 1000 and nt.number_value("1,5") is None
                    and nt.fraction_value("1,5") == 1.5 and nt.fraction_value("x") is None,
                    "number_value / fraction_value")
    passed &= check(_eval_quick_number("1 500 000") == 1_500_000
                    and _eval_quick_number("10^25+3") == F25 + 3
                    and _eval_quick_number("1,5") is None and _eval_quick_number("") is None,
                    "_eval_quick_number: the value when unambiguous, else None")
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
