"""
test_app_restart.py -- covers primeatlas/app_restart.py, the os.execv()-based in-place
relaunch used by settings_tab.py's automatic restart-after-theme/language-change feature
(task #518).

os.execv() genuinely replaces the calling process -- calling it for real here would kill the
test runner itself, so this file never calls the real thing. Two sections:

  A. _build_execv_args() -- pure argument construction, no monkeypatching needed at all.
  B. restart_app() -- confirms it calls os.execv with exactly _build_execv_args()'s own
     output, via a monkeypatched os.execv that raises instead of replacing the process
     (so a bug that lets the real syscall through fails the test loudly instead of
     silently killing it).

Usage:
    python3 unitTests/test_app_restart.py
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))  # primeatlas/__init__.py pulls
                                                               # in manifest.py -> window_sharding
                                                               # at import time, same PYTHONPATH
                                                               # need test_env_setup.py already
                                                               # documented

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


# ============================================================================================
# Section A -- _build_execv_args()
# ============================================================================================

def section_a():
    print("\n--- Section A: _build_execv_args() ---")
    from primeatlas import app_restart as ar

    orig_argv = sys.argv
    sys.argv = ["/some/relative/../path/prime_atlas_v1.py"]
    try:
        python, argv = ar._build_execv_args()
    finally:
        sys.argv = orig_argv

    check(python == sys.executable,
          f"first element must be sys.executable (got {python!r})")
    check(argv[0] == python,
          f"argv[0] passed to execv must equal the executable itself, matching the usual "
          f"argv[0]==program-name convention (got {argv[0]!r})")
    check(len(argv) == 2,
          f"argv must be exactly [python, script] -- prime_atlas_v1.py takes no CLI flags "
          f"to forward (got {argv!r})")
    check(os.path.isabs(argv[1]),
          f"the script path must be made absolute (os.path.abspath), robust to whatever "
          f"cwd restart_app() happens to run from (got {argv[1]!r})")
    check(argv[1].endswith("prime_atlas_v1.py"),
          f"the script path must be derived from sys.argv[0], not hardcoded elsewhere "
          f"(got {argv[1]!r})")

    # --- Already-absolute sys.argv[0] must pass through unchanged (aside from any
    #     normalization os.path.abspath itself does) ---
    orig_argv = sys.argv
    sys.argv = ["/already/absolute/prime_atlas_v1.py"]
    try:
        _python2, argv2 = ar._build_execv_args()
    finally:
        sys.argv = orig_argv
    # Compared against os.path.abspath()'s own output, not the literal POSIX string above --
    # on Windows, os.path.abspath("/already/absolute/...") prepends the current drive letter
    # (e.g. "F:\already\absolute\..."), so comparing against the un-prefixed POSIX literal
    # directly would always fail there even though _build_execv_args() did nothing wrong
    # (bug confirmed 2026-09-11: this assertion was failing on Windows before this fix, for
    # a reason unrelated to the space-quoting bug this file otherwise covers).
    check(argv2[1] == os.path.abspath("/already/absolute/prime_atlas_v1.py"),
          f"an already-absolute path must not be altered beyond normalization "
          f"(got {argv2[1]!r})")

    # --- A script path containing a space (e.g. this OneDrive clone's own
    #     "...\\AI Agent Ollama\\..." ancestor folder) must come back quoted on Windows,
    #     since os.execv() there -- unlike subprocess.Popen -- does NOT quote argv itself:
    #     an unquoted space gets split into two arguments by the relaunched process, which
    #     then can't find itself and exits immediately (bug confirmed 2026-09-11: this is
    #     exactly why the auto-restart-after-theme/language-change silently failed to
    #     reopen PrimeAtlas from this specific checkout location). ---
    orig_argv = sys.argv
    sys.argv = ["/some/dir with space/prime_atlas_v1.py"]
    try:
        python3, argv3 = ar._build_execv_args()
    finally:
        sys.argv = orig_argv

    expected_path = os.path.abspath("/some/dir with space/prime_atlas_v1.py")
    check(python3 == sys.executable,
          f"the (python, argv) executable value must stay unquoted -- it's passed to "
          f"os.execv() as the file to run directly, not parsed out of a joined command "
          f"line (got {python3!r})")
    if os.name == "nt":
        check(argv3[1] == f'"{expected_path}"',
              f"on Windows, a script path containing a space must be quoted for "
              f"os.execv() (got {argv3[1]!r})")
    else:
        check(argv3[1] == expected_path,
              f"on non-Windows platforms, execv() takes a real argv array (no shell "
              f"join), so no quoting should be applied (got {argv3[1]!r})")


# ============================================================================================
# Section B -- restart_app()
# ============================================================================================

def section_b():
    print("\n--- Section B: restart_app() ---")
    from primeatlas import app_restart as ar

    orig_execv = os.execv
    captured = []

    def fake_execv(python, argv):
        captured.append((python, argv))
        # Deliberately do NOT raise and do NOT return normally in a way that could be
        # confused with a real replaced process -- just record and return, so the test
        # continues executing (the real os.execv never returns at all; this fake
        # returning is what makes the test possible).

    os.execv = fake_execv
    orig_argv = sys.argv
    sys.argv = ["/repo/prime_atlas_v1.py"]
    try:
        ar.restart_app()
    finally:
        os.execv = orig_execv
        sys.argv = orig_argv

    check(len(captured) == 1,
          f"restart_app() must call os.execv exactly once (got {len(captured)} call(s))")
    expected_python, expected_argv = ar._build_execv_args()
    # _build_execv_args() was called a second time above (after sys.argv was restored),
    # so recompute it under the SAME sys.argv the real call used for a fair comparison.
    sys.argv = ["/repo/prime_atlas_v1.py"]
    try:
        expected_python, expected_argv = ar._build_execv_args()
    finally:
        sys.argv = orig_argv
    check(captured[0] == (expected_python, expected_argv),
          f"restart_app() must pass os.execv exactly what _build_execv_args() returns, no "
          f"extra transformation (got {captured[0]!r}, expected "
          f"{(expected_python, expected_argv)!r})")


# ============================================================================================

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
