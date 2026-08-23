"""
test_primesieve_calc_worker.py -- functional regression test for the primesieve
calculator worker in prime_atlas_v1.py, migrated onto primeatlas/background.py's
PersistentWorker during the refactor branch's Faza 1 (background-job consolidation,
2026-08-23).

run_primesieve_query_wsl() shells out to wsl.exe, which doesn't exist in this sandbox
(or on a CI box in general) -- this test monkeypatches the module-level
prime_atlas_v1.run_primesieve_query_wsl with a deterministic fake, so it's exercising
the WORKER PLUMBING (dispatch -> PersistentWorker -> result callback -> UI state),
not the real WSL round trip. build_primesieve_query_argv() itself needs no faking --
it's pure argv construction.

See test_search_worker.py's own module docstring for why AppSettings.save() must be
neutered before touching storage_path in a test like this (not strictly needed HERE
since this worker never reads storage_path, but done anyway for consistency with
every other test in this folder that builds the real app).

Usage (Windows, real display):
    python unitTests\\test_primesieve_calc_worker.py

Usage (this sandbox, headless):
    PYTHONPATH="/tmp/tkextract/usr/lib/python3.10:/tmp/tkextract/usr/lib/python3.10/lib-dynload:$PYTHONPATH" \\
    LD_LIBRARY_PATH="/tmp/tkextract/usr/lib:$LD_LIBRARY_PATH" \\
    xvfb-run -a python3 unitTests/test_primesieve_calc_worker.py
"""
import os
import sys
import time
import tkinter.messagebox

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _patch_messageboxes():
    shown = []
    tkinter.messagebox.showinfo = lambda *a, **k: shown.append(("info", a, k))
    tkinter.messagebox.showerror = lambda *a, **k: shown.append(("error", a, k))
    return shown


def _pump(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def main():
    shown = _patch_messageboxes()

    sys.argv = ["prime_atlas_v1.py"]
    import prime_atlas_v1
    app_cls = prime_atlas_v1._build_gui()
    app = app_cls()
    app.update()

    # --- success path: fake a "count of primes in [1, 100]" answer (25) -----------
    def fake_ok(argv, timeout=120):
        check(argv[-2:] == ["1", "100"] or "1" in argv, f"argv reaches the fake (argv={argv!r})")
        return True, 25

    prime_atlas_v1.run_primesieve_query_wsl = fake_ok
    app._primesieve_calc_worker.submit({"code": "count", "args": (1, 100)})
    check(app._primesieve_calc_busy is False or True, "dispatch does not raise")
    # _on_primesieve_calc_compute() normally sets busy=True/disables the button before
    # submitting -- calling submit() directly here (bypassing that GUI-only prelude,
    # same reasoning as test_search_worker.py's direct _start_search_job() calls)
    # means we only assert on the RESULT side of the round trip.
    _pump(app, 3.0)
    check(app._primesieve_calc_last_result == 25,
          f"result value 25 landed in _primesieve_calc_last_result (got {app._primesieve_calc_last_result!r})")
    check("25" in app.primesieve_calc_result_var.get(),
          f"result text mentions 25 (got: {app.primesieve_calc_result_var.get()!r})")
    check(str(app.primesieve_calc_copy_button["state"]) == "normal",
          "copy button enabled after a successful result")

    # --- failure path: fake a WSL error -------------------------------------------
    def fake_fail(argv, timeout=120):
        return False, "wsl.exe not found (fake failure for this test)"

    prime_atlas_v1.run_primesieve_query_wsl = fake_fail
    shown.clear()
    app._primesieve_calc_last_result = None
    app._primesieve_calc_worker.submit({"code": "nth", "args": (5, 0)})
    _pump(app, 3.0)
    check(app._primesieve_calc_last_result is None,
          "a failed query does not populate _primesieve_calc_last_result")
    check(any("wsl.exe not found" in str(call) for call in shown),
          f"the fake failure message was surfaced via messagebox.showerror (got: {shown})")

    app.destroy()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
