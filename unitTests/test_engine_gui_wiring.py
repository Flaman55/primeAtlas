"""The Generation tab's engine selector and the v5/v6 knobs reach the Width cap, Auto, the
launches and Restore.

Drives the real app (tkinter, temp portal folder) with the WSL side stubbed: the RAM probe
returns a fixed reading, WslLoggedRunner and the restore launch record the command instead
of starting it. Checks: the default engine is v6; only the selected engine's knob fields
are shown (the others are hidden and disabled); every shown knob and the engine selector
carry an "i" InfoTip with the knob's info text; a label next to the selector names the
engine version (v5 -> v5.1); v6 Auto fills its own bucket field and the v6 launch carries
the PRIMEATLAS_V6_* knobs and no v5 ones; under v4.1 every knob field is disabled and the
Width cap is 1000; picking v5 enables the knobs and raises every Quick-gen Width spinbox's
cap; Auto under v5 fills the floor-scaled window count and lowers the bucket field when RAM
is short, under v4.1 it gives the old recommendation; a bad v5 knob blocks a v5 run but not
a v4.1 run; pt1 enables only its B and chunk fields, its Auto fills the per-run cap
whatever the RAM, and its launch carries the pt1 env and no v5 knobs; the pipeline launch carries the engine env and persists the choice; Restore
sizes an orchestrator floor with the persisted engine and passes the RAM-reduced bucket
memory; the v5/v6 profile list (Auto, Old, New, Intermediate, Custom) shows only for
those engines, fills their profile fields, switches to Custom on typing, keeps a profile per
engine, is persisted, and Auto picks the knob set by the run's window count. Windows, real
display:
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
    from primeatlas.generation import engine_options, generation_tab, quick_gen_panel, run_budget
    from tkinter import messagebox

    shown = []
    messagebox.showinfo = lambda *a, **k: shown.append(("info", a))
    messagebox.showerror = lambda *a, **k: shown.append(("error", a))
    quick_gen_panel.estimate_wsl_available_ram_bytes = lambda *a, **k: RAM
    generation_tab.WslLoggedRunner = _Runner

    portal = tempfile.mkdtemp(prefix="primeatlas_engine_gui_test_")
    passed = True
    app = None
    try:
        sys.argv = ["prime_atlas_v2.py"]
        from app_sandbox import isolate_app
        isolate_app(portal)
        app = prime_atlas_v2._build_gui()()
        app.update()
        settings_tab = app.settings_tab
        app.update()
        gen = app.generation_tab_widget
        fields = gen._engine_fields

        from primeatlas.generation.generation_settings import DEFAULT_GENERATION_SETTINGS
        default_loop = DEFAULT_GENERATION_SETTINGS["loop"]
        passed &= check(engine_options.resolve(default_loop).engine
                        == engine_options.DEFAULT_ENGINE == "v6",
                        "default engine is v6")
        from primeatlas.core.info_tip import InfoTip
        passed &= check(isinstance(fields.engine_info, InfoTip)
                        and fields.engine_info.text() == gen.T("gen.info_engine"),
                        "the engine selector has its InfoTip")
        passed &= check(all(isinstance(fields.knob_infos[k], InfoTip)
                            and fields.knob_infos[k].text() == gen.T(f"gen.info_{k}")
                            for k in engine_options.KNOB_KEYS),
                        "every knob has an InfoTip with its info text")
        for engine in engine_options.ENGINES:
            fields.engine_var.set(engine)
            app.update()
            own = set(engine_options.engine_knob_keys(engine))
            shown_keys = {k for k, e in fields.knob_entries.items() if e.master.grid_info()}
            passed &= check(shown_keys == own,
                            f"{engine}: only its own knobs are shown ({sorted(shown_keys)})")
            passed &= check(fields.version_var.get()
                            == engine_options.ENGINE_VERSIONS[engine],
                            f"{engine}: version label {fields.version_var.get()!r}")
        tip = fields.knob_infos["v6_bucket_mb"]
        tip.show()
        app.update()
        passed &= check(tip.popup is not None and tip.popup.winfo_exists(),
                        "hovering the i opens the tooltip")
        tip.hide()
        passed &= check(tip.popup is None, "leaving the i closes the tooltip")

        from primeatlas.generation import engine_presets
        for engine in engine_options.ENGINES:
            fields.engine_var.set(engine)
            app.update()
            passed &= check(bool(fields._preset_frame.winfo_manager())
                            == (engine in engine_presets.PRESET_ENGINES),
                            f"{engine}: profile list shown only for v5/v6")
        fields.engine_var.set("v5")
        app.update()
        passed &= check(fields.preset_info.text() == gen.T("gen.info_preset"),
            "the profile list has its InfoTip")
        v6_before = fields.preset("v6")
        fields.set_preset("old")
        passed &= check(fields.knob_vars["v5_segment_kb"].get() == "128"
                        and fields.knob_vars["v5_bucket_mb"].get() == "1024"
                        and fields.preset() == "old",
                        "picking Old fills the v5 profile fields")
        fields.preset_display.set(gen.T("gen.preset_mid"))
        fields._on_preset_picked()
        passed &= check(fields.preset() == "mid"
                        and fields.knob_vars["v5_segment_kb"].get() == "2048"
                        and fields.knob_vars["v5_bucket_mb"].get() == "1024",
                        "picking Intermediate from the list fills its values")
        fields.knob_vars["v5_segment_kb"].set("512")
        passed &= check(fields.preset() == "custom"
                        and fields.preset_display.get() == gen.T("gen.preset_custom"),
                        "typing a profile field switches to Custom")
        passed &= check(fields.preset("v6") == v6_before, "v6 keeps its own profile")
        fields.knob_vars["v5_windows_at_25"].set("20000")
        fields.set_preset("auto")
        passed &= check(fields.knob_vars["v5_bucket_mb"].get() == "8192"
                        and fields.choice(1000)[0].knobs["v5_bucket_mb"] == 1024
                        and fields.choice(10_000)[0].knobs["v5_bucket_mb"] == 8192,
                        "Auto shows New and picks by the run's window count")
        fields.knob_vars["v5_windows_at_25"].set(
            str(engine_options.DEFAULT_KNOBS["v5_windows_at_25"]))
        passed &= check(fields.preset() == "auto", "a sizing knob does not leave the profile")
        passed &= check(fields.settings().get("v5_preset") == "auto"
                        and fields.settings().get("v6_preset") == v6_before,
                        "both profiles are part of the persisted settings")
        fields.set_preset("auto", "v6")
        # The app loads the user's persisted settings, which may already select v5.
        fields.engine_var.set("v4.1")
        app.update()
        states = {key: str(e.cget("state")) for key, e in fields.knob_entries.items()}
        passed &= check(states.pop("ram_budget_pct", None) == "normal"
                        and all(s == "disabled" for s in states.values()),
                        f"under v4.1 only the RAM budget field is enabled ({states})")
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
        passed &= check(all(str(fields.knob_entries[k].cget("state")) == "normal"
                            for k in engine_options.engine_knob_keys("v5")),
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
        fields.knob_vars["ram_budget_pct"].set("25")
        shown.clear()
        gen._on_quick_auto_width_clicked(gen.quick_floor_width_var, 25)
        quarter = run_budget.recommend_run(RAM, "v4.1", 25, 10_000_000, safety_fraction=0.25)
        passed &= check(gen.quick_floor_width_var.get() == str(quarter.windows),
                        f"v4.1 Auto follows a 25 % RAM budget "
                        f"({gen.quick_floor_width_var.get()}, expected {quarter.windows})")
        passed &= check(shown and "25 %" in str(shown[-1][1]),
                        "the Auto dialog names the RAM budget used")
        fields.knob_vars["ram_budget_pct"].set("50")

        fields.engine_var.set("pt1")
        app.update()
        states = {key: str(e.cget("state")) for key, e in fields.knob_entries.items()}
        passed &= check(states["pt1_b"] == states["pt1_chunk_kb"] == "normal"
                        and all(states[k] == "disabled" for k in engine_options.engine_knob_keys("v5")),
                        f"pt1 enables its own fields only ({states})")
        gen._on_quick_auto_width_clicked(gen.quick_floor_width_var, 29)
        passed &= check(gen.quick_floor_width_var.get()
                        == str(engine_options.max_windows_per_run("pt1")),
                        f"pt1 Auto is not RAM-capped ({gen.quick_floor_width_var.get()})")
        fields.knob_vars["pt1_b"].set("12345")
        gen._loop_vars["window_count_per_run"].set("10")
        _Runner.commands.clear()
        gen._on_run_loop()
        bash = _Runner.commands[-1][-1] if _Runner.commands else ""
        passed &= check("PRIMEATLAS_SCANNER_VERSION=pt1 " in bash
                        and "PRIMEATLAS_PT1_B=12345 " in bash
                        and "PRIMEATLAS_V5_" not in bash,
                        f"pipeline launch carries the pt1 env ({bash[:160]}...)")
        gen._loop_runner = None
        gen._loop_vars["window_count_per_run"].set(str(expected.windows))

        fields.engine_var.set("v6")
        app.update()
        expected6 = run_budget.recommend_run(
            RAM, "v6", 25, 10_000_000, bucket_mb=engine_options.DEFAULT_KNOBS["v6_bucket_mb"],
            target_at_25=engine_options.DEFAULT_KNOBS["v6_windows_at_25"],
            max_windows=engine_options.max_windows_per_run("v6"))
        gen._on_quick_auto_width_clicked(gen.quick_floor_width_var, 25)
        passed &= check(gen.quick_floor_width_var.get() == str(expected6.windows)
                        and fields.knob_vars["v6_bucket_mb"].get() == str(expected6.bucket_mb),
                        f"v6 Auto @25 fills its own fields ({gen.quick_floor_width_var.get()} "
                        f"windows, {fields.knob_vars['v6_bucket_mb'].get()} MiB; expected "
                        f"{expected6})")
        gen._loop_vars["window_count_per_run"].set(str(expected6.windows))
        fields.knob_vars["v6_segment_kb"].set("1024")
        _Runner.commands.clear()
        gen._on_run_loop()
        bash = _Runner.commands[-1][-1] if _Runner.commands else ""
        passed &= check("PRIMEATLAS_SCANNER_VERSION=v6 " in bash
                        and "PRIMEATLAS_V6_SEGMENT_KB=1024 " in bash
                        and f"PRIMEATLAS_V6_BUCKET_MB={expected6.bucket_mb} " in bash
                        and "PRIMEATLAS_V5_" not in bash,
                        f"pipeline launch carries the v6 env only ({bash[:200]}...)")
        gen._loop_runner = None
        gen._loop_vars["window_count_per_run"].set(str(expected.windows))

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
