"""The Generation tab's engine selector and v5 knobs reach the Width cap, Auto, the launches
and Restore.

Drives the real app (tkinter, temp portal folder) with the WSL side stubbed: the RAM probe
returns a fixed reading, WslLoggedRunner and the restore launch record the command instead
of starting it. Checks: v4.1 is selected by default with the v5 knob fields disabled and a
Width cap of 1000; picking v5 enables the knobs and raises every Quick-gen Width spinbox's
cap; Auto under v5 fills the floor-scaled window count and lowers the bucket field when RAM
is short, under v4.1 it gives the old recommendation; a bad v5 knob blocks a v5 run but not
a v4.1 run; the pipeline launch carries the engine env and persists the choice; Restore
sizes an orchestrator floor with the persisted engine and passes the RAM-reduced bucket
memory. Windows, real display:
    python unitTests/test_engine_gui_wiring.py
"""
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))

RAM = 3_500_000_000   # an 8 GB host: WSL keeps about half


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


class _Runner:
    """Records the command instead of starting a WSL process."""
    commands = []

    def __init__(self, cmd, *args, **kwargs):
        _Runner.commands.append(cmd)

    def start(self):
        pass

    def is_running(self):
        return True

    def stop(self):
        pass


def main():
    import prime_atlas_v2
    from primeatlas.generation import engine_options, generation_tab, run_budget
    from tkinter import messagebox

    shown = []
    messagebox.showinfo = lambda *a, **k: shown.append(("info", a))
    messagebox.showerror = lambda *a, **k: shown.append(("error", a))
    generation_tab.estimate_wsl_available_ram_bytes = lambda *a, **k: RAM
    generation_tab.WslLoggedRunner = _Runner

    portal = tempfile.mkdtemp(prefix="primeatlas_engine_gui_test_")
    passed = True
    app = None
    try:
        sys.argv = ["prime_atlas_v2.py"]
        app = prime_atlas_v2._build_gui()()
        app.update()
        settings_tab = app.settings_tab
        settings_tab.app_settings.save = lambda: None
        settings_tab.app_settings.set_storage_path(portal)
        settings_tab.wsl["set_portal_folder"](portal)
        app.update()
        gen = app.generation_tab_widget
        fields = gen._engine_fields

        from primeatlas.generation.generation import DEFAULT_GENERATION_SETTINGS
        default_loop = DEFAULT_GENERATION_SETTINGS["loop"]
        passed &= check(engine_options.resolve(default_loop).engine
                        == engine_options.DEFAULT_ENGINE == "v4.1",
                        "default engine is v4.1")
        # The app loads the user's persisted settings, which may already select v5.
        fields.engine_var.set("v4.1")
        app.update()
        passed &= check(all(str(e.cget("state")) == "disabled" for e in fields._knob_entries),
                        "v5 knob fields are disabled under v4.1")
        passed &= check(gen._quick_width_cap() == 1000
                        and gen._validate_quick_width_spinbox("1000")
                        and not gen._validate_quick_width_spinbox("1001"),
                        "v4.1 Width cap is 1000")

        fields.engine_var.set("v5")
        app.update()
        caps = [int(float(s.cget("to"))) for s in gen._quick_width_spinboxes]
        passed &= check(caps and all(c == engine_options.max_windows_per_run("v5") for c in caps),
                        f"v5 raises every Width spinbox cap ({caps})")
        passed &= check(gen._validate_quick_width_spinbox("5000"), "v5 Width accepts 5000")
        passed &= check(all(str(e.cget("state")) == "normal" for e in fields._knob_entries),
                        "v5 knob fields are enabled under v5")

        expected = run_budget.recommend_run(RAM, "v5", 25, 10_000_000)
        gen._on_quick_auto_width_clicked(gen.quick_floor_width_var, 25)
        passed &= check(gen.quick_floor_width_var.get() == str(expected.windows)
                        and fields.knob_vars["v5_bucket_mb"].get() == str(expected.bucket_mb),
                        f"v5 Auto @25: {gen.quick_floor_width_var.get()} windows, "
                        f"{fields.knob_vars['v5_bucket_mb'].get()} MiB "
                        f"(expected {expected.windows}, {expected.bucket_mb})")
        passed &= check(shown and shown[-1][0] == "info", "v5 Auto reports in a dialog")

        floor_var = gen._loop_vars["base_exponent"]
        floor_var.set("25")
        gen._loop_vars["window_count_per_run"].set(str(expected.windows))
        fields.knob_vars["v5_region_kb"].set("abc")
        shown.clear()
        passed &= check(gen._collect_loop_settings_from_form() is None
                        and shown and shown[-1][0] == "error",
                        "a bad v5 knob blocks a v5 run with an error")
        fields.engine_var.set("v4.1")
        parsed = gen._collect_loop_settings_from_form()
        passed &= check(parsed is not None and parsed["engine_choice"].engine == "v4.1",
                        "the same bad knob does not block a v4.1 run")
        gen._on_quick_auto_width_clicked(gen.quick_floor_width_var, 25)
        passed &= check(gen.quick_floor_width_var.get() == "1000",
                        f"v4.1 Auto keeps the old recommendation "
                        f"({gen.quick_floor_width_var.get()})")

        fields.engine_var.set("v5")
        fields.knob_vars["v5_region_kb"].set("2048")
        _Runner.commands.clear()
        gen._on_run_loop()
        bash = _Runner.commands[-1][-1] if _Runner.commands else ""
        passed &= check("PRIMEATLAS_SCANNER_VERSION=v5 " in bash
                        and "PRIMEATLAS_V5_REGION_KB=2048 " in bash
                        and f"PRIMEATLAS_V5_BUCKET_MB={expected.bucket_mb} " in bash,
                        f"pipeline launch carries the v5 env ({bash[:160]}...)")
        loop = gen._generation_settings["loop"]
        passed &= check(loop.get("engine") == "v5" and loop.get("v5_region_kb") == "2048",
                        "the engine choice and knobs are persisted")
        gen._loop_runner = None

        # Restore: an orchestrator floor (25 > primesieve's uint64 reach) with the
        # persisted v5 choice, a full bucket knob and a small RAM reading.
        loop["v5_bucket_mb"] = "1024"
        launched = []
        wsl = settings_tab.wsl
        wsl["estimate_wsl_available_ram_bytes"] = lambda *a, **k: RAM
        wsl["find_continuation_target_idx"] = lambda *a, **k: 0
        wsl["build_wsl_logged_command"] = (
            lambda argv, log, exit_, extra_env=(): launched.append((argv, dict(extra_env))) or ["x"])
        wsl["WslLoggedRunner"] = _Runner
        settings_tab._poll_restore_queue = lambda *a, **k: None
        settings_tab._restore_log = lambda *a, **k: None
        step = SimpleNamespace(base_exponent=25, missing_windows=list(range(10_000)))
        settings_tab._drive_windows_phase(step)
        argv, env = launched[-1] if launched else ([], {})
        passed &= check(env.get("PRIMEATLAS_SCANNER_VERSION") == "v5"
                        and env.get("PRIMEATLAS_V5_BUCKET_MB") == str(expected.bucket_mb)
                        and str(expected.windows) in argv,
                        f"Restore sizes the run with v5 ({expected.windows} windows) and "
                        f"passes the reduced buckets (env {env})")
        settings_tab._restore_runner = None
    finally:
        if app is not None:
            app.destroy()
        shutil.rmtree(portal, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
