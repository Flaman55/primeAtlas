"""
test_constellation_auto_retry.py -- tests for the floor-25-scale fix, spread across
primeatlas/generation.py (read_constellation_checkpoint, build_constellation_finder_
argv's own max_windows) and primeatlas/generation_tab.py (GenerationTab._maybe_auto_
retry_constellation, _maybe_continue_constellation_batch, _scan_const_chunk_for_batch_
marker). Pure-logic batching of constellation_finder_v1.process_floor() itself
(max_windows/remaining-count/BATCH DONE marker) is covered separately, in
test_constellation_finder_engine.py -- this file is specifically the GUI-side wiring
around it.

Background (Artur's field reports, 2026-09-13): running constellation_finder_v1.py
against floor 25 (545,000 source windows) makes the WSL wrapper process die silently
partway through a run -- no Python traceback, no exit code written (see
WslLoggedRunner's own docstring for this exact failure shape: "Proces wsl.exe
zakonczyl sie bez zapisania kodu wyjscia"), confirmed on a SECOND run to die with
literally zero progress each time. Two complementary fixes:

  1. REACTIVE: since constellation_finder_v1.py's own process_floor() writes
     CHECKPOINT.txt after every successfully processed window, a bare relaunch of the
     identical command resumes right where a crash left off -- GenerationTab does this
     automatically (bounded by a retry cap and a real-progress check against the
     floor's own checkpoint) instead of requiring Artur to notice and re-click Run by
     hand every time.
  2. PROACTIVE (Artur's own follow-up: "sprawdź czy faktycznie jest porcjowana ilość
     danych do przetwarzania... skrypt pośredni w pythonie który zarządza co trafia do
     wsl by ten nie dźwigał całości"): every specific-floor run is capped to
     CONSTELLATION_BATCH_SIZE windows per WSL invocation from the start, with
     GenerationTab automatically chaining a fresh WSL process for the next slice on a
     clean exit, so no single process ever has to carry the whole floor.

Never drives a REAL WSL process or a real long-running constellation_finder_v1.py --
_start_constellation_runner is monkeypatched out in every test that exercises the
retry/batching decision logic, same "test the synchronous decision logic directly,
never the real background/subprocess path" convention as test_cudasieve_integration.py
and test_primecount_settings_integration.py.

Usage (Windows, real display):
    python unitTests\\test_constellation_auto_retry.py
"""
import os
import shutil
import sys
import tempfile
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _patch_app_settings(app_settings):
    app_settings.save = lambda: None


def _pump(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def _write_checkpoint(portal, base_exponent, filename):
    folder = os.path.join(portal, f"10p{base_exponent}", "constellations")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "CHECKPOINT.txt"), "w", encoding="utf-8") as f:
        f.write(f"last_processed_file={filename}\n")


def _test_read_constellation_checkpoint():
    from primeatlas.generation import read_constellation_checkpoint

    tmp = tempfile.mkdtemp(prefix="primeatlas_const_checkpoint_test_")
    try:
        check(read_constellation_checkpoint(tmp, 25) is None,
              "no checkpoint file yet -> None")
        _write_checkpoint(tmp, 25, "PRIME_WINDOW_10p25_off_123.bin")
        check(read_constellation_checkpoint(tmp, 25) == "PRIME_WINDOW_10p25_off_123.bin",
              "reads back the last_processed_file value just written")
        check(read_constellation_checkpoint(tmp, 26) is None,
              "a different floor with no checkpoint of its own -> None")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _build_app(tmp_portal):
    sys.argv = ["prime_atlas_v1.py"]
    import prime_atlas_v1
    _patch_app_settings(prime_atlas_v1.APP_SETTINGS)
    app_cls = prime_atlas_v1._build_gui()
    app = app_cls()
    app.update()
    settings_tab = app.settings_tab
    _patch_app_settings(settings_tab.app_settings)
    settings_tab.app_settings.set_storage_path(tmp_portal)
    settings_tab.wsl["set_portal_folder"](tmp_portal)
    app.update()
    return app


def _test_auto_retry_gives_up_with_zero_progress():
    """A relaunch that made literally no progress (checkpoint unchanged) must NOT be
    retried again -- this is the "poisoned first window" case, a permanent failure
    that would otherwise spin identically forever."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_const_retry_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget

        launched = []
        tab._start_constellation_runner = lambda base_exponent: launched.append(base_exponent)

        tab._const_base_exponent_var.set("25")
        tab._on_run_constellation()
        check(launched == ["25"], f"Run launches the floor typed in the field (got {launched!r})")
        check(tab._const_auto_retry_base_exponent == "25",
              "auto-retry state records the floor this run is for")

        # The run "died" (returncode None) having made no progress at all -- no
        # checkpoint file exists before or after.
        retried = tab._maybe_auto_retry_constellation(None)
        check(retried is False, "no progress at all -> does not schedule a retry")
        check(tab._const_auto_retry_base_exponent is None,
              "gives up cleanly -- auto-retry state cleared so a later unrelated exit can't misfire")
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_auto_retry_relaunches_on_real_progress():
    """A relaunch that DID make forward progress (checkpoint advanced) is exactly the
    floor-25 scenario this fix targets: schedule a relaunch of the identical command."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_const_retry_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget

        launched = []
        tab._start_constellation_runner = lambda base_exponent: launched.append(base_exponent)

        tab._const_base_exponent_var.set("25")
        tab._on_run_constellation()
        launched.clear()

        # Simulate process_floor() having advanced the checkpoint before dying.
        _write_checkpoint(tmp, 25, "PRIME_WINDOW_10p25_off_999.bin")

        import primeatlas.generation_tab as generation_tab_module
        original_delay = generation_tab_module.CONSTELLATION_AUTO_RETRY_DELAY_MS
        generation_tab_module.CONSTELLATION_AUTO_RETRY_DELAY_MS = 20
        try:
            retried = tab._maybe_auto_retry_constellation(None)
            check(retried is True, "real forward progress -> schedules a retry")
            check(tab._const_auto_retry_count == 1, "retry counter incremented")
            _pump(app, 0.3)
            check(launched == ["25"],
                  f"the scheduled relaunch actually calls _start_constellation_runner "
                  f"with the same floor (got {launched!r})")
        finally:
            generation_tab_module.CONSTELLATION_AUTO_RETRY_DELAY_MS = original_delay
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_auto_retry_resets_on_success():
    """A run that finishes with a real exit code (0 or otherwise) is not a crash --
    the retry counter must reset so a LATER, unrelated run starts fresh."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_const_retry_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        tab._start_constellation_runner = lambda base_exponent: None

        tab._const_auto_retry_count = 5
        retried = tab._maybe_auto_retry_constellation(0)
        check(retried is False, "a clean exit (returncode 0) is never retried")
        check(tab._const_auto_retry_count == 0, "retry counter resets on a real exit code")
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_auto_retry_stops_at_cap():
    """Even with real forward progress every time, retries stop at
    MAX_CONSTELLATION_AUTO_RETRIES rather than continuing forever."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_const_retry_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        tab._start_constellation_runner = lambda base_exponent: None

        import primeatlas.generation_tab as generation_tab_module
        original_cap = generation_tab_module.MAX_CONSTELLATION_AUTO_RETRIES
        original_delay = generation_tab_module.CONSTELLATION_AUTO_RETRY_DELAY_MS
        generation_tab_module.MAX_CONSTELLATION_AUTO_RETRIES = 3
        generation_tab_module.CONSTELLATION_AUTO_RETRY_DELAY_MS = 3_600_000  # never actually fires in this test
        try:
            tab._const_base_exponent_var.set("25")
            tab._on_run_constellation()

            for i in range(1, 4):
                _write_checkpoint(tmp, 25, f"PRIME_WINDOW_10p25_off_{i}.bin")
                retried = tab._maybe_auto_retry_constellation(None)
                check(retried is True, f"retry {i}/3 is scheduled (real progress each time)")

            _write_checkpoint(tmp, 25, "PRIME_WINDOW_10p25_off_4.bin")
            retried = tab._maybe_auto_retry_constellation(None)
            check(retried is False, "a 4th retry is refused once the cap (3) is reached")
            check(tab._const_auto_retry_base_exponent is None,
                  "auto-retry state cleared once the cap is hit")
        finally:
            generation_tab_module.MAX_CONSTELLATION_AUTO_RETRIES = original_cap
            generation_tab_module.CONSTELLATION_AUTO_RETRY_DELAY_MS = original_delay
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_stop_disables_auto_retry():
    """An explicit Stop click must never be followed by an auto-relaunch."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_const_retry_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        launched = []
        tab._start_constellation_runner = lambda base_exponent: launched.append(base_exponent)

        tab._const_base_exponent_var.set("25")
        tab._on_run_constellation()
        launched.clear()

        # Fake a runner object so _on_stop_constellation has something to call .stop() on.
        class _FakeRunner:
            def stop(self):
                pass
        tab._const_runner = _FakeRunner()

        _write_checkpoint(tmp, 25, "PRIME_WINDOW_10p25_off_1.bin")
        tab._on_stop_constellation()
        retried = tab._maybe_auto_retry_constellation(None)
        check(retried is False, "no auto-retry after an explicit Stop, even with real progress on disk")
        check(launched == [], "no relaunch was ever scheduled after Stop")
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_build_constellation_finder_argv_max_windows():
    from primeatlas.generation import build_constellation_finder_argv

    argv_plain = build_constellation_finder_argv("25")
    check("--max-windows" not in argv_plain,
          f"max_windows=None (the default) omits the flag entirely (got {argv_plain!r})")

    argv_capped = build_constellation_finder_argv("25", max_windows=5000)
    check(argv_capped[-2:] == ["--max-windows", "5000"],
          f"max_windows=5000 appends '--max-windows 5000' at the end (got {argv_capped!r})")

    argv_all_floors = build_constellation_finder_argv(None, max_windows=5000)
    check("25" not in argv_all_floors and argv_all_floors[-2:] == ["--max-windows", "5000"],
          f"base_exponent=None still omits the positional floor arg while keeping "
          f"max_windows (got {argv_all_floors!r})")


def _test_start_constellation_runner_caps_batch_and_snapshots_checkpoint():
    """Exercises the REAL _start_constellation_runner (not monkeypatched, unlike every
    other test in this file) -- only WslLoggedRunner itself is faked, so this proves
    the actual command built for a specific-floor run really does carry
    --max-windows=CONSTELLATION_BATCH_SIZE, and that the checkpoint snapshot used by
    _maybe_auto_retry_constellation()'s progress guard is read fresh from disk right
    before launching."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_const_retry_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget

        _write_checkpoint(tmp, 25, "PRIME_WINDOW_10p25_off_777.bin")

        import primeatlas.generation_tab as generation_tab_module
        recorded_cmds = []

        class _FakeRunner:
            def __init__(self, cmd, *_a, **_k):
                recorded_cmds.append(cmd)

            def start(self):
                pass

            def is_running(self):
                return False

        original_runner_cls = generation_tab_module.WslLoggedRunner
        generation_tab_module.WslLoggedRunner = _FakeRunner
        try:
            tab._const_base_exponent_var.set("25")
            tab._on_run_constellation()
        finally:
            generation_tab_module.WslLoggedRunner = original_runner_cls

        check(len(recorded_cmds) == 1, "exactly one WslLoggedRunner was constructed")
        cmd_str = " ".join(recorded_cmds[0])
        check(f"--max-windows {generation_tab_module.CONSTELLATION_BATCH_SIZE}" in cmd_str,
              f"a specific-floor run's command carries --max-windows "
              f"{generation_tab_module.CONSTELLATION_BATCH_SIZE} (got {cmd_str!r})")
        check(tab._const_last_checkpoint_seen == "PRIME_WINDOW_10p25_off_777.bin",
              f"the checkpoint snapshot is read fresh from disk right before launching "
              f"(got {tab._const_last_checkpoint_seen!r})")
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_scan_const_chunk_for_batch_marker():
    tmp = tempfile.mkdtemp(prefix="primeatlas_const_retry_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget

        check(tab._const_batch_remaining is None, "starts at None (no run has finished yet)")
        tab._scan_const_chunk_for_batch_marker("some unrelated log text\n")
        check(tab._const_batch_remaining is None, "unrelated text leaves it untouched")
        tab._scan_const_chunk_for_batch_marker(
            "[CONSTELLATIONS v1] BATCH DONE -- 12345 window(s) still remain for 10^25.\n")
        check(tab._const_batch_remaining == 12345,
              f"the BATCH DONE marker's own count is parsed out "
              f"(got {tab._const_batch_remaining!r})")
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_maybe_continue_constellation_batch():
    tmp = tempfile.mkdtemp(prefix="primeatlas_const_retry_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        launched = []
        tab._start_constellation_runner = lambda base_exponent: launched.append(base_exponent)

        # No marker seen this run, clean exit -> nothing to continue.
        tab._const_auto_retry_base_exponent = "25"
        tab._const_batch_remaining = None
        check(tab._maybe_continue_constellation_batch(0) is False,
              "returncode 0 with no BATCH DONE marker seen -> nothing to chain")
        check(launched == [], "no relaunch when there was nothing to continue")

        # Marker seen, but the run itself crashed (returncode None) -- the RETRY path
        # owns that case, not batch-continuation.
        tab._const_batch_remaining = 500
        check(tab._maybe_continue_constellation_batch(None) is False,
              "a crashed run's own leftover marker is not acted on here (retry's job)")
        check(launched == [], "no relaunch from the crash case either")
        check(tab._const_batch_remaining is None,
              "the marker is consumed (reset) even when not acted on, so it can't leak "
              "into a later, unrelated call")

        # The real case: clean exit, marker says windows remain.
        tab._const_batch_remaining = 500
        continued = tab._maybe_continue_constellation_batch(0)
        check(continued is True, "clean exit + remaining windows -> chains the next batch")
        check(launched == ["25"], f"the SAME floor is relaunched (got {launched!r})")

        # No floor on record (e.g. an 'every floor with data' run) -> never chains.
        tab._const_auto_retry_base_exponent = None
        tab._const_batch_remaining = 500
        launched.clear()
        check(tab._maybe_continue_constellation_batch(0) is False,
              "no specific floor on record -> batch-continuation never engages")
        check(launched == [], "no relaunch without a specific floor")
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_full_batch_chain_through_real_queue():
    """End-to-end: pushes raw text chunks (including a BATCH DONE marker) onto the
    REAL constellation output queue and drives the REAL _poll_constellation_output
    polling loop, proving the chunk_hook wiring in _drain_output_queue actually
    connects _scan_const_chunk_for_batch_marker to _maybe_continue_constellation_batch
    the way a genuine WslLoggedRunner run would, not just via direct method calls."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_const_retry_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        launched = []
        tab._start_constellation_runner = lambda base_exponent: launched.append(base_exponent)

        tab._const_auto_retry_base_exponent = "25"
        tab._poll_constellation_output()  # starts the self.after(150, ...) polling chain

        tab._const_output_queue.put(
            "[CONSTELLATIONS v1] BATCH DONE -- 42 window(s) still remain for 10^25.\n")
        tab._const_output_queue.put(("__exit__", 0))
        _pump(app, 0.6)

        check(launched == ["25"],
              f"a BATCH DONE marker followed by a clean exit, delivered through the "
              f"real queue/polling machinery, triggers exactly one chained relaunch "
              f"(got {launched!r})")
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    _test_read_constellation_checkpoint()
    _test_auto_retry_gives_up_with_zero_progress()
    _test_auto_retry_relaunches_on_real_progress()
    _test_auto_retry_resets_on_success()
    _test_auto_retry_stops_at_cap()
    _test_stop_disables_auto_retry()
    _test_build_constellation_finder_argv_max_windows()
    _test_start_constellation_runner_caps_batch_and_snapshots_checkpoint()
    _test_scan_const_chunk_for_batch_marker()
    _test_maybe_continue_constellation_batch()
    _test_full_batch_chain_through_real_queue()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"FAIL: {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
