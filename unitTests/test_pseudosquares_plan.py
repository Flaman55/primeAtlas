"""
test_pseudosquares_plan.py -- Quick-gen Pseudosquares mode turns From / Floor / Width /
Threads into one native run, never touching the storage.

A. From given: its floor, the window holding it (From rounded down to the 10^7 grid), Width
   windows; a range crossing the floor's end stops there (clamped flag); floor 32's end is
   10^33; floor 33 runs up to the program's own stop (MAX_STOP, ~1.73 * 10^33), a From
   past it or in floor 34 refused; From below 1 refused.
B. From blank: the Floor's start (no storage lookup -- a native run writes nothing there);
   no Floor either refused; Floor 33 starts at 10^33, a Floor past 33 refused.
C. Low floors: floor 3 is one run of [1000, 10000), whatever the Width.
D. Width below 1 or not a number refused; Threads: blank / Auto / 0 = the program's own
   choice, a positive integer as given, anything else refused.

Usage:
    python unitTests/test_pseudosquares_plan.py
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

import pseudosquares_const as const  # noqa: E402
from primeatlas.generation import pseudosquares_plan as plan_mod  # noqa: E402

failures = []
W = 10_000_000


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def plan(start, floor=None, width=1):
    return plan_mod.plan(start, floor, width, W)


def part_a():
    p = plan(10 ** 25 + 3 * W + 5, width=2)
    check(p == {"floor": 25, "target_idx_start": 3, "count": 2, "lo": 10 ** 25 + 3 * W,
                "hi": 10 ** 25 + 5 * W, "clamped": False},
          "From inside a window: that window, Width windows")
    p = plan(10 ** 26 - W, width=5)
    check(p["hi"] == 10 ** 26 and p["clamped"] and p["count"] == 1,
          "range past the floor's end: stops at the end, clamped, windows counted")
    p = plan(10 ** 33 - 1, width=1)
    check(p["floor"] == 32 and p["hi"] == 10 ** 33 and p["lo"] == 10 ** 33 - W,
          "floor 32: last window ends at 10^33")
    p = plan(10 ** 33, width=1)
    check((p["floor"], p["lo"], p["hi"]) == (33, 10 ** 33, 10 ** 33 + W),
          "From = 10^33: floor 33, one window")
    p = plan(const.MAX_STOP, width=3)
    check(p["floor"] == 33 and p["hi"] == const.MAX_STOP + 1 and p["clamped"]
          and p["count"] == 1, "From = the stop: its window, clamped at the stop")
    check(plan(const.MAX_STOP + 1)["error"] == "beyond_ceiling",
          "From one past the stop (still floor 33) refused")
    check(plan(10 ** 34)["error"] == "beyond_ceiling", "From = 10^34 (floor 34) refused")
    check(plan(10 ** 40)["error"] == "beyond_ceiling", "From far past the stop refused")
    check(plan(0)["error"] == "range_negative", "From 0 refused")
    check(plan(-5)["error"] == "range_negative", "negative From refused")


def part_b():
    p = plan(None, floor=28, width=3)
    check((p["floor"], p["target_idx_start"], p["count"], p["lo"]) == (28, 0, 3, 10 ** 28),
          "blank From: the Floor's start")
    check(plan(None, floor=None)["error"] == "from_required", "blank From and Floor refused")
    p = plan(None, floor=33, width=2)
    check((p["floor"], p["lo"], p["count"]) == (33, 10 ** 33, 2), "blank From, Floor 33: its start")
    check(plan(None, floor=34)["error"] == "beyond_ceiling", "Floor 34 refused")
    check(plan(None, floor=-1)["error"] == "from_required", "negative Floor refused")


def part_c():
    p = plan(None, floor=3, width=40)
    check((p["lo"], p["hi"], p["count"]) == (1000, 10_000, 1),
          "floor 3: one run of the whole floor")
    p = plan(4321, width=7)
    check((p["lo"], p["hi"], p["floor"]) == (1000, 10_000, 3),
          "From inside a low floor: the whole floor")


def part_d():
    check(plan(10 ** 20, width=0)["error"] == "width_invalid", "Width 0 refused")
    check(plan(10 ** 20, width=None)["error"] == "width_invalid", "Width not a number refused")
    for text in ("", "Auto", "auto", " AUTO ", "0"):
        check(plan_mod.parse_threads(text) == 0, f"threads {text!r} -> 0 (program's choice)")
    check(plan_mod.parse_threads("8") == 8, "threads 8 -> 8")
    for text in ("-1", "2.5", "many"):
        check(plan_mod.parse_threads(text) is None, f"threads {text!r} refused")


def main():
    part_a()
    part_b()
    part_c()
    part_d()
    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
