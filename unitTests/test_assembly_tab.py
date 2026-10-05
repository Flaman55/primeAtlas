"""
test_assembly_tab.py -- spec tests for primeatlas/visualization/assembly/assembly_tab.py's
AssemblyTab, the Visualization > Assembly sub-tab.

Spec:
  A. build_assembly_argv: renderer.py as a plain script path, --source none, --viz-mode
     assembly, --upto N; every optional value is omitted when None and forwarded verbatim
     otherwise.
  B. Placement: Assembly is the third Visualization sub-tab, after Rings and Tree, with
     its own AssemblyTab widget.
  C. Launch: an invalid N shows an error and launches nothing; a valid N launches the
     renderer (a fake script here) with the tab's values, locks the launch fields while
     it runs and unlocks them once it exits; the fields are persisted as
     assembly_viz_params; the HUD N (the period) never goes back into the N field (N is
     the label base). First-run defaults: 6 steps, 12 frames per phase, 60 ms/tick,
     HUD and label font 35, node size 15, cell size 12.
  D. Locales: every assembly.* key used exists in both strings_en.json and
     strings_pl.json (the base's storage-fill dialog keys included).
  E. Empty storage: the same fill offer as the Tree sub-tab; Cancel starts the bare
     animation (--assembly-bare), a successful fill the normal one.

Usage:
    python unitTests/test_assembly_tab.py
"""
import json
import os
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


def _value(argv, flag):
    return argv[argv.index(flag) + 1] if flag in argv else None


def section_a_argv():
    print("\n--- A: build_assembly_argv ---")
    from primeatlas.visualization.assembly.assembly_tab import build_assembly_argv, RENDERER_SCRIPT
    argv = build_assembly_argv(500, python_executable="PY")
    check(argv[:2] == ["PY", RENDERER_SCRIPT], f"plain script path launch (got {argv[:2]})")
    check(RENDERER_SCRIPT.replace("\\", "/").endswith("visualization/shared/renderer.py"),
          "the assembly launches the shared renderer")
    check(_value(argv, "--source") == "none" and _value(argv, "--viz-mode") == "assembly"
          and _value(argv, "--upto") == "500", f"--source none --viz-mode assembly --upto 500 (got {argv})")
    for flag in ("--assembly-depth", "--assembly-frames", "--assembly-colors", "--tempo-ms",
                 "--assembly-bare", "--pipe-stdin-commands"):
        check(flag not in argv, f"{flag} is omitted by default")
    argv = build_assembly_argv(10**25, depth=5, frames=9, tempo_ms=200, lane_dots=30, detail_cells=999,
                               max_labels=77, max_lanes=12345, node_size=12.0, cell_size=6.0,
                               hud_font_size=20, label_font_size=14, colors="2=#ff0000",
                               pipe_stdin_commands=True)
    expected = {"--upto": str(10**25), "--assembly-depth": "5", "--assembly-frames": "9", "--tempo-ms": "200",
                "--assembly-lane-dots": "30", "--assembly-detail-cells": "999", "--assembly-max-labels": "77",
                "--assembly-max-lanes": "12345", "--assembly-node-size": "12.0", "--assembly-cell-size": "6.0",
                "--hud-font-size": "20", "--assembly-label-font-size": "14", "--assembly-colors": "2=#ff0000"}
    for flag, value in expected.items():
        check(_value(argv, flag) == value, f"{flag} = {value} (got {_value(argv, flag)!r})")
    check("--pipe-stdin-commands" in argv, "--pipe-stdin-commands when asked")
    check("--assembly-bare" in build_assembly_argv(5, bare=True), "--assembly-bare only when asked")


def _write_fake_renderer(exit_code, linger_seconds=0.5):
    fd, path = tempfile.mkstemp(suffix="_fake_assembly_renderer.py")
    with os.fdopen(fd, "w") as f:
        f.write("import sys, time\n"
                "print('fake assembly renderer: ready', flush=True)\n"
                "print('HUD_STATE:' + '{\"n\": 321, \"count\": 28, \"rebuild_ms\": 1.0, \"lines\": [], "
                "\"running\": false, \"tempo_ms\": 120}', flush=True)\n"
                f"time.sleep({linger_seconds})\n"
                f"sys.exit({exit_code})\n")
    return path


def _pump(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def _pump_until_idle(app, tab, timeout=30.0):
    deadline = time.time() + timeout
    while tab._runner is not None and time.time() < deadline:
        app.update()
        time.sleep(0.02)
    _pump(app, 0.2)


def section_bc_app():
    print("\n--- B/C: placement and launch ---")
    import tkinter.messagebox
    shown = []
    tkinter.messagebox.showerror = lambda *a, **k: shown.append(a)

    sys.argv = ["prime_atlas_v2.py"]
    import prime_atlas_v2
    import primeatlas.visualization.assembly.assembly_tab as assembly_tab_module
    settings = prime_atlas_v2.APP_SETTINGS
    settings.save = lambda: None
    settings._data.pop("assembly_viz_params", None)
    from primeatlas.settings.settings_tab import SettingsTab
    SettingsTab._check_for_app_update = lambda self, *a, **k: None

    launched = []
    real_runner = assembly_tab_module.LocalLoggedRunner

    class _RecordingRunner(real_runner):
        def __init__(self, cmd, *args, **kwargs):
            launched.append(list(cmd))
            super().__init__(cmd, *args, **kwargs)

    assembly_tab_module.LocalLoggedRunner = _RecordingRunner
    assembly_tab_module.find_highest_populated_floor = lambda portal: 0

    app = prime_atlas_v2._build_gui()()
    app.update()
    T = prime_atlas_v2.TRANSLATOR.t
    sub = app.visualization_sub_notebook
    sub_tabs = [sub.tab(t, "text") for t in sub.tabs()]
    check(sub_tabs[:3] == [T("tabs.visualization_rings"), T("tabs.visualization_tree"),
                           T("tabs.visualization_assembly")],
          f"the Visualization sub-tabs are Rings, Tree, Assembly (got {sub_tabs})")
    tab = app.assembly_tab_widget
    check(str(tab.master) == str(app.visualization_assembly_tab), "AssemblyTab is built inside its sub-tab")
    first_run = {"depth_entry": "6", "frames_entry": "12", "tempo_ms_entry": "60", "hud_font_size_entry": "35",
                 "label_font_size_entry": "35", "node_size_entry": "15", "cell_size_entry": "12"}
    got = {attr: getattr(tab, attr).get() for attr in first_run}
    check(got == first_run, f"first-run field defaults (got {got})")

    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "garbage")
    tab._on_open()
    check(len(shown) == 1 and not launched, "an invalid N shows an error and launches nothing")
    shown.clear()

    fake = _write_fake_renderer(0)
    assembly_tab_module.RENDERER_SCRIPT = fake
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "10**6")
    tab.depth_entry.delete(0, "end")
    tab.depth_entry.insert(0, "5")
    tab.frames_entry.delete(0, "end")
    tab.frames_entry.insert(0, "4")
    tab._on_open()
    check(not shown and launched, "a valid N launches the renderer")
    argv = launched[-1] if launched else []
    check(_value(argv, "--upto") == str(10**6) and _value(argv, "--assembly-depth") == "5"
          and _value(argv, "--assembly-frames") == "4" and "--pipe-stdin-commands" in argv,
          f"the launch carries the tab's values (got {argv})")
    check(str(tab.n_entry["state"]) == "disabled" and str(tab.open_button["state"]) == "disabled",
          "launch fields and Start are locked while the renderer runs")
    _pump_until_idle(app, tab)
    check(str(tab.n_entry["state"]) == "normal" and str(tab.open_button["state"]) == "normal",
          "fields and Start unlock once the renderer exits")
    check(tab.n_entry.get() == "10**6",
          f"the HUD N (the period) does not overwrite the N field (got {tab.n_entry.get()!r})")
    saved = settings._data.get("assembly_viz_params") or {}
    check(saved.get("n") == "10**6" and saved.get("depth") == "5" and saved.get("frames") == "4",
          f"the fields are persisted as assembly_viz_params (got {saved})")

    _section_e_empty_storage(app, tab, assembly_tab_module, launched)
    os.remove(fake)
    app.destroy()


def _section_e_empty_storage(app, tab, assembly_tab_module, launched):
    print("\n--- E: empty storage ---")
    check(tab._offer_generate_storage is not None, "the app injects the storage-fill offer")
    assembly_tab_module.find_highest_populated_floor = lambda portal: None
    asked, offered = [], []
    answer = {"value": None}
    tab._ask_generate_range = lambda default_from, default_to: (asked.append((default_from, default_to)),
                                                                 answer["value"])[1]

    def fake_offer(start, end_inclusive, on_finished):
        offered.append((start, end_inclusive, on_finished))
        return True

    real_offer = tab._offer_generate_storage
    tab._offer_generate_storage = fake_offer
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "5000")
    launched.clear()
    tab._on_open()
    check(asked == [("", "5000")], f"asked with From empty and To = N (got {asked})")
    check(launched and not offered, "Cancel starts the animation anyway and generates nothing")
    check(launched and "--assembly-bare" in launched[-1], "Cancel starts the bare animation")
    _pump_until_idle(app, tab)

    answer["value"] = (2, 5000)
    asked.clear()
    launched.clear()
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "5000")
    tab._on_open()
    check(not launched and len(offered) == 1 and offered[0][:2] == (2, 5000),
          f"Generate hands (2, 5000) to the offer and does not open the renderer (got {offered})")
    check(tab.status.get() == tab.T("assembly.status_generating_storage", start="2", end="5,000"),
          f"the status bar says the storage is being generated (got {tab.status.get()!r})")
    assembly_tab_module.find_highest_populated_floor = lambda portal: 0
    offered[0][2](True)
    check(launched and "--assembly-bare" not in launched[-1], "a successful fill starts the normal animation")
    _pump_until_idle(app, tab)
    launched.clear()
    offered[0][2](False)
    check(not launched and tab.status.get() == tab.T("assembly.status_storage_fill_failed"),
          f"a failed fill only reports (got {tab.status.get()!r})")

    assembly_tab_module.find_highest_populated_floor = lambda portal: None
    tab._offer_generate_storage = None
    asked.clear()
    tab._on_open()
    check(not asked and launched, "without an offer callable Start launches directly")
    _pump_until_idle(app, tab)
    tab._offer_generate_storage = real_offer


def section_d_locales():
    print("\n--- D: locales ---")
    import re
    src = open(os.path.join(_REPO_ROOT, "primeatlas", "visualization", "assembly", "assembly_tab.py"),
               encoding="utf-8").read()
    used = set(re.findall(r'_tk\("([a-z_]+)"', src)) | set(re.findall(r'"assembly\.([a-z_]+)"', src))
    base = open(os.path.join(_REPO_ROOT, "primeatlas", "visualization", "shared", "viz_tab_base.py"),
                encoding="utf-8").read()
    used |= set(re.findall(r'_tk\("([a-z_]+)"', base))
    # parse_generate_range returns these keys; the dialog translates them.
    used |= set(re.findall(r'return "(error_generate_[a-z_]+)"', base))
    locales = os.path.join(_REPO_ROOT, "primeatlas", "core", "locales")
    for name in ("strings_en.json", "strings_pl.json"):
        data = json.load(open(os.path.join(locales, name), encoding="utf-8"))
        missing = sorted(k for k in used if f"assembly.{k}" not in data)
        check(not missing, f"{name} has every assembly.* key used (missing {missing})")
        check("tabs.visualization_assembly" in data, f"{name} has tabs.visualization_assembly")


if __name__ == "__main__":
    for section in (section_a_argv, section_bc_app, section_d_locales):
        try:
            section()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(False, f"{section.__name__} raised {type(e).__name__}: {e}")
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
