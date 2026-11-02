"""
test_close_guard_wiring.py -- the close guard wired into the real app (CLOSE_GUARD_PLAN.md):
closing the window with no job closes it at once; with a job it asks (stage shown, default
No) and No keeps everything; Yes on a pt1 run takes the save point, closes the app once
the run settled and saves the console log; a stopped row bumps the floor totals; every
Generation launch path clears a leftover stop request and writes the active-run marker; Stop
on an orchestrator run writes the stop request and kills only the scanner (no hard stop),
a second Stop hard stops; Stop on an engine without the orchestrator hard stops at once;
the run's end deletes marker and stop request and shows the stopped status; the main
window has a WM_DELETE_WINDOW handler; an unwritable stop request is a hard stop;
stop_job_for_close cancels the follow-up search; recover_previous_run settles a marker and
reports it in the Generation console, and keeps it while the process is still alive.

Drives the real app (tkinter, temp portal folder) with the WSL side stubbed: the runner
records instead of starting, kill_wsl_processes / wsl_process_alive are fakes.
Windows, real display:
    python unitTests/test_close_guard_wiring.py
"""
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))

failures = []


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    if not value:
        failures.append(message)


class _Runner:
    def __init__(self, cmd, log_path, exit_path, output_queue, kill_pattern=None):
        self.output_queue = output_queue
        self.kill_pattern = kill_pattern
        self.running = False
        self.hard_stopped = False
        self.tail_lines = []

    def start(self):
        self.running = True

    def is_running(self):
        return self.running

    def is_finished(self):
        return not self.running

    def stop(self):
        self.hard_stopped = True


def close_window(app):
    """What the window manager does when the user closes the main window."""
    app.tk.call(app.protocol("WM_DELETE_WINDOW"))


def finish(gen, app, rc=0):
    gen._loop_runner.running = False
    gen._loop_output_queue.put(("__exit__", rc))
    pump(app)


def append_benchmark_row(portal, row):
    import csv
    import orchestrator_v3
    path = os.path.join(portal, "benchmark_log.csv")
    is_new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=orchestrator_v3.BENCHMARK_FIELDNAMES)
        if is_new:
            w.writeheader()
        w.writerow(row)


def pump(app, seconds=0.6):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def main():
    import prime_atlas_v2
    import generation_stop
    from primeatlas.benchmark.benchmark import read_benchmark_log
    from primeatlas.generation import generation_tab, run_guard
    from tkinter import messagebox

    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    generation_tab.WslLoggedRunner = _Runner
    kills = []
    run_guard.kill_wsl_processes = lambda pattern: kills.append(pattern) or True

    portal = tempfile.mkdtemp(prefix="primeatlas_close_guard_wiring_")
    app = None
    try:
        sys.argv = ["prime_atlas_v2.py"]
        from app_sandbox import isolate_app
        isolate_app(portal)
        app = prime_atlas_v2._build_gui()()
        app.update()
        gen = app.generation_tab_widget

        check(bool(app.protocol("WM_DELETE_WINDOW")), "main window has a close handler")

        # criterion 1: close with no job -> the window closes, no dialog
        asked, destroyed = [], []
        messagebox.askyesno = lambda *a, **k: asked.append(a) or False
        real_destroy = app.destroy
        app.destroy = lambda: destroyed.append(1)
        try:
            close_window(app)
        finally:
            app.destroy = real_destroy
        check(destroyed == [1] and asked == [],
              f"close with no job: window closes, no dialog (destroy {destroyed}, asked {len(asked)})")

        # criterion 2: close with a job -> dialog with its stage, No keeps everything
        logs = os.path.join(portal, ".generation_logs")
        os.makedirs(logs, exist_ok=True)
        gen._start_loop_runner(["wsl.exe"], os.path.join(logs, "n.log"),
                               os.path.join(logs, "n.exit"), "orchestrator_v3.py", 20,
                               engine="pt1", window_m=10_000_000)
        gen._loop_runner.tail_lines = ["[+] Progress: 42.10% (421/1000 chunks) | time: 3s"]
        seen = []
        messagebox.askyesno = lambda *a, **k: seen.append((a, k)) or False
        kills.clear()
        close_window(app)
        message = seen[0][0][1] if seen and len(seen[0][0]) > 1 else ""
        check(len(seen) == 1 and "42.10%" in message,
              f"close with a running job asks, with its stage ({message!r})")
        check(seen and seen[0][1].get("default") == "no", "the dialog defaults to No")
        check(app.winfo_exists() and gen._loop_runner.is_running()
              and not gen._loop_runner.hard_stopped and kills == []
              and not generation_stop.stop_requested(portal),
              "No keeps the app open and the job running")
        finish(gen, app)

        # launch: leftover stop request cleared, marker written
        run_guard.write_stop_request(portal)
        logs = os.path.join(portal, ".generation_logs")
        os.makedirs(logs, exist_ok=True)
        gen._start_loop_runner(["wsl.exe"], os.path.join(logs, "a.log"),
                               os.path.join(logs, "a.exit"), "orchestrator_v3.py", 25,
                               engine="pt1", first_target_idx=3, window_m=10_000_000)
        check(not generation_stop.stop_requested(portal), "launch clears a leftover stop request")
        marker = run_guard.read_active_run(portal)
        check(marker is not None and marker["engine"] == "pt1"
              and marker["scanner_pattern"] == "prime_sieve_pt1.py"
              and marker["base_exponent"] == 25 and marker["first_target_idx"] == 3,
              f"launch writes the active-run marker ({marker})")

        # Stop: save point, then hard stop on the second press
        runner = gen._loop_runner
        gen._on_stop_loop()
        check(generation_stop.stop_requested(portal), "Stop writes the stop request")
        check(kills == ["prime_sieve_pt1.py"], f"Stop kills only the scanner ({kills})")
        check(not runner.hard_stopped, "first Stop is not a hard stop")
        check(gen.loop_status_label.get() == gen.T("gen.loop_stopping_save_point"),
              "status says the written windows are kept")
        gen._on_stop_loop()
        check(runner.hard_stopped, "second Stop hard stops")

        # run end: marker + stop request deleted, stopped status
        runner.running = False
        gen._loop_output_queue.put(("__exit__", 0))
        pump(app)
        check(run_guard.read_active_run(portal) is None, "run end deletes the marker")
        check(not generation_stop.stop_requested(portal), "run end deletes the stop request")
        check(gen.loop_status_label.get() == gen.T("gen.loop_stopped_save_point"),
              f"stopped status shown ({gen.loop_status_label.get()!r})")
        check(gen.job_settled("generation"), "finished run is settled")

        # engine without the orchestrator: hard stop at once
        kills.clear()
        gen._start_loop_runner(["wsl.exe"], os.path.join(logs, "b.log"),
                               os.path.join(logs, "b.exit"), "hybrid_sieve.py", 20)
        runner = gen._loop_runner
        gen._on_stop_loop()
        check(runner.hard_stopped and kills == [] and not generation_stop.stop_requested(portal),
              "Stop on a hybrid run hard stops at once")
        runner.running = False
        gen._loop_output_queue.put(("__exit__", 1))
        pump(app)

        # criterion 4: the stopped row of a save-point stop bumps the floor totals
        from primeatlas.core import storage
        gen._start_loop_runner(["wsl.exe"], os.path.join(logs, "t.log"),
                               os.path.join(logs, "t.exit"), "orchestrator_v3.py", 20,
                               engine="pt1", window_m=10_000_000)
        gen._on_stop_loop()
        append_benchmark_row(portal, {"base_exponent": 20, "windows_written": 2,
                                      "total_primes": 777, "bytes_written": 300,
                                      "write_files": "1", "engine": "pt1",
                                      "total_seconds": 5.0, "run_status": "stopped"})
        finish(gen, app)
        entry = storage.load_totals_cache(portal).get("10p20", {})
        check(entry.get("total") == 777 and entry.get("file_count") == 2,
              f"stopped row bumps the floor totals ({entry.get('total')}, "
              f"{entry.get('file_count')} files)")

        # storage folder unreachable when writing the stop request: hard stop
        gen._start_loop_runner(["wsl.exe"], os.path.join(logs, "u.log"),
                               os.path.join(logs, "u.exit"), "orchestrator_v3.py", 20,
                               engine="pt1", window_m=10_000_000)
        real_write = run_guard.write_stop_request
        run_guard.write_stop_request = lambda folder: False
        kills.clear()
        try:
            gen._on_stop_loop()
        finally:
            run_guard.write_stop_request = real_write
        check(gen._loop_runner.hard_stopped and kills == [],
              "stop request not writable -> hard stop at once")
        finish(gen, app, 1)

        # criterion 8: every Generation launch path deletes a leftover stop request and
        # writes the marker
        launches = (
            ("orchestrator direct", lambda: gen._on_run_orchestrator_direct(20, 0, 2)),
            ("loop", gen._on_run_loop),
            ("primesieve", lambda: gen._on_run_primesieve(20, 0, 2)),
            ("cudasieve", lambda: gen._on_run_cudasieve(20, 0, 2)),
            ("hybrid", lambda: gen._on_run_hybrid(20, 1, 1, 1000)),
            ("hybrid narrow", lambda: gen._on_run_hybrid_narrow(
                10 ** 20, 10 ** 20 + 10_000_000, 10 ** 20, 1000)),
        )
        for name, launch in launches:
            run_guard.write_stop_request(portal)
            run_guard.clear_active_run(portal)
            previous = gen._loop_runner
            try:
                launch()
                pump(app, 0.2)
            except Exception as exc:  # noqa: BLE001 -- reported as a failed check
                check(False, f"{name} launch raised {exc!r}")
                continue
            started = gen._loop_runner is not None and gen._loop_runner is not previous
            check(started, f"{name}: a run is launched")
            check(not generation_stop.stop_requested(portal),
                  f"{name}: launch deletes a leftover stop request")
            check(run_guard.read_active_run(portal) is not None,
                  f"{name}: launch writes the active-run marker")
            if started:
                finish(gen, app)

        # close stop cancels the follow-up search
        gen._pending_search_after_prime_gen = {"kind": "prime", "base_exponent": 20, "number": 1}
        gen.stop_job_for_close("ktuple")
        check(gen._pending_search_after_prime_gen is None, "stop_job_for_close cancels follow-ups")

        # recovery on start
        run_guard.wsl_process_alive = lambda pattern: False
        rows_before = len(read_benchmark_log(portal)[1])
        run_guard.write_active_run(portal, {"base_exponent": 20, "engine": "v5",
                                            "kill_pattern": "orchestrator_v3.py",
                                            "rows_before": rows_before, "first_target_idx": 0,
                                            "window_m": 10_000_000, "started_at": time.time()})
        before = gen.loop_console.get_text()
        done = []
        gen.recover_previous_run(on_done=lambda: done.append(1))
        pump(app, 2.0)
        added = gen.loop_console.get_text()[len(before):]
        check(run_guard.read_active_run(portal) is None, "recovery deletes the marker")
        check("10^20" in added, f"recovery is reported in the console ({added.strip()!r})")
        check(done == [1], "recovery calls on_done after changing the totals")

        # criterion 9: a process still alive keeps the marker and says so
        run_guard.wsl_process_alive = lambda pattern: True
        run_guard.write_active_run(portal, {"base_exponent": 20, "engine": "v5",
                                            "kill_pattern": "orchestrator_v3.py",
                                            "rows_before": 0, "first_target_idx": 0,
                                            "window_m": 10_000_000, "started_at": time.time()})
        before = gen.loop_console.get_text()
        gen.recover_previous_run(on_done=lambda: None)
        pump(app, 2.0)
        added = gen.loop_console.get_text()[len(before):]
        check(run_guard.read_active_run(portal) is not None, "live process: marker kept")
        check("orchestrator_v3.py" in added, f"live process: message shown ({added.strip()!r})")
        run_guard.clear_active_run(portal)

        # criterion 4: Yes -> save point of the pt1 run, the app closes once it settled,
        # console log saved
        gen._start_loop_runner(["wsl.exe"], os.path.join(logs, "y.log"),
                               os.path.join(logs, "y.exit"), "orchestrator_v3.py", 20,
                               engine="pt1", window_m=10_000_000)
        gen._loop_runner.tail_lines = ["[+] Progress: 10.00% (1/10 chunks) | time: 1s"]
        gen.loop_console.append("console of the stopped run\n")
        messagebox.askyesno = lambda *a, **k: True
        kills.clear()
        close_window(app)
        check(generation_stop.stop_requested(portal) and kills == ["prime_sieve_pt1.py"]
              and not gen._loop_runner.hard_stopped,
              f"Yes takes the save point: stop request + scanner kill only ({kills})")
        check(app.winfo_exists(), "app stays open while the run is stopping")
        finish(gen, app)
        pump(app, 1.0)
        try:
            closed = not app.winfo_exists()
        except Exception:  # noqa: BLE001 -- a destroyed Tk raises on every call
            closed = True
        check(closed, "app closes after the stopped run settled")
        saved = [n for n in os.listdir(logs) if n.startswith("closed_generation_")]
        text = ""
        if saved:
            with open(os.path.join(logs, saved[0]), encoding="utf-8") as f:
                text = f.read()
        check("console of the stopped run" in text,
              f"console log file written ({saved})")
        if closed:
            app = None
    finally:
        if app is not None:
            try:
                app.destroy()
            except Exception:  # noqa: BLE001 -- already destroyed by a failed close check
                pass
        shutil.rmtree(portal, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
