"""
test_sphere_tab.py -- spec tests for primeatlas/visualization/sphere/sphere_tab.py's
SphereTab, the Visualization > Sphere sub-tab.

Spec:
  A. build_sphere_argv: renderer.py as a plain script path, --source none, --viz-mode
     sphere (or the given viz-mode), --upto N; --portal-folder only when given; every
     optional value is omitted when None and forwarded verbatim otherwise.
  B. Placement: Sphere is the third Visualization sub-tab, after Rings and Tree, with its
     own SphereTab widget; its visualization-mode selector offers rings and fibers.
  C. Launch: an invalid N shows an error and launches nothing; a valid N launches the
     renderer (a fake script here) with the tab's field values and the storage folder,
     locks the launch fields while it runs and unlocks them once it exits; the last HUD N
     goes back into the N field; the fields are persisted as sphere_viz_params. On a first
     run the fields hold the defaults: 200 rings, 8 frames per N, tempo 60, spin 0.4, step 1,
     chunk 100000, 96 segments, 1000 curves, point 9, node 22, HUD and label font 35, playback
     step N, 32 visible fibers, pair cap 2000000, 30 fiber samples, fibers resonance; the
     playback-step selector offers N and p and goes out as --sphere-step.
  F. Fibers: with the fibers mode selected Start launches --viz-mode sphere_fibers with
     --sphere-fibers (the fibers selector: resonance or lineage), --sphere-visible-fibers,
     --sphere-pair-cap and --sphere-fiber-samples; the mode and the fibers kind are
     persisted; the rings mode sends none of the fibers arguments.
  G. Draw rings: a checkbox, on by default; off sends --sphere-hide-rings (in both modes),
     on sends nothing; it is persisted as show_rings.
  D. Locales: every sphere.* key used exists in both strings_en.json and strings_pl.json
     (the base's storage-fill dialog keys included), and tabs.visualization_sphere.
  E. Empty storage: Start asks for a range to generate (From empty, To = N); Generate hands
     it to the app's storage-fill offer without opening the renderer and a successful fill
     starts the sphere by itself, a failed one only reports; Cancel starts the sphere
     without a storage (no --portal-folder). Without an offer callable Start launches
     directly.

Usage:
    python unitTests/test_sphere_tab.py
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
    print("\n--- A: build_sphere_argv ---")
    from primeatlas.visualization.sphere.sphere_tab import build_sphere_argv, RENDERER_SCRIPT
    argv = build_sphere_argv(500, python_executable="PY")
    check(argv[:2] == ["PY", RENDERER_SCRIPT], f"plain script path launch (got {argv[:2]})")
    check(RENDERER_SCRIPT.replace("\\", "/").endswith("visualization/shared/renderer.py"),
          "the sphere launches the shared renderer")
    check(_value(argv, "--source") == "none" and _value(argv, "--viz-mode") == "sphere"
          and _value(argv, "--upto") == "500", f"--source none --viz-mode sphere --upto 500 (got {argv})")
    for flag in ("--portal-folder", "--sphere-rings", "--tempo-ms", "--pipe-stdin-commands", "--sphere-step",
                 "--sphere-fibers", "--sphere-visible-fibers", "--sphere-pair-cap", "--sphere-fiber-samples"):
        check(flag not in argv, f"{flag} is omitted by default")
    argv = build_sphere_argv(10 ** 25, portal_folder="D:/P", rings=300, frames=5, tempo_ms=90, spin=1.5, n_step=7,
                             chunk=5000, segments=64, max_curves=50, point_size=6.0, node_size=30.0,
                             hud_font_size=20, label_font_size=14, step="p", pipe_stdin_commands=True,
                             viz_mode="sphere_fibers", fibers="lineage", visible_fibers=12, pair_cap=999,
                             fiber_samples=40)
    expected = {"--upto": str(10 ** 25), "--portal-folder": "D:/P", "--sphere-rings": "300", "--sphere-frames": "5",
                "--tempo-ms": "90", "--sphere-spin": "1.5", "--n-step": "7", "--sphere-chunk": "5000",
                "--sphere-segments": "64", "--sphere-max-curves": "50", "--sphere-point-size": "6.0",
                "--sphere-node-size": "30.0", "--hud-font-size": "20", "--sphere-label-font-size": "14",
                "--sphere-step": "p", "--viz-mode": "sphere_fibers", "--sphere-fibers": "lineage",
                "--sphere-visible-fibers": "12", "--sphere-pair-cap": "999", "--sphere-fiber-samples": "40"}
    for flag, value in expected.items():
        check(_value(argv, flag) == value, f"{flag} = {value} (got {_value(argv, flag)!r})")
    check("--pipe-stdin-commands" in argv, "--pipe-stdin-commands when asked")


def _write_fake_renderer(exit_code, linger_seconds=0.5):
    fd, path = tempfile.mkstemp(suffix="_fake_sphere_renderer.py")
    with os.fdopen(fd, "w") as f:
        f.write("import sys, time\n"
                "print('fake sphere renderer: ready', flush=True)\n"
                "print('HUD_STATE:' + '{\"n\": 4321, \"count\": 200, \"rebuild_ms\": 1.0, \"lines\": [], "
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


def section_bc_app():
    print("\n--- B/C: placement and launch ---")
    import tkinter.messagebox
    shown = []
    tkinter.messagebox.showerror = lambda *a, **k: shown.append(a)

    sys.argv = ["prime_atlas_v2.py"]
    import prime_atlas_v2
    import primeatlas.visualization.sphere.sphere_tab as sphere_tab_module
    settings = prime_atlas_v2.APP_SETTINGS
    settings.save = lambda: None
    settings._data.pop("sphere_viz_params", None)
    from primeatlas.settings.settings_tab import SettingsTab
    SettingsTab._check_for_app_update = lambda self, *a, **k: None

    launched = []
    real_runner = sphere_tab_module.LocalLoggedRunner

    class _RecordingRunner(real_runner):
        def __init__(self, cmd, *args, **kwargs):
            launched.append(list(cmd))
            super().__init__(cmd, *args, **kwargs)

    sphere_tab_module.LocalLoggedRunner = _RecordingRunner
    sphere_tab_module.find_highest_populated_floor = lambda portal: 0

    app = prime_atlas_v2._build_gui()()
    app.update()
    T = prime_atlas_v2.TRANSLATOR.t
    sub = app.visualization_sub_notebook
    sub_tabs = [sub.tab(t, "text") for t in sub.tabs()]
    check(sub_tabs[:3] == [T("tabs.visualization_rings"), T("tabs.visualization_tree"),
                           T("tabs.visualization_sphere")],
          f"the Visualization sub-tabs are Rings, Tree, Sphere (got {sub_tabs})")
    tab = app.sphere_tab_widget
    check(str(tab.master) == str(app.visualization_sphere_tab), "SphereTab is built inside the Sphere sub-tab")
    check(tab.current_mode() == "rings"
          and list(tab.mode_combo.cget("values")) == [T("sphere.mode_rings"), T("sphere.mode_fibers")],
          "the mode selector offers rings and fibers")
    check(tab.current_fibers() == "resonance"
          and list(tab.fibers_combo.cget("values")) == [T("sphere.fibers_resonance"), T("sphere.fibers_lineage")],
          "the fibers selector offers resonance (default) and lineage")
    first_run = {"rings_entry": "200", "frames_entry": "8", "tempo_ms_entry": "60", "spin_entry": "0.4",
                 "n_step_entry": "1", "chunk_entry": "100000", "segments_entry": "96", "max_curves_entry": "1000",
                 "point_size_entry": "9", "node_size_entry": "22", "hud_font_size_entry": "35",
                 "label_font_size_entry": "35", "visible_fibers_entry": "32", "pair_cap_entry": "2000000",
                 "fiber_samples_entry": "30"}
    got = {attr: getattr(tab, attr).get() for attr in first_run}
    check(got == first_run, f"first-run field defaults (got {got})")
    check(tab.current_step() == "n" and list(tab.step_combo.cget("values")) == [T("sphere.step_n"), T("sphere.step_p")],
          "the playback step offers N (default) and p")

    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "garbage")
    tab._on_open()
    check(len(shown) == 1 and not launched, "an invalid N shows an error and launches nothing")
    shown.clear()

    fake = _write_fake_renderer(0)
    sphere_tab_module.RENDERER_SCRIPT = fake
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "10**6")
    tab.rings_entry.delete(0, "end")
    tab.rings_entry.insert(0, "333")
    tab.step_combo.current(1)
    tab._on_open()
    check(not shown and launched, "a valid N launches the renderer")
    argv = launched[-1] if launched else []
    check(_value(argv, "--upto") == str(10 ** 6) and _value(argv, "--sphere-rings") == "333"
          and _value(argv, "--tempo-ms") == "60" and _value(argv, "--sphere-step") == "p"
          and "--pipe-stdin-commands" in argv,
          f"the launch carries the tab's values (got {argv})")
    check(_value(argv, "--viz-mode") == "sphere" and "--sphere-fibers" not in argv
          and "--sphere-pair-cap" not in argv, "the rings mode sends no fibers arguments")
    check(_value(argv, "--portal-folder") == str(prime_atlas_v2.PORTAL_FOLDER),
          f"the storage folder is passed (got {_value(argv, '--portal-folder')!r})")
    check(str(tab.n_entry["state"]) == "disabled" and str(tab.open_button["state"]) == "disabled"
          and str(tab.mode_combo["state"]) == "disabled" and str(tab.step_combo["state"]) == "disabled",
          "launch fields and Start are locked while the renderer runs")
    _pump_until_idle(app, tab)
    check(str(tab.n_entry["state"]) == "normal" and str(tab.open_button["state"]) == "normal",
          "fields and Start unlock once the renderer exits")
    check(tab.n_entry.get() == "4321", f"the last HUD N goes back into the N field (got {tab.n_entry.get()!r})")
    saved = settings._data.get("sphere_viz_params") or {}
    check(saved.get("n") == "10**6" and saved.get("rings") == "333" and saved.get("viz_mode") == "rings"
          and saved.get("step") == "p",
          f"the fields are persisted as sphere_viz_params (got {saved})")

    _section_f_fibers(app, tab, settings, launched)
    _section_e_empty_storage(app, tab, sphere_tab_module, launched)
    os.remove(fake)
    app.destroy()


def _section_f_fibers(app, tab, settings, launched):
    print("\n--- F: fibers ---")
    tab.mode_combo.current(1)
    tab.fibers_combo.current(1)
    tab.visible_fibers_entry.delete(0, "end")
    tab.visible_fibers_entry.insert(0, "50")
    launched.clear()
    tab._on_open()
    argv = launched[-1] if launched else []
    check(_value(argv, "--viz-mode") == "sphere_fibers" and _value(argv, "--sphere-fibers") == "lineage"
          and _value(argv, "--sphere-visible-fibers") == "50" and _value(argv, "--sphere-pair-cap") == "2000000"
          and _value(argv, "--sphere-fiber-samples") == "30", f"the fibers launch (got {argv})")
    check(str(tab.fibers_combo["state"]) == "disabled", "the fibers selector is locked while it runs")
    check("--sphere-hide-rings" not in argv, "rings drawn by default: no --sphere-hide-rings")
    _pump_until_idle(app, tab)
    saved = settings._data.get("sphere_viz_params") or {}
    check(saved.get("viz_mode") == "fibers" and saved.get("fibers") == "lineage" and saved.get("visible_fibers") == "50",
          f"mode and fibers kind persisted (got {saved})")
    print("\n--- G: draw rings ---")
    check(tab.show_rings_var.get() is True, "draw rings is on by default")
    tab.show_rings_var.set(False)
    launched.clear()
    tab._on_open()
    argv = launched[-1] if launched else []
    check("--sphere-hide-rings" in argv, f"off sends --sphere-hide-rings (got {argv})")
    _pump_until_idle(app, tab)
    saved = settings._data.get("sphere_viz_params") or {}
    check(saved.get("show_rings") is False, f"persisted as show_rings (got {saved.get('show_rings')!r})")
    tab.show_rings_var.set(True)
    tab.mode_combo.current(0)
    tab.fibers_combo.current(0)


def _section_e_empty_storage(app, tab, sphere_tab_module, launched):
    print("\n--- E: empty storage ---")
    check(tab._offer_generate_storage is not None, "the app injects the storage-fill offer")
    sphere_tab_module.find_highest_populated_floor = lambda portal: None
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
    check(launched and not offered and "--portal-folder" not in launched[-1],
          "Cancel starts the sphere without a storage")
    _pump_until_idle(app, tab)

    answer["value"] = (2, 5000)
    launched.clear()
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "5000")
    tab._on_open()
    check(not launched and len(offered) == 1 and offered[0][:2] == (2, 5000),
          f"Generate hands (2, 5000) to the offer and does not open the renderer (got {offered})")
    check(tab.status.get() == tab.T("sphere.status_generating_storage", start="2", end="5,000"),
          f"the status bar says the storage is being generated (got {tab.status.get()!r})")
    sphere_tab_module.find_highest_populated_floor = lambda portal: 0
    offered[0][2](True)
    check(launched and "--portal-folder" in launched[-1], "a successful fill starts the sphere with the storage")
    _pump_until_idle(app, tab)
    launched.clear()
    offered[0][2](False)
    check(not launched and tab.status.get() == tab.T("sphere.status_storage_fill_failed"),
          f"a failed fill only reports (got {tab.status.get()!r})")

    sphere_tab_module.find_highest_populated_floor = lambda portal: None
    tab._offer_generate_storage = None
    asked.clear()
    tab._on_open()
    check(not asked and launched, "without an offer callable Start launches directly")
    _pump_until_idle(app, tab)
    tab._offer_generate_storage = real_offer


def section_d_locales():
    print("\n--- D: locales ---")
    import re
    src = open(os.path.join(_REPO_ROOT, "primeatlas", "visualization", "sphere", "sphere_tab.py"),
               encoding="utf-8").read()
    used = set(re.findall(r'_tk\("([a-z_]+)"', src)) | set(re.findall(r'"sphere\.([a-z_]+)"', src))
    used |= set(re.findall(r'"([a-z_]+_label)", "[a-z_]+", "[^"]*", "[a-z]+"\)', src))
    base = open(os.path.join(_REPO_ROOT, "primeatlas", "visualization", "shared", "viz_tab_base.py"),
                encoding="utf-8").read()
    used |= set(re.findall(r'_tk\("([a-z_]+)"', base))
    used |= set(re.findall(r'return "(error_generate_[a-z_]+)"', base))
    locales = os.path.join(_REPO_ROOT, "primeatlas", "core", "locales")
    for name in ("strings_en.json", "strings_pl.json"):
        data = json.load(open(os.path.join(locales, name), encoding="utf-8"))
        missing = sorted(k for k in used if f"sphere.{k}" not in data)
        check(not missing, f"{name} has every sphere.* key used (missing {missing})")
        check("tabs.visualization_sphere" in data, f"{name} has tabs.visualization_sphere")
    check(len(used) > 40, f"the key scan found the tab's keys ({len(used)})")


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
