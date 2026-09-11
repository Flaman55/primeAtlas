"""
app_restart.py -- relaunches the running PrimeAtlas process in place.

Context (Artur, 2026-09-02): changing the language or theme in Settings only writes the
new choice to AppSettings (see app_settings.py's `language`/`theme` docstrings) -- neither
rebuilds the already-constructed widgets, since a live relabel/retheme of every widget in
all 5 tabs would be a much larger and riskier change than just restarting. Previously this
meant the user had to manually close and reopen PrimeAtlas for the change to take effect
(settings_tab.py just showed a "restart required" note). This module makes that automatic:
after saving the change, settings_tab.py calls restart_app() itself instead of just telling
the user to do it by hand.

Uses os.execv() (replace this process image in place), NOT subprocess.Popen(...) +
sys.exit() -- execv means there is exactly one PrimeAtlas process at any instant (the old
one's PID becomes the new one's PID), matching what the .bat/.vbs launchers and the user's
own mental model expect ("PrimeAtlas restarted", not "a second PrimeAtlas briefly existed
alongside the first"). This does mean no Python-level cleanup code runs afterward (no
`finally` blocks, no `atexit` handlers) -- acceptable here since AppSettings.save() and
every other persistence call in this app writes synchronously and immediately, not batched
for a graceful-shutdown flush.

_build_execv_args() is split out from restart_app() itself purely so it's unit-testable:
os.execv() genuinely replaces the calling process, so calling it for real inside a test
would kill the test runner. Tests exercise _build_execv_args()'s argument construction
directly and separately confirm restart_app() calls os.execv with exactly those arguments,
via monkeypatching os.execv rather than actually invoking it -- same "thin wrapper around
the one real syscall" split as env_setup.py's _run_windows()/_run_elevated_ps1().

Pure Python, no tkinter dependency -- exercised directly by unit tests
(unitTests/test_app_restart.py), same "backend has zero UI dependency" split as every
other primeatlas/ module.
"""
import os
import sys


def _build_execv_args():
    """Returns (python_executable, argv_list) for relaunching this same script with no
    extra arguments -- prime_atlas_v1.py currently takes no CLI flags at all (confirmed:
    no argparse, no sys.argv use anywhere in that file), so there is nothing from the
    CURRENT invocation that needs to be forwarded. os.path.abspath() on sys.argv[0] makes
    this robust to whatever relative/absolute form the original launch used (the .bat
    launcher `cd /d`s into the script's own directory first, but this doesn't rely on
    that -- it computes an absolute path itself regardless of the current working
    directory at restart time).

    Confirmed bug (Artur, 2026-09-11): on Windows, os.execv() builds the new process's
    command line by naively space-joining argv -- unlike subprocess.Popen, it does NOT
    quote elements containing spaces. Any checkout path with a space in it (e.g. this
    OneDrive clone's "...\\AI Agent Ollama\\..." ancestor) then gets split at that space
    by the relaunched process, which fails to find itself and exits immediately -- since
    this already replaced the original process, the user just sees PrimeAtlas close
    without reopening, with no visible error (it's a GUI app). Wrapping any argv element
    that contains a space in double quotes (Windows' own quoting convention, which
    CommandLineToArgvW -- and therefore the relaunched Python's own argv parsing --
    strips back off) fixes it. The `python` value returned alongside argv is passed to
    os.execv() as the file to execute, resolved directly rather than parsed out of the
    joined command line, so it's returned unquoted."""
    python = sys.executable
    script = os.path.abspath(sys.argv[0])
    if os.name == "nt":
        argv = [f'"{a}"' if " " in a else a for a in (python, script)]
    else:
        argv = [python, script]
    return python, argv


def restart_app():
    """Replaces the current process with a fresh PrimeAtlas launch. Never returns (either
    the process image is replaced, or -- on the rare platform/permission failure where
    os.execv itself raises -- the exception propagates to the caller, which is expected to
    be running inside a GUI callback and will surface it the same way any other uncaught
    exception there would)."""
    python, argv = _build_execv_args()
    os.execv(python, argv)
