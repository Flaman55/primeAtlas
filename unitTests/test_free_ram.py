"""
test_free_ram.py -- the free RAM every RAM budget of Atlas is a share of
(primeatlas/generation/wsl_resources.py).

A. free_ram_for_run(wsl_available, windows_free): the lower of WSL's MemAvailable and the
   RAM free in Windows, so a WSL limit above what Windows has left never sizes a run; an
   unreadable Windows value leaves the WSL value alone; an unreadable or non-positive WSL
   value gives None (the sieve runs in WSL: no reading, no guess), whatever Windows says.
B. estimate_free_ram_bytes() reads both probes once and combines them like A; the WSL probe
   gets the timeout.
C. Every reader of the free RAM uses estimate_free_ram_bytes: the time simulation and the
   engine proposal, the Quick-gen Auto buttons and Settings -> Restore.
D. The texts that name the free RAM say it is the lower of WSL's and Windows' (en and pl).

Usage:
    python unitTests/test_free_ram.py
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "constellation"))

failures = []
GIB = 1024 ** 3


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_combine():
    print("\n--- A. free_ram_for_run ---")
    from primeatlas.generation.wsl_resources import free_ram_for_run
    for wsl, win, want, what in (
            (47 * GIB, 10 * GIB, 10 * GIB, "Windows has less free than WSL sees: Windows"),
            (10 * GIB, 47 * GIB, 10 * GIB, "WSL has less available than Windows: WSL"),
            (20 * GIB, 20 * GIB, 20 * GIB, "equal values: that value"),
            (47 * GIB, 1024 ** 2, 1024 ** 2, "Windows nearly full: 1 MiB, never skipped"),
            (47 * GIB, None, 47 * GIB, "Windows unreadable: WSL alone"),
            (None, 10 * GIB, None, "WSL unreadable: None, Windows alone never sizes a run"),
            (0, 10 * GIB, None, "WSL 0: None"),
            (-5, 10 * GIB, None, "WSL negative: None"),
            (None, None, None, "both unreadable: None")):
        got = free_ram_for_run(wsl, win)
        check(got == want, f"{what} ({wsl}, {win}) -> {want} (got {got})")


def _test_estimate():
    print("\n--- B. estimate_free_ram_bytes ---")
    from primeatlas.core import windows_hardware
    from primeatlas.generation import wsl_resources
    saved = (wsl_resources.estimate_wsl_available_ram_bytes, windows_hardware.windows_ram)
    calls = []
    try:
        wsl_resources.estimate_wsl_available_ram_bytes = (
            lambda timeout=10: calls.append(timeout) or 47 * GIB)
        windows_hardware.windows_ram = lambda: (64 * GIB, 12 * GIB)
        got = wsl_resources.estimate_free_ram_bytes(timeout=7)
        check(got == 12 * GIB, f"WSL 47 GiB, Windows 12 GiB free -> 12 GiB (got {got})")
        check(calls == [7], f"the WSL probe runs once with the timeout ({calls})")
        windows_hardware.windows_ram = lambda: (None, None)
        got = wsl_resources.estimate_free_ram_bytes()
        check(got == 47 * GIB, f"Windows unreadable -> the WSL value (got {got})")
        wsl_resources.estimate_wsl_available_ram_bytes = lambda timeout=10: None
        windows_hardware.windows_ram = lambda: (64 * GIB, 12 * GIB)
        got = wsl_resources.estimate_free_ram_bytes()
        check(got is None, f"WSL unreadable -> None (got {got})")
    finally:
        wsl_resources.estimate_wsl_available_ram_bytes, windows_hardware.windows_ram = saved


def _test_readers():
    print("\n--- C. readers use estimate_free_ram_bytes ---")
    from primeatlas.generation import quick_gen_panel, time_simulation_controls, wsl_resources
    from primeatlas.app import settings_wiring
    for module in (time_simulation_controls, quick_gen_panel):
        check(getattr(module, "estimate_free_ram_bytes", None)
              is wsl_resources.estimate_free_ram_bytes,
              f"{module.__name__} reads estimate_free_ram_bytes")
        check(not hasattr(module, "estimate_wsl_available_ram_bytes"),
              f"{module.__name__} no longer reads the WSL value alone")
    with open(settings_wiring.__file__, encoding="utf-8") as f:
        source = f.read()
    check('"estimate_free_ram_bytes": estimate_free_ram_bytes' in source
          and "estimate_wsl_available_ram_bytes" not in source,
          "Settings -> Restore gets estimate_free_ram_bytes")
    restore = os.path.join(_REPO_ROOT, "primeatlas", "settings", "restore_section.py")
    with open(restore, encoding="utf-8") as f:
        source = f.read()
    check('self.wsl["estimate_free_ram_bytes"]()' in source
          and "estimate_wsl_available_ram_bytes" not in source,
          "restore_section sizes its runs by estimate_free_ram_bytes")


def _test_texts():
    print("\n--- D. texts name both sides ---")
    from primeatlas.core.i18n import Translator
    keys = ("gen.field_ram_budget_pct", "gen.info_ram_budget_pct", "gen.confirm_ram_over_budget",
            "quick.auto_ram_result", "quick.auto_ram_result_v5", "timesim.ram_value",
            "timesim.info_ram")
    for lang in ("en", "pl"):
        T = Translator(lang)
        for key in keys:
            text = T(key)
            check("Windows" in text and "WSL" in text, f"[{lang}] {key} names WSL and Windows")


def main():
    _test_combine()
    _test_estimate()
    _test_readers()
    _test_texts()


if __name__ == "__main__":
    main()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  FAIL: {f}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
