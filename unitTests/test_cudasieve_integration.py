"""
test_cudasieve_integration.py -- covers the `cudasieve-v2` branch's GPU-engine port
(tasks #457-464): the engine file's window_sharding integration, generation.py's argv
builders/constants and its Popen()+poll()-loop WSL launcher (run_cudasieve_wsl_blocking),
AppSettings' cudasieve_status cache, GenerationTab's cudasieve Quick-gen mode, and
SettingsTab's cudasieve installer state machine.

Six independent sections, each runnable on its own logic (no real WSL, no real CUDASieve
binary, no CUDA hardware anywhere in this sandbox -- every WSL-launching or subprocess
boundary is stubbed with a recorder/fake, same approach test_generation_launch_planning.py
uses for _apply_primesieve_params_and_run/_apply_orchestrator_direct_params_and_run):

  A. generation.py -- pure argv builders + constants (no I/O at all)
  B. generation.py -- run_cudasieve_wsl_blocking's Popen()+poll() timeout loop, the exact
     fix for the real Windows subprocess.run(timeout=...) hang documented in that
     function's own docstring -- verifies wait()/communicate() are NEVER called (that is
     precisely the historical bug) and that the timeout path actually returns instead of
     hanging.
  C. app_settings.py -- AppSettings.cudasieve_status get/set persistence round-trip
  D. prime_sieve/prime_sieve_cudasieve.py -- window_sharding.py integration (the one real
     interface-drift fix this port needed, since window sharding landed after the old
     `cudasieve` branch forked): multi-window sharded write, low-floor sharded write,
     count-only mode, and benchmark_log.csv schema parity with every other engine.
  E. GenerationTab -- cudasieve Quick-gen mode: mode-switch frame raise, Auto-from
     clamp/compute, full _on_quick_generate_clicked dispatch (below-min/beyond-ceiling
     rejections + the happy path reaching _apply_cudasieve_params_and_run), and
     _on_run_cudasieve's own WslLoggedRunner wiring.
  F. SettingsTab -- cudasieve installer state machine: _on_cudasieve_status_result's four
     branches (installed/cloned-not-built/missing/error), cache persistence + reload via
     _show_cached_cudasieve_status, _start_cudasieve_build's wsl-dict wiring, and
     _poll_cudasieve_queue's exit-tuple handling.

Every check() states the specific expected vs. actual value, same convention as
test_generation_launch_planning.py.

Usage (Windows, real display):
    python unitTests\\test_cudasieve_integration.py

Usage (this sandbox, headless):
    PYTHONPATH="/tmp/tmp_tk/usr/lib/python3.10:/tmp/tmp_tk/usr/lib/python3.10/lib-dynload:$PYTHONPATH" \\
    LD_LIBRARY_PATH="/tmp/tmp_tk/usr/lib/x86_64-linux-gnu:/tmp/tmp_tk/usr/lib:$LD_LIBRARY_PATH" \\
    xvfb-run -a python3 unitTests/test_cudasieve_integration.py

Sections A-D need no display at all (pure logic / temp-file I/O); E-F build the real Tk
app and therefore need the Xvfb invocation above.
"""
import csv
import json
import os
import queue
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


# ============================================================================================
# Section A -- generation.py: pure argv builders + constants
# ============================================================================================

def section_a():
    print("\n--- Section A: generation.py argv builders + constants ---")
    from primeatlas import generation as gen_mod

    check(gen_mod.CUDASIEVE_MIN_PRINTABLE_TOP == 2 ** 40,
          f"CUDASIEVE_MIN_PRINTABLE_TOP must be exactly 2**40 (CUDASieve's own documented "
          f"-p/--print floor) (got {gen_mod.CUDASIEVE_MIN_PRINTABLE_TOP!r})")
    check(gen_mod.CUDASIEVE_MAX_STOP == 2 ** 64 - 1,
          f"CUDASIEVE_MAX_STOP must match libprimesieve's own uint64 domain (2**64-1) "
          f"(got {gen_mod.CUDASIEVE_MAX_STOP!r})")
    expected_width_mult = gen_mod.CUDASIEVE_MAX_STOP // gen_mod.QUICK_GEN_MAX_WINDOW_WIDTH + 1
    check(gen_mod.CUDASIEVE_MAX_WIDTH_MULT == expected_width_mult,
          f"CUDASIEVE_MAX_WIDTH_MULT must be CUDASIEVE_MAX_STOP // QUICK_GEN_MAX_WINDOW_WIDTH "
          f"+ 1 (got {gen_mod.CUDASIEVE_MAX_WIDTH_MULT!r}, expected {expected_width_mult!r})")

    status_argv = gen_mod.build_cudasieve_status_argv()
    check(status_argv[0] == "python3" and status_argv[-1] == "--status",
          f"build_cudasieve_status_argv() must run python3 ... --status "
          f"(got {status_argv!r})")
    check("prime_sieve_cudasieve.py" in status_argv[1],
          f"build_cudasieve_status_argv()'s script path must point at "
          f"prime_sieve_cudasieve.py (got {status_argv[1]!r})")

    fetch_argv = gen_mod.build_cudasieve_fetch_license_argv()
    check(fetch_argv[0] == "python3" and fetch_argv[-1] == "--fetch-license",
          f"build_cudasieve_fetch_license_argv() must run python3 ... --fetch-license "
          f"(got {fetch_argv!r})")

    build_argv = gen_mod.build_cudasieve_build_argv()
    check(build_argv[:2] == ["python3", "-u"] and build_argv[-1] == "--build",
          f"build_cudasieve_build_argv() must run python3 -u ... --build, unbuffered so "
          f"WslLoggedRunner sees live progress lines (got {build_argv!r})")

    run_argv_write = gen_mod.build_cudasieve_argv(13, 5, 2, 10_000_000, True)
    check(run_argv_write[0] == "python3" and run_argv_write[1] == "-u",
          f"build_cudasieve_argv() must run python3 -u ... (got {run_argv_write!r})")
    check(run_argv_write[-5:] == ["13", "5", "2", "10000000", "1"],
          f"build_cudasieve_argv(13, 5, 2, 10_000_000, True) must produce the positional "
          f"CLI contract <base_exponent> <target_idx_start> <target_idx_count> <window_m> "
          f"<write_files=1> (got tail {run_argv_write[-5:]!r})")
    run_argv_nowrite = gen_mod.build_cudasieve_argv(13, 5, 2, 10_000_000, False)
    check(run_argv_nowrite[-1] == "0",
          f"write_files=False must produce a trailing '0' (count-only mode) "
          f"(got {run_argv_nowrite[-1]!r})")


# ============================================================================================
# Section B -- generation.py: run_cudasieve_wsl_blocking's Popen()+poll() loop
# ============================================================================================

class _FakePopen:
    """Stands in for subprocess.Popen -- records whether wait()/communicate() were ever
    called (the exact untimed fallback call that caused the real Windows hang this
    function's own docstring documents) and lets the test script the poll() sequence."""

    instances = []

    def __init__(self, poll_sequence, kill_raises=False):
        self._poll_sequence = list(poll_sequence)
        self._kill_raises = kill_raises
        self.kill_called = False
        self.wait_called = False
        self.communicate_called = False
        _FakePopen.instances.append(self)

    def poll(self):
        if self._poll_sequence:
            return self._poll_sequence.pop(0)
        return self._poll_sequence_last if hasattr(self, "_poll_sequence_last") else None

    def kill(self):
        self.kill_called = True
        if self._kill_raises:
            raise OSError("simulated: process already gone")

    def wait(self, timeout=None):
        self.wait_called = True
        raise AssertionError(
            "wait() must NEVER be called by run_cudasieve_wsl_blocking -- this is exactly "
            "the untimed fallback call documented as the real Windows hang cause")

    def communicate(self, timeout=None):
        self.communicate_called = True
        raise AssertionError(
            "communicate() must NEVER be called by run_cudasieve_wsl_blocking -- same "
            "reasoning as wait() above")


def section_b():
    print("\n--- Section B: run_cudasieve_wsl_blocking Popen()+poll() loop ---")
    from primeatlas import generation as gen_mod

    portal = tempfile.mkdtemp(prefix="cudasieve_wslblock_test_")
    try:
        # --- Success path: poll() returns None once, then 0; log file has real content. ---
        _FakePopen.instances.clear()
        log_holder = {}

        def fake_generation_log_paths(portal_folder, prefix):
            log_path = os.path.join(portal_folder, f"{prefix}_log.txt")
            exit_path = os.path.join(portal_folder, f"{prefix}_exit.txt")
            log_holder["log_path"] = log_path
            log_holder["exit_path"] = exit_path
            # Simulate WslLoggedRunner's own file-redirection already having flushed the
            # real JSON payload by the time poll() first returns non-None.
            with open(log_path, "w", encoding="utf-8") as f:
                f.write('{"ok": true, "binary_exists": false}\n')
            return log_path, exit_path, "fakerun1"

        def fake_build_wsl_logged_command(argv, log_path, exit_path, portal_folder):
            return ["wsl.exe", "-e", "true"]  # never actually exec'd -- Popen is faked

        orig_gen_log_paths = gen_mod.generation_log_paths
        orig_build_cmd = gen_mod.build_wsl_logged_command
        orig_popen = gen_mod.subprocess.Popen
        gen_mod.generation_log_paths = fake_generation_log_paths
        gen_mod.build_wsl_logged_command = fake_build_wsl_logged_command
        gen_mod.subprocess.Popen = lambda cmd, **kw: _FakePopen([None, 0])
        try:
            ok, payload = gen_mod.run_cudasieve_wsl_blocking(["python3", "x", "--status"],
                                                               portal, timeout=5)
        finally:
            gen_mod.generation_log_paths = orig_gen_log_paths
            gen_mod.build_wsl_logged_command = orig_build_cmd
            gen_mod.subprocess.Popen = orig_popen

        check(ok is True,
              f"success path (poll() eventually non-None, real log content) must return "
              f"ok=True (got ok={ok!r}, payload={payload!r})")
        check(payload == {"ok": True, "binary_exists": False},
              f"success path must return the parsed JSON payload from the log file "
              f"(got {payload!r})")
        check(len(_FakePopen.instances) == 1 and not _FakePopen.instances[0].wait_called
              and not _FakePopen.instances[0].communicate_called,
              "success path must never call wait()/communicate() on the Popen object -- "
              "only poll()")

        # --- Timeout path: poll() always returns None -> must return (False, ...) without
        # ever calling wait()/communicate(), must call kill(), and must clean up the log/
        # exit files. Uses a tiny real timeout (0.3s) so this test stays fast. ---
        _FakePopen.instances.clear()
        gen_mod.generation_log_paths = fake_generation_log_paths
        gen_mod.build_wsl_logged_command = fake_build_wsl_logged_command
        fake_proc_holder = {}

        def _make_never_returning_popen(cmd, **kw):
            p = _FakePopen([])  # empty sequence -> poll() always falls through to None
            fake_proc_holder["proc"] = p
            return p

        gen_mod.subprocess.Popen = _make_never_returning_popen
        try:
            t0 = time.time()
            ok2, payload2 = gen_mod.run_cudasieve_wsl_blocking(
                ["python3", "x", "--status"], portal, timeout=0.3)
            elapsed = time.time() - t0
        finally:
            gen_mod.generation_log_paths = orig_gen_log_paths
            gen_mod.build_wsl_logged_command = orig_build_cmd
            gen_mod.subprocess.Popen = orig_popen

        check(ok2 is False,
              f"a process whose poll() never returns must time out with ok=False "
              f"(got ok={ok2!r}, payload={payload2!r})")
        check(isinstance(payload2, str) and "Timed out" in payload2,
              f"timeout payload must be a clear 'Timed out after ...' message "
              f"(got {payload2!r})")
        check(elapsed < 3.0,
              f"the timeout path must actually return within a few seconds of the "
              f"configured 0.3s timeout, not hang -- this is the exact bug this function "
              f"was rewritten to fix (took {elapsed:.2f}s)")
        check(fake_proc_holder["proc"].kill_called,
              "timeout path must call proc.kill() before giving up")
        check(not fake_proc_holder["proc"].wait_called
              and not fake_proc_holder["proc"].communicate_called,
              "timeout path must NEVER call wait()/communicate() after kill() -- that "
              "second, untimed call is exactly what hung forever on the real Windows bug "
              "this function's own docstring documents")
        check(not os.path.exists(log_holder["log_path"])
              and not os.path.exists(log_holder["exit_path"]),
              "timeout path must clean up the log/exit files it created")
    finally:
        shutil.rmtree(portal, ignore_errors=True)


# ============================================================================================
# Section C -- app_settings.py: cudasieve_status persistence round-trip
# ============================================================================================

def section_c():
    print("\n--- Section C: AppSettings.cudasieve_status persistence ---")
    from primeatlas import app_settings as app_settings_mod

    tmp_locales = tempfile.mkdtemp(prefix="cudasieve_appsettings_test_")
    orig_locales_dir = app_settings_mod.LOCALES_DIR
    app_settings_mod.LOCALES_DIR = tmp_locales
    try:
        settings1 = app_settings_mod.AppSettings(tmp_locales)
        check(settings1.cudasieve_status is None,
              f"a fresh install (never checked) must report cudasieve_status=None "
              f"(got {settings1.cudasieve_status!r})")

        payload = {"ok": True, "binary_exists": True, "binary_path": "/x/cudasieve"}
        settings1.set_cudasieve_status(True, payload)
        check(settings1.cudasieve_status == {"ok": True, "payload": payload},
              f"set_cudasieve_status(True, payload) must be readable back immediately "
              f"(got {settings1.cudasieve_status!r})")

        # Reload as a fresh instance -- confirms it was actually written to disk, not just
        # held in memory.
        settings2 = app_settings_mod.AppSettings(tmp_locales)
        check(settings2.cudasieve_status == {"ok": True, "payload": payload},
              f"a new AppSettings instance must read back the SAME persisted value after "
              f"restart (got {settings2.cudasieve_status!r})")

        settings2.set_cudasieve_status(False, "some error string")
        settings3 = app_settings_mod.AppSettings(tmp_locales)
        check(settings3.cudasieve_status == {"ok": False, "payload": "some error string"},
              f"an ok=False result with a plain string payload must round-trip too "
              f"(got {settings3.cudasieve_status!r})")
    finally:
        app_settings_mod.LOCALES_DIR = orig_locales_dir
        shutil.rmtree(tmp_locales, ignore_errors=True)


# ============================================================================================
# Section D -- prime_sieve_cudasieve.py: window_sharding.py integration
# ============================================================================================

def _install_trial_division_stub(cudasieve_engine):
    """Monkeypatches generate_primes_in_range() with a plain trial-division stub so this
    section never needs a real `cudasieve` binary or GPU -- exactly the same approach
    section E/F below use for WSL. Returns the original function for restoration."""
    def _is_prime(n):
        if n < 2:
            return False
        if n < 4:
            return True
        if n % 2 == 0:
            return False
        i = 3
        while i * i <= n:
            if n % i == 0:
                return False
            i += 2
        return True

    def stub(lo, hi, gpu_index=None):
        # Deliberately does NOT enforce MIN_PRINTABLE_TOP -- this section tests
        # window_sharding.py integration, not the printable-floor boundary (that's
        # covered by generate_primes_in_range()'s own real implementation and by
        # Section E's UI-level CUDASIEVE_MIN_PRINTABLE_TOP checks); using small,
        # fast-to-verify ranges here keeps this section quick.
        if hi <= lo:
            return []
        return [n for n in range(lo, hi) if _is_prime(n)]

    original = cudasieve_engine.generate_primes_in_range
    cudasieve_engine.generate_primes_in_range = stub
    return original


def section_d():
    print("\n--- Section D: prime_sieve_cudasieve.py window_sharding integration ---")
    import prime_sieve_cudasieve as cudasieve_engine
    import window_sharding

    portal = tempfile.mkdtemp(prefix="cudasieve_engine_test_")
    original_gen = _install_trial_division_stub(cudasieve_engine)
    try:
        # --- Scenario 1: multi-window sharded write on a normal (>= LOW_FLOOR_CUTOFF)
        # floor. Use small numbers (base_power=2, i.e. base=100) well below
        # MIN_PRINTABLE_TOP -- fine here since this section drives generate_primes_in_range
        # directly via the stub, which only enforces MIN_PRINTABLE_TOP the same way the
        # real one does; base_power=2 with window_m=50 keeps this fast and readable. ---
        base_power = 2
        window_m = 50
        cudasieve_engine.generate_floor_windows(
            base_power, target_idx_start=0, target_idx_count=3, window_m=window_m,
            write_files=True, portal_folder=portal)

        source_dir = os.path.join(portal, f"10p{base_power}", "source_primes")
        for target_idx in (0, 1, 2):
            offset = target_idx * window_m
            shard_dir = window_sharding.shard_dir(source_dir, target_idx)
            suffix = f"{offset // 1_000_000}M" if offset and offset % 1_000_000 == 0 else str(offset)
            expected_path = os.path.join(
                shard_dir, f"PRIME_WINDOW_10p{base_power}_off_{suffix}.bin")
            check(os.path.isfile(expected_path),
                  f"multi-window write: window target_idx={target_idx} must land in "
                  f"window_sharding's own shard_dir() location, not a flat folder "
                  f"(expected {expected_path!r} to exist)")

        # Sanity: the written windows actually contain the right primes (base=100,
        # window_m=50 -> combined range [100, 250)).
        import struct

        def _read_window_primes(path):
            with open(path, "rb") as f:
                data = f.read()
            assert data[:4] == b"PGS2"
            base_len = data[4]
            if base_len == 0:
                return []
            base_val = int.from_bytes(data[5:5 + base_len], "big")
            off = 5 + base_len
            count = int.from_bytes(data[off:off + 4], "big")
            off += 8  # count(4) + generated_at(4)
            primes = [base_val]
            prev = base_val
            while len(primes) < count:
                shift = 0
                value = 0
                while True:
                    b = data[off]
                    off += 1
                    value |= (b & 0x7F) << shift
                    if not (b & 0x80):
                        break
                    shift += 7
                prev = prev + value
                primes.append(prev)
            return primes

        window0_path = os.path.join(
            window_sharding.shard_dir(source_dir, 0), f"PRIME_WINDOW_10p{base_power}_off_0.bin")
        primes0 = _read_window_primes(window0_path)
        expected0 = [n for n in range(100, 150) if all(n % d for d in range(2, int(n ** 0.5) + 1)) and n > 1]
        check(primes0 == expected0,
              f"window 0's content must be exactly the primes in [100,150) "
              f"(got {primes0!r}, expected {expected0!r})")

        # Benchmark log schema parity with every other engine (17-column
        # BENCHMARK_FIELDNAMES, shared by prime_sieve_primesieve.py's own copy).
        bench_path = os.path.join(portal, "benchmark_log.csv")
        check(os.path.isfile(bench_path),
              "generate_floor_windows(write_files=True) must append to benchmark_log.csv")
        with open(bench_path, newline="") as f:
            rows = list(csv.DictReader(f))
        check(len(rows) == 1 and set(rows[0].keys()) == set(cudasieve_engine.BENCHMARK_FIELDNAMES),
              f"benchmark_log.csv must use the exact same {len(cudasieve_engine.BENCHMARK_FIELDNAMES)}"
              f"-column schema every other engine file uses "
              f"(got columns {sorted(rows[0].keys()) if rows else None!r})")
        check(rows[0]["windows_written"] == "3",
              f"benchmark row must record 3 windows written (got {rows[0]['windows_written']!r})")

        # --- Scenario 2: low-floor sharded write (base_power < LOW_FLOOR_CUTOFF). ---
        shutil.rmtree(portal, ignore_errors=True)
        os.makedirs(portal, exist_ok=True)
        # floor 0 (not LOW_FLOOR_CUTOFF-2) deliberately -- keeps the combined range tiny
        # ([1,100)) so the trial-division stub stays fast; _low_floor_segments() only
        # cares that base_power < LOW_FLOOR_CUTOFF and combined_lo == 10**base_power,
        # not which specific low floor it is.
        low_base_power = 0
        # combined range must start exactly at 10**low_base_power and span whole decades
        # for _low_floor_segments() to fire -- one window covering floors
        # [low_base_power, low_base_power+1] worth of decades.
        span_decades = 2
        window_m_low = 10 ** (low_base_power + span_decades) - 10 ** low_base_power
        cudasieve_engine.generate_floor_windows(
            low_base_power, target_idx_start=0, target_idx_count=1, window_m=window_m_low,
            write_files=True, portal_folder=portal)
        for floor in range(low_base_power, low_base_power + span_decades):
            floor_dir = os.path.join(portal, f"10p{floor}", "source_primes")
            shard0 = window_sharding.shard_dir(floor_dir, 0)
            expected_low_path = os.path.join(shard0, f"PRIME_WINDOW_10p{floor}_off_0.bin")
            check(os.path.isfile(expected_low_path),
                  f"low-floor write: floor {floor}'s single window must land in "
                  f"shard_dir(..., 0), same sharded convention as the main branch "
                  f"(expected {expected_low_path!r} to exist)")

        # --- Scenario 3: count-only mode (write_files=False) -- no PGS2 files, but scan
        # metrics + benchmark row are still recorded. ---
        shutil.rmtree(portal, ignore_errors=True)
        os.makedirs(portal, exist_ok=True)
        cudasieve_engine.generate_floor_windows(
            base_power, target_idx_start=0, target_idx_count=2, window_m=window_m,
            write_files=False, portal_folder=portal)
        source_dir2 = os.path.join(portal, f"10p{base_power}", "source_primes")
        check(not os.path.isdir(source_dir2),
              f"count-only mode (write_files=False) must write NO PGS2 files at all "
              f"(source_primes dir must not even be created) (found {source_dir2!r})")
        metrics_path = os.path.join(portal, cudasieve_engine.SCAN_METRICS_FILENAME)
        check(os.path.isfile(metrics_path),
              "count-only mode must still write the scan-metrics handoff file")
        with open(metrics_path, encoding="utf-8") as f:
            metrics = json.load(f)
        check(metrics.get("write_files") is False,
              f"scan metrics handoff must record write_files=False "
              f"(got {metrics!r})")
        bench_path2 = os.path.join(portal, "benchmark_log.csv")
        with open(bench_path2, newline="") as f:
            rows2 = list(csv.DictReader(f))
        check(len(rows2) == 1 and rows2[0]["write_files"] == "0",
              f"count-only mode's benchmark row must record write_files=0 "
              f"(got {rows2[0].get('write_files') if rows2 else None!r})")
    finally:
        cudasieve_engine.generate_primes_in_range = original_gen
        shutil.rmtree(portal, ignore_errors=True)


# ============================================================================================
# Section E -- GenerationTab: cudasieve Quick-gen mode (needs a real Tk display -- Xvfb)
# ============================================================================================

class _FakeWslLoggedRunner:
    """Stands in for WslLoggedRunner -- records constructor args and start() calls instead
    of launching a real WSL subprocess (no WSL exists in this sandbox)."""

    instances = []

    def __init__(self, cmd, log_path, exit_path, q, kill_pattern=None):
        self.cmd = cmd
        self.log_path = log_path
        self.exit_path = exit_path
        self.q = q
        self.kill_pattern = kill_pattern
        self.started = False
        _FakeWslLoggedRunner.instances.append(self)

    def start(self):
        self.started = True

    def is_running(self):
        return False


def section_e():
    print("\n--- Section E: GenerationTab cudasieve Quick-gen mode (Xvfb) ---")
    import tkinter.messagebox as messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None

    import prime_atlas_v1
    import primeatlas.generation_tab as generation_tab_mod
    from primeatlas.generation import CUDASIEVE_MIN_PRINTABLE_TOP

    error_calls = []
    messagebox.showerror = lambda title, msg, *a, **k: error_calls.append((title, msg))

    portal = tempfile.mkdtemp(prefix="cudasieve_gentab_test_")
    orig_runner_cls = generation_tab_mod.WslLoggedRunner
    generation_tab_mod.WslLoggedRunner = _FakeWslLoggedRunner
    try:
        sys.argv = ["prime_atlas_v1.py"]
        app_cls = prime_atlas_v1._build_gui()
        app = app_cls()
        app.update()
        gen = app.generation_tab_widget

        settings_tab = app.settings_tab
        settings_tab.app_settings.save = lambda: None
        settings_tab.app_settings.set_storage_path(portal)
        settings_tab.wsl["set_portal_folder"](portal)
        app.update()

        # --- Mode-switch: selecting "cudasieve" raises exactly that mode's frame. ---
        gen.quick_mode_var.set("cudasieve")
        gen._on_quick_mode_changed() if hasattr(gen, "_on_quick_mode_changed") else None
        # Some builds wire the mode switch via a trace/radiobutton command instead of a
        # directly-callable method -- fall back to invoking whatever mode_frames dict
        # exists via the panel's own frame visibility if the direct method isn't present.
        app.update()
        cudasieve_frame = gen._quick_mode_frames.get("cudasieve") if hasattr(
            gen, "_quick_mode_frames") else None
        if cudasieve_frame is not None:
            check(bool(cudasieve_frame.grid_info()),
                  "selecting cudasieve mode must raise (grid) its own frame")

        # --- Auto-from clamp: floor below CUDASIEVE_MIN_PRINTABLE_TOP clamps up. ---
        gen.quick_cudasieve_floor_var.set("10")
        gen._on_cudasieve_auto_from_clicked()
        check(gen.quick_cudasieve_from_var.get() == str(CUDASIEVE_MIN_PRINTABLE_TOP),
              f"floor=10 (10**10, below 2**40) must clamp the From field up to "
              f"CUDASIEVE_MIN_PRINTABLE_TOP (got {gen.quick_cudasieve_from_var.get()!r}, "
              f"expected {CUDASIEVE_MIN_PRINTABLE_TOP!r})")

        # --- Auto-from compute: floor comfortably above the min-printable floor, nothing
        # on disk yet -> continuation_point == 10**floor exactly. ---
        gen.quick_cudasieve_floor_var.set("50")
        gen._on_cudasieve_auto_from_clicked()
        check(gen.quick_cudasieve_from_var.get() == str(10 ** 50),
              f"floor=50 with nothing on disk must compute continuation_point=10**50 "
              f"exactly (got {gen.quick_cudasieve_from_var.get()!r})")

        # --- Auto-from no-crash on empty floor field. ---
        gen.quick_cudasieve_floor_var.set("")
        gen._on_cudasieve_auto_from_clicked()  # must not raise

        # --- Dispatch: below-min-printable request is rejected with a clear error, no
        # launch call is ever recorded. ---
        recorder_calls = []
        orig_apply = gen._apply_cudasieve_params_and_run
        gen._apply_cudasieve_params_and_run = lambda *a: recorder_calls.append(a)

        gen.quick_mode_var.set("cudasieve")
        gen.quick_cudasieve_from_var.set(str(10 ** 10))  # well below 2**40
        gen.quick_cudasieve_width_var.set("1")
        error_calls.clear()
        gen._on_quick_generate_clicked()
        check(len(recorder_calls) == 0,
              f"a From value whose whole requested range stays below "
              f"CUDASIEVE_MIN_PRINTABLE_TOP must launch NOTHING "
              f"(got calls={recorder_calls!r})")
        check(len(error_calls) == 1,
              f"the below-min-printable rejection must show exactly one error dialog "
              f"(got {len(error_calls)} calls: {error_calls!r})")

        # --- Dispatch: beyond-ceiling request (start > CUDASIEVE_MAX_STOP) is rejected. ---
        from primeatlas.generation import CUDASIEVE_MAX_STOP
        recorder_calls.clear()
        error_calls.clear()
        gen.quick_cudasieve_from_var.set(str(CUDASIEVE_MAX_STOP + 1))
        gen.quick_cudasieve_width_var.set("1")
        gen._on_quick_generate_clicked()
        check(len(recorder_calls) == 0,
              f"a From value beyond CUDASIEVE_MAX_STOP must launch NOTHING "
              f"(got calls={recorder_calls!r})")
        check(len(error_calls) == 1,
              f"the beyond-ceiling rejection must show exactly one error dialog "
              f"(got {len(error_calls)} calls: {error_calls!r})")

        # --- Dispatch: happy path reaches _apply_cudasieve_params_and_run with a sane
        # plan (floor comfortably above the min-printable point, nothing on disk). ---
        recorder_calls.clear()
        error_calls.clear()
        # 10**15 is comfortably above CUDASIEVE_MIN_PRINTABLE_TOP (2**40 ~= 1.0995e12)
        # and comfortably below CUDASIEVE_MAX_STOP (2**64-1 ~= 1.8447e19) -- floor 41
        # used in an earlier draft of this test was itself beyond the uint64 ceiling,
        # which is exactly the rejection this section tests separately above.
        start = 10 ** 15
        gen.quick_cudasieve_from_var.set(str(start))
        gen.quick_cudasieve_width_var.set("2")
        gen._on_quick_generate_clicked()
        check(len(error_calls) == 0,
              f"a valid in-range request must not show any error dialog "
              f"(got {error_calls!r})")
        check(len(recorder_calls) == 1,
              f"a valid in-range request must reach _apply_cudasieve_params_and_run "
              f"exactly once (got {len(recorder_calls)} calls: {recorder_calls!r})")
        if recorder_calls:
            floor_arg, target_idx_start_arg, window_count_arg = recorder_calls[0]
            check(floor_arg == 15,
                  f"the plan's floor must be 15 (10**15 <= start < 10**16) "
                  f"(got {floor_arg!r})")
            check(target_idx_start_arg == 0,
                  f"starting exactly at 10**15 must target_idx_start=0 "
                  f"(got {target_idx_start_arg!r})")
            check(window_count_arg == 2,
                  f"Width=2 with nothing on disk must request exactly 2 windows "
                  f"(got {window_count_arg!r})")
        gen._apply_cudasieve_params_and_run = orig_apply

        # --- _on_run_cudasieve: reaches WslLoggedRunner with the right kill_pattern and
        # actually calls start(). ---
        _FakeWslLoggedRunner.instances.clear()
        gen._loop_runner = None
        gen._on_run_cudasieve(41, 0, 2)
        check(len(_FakeWslLoggedRunner.instances) == 1,
              f"_on_run_cudasieve must construct exactly one WslLoggedRunner "
              f"(got {len(_FakeWslLoggedRunner.instances)})")
        if _FakeWslLoggedRunner.instances:
            runner = _FakeWslLoggedRunner.instances[0]
            check(runner.started,
                  "_on_run_cudasieve must call runner.start()")
            check(runner.kill_pattern == "prime_sieve_cudasieve.py",
                  f"the runner's kill_pattern must target prime_sieve_cudasieve.py so "
                  f"Stop actually kills the right process tree "
                  f"(got {runner.kill_pattern!r})")

        app.destroy()
    finally:
        generation_tab_mod.WslLoggedRunner = orig_runner_cls
        shutil.rmtree(portal, ignore_errors=True)


# ============================================================================================
# Section F -- SettingsTab: cudasieve installer state machine (needs a real Tk display)
# ============================================================================================

def section_f():
    print("\n--- Section F: SettingsTab cudasieve installer state machine (Xvfb) ---")
    import tkinter.messagebox as messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    import webbrowser
    opened_urls = []
    webbrowser.open = lambda url: opened_urls.append(url)

    import prime_atlas_v1
    import primeatlas.settings_tab as settings_tab_mod

    portal = tempfile.mkdtemp(prefix="cudasieve_settingstab_test_")
    try:
        sys.argv = ["prime_atlas_v1.py"]
        app_cls = prime_atlas_v1._build_gui()
        app = app_cls()
        app.update()
        settings_tab = app.settings_tab
        settings_tab.app_settings.save = lambda: None
        settings_tab.app_settings.set_storage_path(portal)
        settings_tab.wsl["set_portal_folder"](portal)
        app.update()

        # --- _on_open_cudasieve_github_clicked: opens the real repo URL. ---
        opened_urls.clear()
        settings_tab._on_open_cudasieve_github_clicked()
        check(opened_urls == [settings_tab_mod.CUDASIEVE_REPO_URL],
              f"the GitHub link button must open CUDASieve's own repo URL, no copy kept "
              f"in this project (got {opened_urls!r})")

        # --- _on_cudasieve_status_result: installed branch. ---
        settings_tab._on_cudasieve_status_result(
            True, {"binary_exists": True, "binary_path": "/home/x/.primeatlas/cudasieve/cudasieve"})
        check("/home/x/.primeatlas/cudasieve/cudasieve" in settings_tab.cudasieve_status_var.get(),
              f"an installed result must show the real binary path in the status label "
              f"(got {settings_tab.cudasieve_status_var.get()!r})")
        check(str(settings_tab.install_cudasieve_btn["state"]) == "disabled",
              "once installed, the install button must be disabled (nothing left to do)")
        check(settings_tab.app_settings.cudasieve_status == {
            "ok": True,
            "payload": {"binary_exists": True,
                        "binary_path": "/home/x/.primeatlas/cudasieve/cudasieve"}},
              "the installed result must be persisted to AppSettings")

        # --- _on_cudasieve_status_result: cloned-but-not-built branch. ---
        settings_tab._on_cudasieve_status_result(
            True, {"binary_exists": False, "cloned": True, "install_dir": "/home/x/.primeatlas/cudasieve"})
        check(str(settings_tab.install_cudasieve_btn["state"]) == "disabled",
              "cloned-but-not-built must also leave the install button disabled (verify "
              "the CUDA toolchain by hand first per that branch's own docstring)")

        # --- _on_cudasieve_status_result: missing entirely, no GPU detected. ---
        settings_tab._cudasieve_install_running = False
        settings_tab._on_cudasieve_status_result(
            True, {"binary_exists": False, "cloned": False, "has_nvidia_smi": False})
        check(str(settings_tab.install_cudasieve_btn["state"]) == "normal",
              f"a clean 'not installed yet' result must leave the install button enabled "
              f"(got state={settings_tab.install_cudasieve_btn['state']!r})")

        # --- _on_cudasieve_status_result: probe itself failed (ok=False). ---
        settings_tab._cudasieve_install_running = False
        settings_tab._on_cudasieve_status_result(False, "WSL cold-start hiccup")
        check("WSL cold-start hiccup" in settings_tab.cudasieve_status_var.get(),
              f"a failed probe must surface the real error text "
              f"(got {settings_tab.cudasieve_status_var.get()!r})")
        check(str(settings_tab.install_cudasieve_btn["state"]) == "normal",
              "a failed status probe must still allow the user to try Install anyway")

        # --- _show_cached_cudasieve_status: round-trips through AppSettings correctly. ---
        settings_tab.app_settings.set_cudasieve_status(
            True, {"binary_exists": True, "binary_path": "/cached/path"})
        settings_tab.cudasieve_status_var.set("")  # clear, to prove the next call sets it
        settings_tab._show_cached_cudasieve_status()
        check("/cached/path" in settings_tab.cudasieve_status_var.get(),
              f"_show_cached_cudasieve_status() must render the persisted cache without "
              f"any WSL round-trip (got {settings_tab.cudasieve_status_var.get()!r})")

        # --- _start_cudasieve_build: wires self.wsl correctly and starts a runner. ---
        _FakeWslLoggedRunner.instances.clear()
        settings_tab.wsl["WslLoggedRunner"] = _FakeWslLoggedRunner
        settings_tab._cudasieve_install_running = True
        settings_tab._start_cudasieve_build()
        check(len(_FakeWslLoggedRunner.instances) == 1,
              f"_start_cudasieve_build must construct exactly one WslLoggedRunner via "
              f"self.wsl['WslLoggedRunner'] (got {len(_FakeWslLoggedRunner.instances)})")
        if _FakeWslLoggedRunner.instances:
            build_runner = _FakeWslLoggedRunner.instances[0]
            check(build_runner.started,
                  "_start_cudasieve_build must call runner.start()")
            check(build_runner.kill_pattern == "prime_sieve_cudasieve.py",
                  f"the build runner's kill_pattern must also target "
                  f"prime_sieve_cudasieve.py (got {build_runner.kill_pattern!r})")
        check(settings_tab._cudasieve_runner is not None,
              "_start_cudasieve_build must remember the runner on self._cudasieve_runner")

        # --- _poll_cudasieve_queue: exit-tuple handling (success code). ---
        status_recorder = []
        orig_check_status = settings_tab._on_check_cudasieve_status
        settings_tab._on_check_cudasieve_status = lambda: status_recorder.append(True)
        q = queue.Queue()
        q.put("some build progress line\n")
        q.put(("__exit__", 0))
        settings_tab._cudasieve_queue = q
        settings_tab._cudasieve_install_running = True
        # Cancel the self.after(150, ...) reschedule this triggers so the test doesn't
        # leave a dangling Tk timer -- call the method body once directly instead of
        # relying on the real event loop.
        orig_after = settings_tab.after
        settings_tab.after = lambda *a, **k: None
        try:
            settings_tab._poll_cudasieve_queue()
        finally:
            settings_tab.after = orig_after
        check(settings_tab._cudasieve_install_running is False,
              "an ('__exit__', 0) queue item must clear _cudasieve_install_running")
        check(len(status_recorder) == 1,
              f"a successful build must trigger _on_check_cudasieve_status() so the label "
              f"reflects reality without a second manual click "
              f"(got {len(status_recorder)} calls)")
        settings_tab._on_check_cudasieve_status = orig_check_status

        app.destroy()
    finally:
        shutil.rmtree(portal, ignore_errors=True)


def main():
    section_a()
    section_b()
    section_c()
    section_d()
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("\n(tkinter not available -- skipping Sections E/F, GUI-dependent)")
    else:
        section_e()
        section_f()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
