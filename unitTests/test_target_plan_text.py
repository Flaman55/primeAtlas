"""Texts of the target planner (primeatlas/generation/target_plan_text.py), in both languages.

Rules checked:
  - errors: the first five bad lines with their line numbers, reason and text, then how
    many more; every error key has a text in both locales;
  - a table row: number, floor, range, windows, targets, method (Atlas with its engine or
    Pseudosquares), time;
  - the summary: the plan's total, both comparison totals (n/a when a method has no
    calibration), the targets already in the storage, the unplanned windows, the
    estimated-engine and Pseudosquares-from-count notes and the note that Pseudosquares
    writes nothing, each only when it applies.
    python unitTests/test_target_plan_text.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

ERROR_KEYS = ("not_number", "too_many_fields", "center_below_one", "radius_negative",
              "below_min", "above_max", "too_many")


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def duration(seconds):
    return f"{seconds:.0f} s"


def main():
    from primeatlas.core.i18n import Translator
    from primeatlas.generation import target_plan_text as tpt, target_planner as tp
    from primeatlas.generation.target_plan_costs import Costs
    passed = True
    for lang in ("en", "pl"):
        T = Translator(lang)
        for key in ERROR_KEYS:
            text = T(f"target_planner.error_{key}")
            passed &= check(text and not text.startswith("target_planner."),
                            f"{lang}: error text for {key}")
        errors = [tp.LineError(n, "not_number", f"x{n}") for n in range(1, 9)]
        text = tpt.errors_text(errors, T)
        passed &= check(all(f"x{n}" in text for n in range(1, 6)) and "x6" not in text
                        and T("target_planner.errors_more", count=3) in text,
                        f"{lang}: five errors shown, then '3 more' ({text!r})")

        F = 10 ** 25
        atlas = tp.Group(25, 4, 300, tp.METHOD_ATLAS, "v7", 120.0, ((4, 300),), 7, F + 40,
                         F + 50)
        pss = tp.Group(25, 900, 2, tp.METHOD_PSS, None, 5.0, ((900, 2),), 1, F + 90, F + 99)
        row = tpt.row_values(3, atlas, T, duration)
        passed &= check(row == ("3", "25", str(F + 40), str(F + 50), "300", "7",
                                T("target_planner.method_atlas", engine="v7"), "120 s"),
                        f"{lang}: an Atlas row ({row})")
        row = tpt.row_values(4, pss, T, duration)
        passed &= check(row[6] == T("target_planner.method_pss") and row[4] == "2",
                        f"{lang}: a Pseudosquares row ({row})")

        plan = tp.Plan([atlas, pss], 125.0, 220.0, 402.0, 0, [])
        costs = Costs(None, None, False, "pseudosquares_print")
        text = tpt.summary_text(plan, costs, T, duration)
        passed &= check(T("target_planner.summary", groups=2, time="125 s") in text
                        and T("target_planner.compare", atlas="220 s", pss="402 s") in text
                        and T("target_planner.pss_writes_nothing") in text
                        and T("target_planner.stored", count=0) not in text
                        and T("target_planner.atlas_estimated") not in text
                        and T("target_planner.pss_from_count") not in text,
                        f"{lang}: summary with comparisons and the PSS note ({text!r})")
        plan = tp.Plan([atlas], 120.0, None, None, 3, [(7, 1)])
        costs = Costs(None, None, True, "pseudosquares_count")
        text = tpt.summary_text(plan._replace(seconds=None), costs, T, duration)
        na = T("target_planner.not_available")
        passed &= check(T("target_planner.compare", atlas=na, pss=na) in text
                        and T("target_planner.stored", count=3) in text
                        and T("target_planner.unplanned", count=1) in text
                        and T("target_planner.atlas_estimated") in text
                        and T("target_planner.pss_from_count") in text
                        and T("target_planner.pss_writes_nothing") not in text,
                        f"{lang}: n/a comparisons, stored, unplanned and flags ({text!r})")
        empty = tp.Plan([], 0, 0.0, 0.0, 2, [])
        text = tpt.summary_text(empty, Costs(None, None, False, None), T, duration)
        passed &= check(T("target_planner.all_stored") in text,
                        f"{lang}: everything stored ({text!r})")
        passed &= check(len(T("target_planner.howto")) > 200,
                        f"{lang}: the how-to text is there")
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
