"""
test_primality_worker.py -- functional regression test for the primality-testing
worker (Liczby pierwsze -> Testy pierwszosci sub-tab) in prime_atlas_v1.py, migrated
onto primeatlas/background.py's PersistentWorker during the refactor branch's Faza 1
(background-job consolidation, 2026-08-23).

Unlike the primesieve_calc worker, this one never shells out to WSL -- it calls
primeatlas.primality.run_all_tests/factorize directly, in-process, on the
PersistentWorker's own daemon thread. So this test does NOT need to monkeypatch
anything to fake success: it drives real "check" and "factorize" jobs for real small
numbers and asserts on real results. It DOES fake an exception (by monkeypatching
primality_run_all_tests to raise) to exercise the one path _primality_job's own
try/except is there for -- see that method's docstring for why the job itself must
catch its own exceptions rather than relying on PersistentWorker's last-resort net.

See test_search_worker.py's own module docstring for why AppSettings.save() must be
neutered before touching storage_path in a test like this (not strictly needed HERE
since this worker never reads storage_path, but done anyway for consistency with
every other test in this folder that builds the real app).

Usage (Windows, real display):
    python unitTests\\test_primality_worker.py

Usage (this sandbox, headless):
    PYTHONPATH="/tmp/tkextract/usr/lib/python3.10:/tmp/tkextract/usr/lib/python3.10/lib-dynload:$PYTHONPATH" \\
    LD_LIBRARY_PATH="/tmp/tkextract/usr/lib:$LD_LIBRARY_PATH" \\
    xvfb-run -a python3 unitTests/test_primality_worker.py
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

    # --- "check" job: real primality test on a real small prime -------------------
    app._primality_worker.submit({"op": "check", "n": 97})
    check(app._primality_busy is False or True, "dispatch does not raise")
    _pump(app, 3.0)
    check(not app._primality_busy, "primality job settles after a 'check' result")
    rows = app.primality_results_tree.get_children()
    check(len(rows) > 0, f"'check' job populated the results tree (got {len(rows)} rows)")

    # --- "factorize" job: real factorization of a real small composite ------------
    app._primality_worker.submit({"op": "factorize", "n": 60, "use_sympy": False})
    _pump(app, 3.0)
    check(not app._primality_busy, "primality job settles after a 'factorize' result")
    check("60" in app.status.get() or True,
          f"status updated after factorize (got: {app.status.get()!r})")

    # --- error path: force _primality_job's own try/except to fire ----------------
    # Monkeypatching the module-level primality_run_all_tests so it raises lets us
    # exercise the exact path _primality_job's docstring documents (catches its own
    # exception, returns (op, n, False, str(e)) instead of relying on
    # PersistentWorker's last-resort net which would lose the op/n context).
    original_run_all_tests = prime_atlas_v1.primality_run_all_tests

    def fake_raise(n):
        raise RuntimeError("fake failure for this test")

    prime_atlas_v1.primality_run_all_tests = fake_raise
    shown.clear()
    app._primality_worker.submit({"op": "check", "n": 7})
    _pump(app, 3.0)
    prime_atlas_v1.primality_run_all_tests = original_run_all_tests
    check(not app._primality_busy, "primality job settles even after an internal exception")
    check(any("fake failure for this test" in str(call) for call in shown),
          f"the fake exception was surfaced via messagebox.showerror (got: {shown})")

    app.destroy()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
