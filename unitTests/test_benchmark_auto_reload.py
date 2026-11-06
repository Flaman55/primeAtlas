"""
test_benchmark_auto_reload.py -- a finished generation run rereads the Benchmark tab's log, so
its new row shows without pressing Refresh (isolated app, no WSL).

Checks: GenerationTab's run-finished handler calls the Benchmark tab's reload once, and a
real row appended to the portal's benchmark_log.csv before it is in the tab's rows after it.

Usage (Windows, real display):
    python unitTests/test_benchmark_auto_reload.py
"""
import csv
import os
import sys
import tkinter.messagebox

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, _SCRIPT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def main():
    tkinter.messagebox.showinfo = lambda *a, **k: None
    tkinter.messagebox.showerror = lambda *a, **k: None
    from app_sandbox import isolate_app
    from benchmark_log_schema import BENCHMARK_FIELDNAMES
    prime_atlas_v2, _portal = isolate_app()
    app = prime_atlas_v2._build_gui()()
    app.update()
    try:
        gen, bench = app.generation_tab_widget, app.benchmark_tab_widget
        portal = gen._get_portal_folder()
        os.makedirs(portal, exist_ok=True)
        log = os.path.join(portal, "benchmark_log.csv")
        is_new = not os.path.exists(log)
        with open(log, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES)
            if is_new:
                writer.writeheader()
            writer.writerow({name: "" for name in BENCHMARK_FIELDNAMES}
                            | {"engine": "v4.1", "base_exponent": "19", "threads": "24",
                               "run_timestamp_utc": "2026-11-05 12:24:15 UTC"})
        before = len(bench._benchmark_rows)
        calls = []
        original = bench.reload_benchmark_log
        bench.reload_benchmark_log = lambda: (calls.append(1), original())
        gen._on_loop_finished(0)
        app.update()
        check(calls == [1], "run finished: Benchmark log reread once")
        check(len(bench._benchmark_rows) == before + 1, "the new row is in the tab")
    finally:
        app.destroy()
    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
