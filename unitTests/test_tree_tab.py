"""
test_tree_tab.py -- spec tests for primeatlas/visualization/tree/tree_tab.py's TreeTab, the
Visualization > Tree sub-tab.

Spec:
  A. build_tree_argv: renderer.py as a plain script path, --source none, --viz-mode tree,
     --upto N; every optional value is omitted when None and forwarded verbatim
     otherwise; highlight layers are comma-joined.
  B. Placement: Tree is the second Visualization sub-tab, next to Rings, with its own
     TreeTab widget.
  C. Launch: an invalid N shows an error and launches nothing; a valid N launches the
     renderer (a fake script here) with the tab's field values, locks the launch fields
     while it runs and unlocks them once it exits; the fields are persisted as
     tree_viz_params.
  D. Locales: every tree.* key used exists in both strings_en.json and strings_pl.json.

Usage:
    python unitTests/test_tree_tab.py
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
    print("\n--- A: build_tree_argv ---")
    from primeatlas.visualization.tree.tree_tab import build_tree_argv, RENDERER_SCRIPT
    argv = build_tree_argv(500, python_executable="PY")
    check(argv[:2] == ["PY", RENDERER_SCRIPT], f"plain script path launch (got {argv[:2]})")
    check(RENDERER_SCRIPT.replace("\\", "/").endswith("visualization/shared/renderer.py"),
          "the tree launches the shared renderer")
    check(_value(argv, "--source") == "none" and _value(argv, "--viz-mode") == "tree"
          and _value(argv, "--upto") == "500", f"--source none --viz-mode tree --upto 500 (got {argv})")
    for flag in ("--tree-depth", "--tree-branches", "--tree-highlight", "--tree-colors", "--n-step", "--tree-axis",
                 "--pipe-stdin-commands"):
        check(flag not in argv, f"{flag} is omitted by default")
    argv = build_tree_argv(10**25, depth=5, branches=4, height=1.5, n_step=7, tempo_ms=200,
                           max_nodes=999, max_points=12345, multiples=5, axis="multiples", colors="2=#ff0000", highlight=["primes"],
                           max_stripes=3, node_size=12.0, point_size=6.0, hud_font_size=20,
                           label_font_size=14, pipe_stdin_commands=True)
    expected = {"--upto": str(10**25), "--tree-depth": "5", "--tree-branches": "4", "--tree-height": "1.5",
                "--n-step": "7", "--tempo-ms": "200", "--tree-max-nodes": "999", "--tree-max-points": "12345",
                "--tree-multiples": "5", "--tree-axis": "multiples",
                "--tree-colors": "2=#ff0000", "--tree-highlight": "primes", "--tree-max-stripes": "3",
                "--tree-node-size": "12.0", "--point-size": "6.0", "--hud-font-size": "20",
                "--tree-label-font-size": "14"}
    for flag, value in expected.items():
        check(_value(argv, flag) == value, f"{flag} = {value} (got {_value(argv, flag)!r})")
    check("--pipe-stdin-commands" in argv, "--pipe-stdin-commands when asked")


def _write_fake_renderer(exit_code, linger_seconds=0.5):
    fd, path = tempfile.mkstemp(suffix="_fake_tree_renderer.py")
    with os.fdopen(fd, "w") as f:
        f.write("import sys, time\n"
                "print('fake tree renderer: ready', flush=True)\n"
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

    app = prime_atlas_v2._build_gui()()
    app.update()
    T = prime_atlas_v2.TRANSLATOR.t
    sub = app.visualization_sub_notebook
    sub_tabs = [sub.tab(t, "text") for t in sub.tabs()]
    check(sub_tabs[:2] == [T("tabs.visualization_rings"), T("tabs.visualization_tree")],
          f"the Visualization sub-tabs are Rings then Tree (got {sub_tabs})")
    tab = app.tree_tab_widget
    check(str(tab.master) == str(app.visualization_tree_tab), "TreeTab is built inside the Tree sub-tab")

    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "garbage")
    tab._on_open()
    check(len(shown) == 1 and not launched, "an invalid N shows an error and launches nothing")
    shown.clear()

    fake = _write_fake_renderer(0)
    tree_tab_module.RENDERER_SCRIPT = fake
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "10**6")
    tab.depth_entry.delete(0, "end")
    tab.depth_entry.insert(0, "5")
    tab.branches_entry.delete(0, "end")
    tab.branches_entry.insert(0, "4")
    tab.highlight_vars["primes"].set(True)
    tab._on_open()
    check(not shown and launched, "a valid N launches the renderer")
    argv = launched[-1] if launched else []
    check(_value(argv, "--upto") == str(10**6) and _value(argv, "--tree-depth") == "5"
          and _value(argv, "--tree-branches") == "4" and _value(argv, "--tree-highlight") == "primes"
          and "--pipe-stdin-commands" in argv,
          f"the launch carries the tab's values (got {argv})")
    check(str(tab.n_entry["state"]) == "disabled" and str(tab.open_button["state"]) == "disabled",
          "launch fields and Start are locked while the renderer runs")
    _pump_until_idle(app, tab)
    check(str(tab.n_entry["state"]) == "normal" and str(tab.open_button["state"]) == "normal",
          "fields and Start unlock once the renderer exits")
    check(tab.n_entry.get() == "321", f"the last HUD N goes back into the N field (got {tab.n_entry.get()!r})")
    saved = settings._data.get("tree_viz_params") or {}
    check(saved.get("n") == "10**6" and saved.get("depth") == "5" and saved.get("highlight_primes") is True,
          f"the fields are persisted as tree_viz_params (got {saved})")
    os.remove(fake)
    app.destroy()


def section_d_locales():
    print("\n--- D: locales ---")
    import re
    src = open(os.path.join(_REPO_ROOT, "primeatlas", "visualization", "tree", "tree_tab.py"),
               encoding="utf-8").read()
    used = set(re.findall(r'_tk\("([a-z_]+)"', src)) | set(re.findall(r'"tree\.([a-z_]+)"', src))
    base = open(os.path.join(_REPO_ROOT, "primeatlas", "visualization", "shared", "viz_tab_base.py"),
                encoding="utf-8").read()
    used |= set(re.findall(r'_tk\("([a-z_]+)"', base))
    locales = os.path.join(_REPO_ROOT, "primeatlas", "core", "locales")
    for name in ("strings_en.json", "strings_pl.json"):
        data = json.load(open(os.path.join(locales, name), encoding="utf-8"))
        missing = sorted(k for k in used if f"tree.{k}" not in data)
        check(not missing, f"{name} has every tree.* key used (missing {missing})")
        check("tabs.visualization_tree" in data, f"{name} has tabs.visualization_tree")


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
