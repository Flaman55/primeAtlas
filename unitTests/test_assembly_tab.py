"""
test_assembly_tab.py -- spec tests for the assembly mode of the Visualization > Tree sub-tab
(primeatlas/visualization/tree/tree_tab.py's TreeTab) and its argv builder
(primeatlas/visualization/assembly/assembly_argv.py).

Spec:
  A. build_assembly_argv: renderer.py as a plain script path, --source none, --viz-mode
     assembly, --upto N; every optional value is omitted when None/empty and forwarded
     verbatim otherwise.
  B. Placement: the Visualization sub-tabs are Rings and Tree only; the Tree sub-tab has a
     visualization-mode selector (tree, assembly), tree on a first run.
  C. Switching: the tree-only options are shown in tree mode and the assembly-only
     options in assembly mode, never both; the common options (n, value-label cap, HUD and
     label font, node size, colors) stay the same widgets in both modes.
  D. Assembly launch: --viz-mode assembly with the assembly fields and the common ones
     (--assembly-label-font-size, --assembly-node-size, --assembly-colors,
     --assembly-max-labels, --hud-font-size); console/status texts are the assembly ones;
     the mode selector is locked while it runs; the HUD N (the period) does not go back
     into the n field; tree_viz_params records viz_mode "assembly" and the assembly
     fields (assembly_* keys). First-run assembly defaults: 6 steps, 12 frames, 60 ms,
     cell size 12, spacing auto. Back in tree mode a launch is the tree again.
  E. Empty storage in assembly mode: the same fill offer; Cancel starts the bare
     animation (--assembly-bare).
  F. Locales: every assembly.* key the tab uses (its own and the base's runtime keys)
     exists in both locale files; the mode labels exist under tree.*.

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
    from primeatlas.visualization.assembly.assembly_argv import build_assembly_argv, RENDERER_SCRIPT
    argv = build_assembly_argv(500, python_executable="PY")
    check(argv[:2] == ["PY", RENDERER_SCRIPT], f"plain script path launch (got {argv[:2]})")
    check(RENDERER_SCRIPT.replace("\\", "/").endswith("visualization/shared/renderer.py"),
          "the assembly launches the shared renderer")
    check(_value(argv, "--source") == "none" and _value(argv, "--viz-mode") == "assembly"
          and _value(argv, "--upto") == "500", f"--source none --viz-mode assembly --upto 500 (got {argv})")
    for flag in ("--assembly-depth", "--assembly-frames", "--assembly-colors", "--tempo-ms",
                 "--assembly-cell-spacing", "--assembly-bare", "--pipe-stdin-commands"):
        check(flag not in argv, f"{flag} is omitted by default")
    argv = build_assembly_argv(10**25, depth=5, frames=9, tempo_ms=200, lane_dots=30, detail_cells=999,
                               max_labels=77, max_lanes=12345, node_size=12.0, cell_size=6.0,
                               hud_font_size=20, label_font_size=14, colors="2=#ff0000",
                               cell_spacing="40", pipe_stdin_commands=True)
    expected = {"--upto": str(10**25), "--assembly-depth": "5", "--assembly-frames": "9", "--tempo-ms": "200",
                "--assembly-lane-dots": "30", "--assembly-detail-cells": "999", "--assembly-max-labels": "77",
                "--assembly-max-lanes": "12345", "--assembly-node-size": "12.0", "--assembly-cell-size": "6.0",
                "--hud-font-size": "20", "--assembly-label-font-size": "14", "--assembly-colors": "2=#ff0000",
                "--assembly-cell-spacing": "40"}
    for flag, value in expected.items():
        check(_value(argv, flag) == value, f"{flag} = {value} (got {_value(argv, flag)!r})")
    check("--pipe-stdin-commands" in argv, "--pipe-stdin-commands when asked")
    check("--assembly-bare" in build_assembly_argv(5, bare=True), "--assembly-bare only when asked")


def _write_fake_renderer(exit_code, linger_seconds=0.5):
    fd, path = tempfile.mkstemp(suffix="_fake_assembly_renderer.py")
    with os.fdopen(fd, "w") as f:
        f.write("import sys, time\n"
                "print('fake assembly renderer: ready', flush=True)\n"
                "print('HUD_STATE:' + '{\"n\": 30030, \"count\": 5760, \"rebuild_ms\": 1.0, \"lines\": [], "
                "\"running\": false, \"tempo_ms\": 60}', flush=True)\n"
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


def _set(entry, text):
    entry.delete(0, "end")
    entry.insert(0, text)


def _packed(widget):
    return widget.winfo_manager() != ""


def section_bcde_app():
    print("\n--- B: placement ---")
    import tkinter.messagebox
    shown = []
    tkinter.messagebox.showerror = lambda *a, **k: shown.append(a)

    sys.argv = ["prime_atlas_v2.py"]
    import prime_atlas_v2
    import primeatlas.visualization.tree.tree_tab as tree_tab_module
    settings = prime_atlas_v2.APP_SETTINGS
    settings.save = lambda: None
    settings._data.pop("tree_viz_params", None)
    from primeatlas.settings.settings_tab import SettingsTab
    SettingsTab._check_for_app_update = lambda self, *a, **k: None

    launched = []
    real_runner = tree_tab_module.LocalLoggedRunner

    class _RecordingRunner(real_runner):
        def __init__(self, cmd, *args, **kwargs):
            launched.append(list(cmd))
            super().__init__(cmd, *args, **kwargs)

    tree_tab_module.LocalLoggedRunner = _RecordingRunner
    tree_tab_module.find_highest_populated_floor = lambda portal: 0

    app = prime_atlas_v2._build_gui()()
    app.update()
    T = prime_atlas_v2.TRANSLATOR.t
    sub = app.visualization_sub_notebook
    sub_tabs = [sub.tab(t, "text") for t in sub.tabs()]
    check(sub_tabs == [T("tabs.visualization_rings"), T("tabs.visualization_tree")],
          f"the Visualization sub-tabs are Rings and Tree only (got {sub_tabs})")
    check(not hasattr(app, "assembly_tab_widget"), "no separate Assembly sub-tab")
    tab = app.tree_tab_widget
    check(tab.current_mode() == "tree", f"first run: tree mode (got {tab.current_mode()})")

    print("\n--- C: switching ---")
    check(_packed(tab.tree_options) and not _packed(tab.assembly_options), "tree mode shows only the tree options")
    common = [tab.n_entry, tab.max_labels_entry, tab.hud_font_size_entry, tab.label_font_size_entry,
              tab.node_size_entry, tab.colors_entry]
    tab.set_mode("assembly")
    app.update()
    check(tab.current_mode() == "assembly", "the selector switches to assembly")
    check(_packed(tab.assembly_options) and not _packed(tab.tree_options),
          "assembly mode shows only the assembly options")
    check(all(_packed(w.master) or _packed(w) for w in common) and
          [tab.n_entry, tab.max_labels_entry, tab.hud_font_size_entry, tab.label_font_size_entry,
           tab.node_size_entry, tab.colors_entry] == common, "the common options stay, the same widgets")
    first_run = {"assembly_depth_entry": "6", "frames_entry": "12", "assembly_tempo_ms_entry": "60",
                 "cell_size_entry": "12", "cell_spacing_entry": "auto"}
    got = {attr: getattr(tab, attr).get() for attr in first_run}
    check(got == first_run, f"first-run assembly defaults (got {got})")

    print("\n--- D: assembly launch ---")
    fake = _write_fake_renderer(0)
    tree_tab_module.RENDERER_SCRIPT = fake
    import primeatlas.visualization.assembly.assembly_argv as assembly_argv_module
    assembly_argv_module.RENDERER_SCRIPT = fake
    _set(tab.n_entry, "10**6")
    _set(tab.assembly_depth_entry, "5")
    _set(tab.frames_entry, "4")
    _set(tab.label_font_size_entry, "21")
    _set(tab.node_size_entry, "13")
    _set(tab.colors_entry, "2=#ff0000")
    _set(tab.max_labels_entry, "777")
    _set(tab.hud_font_size_entry, "22")
    launched.clear()
    tab._on_open()
    argv = launched[-1] if launched else []
    check(_value(argv, "--viz-mode") == "assembly" and _value(argv, "--upto") == str(10**6),
          f"an assembly launch (got {argv})")
    expected = {"--assembly-depth": "5", "--assembly-frames": "4", "--tempo-ms": "60",
                "--assembly-label-font-size": "21", "--assembly-node-size": "13.0", "--assembly-colors": "2=#ff0000",
                "--assembly-max-labels": "777", "--hud-font-size": "22", "--assembly-cell-spacing": "auto"}
    for flag, value in expected.items():
        check(_value(argv, flag) == value, f"{flag} = {value} (got {_value(argv, flag)!r})")
    check("--tree-depth" not in argv, "no tree arguments")
    check(tab.status.get() == tab.T("assembly.status_launching"),
          f"the status uses the assembly texts (got {tab.status.get()!r})")
    check(str(tab.mode_combo["state"]) == "disabled", "the mode selector is locked while it runs")
    _pump_until_idle(app, tab)
    check(str(tab.mode_combo["state"]) == "readonly", "the selector unlocks once it exits")
    check(tab.n_entry.get() == "10**6", f"the HUD N (the period) does not overwrite n (got {tab.n_entry.get()!r})")
    saved = settings._data.get("tree_viz_params") or {}
    check(saved.get("viz_mode") == "assembly" and saved.get("assembly_depth") == "5"
          and saved.get("frames") == "4" and saved.get("label_font_size") == "21",
          f"tree_viz_params records the mode and the fields (got {saved})")

    tab.set_mode("tree")
    launched.clear()
    tab._on_open()
    argv = launched[-1] if launched else []
    check(_value(argv, "--viz-mode") == "tree" and _value(argv, "--tree-label-font-size") == "21"
          and _value(argv, "--tree-node-size") == "13.0",
          f"back in tree mode: a tree launch with the common values (got {argv})")
    check(tab.status.get() == tab.T("tree.status_launching"), "tree texts again")
    _pump_until_idle(app, tab)

    print("\n--- E: empty storage ---")
    tab.set_mode("assembly")
    tree_tab_module.find_highest_populated_floor = lambda portal: None
    tab._ask_generate_range = lambda default_from, default_to: None
    launched.clear()
    tab._on_open()
    check(launched and "--assembly-bare" in launched[-1] and _value(launched[-1], "--viz-mode") == "assembly",
          "Cancel starts the bare animation")
    _pump_until_idle(app, tab)
    tree_tab_module.find_highest_populated_floor = lambda portal: 0
    os.remove(fake)
    app.destroy()


def section_f_locales():
    print("\n--- F: locales ---")
    import re
    src = open(os.path.join(_REPO_ROOT, "primeatlas", "visualization", "tree", "tree_tab.py"),
               encoding="utf-8").read()
    base = open(os.path.join(_REPO_ROOT, "primeatlas", "visualization", "shared", "viz_tab_base.py"),
                encoding="utf-8").read()
    runtime = set(re.findall(r'_tk\("([a-z_]+)"', base)) | set(re.findall(r'return "(error_generate_[a-z_]+)"', base))
    runtime |= {"error_dialog_title", "error_n_invalid"}
    used = runtime | set(re.findall(r'_ak\("([a-z_]+)"', src)) | set(re.findall(r'"assembly\.([a-z_]+)"', src))
    locales = os.path.join(_REPO_ROOT, "primeatlas", "core", "locales")
    for name in ("strings_en.json", "strings_pl.json"):
        data = json.load(open(os.path.join(locales, name), encoding="utf-8"))
        missing = sorted(k for k in used if f"assembly.{k}" not in data)
        check(not missing, f"{name} has every assembly.* key used (missing {missing})")
        for key in ("mode_label", "mode_tree", "mode_assembly", "section_common"):
            check(f"tree.{key}" in data, f"{name} has tree.{key}")
        check("tabs.visualization_assembly" not in data, f"{name}: no Assembly sub-tab title left")


if __name__ == "__main__":
    for section in (section_a_argv, section_bcde_app, section_f_locales):
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
