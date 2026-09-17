"""
test_constellation_auto_retry.py -- tests for the floor-25-scale fix, spread across
primeatlas/generation/generation.py (read_constellation_checkpoint, build_constellation_finder_
argv's own max_windows) and primeatlas/generation/generation_tab.py (GenerationTab._maybe_auto_
retry_constellation, _maybe_continue_constellation_batch, _scan_const_chunk_for_batch_
marker). Pure-logic batching of constellation_finder_v1.process_floor() itself
(max_windows/remaining-count/BATCH DONE marker) is covered separately, in
test_constellation_finder_engine.py -- this file is specifically the GUI-side wiring
around it.

Background: running constellation_finder_v1.py against floor 25 (545,000 source
windows) makes the WSL wrapper process die silently partway through a run -- no
Python traceback, no exit code written (see WslLoggedRunner's own docstring for
this exact failure shape), confirmed on a SECOND run to die with literally zero
progress each time. Two complementary fixes:

  1. REACTIVE: since constellation_finder_v1.py's own process_floor() writes
     CHECKPOINT.txt after every successfully processed window, a bare relaunch of the
     identical command resumes right where a crash left off -- GenerationTab does this
     automatically (bounded by a retry cap and a real-progress check against the
     floor's own checkpoint) instead of requiring a manual re-click of Run every time.
  2. PROACTIVE: every specific-floor run is capped to CONSTELLATION_BATCH_SIZE windows
     per WSL invocation from the start, with GenerationTab automatically chaining a
     fresh WSL process for the next slice on a clean exit, so no single process ever
     has to carry the whole floor.

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
    from primeatlas.generation.generation import read_constellation_checkpoint

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

        import primeatlas.generation.generation_tab as generation_tab_module
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

        import primeatlas.generation.generation_tab as generation_tab_module
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


def _test_graceful_stop_writes_sentinel_and_cleans_up():
    """Stop click's FIRST action must be the graceful sentinel file, not an immediate
    kill -- see _on_stop_constellation()'s own docstring for why:
    append_prime_window()'s header-before-payload write order means an immediate
    terminate()+pkill can corrupt a hit file, not just lose progress. The sentinel
    must disappear again once the run's
    own exit sentinel arrives -- via _on_constellation_finished(), win or lose -- so it
    can never block the NEXT launch, and the grace-period fallback timer must be
    cancelled on that same clean exit so it can never fire against a LATER, unrelated
    run."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_const_retry_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        tab._start_constellation_runner = lambda base_exponent: None

        import primeatlas.generation.generation_tab as generation_tab_module
        stop_path = os.path.join(tmp, generation_tab_module.CONSTELLATION_STOP_REQUEST_FILENAME)

        tab._const_base_exponent_var.set("25")
        tab._on_run_constellation()

        class _FakeRunner:
            def __init__(self):
                self.stopped = False

            def stop(self):
                self.stopped = True

            def is_running(self):
                return True
        fake = _FakeRunner()
        tab._const_runner = fake

        tab._on_stop_constellation()
        check(os.path.exists(stop_path),
              "Stop click writes the graceful-stop sentinel file")
        check(fake.stopped is False,
              "the hard kill is NOT called immediately -- graceful stop gets a chance first")
        check(tab._const_stop_grace_after_id is not None,
              "a grace-period fallback timer is scheduled")

        # Simulate the run exiting cleanly in response to the sentinel, well before the
        # grace period would have elapsed.
        tab._on_constellation_finished(0)
        check(not os.path.exists(stop_path),
              "the sentinel is removed once the run's own exit sentinel arrives")
        check(tab._const_stop_grace_after_id is None,
              "the pending grace-period timer is cancelled on a clean exit -- must "
              "never fire against a LATER, unrelated run")
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_graceful_stop_falls_back_to_hard_kill_after_grace_period():
    """If the process is still running once the grace period elapses (stuck somewhere
    that never reaches process_floor()'s own loop-top stop check -- e.g. the WSL/DrvFs
    degradation the whole floor-25 fix exists to work around), the ORIGINAL hard
    terminate()+pkill must still fire: this feature must never turn Stop into a button
    that can silently do nothing forever."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_const_retry_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        tab._start_constellation_runner = lambda base_exponent: None

        tab._const_base_exponent_var.set("25")
        tab._on_run_constellation()

        class _FakeRunner:
            def __init__(self):
                self.stopped = False

            def stop(self):
                self.stopped = True

            def is_running(self):
                return True
        fake = _FakeRunner()
        tab._const_runner = fake

        tab._on_stop_constellation()
        check(fake.stopped is False, "hard kill not called yet, right after the Stop click")

        # Directly invoke the grace-period callback (same as self.after() firing) rather
        # than actually sleeping CONSTELLATION_STOP_GRACE_MS in this test.
        tab._force_stop_constellation_if_still_running()
        check(fake.stopped is True,
              "still running once the grace period elapses -> falls back to the hard kill")
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_floor_progress_scales_bar_to_whole_floor():
    """_GEN_CONST_FLOOR_PROGRESS_RE's own line (see generation.py) must make the shared
    bar/status track the WHOLE floor, not just the current --max-windows batch -- see
    _update_shared_progress_from_generation_chunk()'s own handling of it. Without this,
    the bar/status snaps back to near-zero at every chained batch boundary."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_const_retry_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        bar = tab.totals_progress
        tab._gen_progress_bar_active = True

        import primeatlas.generation.generation_tab as generation_tab_module

        tab._update_shared_progress_from_generation_chunk(
            "[CONSTELLATIONS v2] FLOOR PROGRESS: batch_size=5000 total_windows=545000 "
            "already_done_before_batch=340000\n")
        check(tab._const_floor_total_windows == 545000, "floor total recorded")
        check(tab._const_floor_already_done == 340000,
              "already-done-before-this-batch recorded")

        tab._update_shared_progress_from_generation_chunk(
            "[CONSTELLATIONS v2] 1234/5000: PRIME_WINDOW_whatever.bin -- primes=1 "
            "peeked_head=0 new_hits=0 (0.01s)\n")
        check(int(bar["maximum"]) == 545000,
              f"bar maximum is the WHOLE floor, not this batch's own 5000 "
              f"(got {bar['maximum']!r})")
        check(int(bar["value"]) == 340000 + 1234,
              f"bar value is already-done-before-this-batch + this batch's own progress "
              f"(got {bar['value']!r})")
        expected_batch_count = -(-545000 // generation_tab_module.CONSTELLATION_BATCH_SIZE)
        expected_batch_num = 340000 // generation_tab_module.CONSTELLATION_BATCH_SIZE + 1
        check(tab.status.get() == tab.T(
                  "gen.status_progress_const_batch", done=340000 + 1234, total=545000,
                  batch_num=expected_batch_num, batch_count=expected_batch_count),
              f"status text shows floor-wide done/total plus batch X/Y "
              f"(got {tab.status.get()!r})")
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_floor_progress_resets_between_launches():
    """A fresh _start_constellation_runner() call must clear the floor-progress state --
    a stale total/already-done count from a PREVIOUS floor must never leak into a new
    run's own bar/status before that new run prints its own FLOOR PROGRESS line."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_const_retry_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        tab._const_floor_total_windows = 999
        tab._const_floor_already_done = 111

        import primeatlas.generation.generation_tab as generation_tab_module

        class _FakeRunner:
            def __init__(self, *a, **k):
                pass

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
        check(tab._const_floor_total_windows is None,
              "a fresh launch clears the previous floor's total")
        check(tab._const_floor_already_done is None,
              "a fresh launch clears the previous floor's already-done count")
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_elapsed_and_eta_in_status():
    """Elapsed time (since the session's own Run click) and ETA (windows-remaining /
    wall-clock rate since the floor total was last anchored) both show up in the shared
    status text. Drives a fake clock (replacing the `time` name generation_tab.py
    itself sees, not the real stdlib module) so the test is fully deterministic instead
    of racing a real 10/30s sleep."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_const_retry_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        tab._start_constellation_runner = lambda base_exponent: None

        import primeatlas.generation.generation_tab as generation_tab_module

        class _FakeClock:
            def __init__(self, start):
                self.now = start

            def time(self):
                return self.now
        fake_clock = _FakeClock(1_000_000.0)
        original_time_module = generation_tab_module.time
        generation_tab_module.time = fake_clock
        try:
            tab._const_base_exponent_var.set("25")
            tab._on_run_constellation()  # anchors _const_session_start_time = now

            tab._update_shared_progress_from_generation_chunk(
                "[CONSTELLATIONS v2] FLOOR PROGRESS: batch_size=5000 total_windows=10000 "
                "already_done_before_batch=0\n")

            # Too few windows processed so far this session (CONSTELLATION_ETA_MIN_
            # WINDOWS=3) -> elapsed is shown, but no ETA yet.
            fake_clock.now += 10.0
            tab._update_shared_progress_from_generation_chunk(
                "[CONSTELLATIONS v2] 2/5000: PRIME_WINDOW_a.bin -- primes=1 "
                "peeked_head=0 new_hits=0 (0.01s)\n")
            status = tab.status.get()
            check("ETA" not in status,
                  f"fewer than CONSTELLATION_ETA_MIN_WINDOWS processed -> no ETA yet "
                  f"(got {status!r})")
            check("10s" in status,
                  f"elapsed time IS shown even before ETA becomes available "
                  f"(got {status!r})")

            # Now enough windows have been processed (5 >= 3) -> ETA appears, computed
            # from the wall-clock rate since the baseline (5 windows / 30s elapsed).
            fake_clock.now += 20.0
            tab._update_shared_progress_from_generation_chunk(
                "[CONSTELLATIONS v2] 5/5000: PRIME_WINDOW_b.bin -- primes=1 "
                "peeked_head=0 new_hits=0 (0.01s)\n")
            status = tab.status.get()
            check("ETA" in status, f"enough windows processed -> ETA now shown (got {status!r})")
            # remaining=10000-5=9995, rate=5/30 windows/s -> eta=9995*30/5=59970s=16h39m
            check("16h39m" in status,
                  f"ETA reflects the wall-clock rate since the baseline "
                  f"(got {status!r})")
        finally:
            generation_tab_module.time = original_time_module
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_eta_baseline_resets_on_new_run_not_on_chained_batch():
    """A fresh Run click must reset BOTH the elapsed clock and the ETA baseline (a
    brand-new session has no history to average over); a CHAINED batch continuation for
    the SAME floor must reset NEITHER (the whole point of measuring the rate on the
    GUI's own wall clock is to average over the real cost of the whole floor scan,
    batch-relaunch overhead included -- see CONSTELLATION_ETA_MIN_WINDOWS's own
    module-level comment)."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_const_retry_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        launched = []
        tab._start_constellation_runner = lambda base_exponent: launched.append(base_exponent)

        tab._const_base_exponent_var.set("25")
        tab._on_run_constellation()
        session_start_1 = tab._const_session_start_time
        check(session_start_1 is not None, "a fresh Run click anchors the session clock")

        tab._update_shared_progress_from_generation_chunk(
            "[CONSTELLATIONS v2] FLOOR PROGRESS: batch_size=5000 total_windows=10000 "
            "already_done_before_batch=0\n")
        baseline_time_1 = tab._const_eta_baseline_time
        check(baseline_time_1 is not None, "the first FLOOR PROGRESS line anchors the ETA baseline")

        # Chained batch continuation for the SAME floor (same total_windows) -- the
        # session clock and the ETA baseline must both survive untouched.
        tab._const_auto_retry_base_exponent = "25"
        tab._const_batch_remaining = 5000
        continued = tab._maybe_continue_constellation_batch(0)
        check(continued is True, "batch continuation is launched (sanity check on the test setup)")
        check(tab._const_session_start_time == session_start_1,
              "a chained batch continuation must NOT reset the session's elapsed clock")
        tab._update_shared_progress_from_generation_chunk(
            "[CONSTELLATIONS v2] FLOOR PROGRESS: batch_size=5000 total_windows=10000 "
            "already_done_before_batch=5000\n")
        check(tab._const_eta_baseline_time == baseline_time_1,
              "an UNCHANGED floor total (same floor, next chained batch) must NOT "
              "reset the ETA baseline -- the rate keeps averaging over the whole scan")

        # A genuinely fresh Run click (e.g. a different floor, or the same one restarted
        # by hand) resets both.
        tab._const_base_exponent_var.set("26")
        tab._on_run_constellation()
        check(tab._const_session_start_time != session_start_1,
              "a fresh Run click DOES reset the session's elapsed clock")
        check(tab._const_eta_baseline_time is None,
              "a fresh Run click clears the ETA baseline too, pending this new "
              "session's own first FLOOR PROGRESS line")
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_build_constellation_finder_argv_max_windows():
    from primeatlas.generation.generation import build_constellation_finder_argv

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

        import primeatlas.generation.generation_tab as generation_tab_module
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
            "[CONSTELLATIONS v2] BATCH DONE -- 12345 window(s) still remain for 10^25.\n")
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
            "[CONSTELLATIONS v2] BATCH DONE -- 42 window(s) still remain for 10^25.\n")
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
    _test_graceful_stop_writes_sentinel_and_cleans_up()
    _test_graceful_stop_falls_back_to_hard_kill_after_grace_period()
    _test_floor_progress_scales_bar_to_whole_floor()
    _test_floor_progress_resets_between_launches()
    _test_elapsed_and_eta_in_status()
    _test_eta_baseline_resets_on_new_run_not_on_chained_batch()
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
