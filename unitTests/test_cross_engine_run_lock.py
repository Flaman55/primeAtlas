"""
test_cross_engine_run_lock.py -- regression tests for GenerationTab's cross-engine
mutual exclusion between self._loop_runner (every Quick-gen/loop/hybrid/orchestrator-
direct launch path), self._const_runner (Constellations search) and self._ktuple_runner
(targeted k-tuple sieve).

All three funnel their live WSL output through the SAME
_update_shared_progress_from_generation_chunk(), which keeps its parsing state
(self._gen_step_total, self._const_floor_total_windows, self._const_run_start_
already_done, etc.) in plain instance attributes with no per-engine namespacing, so
two engines running at once (each with its own 150ms polling loop) would corrupt
each other's bar/status values.

Contract (see run_progress.py's _other_engine_is_running/_lock_other_run_buttons/
_unlock_other_run_buttons docstrings): every launch path (1) grays out the OTHER two
engines' Run buttons for the whole session (not just one chained batch/iteration),
released only once that engine has GENUINELY finished, and (2) refuses to launch if
another engine is already running even when called directly (a non-button call path,
e.g. a search box's "generate missing window" auto-offer).

Never drives a REAL WSL process -- WslLoggedRunner is monkeypatched out in every test
here, same convention as test_constellation_auto_retry.py.

Usage (Windows, real display):
    python unitTests\\test_cross_engine_run_lock.py
"""
import os
import shutil
import sys
import tempfile
import tkinter.messagebox

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


def _build_app(tmp_portal):
    sys.argv = ["prime_atlas_v2.py"]
    import prime_atlas_v2
    from app_sandbox import isolate_app
    isolate_app(tmp_portal)
    app_cls = prime_atlas_v2._build_gui()
    app = app_cls()
    app.update()
    app.update()
    return app


class _FakeRunner:
    """Stands in for WslLoggedRunner -- never actually spawns anything, just
    remembers whether it's "running" so is_running() checks behave like the real
    thing without a live subprocess."""

    def __init__(self, *a, **k):
        self._running = True

    def start(self):
        pass

    def stop(self):
        self._running = False

    def is_running(self):
        return self._running


def _patch_wsl_runner(generation_tab_module):
    original = generation_tab_module.WslLoggedRunner
    generation_tab_module.WslLoggedRunner = _FakeRunner
    return original


def _test_other_engine_is_running_detects_each_combo():
    tmp = tempfile.mkdtemp(prefix="primeatlas_cross_engine_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget

        check(tab._other_engine_is_running("loop") is False,
              "nothing running yet -> False for every engine")

        tab._const_runner = _FakeRunner()
        check(tab._other_engine_is_running("loop") is True,
              "a running const engine counts as 'other' for loop")
        check(tab._other_engine_is_running("ktuple") is True,
              "a running const engine counts as 'other' for ktuple")
        check(tab._other_engine_is_running("const") is False,
              "a running const engine does NOT count as 'other' for itself")

        tab._const_runner.stop()
        check(tab._other_engine_is_running("loop") is False,
              "a stopped const engine no longer counts as 'other'")

        tab._loop_runner = _FakeRunner()
        tab._ktuple_runner = _FakeRunner()
        check(tab._other_engine_is_running("const") is True,
              "either loop or ktuple running counts as 'other' for const")
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_starting_loop_run_locks_const_and_ktuple_buttons():
    tmp = tempfile.mkdtemp(prefix="primeatlas_cross_engine_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        import primeatlas.generation.generation_tab as generation_tab_module
        original_runner = _patch_wsl_runner(generation_tab_module)
        try:
            tab._loop_vars["base_exponent"].set("12")
            tab._loop_vars["run_count"].set("1")
            tab._loop_vars["n_instances"].set("1")
            tab._loop_vars["window_count_per_run"].set("1")
            tab._loop_vars["workers"].set("1")
            tab._loop_vars["batches_per_worker"].set("1")
            tab._loop_vars["window_m"].set("1000")
            tab._on_run_loop()
            check(str(tab.loop_run_btn["state"]) == "disabled",
                  "the launched engine's own Run button is disabled (pre-existing behavior)")
            check(str(tab.const_run_btn["state"]) == "disabled",
                  "constellation Run is grayed out while a loop run is active")
            check(str(tab.ktuple_run_btn["state"]) == "disabled",
                  "ktuple Run is grayed out while a loop run is active")
            check(str(tab.ktuple_auto_btn["state"]) == "disabled",
                  "ktuple Auto is grayed out while a loop run is active")
            check(tab._quick_panels and all(
                      str(panel["generate_btn"]["state"]) == "normal"
                      for panel in tab._quick_panels),
                  "the loop engine's OWN Quick-gen Generate buttons stay enabled "
                  "while IT is the one running -- it doubles as the Stop control "
                  "(see _on_run_loop's own text swap), _lock_other_run_buttons() "
                  "must not disable it in this direction")
        finally:
            generation_tab_module.WslLoggedRunner = original_runner
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_starting_constellation_run_locks_loop_and_ktuple_buttons():
    tmp = tempfile.mkdtemp(prefix="primeatlas_cross_engine_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        import primeatlas.generation.generation_tab as generation_tab_module
        original_runner = _patch_wsl_runner(generation_tab_module)
        try:
            tab._const_base_exponent_var.set("25")
            tab._on_run_constellation()
            check(str(tab.const_run_btn["state"]) == "disabled",
                  "the launched engine's own Run button is disabled (pre-existing behavior)")
            check(str(tab.loop_run_btn["state"]) == "disabled",
                  "loop Run (low-level) is grayed out while a constellation run is active")
            check(tab._quick_panels and all(
                      str(panel["generate_btn"]["state"]) == "disabled"
                      for panel in tab._quick_panels),
                  "every Quick-gen panel's own Generate button is ALSO grayed out "
                  "while a constellation run is active (the user-facing launch button, "
                  "not just the low-level loop_run_btn)")
            check(str(tab.ktuple_run_btn["state"]) == "disabled",
                  "ktuple Run is grayed out while a constellation run is active")
            check(str(tab.ktuple_auto_btn["state"]) == "disabled",
                  "ktuple Auto is grayed out while a constellation run is active")
        finally:
            generation_tab_module.WslLoggedRunner = original_runner
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_starting_ktuple_run_locks_loop_and_const_buttons():
    tmp = tempfile.mkdtemp(prefix="primeatlas_cross_engine_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        import primeatlas.generation.generation_tab as generation_tab_module
        original_runner = _patch_wsl_runner(generation_tab_module)
        try:
            tab._ktuple_vars["base_exponent"].set("12")
            tab.ktuple_k_combo.current(0)
            tab.ktuple_variant_combo.current(0)
            tab._ktuple_vars["n_locations"].set("10")
            tab._ktuple_vars["window_m"].set("1000")
            tab.ktuple_strategy_combo.current(0)
            tab._launch_ktuple(auto=False)
            check(str(tab.ktuple_run_btn["state"]) == "disabled",
                  "the launched engine's own Run button is disabled (pre-existing behavior)")
            check(str(tab.loop_run_btn["state"]) == "disabled",
                  "loop Run (low-level) is grayed out while a ktuple run is active")
            check(tab._quick_panels and all(
                      str(panel["generate_btn"]["state"]) == "disabled"
                      for panel in tab._quick_panels),
                  "every Quick-gen panel's own Generate button is ALSO grayed out "
                  "while a ktuple run is active")
            check(str(tab.const_run_btn["state"]) == "disabled",
                  "constellation Run is grayed out while a ktuple run is active")
        finally:
            generation_tab_module.WslLoggedRunner = original_runner
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_guard_blocks_launch_while_other_engine_running():
    """The non-button backstop: even called directly (bypassing whatever the button's
    own disabled state would otherwise prevent), a launch path must refuse to start
    while another engine is already running."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_cross_engine_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        tab._const_runner = _FakeRunner()  # simulates an active constellation run

        import primeatlas.generation.generation_tab as generation_tab_module
        original_runner = _patch_wsl_runner(generation_tab_module)
        try:
            tab._loop_vars["base_exponent"].set("12")
            tab._loop_vars["run_count"].set("1")
            tab._loop_vars["n_instances"].set("1")
            tab._loop_vars["window_count_per_run"].set("1")
            tab._loop_vars["workers"].set("1")
            tab._loop_vars["batches_per_worker"].set("1")
            tab._loop_vars["window_m"].set("1000")
            tab._on_run_loop()
            check(tab._loop_runner is None,
                  "_on_run_loop() refuses to launch while the constellation engine "
                  "is running, even called directly")
        finally:
            generation_tab_module.WslLoggedRunner = original_runner
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_finishing_loop_run_unlocks_all_buttons():
    tmp = tempfile.mkdtemp(prefix="primeatlas_cross_engine_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        tab._lock_other_run_buttons("loop")
        check(str(tab.const_run_btn["state"]) == "disabled", "setup: const is locked")
        tab._on_loop_finished(0)
        check(str(tab.loop_run_btn["state"]) == "normal", "loop Run re-enabled on finish")
        check(str(tab.const_run_btn["state"]) == "normal", "const Run re-enabled on finish")
        check(str(tab.ktuple_run_btn["state"]) == "normal", "ktuple Run re-enabled on finish")
        check(str(tab.ktuple_auto_btn["state"]) == "normal", "ktuple Auto re-enabled on finish")
        check(tab._quick_panels and all(
                  str(panel["generate_btn"]["state"]) == "normal"
                  for panel in tab._quick_panels),
              "every Quick-gen panel's own Generate button is re-enabled on finish")
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_finishing_ktuple_run_unlocks_all_buttons():
    tmp = tempfile.mkdtemp(prefix="primeatlas_cross_engine_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        tab._lock_other_run_buttons("ktuple")
        check(str(tab.loop_run_btn["state"]) == "disabled", "setup: loop is locked")
        tab._on_ktuple_finished(0)
        check(str(tab.loop_run_btn["state"]) == "normal", "loop Run re-enabled on finish")
        check(str(tab.const_run_btn["state"]) == "normal", "const Run re-enabled on finish")
        check(str(tab.ktuple_run_btn["state"]) == "normal", "ktuple Run re-enabled on finish")
        check(str(tab.ktuple_auto_btn["state"]) == "normal", "ktuple Auto re-enabled on finish")
        check(tab._quick_panels and all(
                  str(panel["generate_btn"]["state"]) == "normal"
                  for panel in tab._quick_panels),
              "every Quick-gen panel's own Generate button is re-enabled on finish")
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_chained_constellation_batch_keeps_lock_until_genuinely_done():
    """A chained --max-windows batch continuation (see _maybe_continue_constellation_
    batch) must NOT release the cross-engine lock -- only true completion (no further
    batch scheduled) should."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_cross_engine_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        tab._lock_other_run_buttons("const")
        tab._maybe_auto_retry_constellation = lambda returncode: False
        tab._maybe_continue_constellation_batch = lambda returncode: True  # "chained"
        tab._on_constellation_finished(0)
        check(str(tab.loop_run_btn["state"]) == "disabled",
              "a chained batch continuation must NOT unlock the other engines")

        tab._maybe_continue_constellation_batch = lambda returncode: False  # "genuinely done"
        tab._on_constellation_finished(0)
        check(str(tab.loop_run_btn["state"]) == "normal",
              "genuine completion (no further batch scheduled) DOES unlock the other engines")
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_verify_section():
    """Section D (verify_section.py): its launch locks every other engine and carries the
    pt1 knobs and the store verification script (the v7.3 sieve's with its pass width when
    that method is chosen); a bad field launches nothing; another
    running engine blocks it; Stop writes the generation stop request; finishing unlocks
    everything and clears the request."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_cross_engine_test_")
    try:
        app = _build_app(tmp)
        tab = app.generation_tab_widget
        import primeatlas.generation.generation_tab as generation_tab_module
        import generation_stop
        launched = []

        class _Recorder(_FakeRunner):
            def __init__(self, cmd, *a, **k):
                super().__init__()
                launched.append((cmd, k.get("kill_pattern")))

        original_runner = generation_tab_module.WslLoggedRunner
        generation_tab_module.WslLoggedRunner = _Recorder
        try:
            import storage_kinds
            from tkinter import messagebox
            errors = []
            original_error = messagebox.showerror
            messagebox.showerror = lambda title, msg: errors.append(msg)
            tab._verify_vars["base_exponent"].set("x")
            tab._on_run_verify()
            check(tab._verify_runner is None and not launched,
                  "verify: a bad floor launches nothing")
            tab._verify_vars["width_exp"].set("7")
            tab._verify_vars["base_exponent"].set("29")
            tab._refresh_verify_count()
            tab._on_run_verify()
            check(tab._verify_runner is None and errors
                  and errors[-1] == tab.T("gen.verify_error_no_windows"),
                  "verify: a floor without P windows launches nothing")
            for off, label in ((0, "0"), (10 ** 7, "10M"), (2 * 10 ** 7, "20M")):
                path = storage_kinds.window_path(tmp, 29, off, 10 ** 7, label,
                                                 storage_kinds.KIND_P)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "wb").close()
            tab._refresh_verify_count()
            check(tab._verify_vars["max_windows"].get() == "3"
                  and "3" in tab._verify_total_text.get(),
                  "verify: the Windows field counts the floor's P windows")
            tab._verify_vars["width_exp"].set("8")
            tab._refresh_verify_count()
            check(tab._verify_vars["max_windows"].get() == "1",
                  "verify: a wider window recounts (only offset 0 is on the 10^8 grid)")
            tab._verify_vars["width_exp"].set("7")
            tab._refresh_verify_count()
            tab._verify_vars["threads"].set("0")
            tab._on_run_verify()
            check(tab._verify_runner is None, "verify: 0 threads launches nothing")
            tab._verify_vars["threads"].set("Auto")
            tab._loop_vars["workers"].set("7")
            tab._verify_vars["max_windows"].set("2")
            values = tab._verify_values()
            check(values == {"base_exponent": 29, "window_m": 10 ** 7, "max_windows": 2,
                             "threads": 7, "method": "proof"},
                  f"verify: Auto threads = the form's workers, 2 of 3 windows ({values})")
            tab._verify_vars["max_windows"].set("3")
            check(tab._verify_values()["max_windows"] == 0,
                  "verify: the full count is passed as 0 (all)")
            check(tab._verify_vars["method"].get() == "proof"
                  and tab._verify_method_text.get() == tab.T("gen.verify_method_proof"),
                  "verify: the pt1.1 proof is the default method")
            tab._verify_method_text.set(tab.T("gen.verify_method_sieve"))
            tab._on_verify_method_chosen()
            tab._verify_vars["pass_exp"].set("13")
            check(tab._verify_values() is None, "verify: a pass of 10^13 is refused")
            tab._verify_vars["pass_exp"].set("6")
            check(tab._verify_values() is None, "verify: a pass narrower than a window is refused")
            tab._verify_vars["pass_exp"].set("11")
            values = tab._verify_values()
            check(values is not None and values["method"] == "sieve"
                  and values["pass_numbers"] == 10 ** 11,
                  f"verify: the v7.3 sieve with passes of 10^11 ({values})")
            text = tab._refresh_verify_estimate()
            check("?" in text and "pt1.1" in text and "v7.3" in text,
                  f"verify: without benchmark rows both estimates say ? ({text})")
            tab._verify_method_text.set(tab.T("gen.verify_method_proof"))
            tab._on_verify_method_chosen()
            messagebox.showerror = original_error
            tab._ktuple_runner = _FakeRunner()
            tab._on_run_verify()
            check(tab._verify_runner is None,
                  "verify: refuses while another engine is running")
            tab._ktuple_runner.stop()
            with open(generation_stop.stop_request_path(tmp), "w") as f:
                f.write("left over")
            tab._on_run_verify()
            cmd = " ".join(str(t) for t in launched[-1][0]) if launched else ""
            check(tab._verify_runner is not None and "pt1_verify_store.py" in cmd
                  and "PRIMEATLAS_PT1_B=" in cmd and "PRIMEATLAS_PT1_CHUNK_KB=" in cmd
                  and launched[-1][1] == "pt1_verify_store.py",
                  f"verify: launches pt1_verify_store.py with pt1's knobs ({cmd[-160:]})")
            check(not generation_stop.stop_requested(tmp),
                  "verify: a stop request left over is cleared before the launch")
            check(str(tab.verify_run_btn["state"]) == "disabled"
                  and str(tab.loop_run_btn["state"]) == "disabled"
                  and str(tab.const_run_btn["state"]) == "disabled"
                  and str(tab.ktuple_run_btn["state"]) == "disabled",
                  "verify: every other Run button is grayed out")
            check(tab._other_engine_is_running("loop") is True,
                  "verify: a running verification counts as 'other' for loop")
            tab._on_stop_verify()
            check(generation_stop.stop_requested(tmp), "verify: Stop writes the stop request")
            tab._verify_runner.stop()
            tab._on_verify_finished(0)
            check(str(tab.loop_run_btn["state"]) == "normal"
                  and str(tab.verify_run_btn["state"]) == "normal"
                  and not generation_stop.stop_requested(tmp),
                  "verify: finishing unlocks every engine and clears the stop request")
            tab._lock_other_run_buttons("loop")
            check(str(tab.verify_run_btn["state"]) == "disabled",
                  "verify Run is grayed out while a loop run is active")
            tab._unlock_other_run_buttons()
            tab._verify_method_text.set(tab.T("gen.verify_method_sieve"))
            tab._on_verify_method_chosen()
            tab._verify_vars["pass_exp"].set("8")
            tab._on_run_verify()
            cmd = " ".join(str(t) for t in launched[-1][0]) if launched else ""
            check(tab._verify_runner is not None and "v73_verify_store.py" in cmd
                  and "v73_verify_store.py' 29 7 10000000 0 100000000 " in cmd
                  and launched[-1][1] == "v73_verify_store.py",
                  f"verify: the sieve method launches v73_verify_store.py ({cmd[-160:]})")
            tab._verify_runner.stop()
            tab._on_verify_finished(0)
        finally:
            generation_tab_module.WslLoggedRunner = original_runner
        app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    tkinter.messagebox.showinfo = lambda *a, **k: None
    tkinter.messagebox.showerror = lambda *a, **k: None
    _test_verify_section()

    _test_other_engine_is_running_detects_each_combo()
    _test_starting_loop_run_locks_const_and_ktuple_buttons()
    _test_starting_constellation_run_locks_loop_and_ktuple_buttons()
    _test_starting_ktuple_run_locks_loop_and_const_buttons()
    _test_guard_blocks_launch_while_other_engine_running()
    _test_finishing_loop_run_unlocks_all_buttons()
    _test_finishing_ktuple_run_unlocks_all_buttons()
    _test_chained_constellation_batch_keeps_lock_until_genuinely_done()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
