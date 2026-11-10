"""
test_verify_plan.py -- primeatlas/generation/verify_plan.py: the Generation tab's Section D
fields turned into pt1_verify_store.py's arguments. The window count comes from a fake P
store (empty files are enough: only names are read); off-grid windows, D files, other floors
and a missing floor never count; the Windows field maps the total and more to "all"; the
Threads field resolves Auto, Max and numbers and refuses everything else.

Usage:
    python unitTests/test_verify_plan.py
"""
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

import storage_kinds  # noqa: E402
from primeatlas.generation import verify_plan  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _touch(portal, floor, offset, window_m, label, kind):
    path = storage_kinds.window_path(portal, floor, offset, window_m, label, kind)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()


def _test_parse_int():
    check(verify_plan.parse_int(" 29 ", 0) == 29, "parse_int trims spaces")
    check(verify_plan.parse_int("0", 0) == 0, "parse_int: 0 allowed with minimum 0")
    for text in ("", None, "x", "-1", "2.5", "1e3"):
        check(verify_plan.parse_int(text, 0) is None, f"parse_int refuses {text!r}")
    check(verify_plan.parse_int("0", 1) is None, "parse_int: 0 refused with minimum 1")


def _test_window_count():
    portal = tempfile.mkdtemp(prefix="primeatlas_verify_plan_test_")
    try:
        m7 = 10 ** 7
        for off in (0, m7, 2 * m7):
            _touch(portal, 29, off, m7, "0" if off == 0 else f"{off // 1_000_000}M",
                   storage_kinds.KIND_P)
        _touch(portal, 29, 5_000_000, m7, "5M", storage_kinds.KIND_P)   # off the 10^7 grid
        _touch(portal, 29, 3 * m7, m7, "30M", storage_kinds.KIND_D)     # D: never counted
        _touch(portal, 30, 0, m7, "0", storage_kinds.KIND_P)            # another floor
        check(verify_plan.window_count(portal, 29, 7) == 3,
              "width 10^7: the three P windows on the grid, not the off-grid one or D")
        check(verify_plan.window_count(portal, 29, 6) == 4,
              "width 10^6: every P window is on the grid")
        check(verify_plan.window_count(portal, 29, 8) == 1, "width 10^8: only offset 0")
        check(verify_plan.window_count(portal, 30, 7) == 1, "floor 30 counts its own window")
        check(verify_plan.window_count(portal, 31, 7) == 0, "a floor without a folder: 0")
        check(verify_plan.window_count(portal, None, 7) == 0, "no floor: 0")
        check(verify_plan.window_count(portal, 29, None) == 0, "no width: 0")
        check(verify_plan.window_count("", 29, 7) == 0, "no storage folder: 0")
        offsets = [o for o, _p in storage_kinds.p_windows_on_grid(portal, 29, m7)]
        check(offsets == [0, m7, 2 * m7], f"p_windows_on_grid ascending ({offsets})")
    finally:
        shutil.rmtree(portal, ignore_errors=True)


def _test_max_windows_arg():
    check(verify_plan.max_windows_arg("3", 3) == 0, "the total -> 0 (all)")
    check(verify_plan.max_windows_arg("500", 3) == 0, "more than the total -> 0 (all)")
    check(verify_plan.max_windows_arg("2", 3) == 2, "fewer -> the first 2")
    check(verify_plan.max_windows_arg(" 1 ", 3) == 1, "one window")
    for text in ("0", "", "x", "-2"):
        check(verify_plan.max_windows_arg(text, 3) is None, f"Windows refuses {text!r}")


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
    choices = verify_plan.THREAD_CHOICES
    check(choices[:3] == ["Auto", "Max", "1"] and choices[-1] == "256",
          f"the spinbox steps Auto, Max, 1..256 ({choices[:3]}..{choices[-1]})")


def main():
    _test_parse_int()
    _test_window_count()
    _test_max_windows_arg()
    _test_resolve_threads()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
