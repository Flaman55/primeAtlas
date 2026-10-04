"""
test_entry_point_shim.py -- covers prime_atlas_v1.py, the compatibility entry point that
runs prime_atlas_v2.py. Installed shortcuts and app_restart.py's relaunch (sys.argv[0])
name prime_atlas_v1.py, so it must keep starting the current application.

  A. Running prime_atlas_v1.py executes prime_atlas_v2.py as __main__ (runpy.run_path is
     monkeypatched, so no GUI starts).
  B. prime_atlas_v1.py holds no application code of its own.

Usage:
    python unitTests/test_entry_point_shim.py
"""
import os
import runpy
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
_SHIM = os.path.join(_REPO_ROOT, "prime_atlas_v1.py")
_TARGET = os.path.join(_REPO_ROOT, "prime_atlas_v2.py")

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def section_a():
    print("\n--- Section A: running the shim runs prime_atlas_v2.py ---")
    check(os.path.isfile(_TARGET), "prime_atlas_v2.py exists next to prime_atlas_v1.py")
    calls = []
    real_run_path = runpy.run_path

    def fake_run_path(path, init_globals=None, run_name=None):
        calls.append((path, run_name))
        return {}

    runpy.run_path = fake_run_path
    try:
        real_run_path(_SHIM, run_name="__main__")
    finally:
        runpy.run_path = real_run_path
    check(len(calls) == 1, f"the shim calls runpy.run_path exactly once (got {len(calls)})")
    if calls:
        path, run_name = calls[0]
        check(os.path.normcase(os.path.abspath(path)) == os.path.normcase(_TARGET),
              f"the shim runs prime_atlas_v2.py from its own directory (got {path!r})")
        check(run_name == "__main__", f"prime_atlas_v2.py runs as __main__ (got {run_name!r})")


def section_b():
    print("\n--- Section B: the shim holds no application code ---")
    src = open(_SHIM, encoding="utf-8").read()
    code_lines = [l for l in src.splitlines() if l.strip() and not l.strip().startswith("#")]
    check(len(code_lines) <= 12, f"prime_atlas_v1.py stays a few lines long (got {len(code_lines)})")
    check("tkinter" not in src and "primeatlas" not in src.replace("prime_atlas_v2", ""),
          "prime_atlas_v1.py imports neither tkinter nor the primeatlas package")


if __name__ == "__main__":
    section_a()
    section_b()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All checks passed.")
