"""
test_rings_tab.py -- tests for primeatlas/rings_tab.py's RingsTab (Faza 3 of the
ring-visualization rollout, see PLAN.md at the repo root).

Two layers, same split as most tab test files in this folder:

1. build_renderer_argv() is pure argv construction (no tkinter) -- checked directly,
   no app/display needed at all.

2. The RingsTab widget itself is exercised against a REAL local subprocess, not a
   mocked LocalLoggedRunner -- monkeypatching primeatlas.rings_tab.RENDERER_SCRIPT to
   point at a tiny fixture script (written to a temp file) that just prints a couple
   of lines and exits 0 or 1, instead of the real primeatlas/ring_viz/renderer.py
   (which imports moderngl/glfw and needs a real GPU/display -- neither exists in
   this sandbox, and isn't the point of this test anyway). This exercises the actual
   LocalLoggedRunner subprocess-launch + queue-drain + __exit__ handling end-to-end,
   which is exactly what LocalLoggedRunner's own docstring says it's meant to be
   testable against ("a trivial local command ... without any WSL install required").
   No moderngl/glfw import ever happens on this path.

Usage (Windows, real display):
    python unitTests\\test_rings_tab.py

Usage (this sandbox, headless):
    PYTHONPATH="/tmp/tkextract/usr/lib/python3.10:/tmp/tkextract/usr/lib/python3.10/lib-dynload:$PYTHONPATH" \\
    LD_LIBRARY_PATH="/tmp/tkextract/usr/lib:$LD_LIBRARY_PATH" \\
    xvfb-run -a python3 unitTests/test_rings_tab.py
"""
import os
import sys
import tempfile
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
# primeatlas/__init__.py imports manifest.py, which imports window_sharding --
# needed even just to import primeatlas.rings_tab for _test_build_renderer_argv
# below, same reason test_ring_viz_renderer.py adds this (see that file).
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_build_renderer_argv():
    from primeatlas.rings_tab import build_renderer_argv, RENDERER_SCRIPT

    argv = build_renderer_argv("/some/portal", 12345, python_executable="FAKE_PY")
    check(argv[0] == "FAKE_PY", f"argv[0] is the given python_executable (got {argv[0]!r})")
    check(argv[1] == RENDERER_SCRIPT,
          f"argv[1] is the renderer script's PLAIN PATH, not a -m module spec "
          f"(got {argv[1]!r}) -- see renderer.py's own docstring for why -m breaks "
          f"its internal sys.path fix")
    check("--source" in argv and argv[argv.index("--source") + 1] == "magazyn",
          "argv includes --source magazyn")
    check("--portal-folder" in argv and argv[argv.index("--portal-folder") + 1] == "/some/portal",
          "argv includes --portal-folder with the given folder")
    check("--upto" in argv and argv[argv.index("--upto") + 1] == "12345",
          "argv includes --upto with the given N as a string")

    default_argv = build_renderer_argv("/x", 1)
    check(default_argv[0] == sys.executable,
          f"python_executable defaults to sys.executable, THIS interpreter, not a bare "
          f"'python' resolved from PATH (got {default_argv[0]!r})")
    check("--windows" not in default_argv,
          f"no --windows arg at all when windows=() (matches renderer.py's own default "
          f"of no highlighting) (got {default_argv!r})")

    # [ADDED Faza 4, see PLAN.md] Window-highlight-family argv wiring.
    windows_argv = build_renderer_argv("/x", 1, windows=["bertrand", "legendre"])
    check("--windows" in windows_argv and windows_argv[windows_argv.index("--windows") + 1] == "bertrand,legendre",
          f"--windows joins the given family ids with commas (got {windows_argv!r})")
    check("--general-law-theta" not in windows_argv,
          f"--general-law-theta is omitted when generalLaw isn't among the enabled windows "
          f"(got {windows_argv!r})")

    gl_argv = build_renderer_argv("/x", 1, windows=["generalLaw"], general_law_theta=0.7,
                                   general_law_mode="sliding")
    check("--general-law-theta" in gl_argv and gl_argv[gl_argv.index("--general-law-theta") + 1] == "0.7",
          f"--general-law-theta is included and correct when generalLaw IS enabled (got {gl_argv!r})")
    check("--general-law-mode" in gl_argv and gl_argv[gl_argv.index("--general-law-mode") + 1] == "sliding",
          f"--general-law-mode is included and correct when generalLaw IS enabled (got {gl_argv!r})")

    # [ADDED Faza 4 point-size investigation, see PLAN.md / task #593] point_size argv wiring.
    check("--point-size" not in default_argv,
          f"no --point-size arg at all when point_size=None (matches renderer.py's own "
          f"argparse default) (got {default_argv!r})")
    ps_argv = build_renderer_argv("/x", 1, point_size=12.5)
    check("--point-size" in ps_argv and ps_argv[ps_argv.index("--point-size") + 1] == "12.5",
          f"--point-size is included and correct when a value is given (got {ps_argv!r})")

    # [ADDED Faza 6, see PLAN.md] Track P / auto-orbit argv wiring.
    check("--track-primes" not in default_argv,
          f"no --track-primes arg at all when track_primes=() (matches renderer.py's "
          f"own default of no tracking) (got {default_argv!r})")
    check("--auto-orbit" not in default_argv,
          f"no --auto-orbit flag at all when auto_orbit=False (got {default_argv!r})")
    tp_argv = build_renderer_argv("/x", 1, track_primes=["2", "3", "5"])
    check("--track-primes" in tp_argv and tp_argv[tp_argv.index("--track-primes") + 1] == "2,3,5",
          f"--track-primes joins the given values with commas, preserving order "
          f"(got {tp_argv!r})")
    ao_argv = build_renderer_argv("/x", 1, auto_orbit=True)
    check("--auto-orbit" in ao_argv, f"--auto-orbit flag is included when auto_orbit=True (got {ao_argv!r})")
    # Deliberately str(p), not int(p) -- a raw, unvalidated string from the Track P
    # text field must pass through here without raising, even if it's garbage;
    # renderer.py's own --track-primes parsing is where validation happens (same
    # convention as --windows's unknown-family check) -- see build_renderer_argv's
    # own doc-comment for why.
    garbage_argv = build_renderer_argv("/x", 1, track_primes=["2", "not-a-number"])
    check("--track-primes" in garbage_argv and
          garbage_argv[garbage_argv.index("--track-primes") + 1] == "2,not-a-number",
          f"a non-numeric track_primes entry passes through as a plain string instead "
          f"of raising inside the GUI thread (got {garbage_argv!r})")

    # [ADDED Faza 9, see PLAN.md] Load Range argv wiring.
    check("--load-range" not in default_argv,
          f"no --load-range arg at all when load_range=None (matches renderer.py's own "
          f"default of sequential mode) (got {default_argv!r})")
    lr_argv = build_renderer_argv("/x", 1, load_range=(100, 500))
    check("--load-range" in lr_argv and lr_argv[lr_argv.index("--load-range") + 1] == "100,500",
          f"--load-range joins the (from, to) pair with a comma (got {lr_argv!r})")

    # [ADDED Faza 11C, see PLAN.md -- Artur's real-screen HUD-too-small +
    # independent hit-point-size report] hit_point_size/hud_font_size argv
    # wiring, mirroring point_size's own omit-if-None convention exactly.
    # [UPDATED Artur, 2026-09-09] renderer.py's own argparse defaults are now
    # 40.0 / 35 (previously None-falls-back-to-point-size / 16px) -- this
    # test only checks build_renderer_argv's own function-level default
    # (None omits the flag from argv), which is unchanged; the actual
    # numeric value that then applies lives in renderer.py's argparse, not
    # here.
    check("--hit-point-size" not in default_argv,
          f"no --hit-point-size arg at all when hit_point_size=None (renderer.py's own "
          f"argparse default of 40.0 then applies) (got {default_argv!r})")
    check("--hud-font-size" not in default_argv,
          f"no --hud-font-size arg at all when hud_font_size=None (renderer.py's own "
          f"argparse default of 35px then applies) (got {default_argv!r})")
    hps_argv = build_renderer_argv("/x", 1, hit_point_size=8.0)
    check("--hit-point-size" in hps_argv and hps_argv[hps_argv.index("--hit-point-size") + 1] == "8.0",
          f"--hit-point-size is included and correct when a value is given (got {hps_argv!r})")
    hfs_argv = build_renderer_argv("/x", 1, hud_font_size=32)
    check("--hud-font-size" in hfs_argv and hfs_argv[hfs_argv.index("--hud-font-size") + 1] == "32",
          f"--hud-font-size is included and correct when a value is given (got {hfs_argv!r})")


def _write_fake_renderer(exit_code):
    """A stand-in for primeatlas/ring_viz/renderer.py that never touches moderngl/glfw
    -- just proves the real subprocess round trip (launch, live stdout lines, exit
    code) works, independent of anything GPU/display-related. Ignores its argv
    entirely (real renderer.py's own argv contract is covered separately by
    _test_build_renderer_argv above)."""
    fd, path = tempfile.mkstemp(suffix="_fake_renderer.py")
    with os.fdopen(fd, "w") as f:
        f.write(
            "import sys\n"
            "print('fake renderer: loading magazyn...')\n"
            "print('fake renderer: ready')\n"
            f"sys.exit({exit_code})\n"
        )
    return path


def _pump(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def main():
    _test_build_renderer_argv()

    import tkinter.messagebox
    shown = []
    tkinter.messagebox.showerror = lambda *a, **k: shown.append(("error", a, k))

    sys.argv = ["prime_atlas_v1.py"]
    import prime_atlas_v1
    import primeatlas.rings_tab as rings_tab_module
    app_cls = prime_atlas_v1._build_gui()
    app = app_cls()
    app.update()
    tab = app.rings_tab_widget

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_rings_tab_test_portal_")

    # --- N-hint field: live floor guess, no crash on garbage input ------------------
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "12345")
    tab._on_n_changed()
    check(tab.n_hint_var.get() != "", "a valid numeric N produces a non-empty floor hint")

    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "not a number")
    tab._on_n_changed()
    check(tab.n_hint_var.get() == tab.T("rings.hint_invalid"),
          f"garbage input shows the invalid-number hint, does not raise "
          f"(got {tab.n_hint_var.get()!r})")

    # --- error path: no N entered ----------------------------------------------------
    tab.n_entry.delete(0, "end")
    shown.clear()
    tab._on_open()
    check(len(shown) == 1 and shown[0][0] == "error",
          "opening with an empty N field shows an error dialog instead of launching")
    check(tab._runner is None, "no runner was started for the empty-N case")

    # --- success path: real subprocess, fake renderer script, exit 0 ----------------
    fake_ok_script = _write_fake_renderer(0)
    rings_tab_module.RENDERER_SCRIPT = fake_ok_script
    tab._get_portal_folder = lambda: tmp_portal
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    shown.clear()
    tab._on_open()
    check(str(tab.open_button["state"]) == "disabled",
          "open button disabled immediately after launch")
    check(str(tab.stop_button["state"]) == "normal",
          "stop button enabled immediately after launch")
    _pump(app, 3.0)
    check(str(tab.open_button["state"]) == "normal",
          "open button re-enabled after the fake renderer process exits 0")
    check(str(tab.stop_button["state"]) == "disabled",
          "stop button disabled again after the fake renderer process exits 0")
    check(tab._runner is None, "runner reference cleared after a clean exit")
    console_text = tab.console.text.get("1.0", "end")
    check("fake renderer: ready" in console_text,
          f"the fake renderer's real stdout line reached the console pane "
          f"(got console text: {console_text!r})")
    check("--track-primes" not in console_text and "--auto-orbit" not in console_text,
          f"empty Track P field + unchecked Auto orbit means neither flag reaches "
          f"the launched argv (got console text: {console_text!r})")
    os.remove(fake_ok_script)

    # --- [ADDED Faza 6, see PLAN.md] Track P field + Auto orbit checkbox wiring ----
    # Uses runner.cmd directly (the actual argv LocalLoggedRunner launched)
    # rather than scraping console text, which is cumulative across every
    # _on_open() call in this test and would make substring checks fragile.
    fake_ok_script2 = _write_fake_renderer(0)
    rings_tab_module.RENDERER_SCRIPT = fake_ok_script2
    tab.track_primes_entry.delete(0, "end")
    tab.track_primes_entry.insert(0, "2, 3, 5")
    tab.auto_orbit_var.set(True)
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    shown.clear()
    tab._on_open()
    launched_cmd = list(tab._runner.cmd) if tab._runner is not None else []
    check("--track-primes" in launched_cmd and
          launched_cmd[launched_cmd.index("--track-primes") + 1] == "2,3,5",
          f"Track P field's comma-separated value reaches the launched argv, "
          f"whitespace stripped (got argv: {launched_cmd!r})")
    check("--auto-orbit" in launched_cmd,
          f"checked Auto orbit checkbox adds --auto-orbit to the launched argv "
          f"(got argv: {launched_cmd!r})")
    _pump(app, 3.0)
    os.remove(fake_ok_script2)
    tab.track_primes_entry.delete(0, "end")
    tab.auto_orbit_var.set(False)

    # --- [ADDED Faza 9, see PLAN.md] Load Range From/To field wiring ----------------
    fake_ok_script3 = _write_fake_renderer(0)
    rings_tab_module.RENDERER_SCRIPT = fake_ok_script3
    tab.load_range_from_entry.delete(0, "end")
    tab.load_range_from_entry.insert(0, "100")
    tab.load_range_to_entry.delete(0, "end")
    tab.load_range_to_entry.insert(0, "500")
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    shown.clear()
    tab._on_open()
    launched_cmd = list(tab._runner.cmd) if tab._runner is not None else []
    check("--load-range" in launched_cmd and
          launched_cmd[launched_cmd.index("--load-range") + 1] == "100,500",
          f"both From/To fields filled in reach the launched argv as --load-range "
          f"FROM,TO (got argv: {launched_cmd!r})")
    _pump(app, 3.0)
    os.remove(fake_ok_script3)

    # Leaving one field blank must NOT activate range mode (silent fallback to
    # sequential, per _on_open's own doc-comment -- no crash, no --load-range).
    fake_ok_script4 = _write_fake_renderer(0)
    rings_tab_module.RENDERER_SCRIPT = fake_ok_script4
    tab.load_range_from_entry.delete(0, "end")
    tab.load_range_from_entry.insert(0, "100")
    tab.load_range_to_entry.delete(0, "end")  # To left blank
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    shown.clear()
    tab._on_open()
    launched_cmd = list(tab._runner.cmd) if tab._runner is not None else []
    check("--load-range" not in launched_cmd,
          f"a half-filled Load Range (From set, To blank) omits --load-range entirely, "
          f"does not raise (got argv: {launched_cmd!r})")
    _pump(app, 3.0)
    os.remove(fake_ok_script4)
    tab.load_range_from_entry.delete(0, "end")
    tab.load_range_to_entry.delete(0, "end")

    # --- [ADDED Faza 11, see PLAN.md] HUD panel: direct _apply_hud_state unit test --
    tab.hud_var.set("stale")
    tab._apply_hud_state(
        '{"n": 1234, "count": 56, "rebuild_ms": 2.5, "lines": ["line one", "line two"], '
        '"running": true, "tempo_ms": 80}'
    )
    hud_text = tab.hud_var.get()
    check("1,234" in hud_text and "56" in hud_text,
          f"HUD panel header shows N and ring count, thousands-separated (got {hud_text!r})")
    check("line one" in hud_text and "line two" in hud_text,
          f"HUD panel body includes every hud line (got {hud_text!r})")
    check("80" in hud_text, f"HUD panel shows the current running tempo (got {hud_text!r})")

    tab._apply_hud_state("not valid json{{{")
    check(tab.hud_var.get() == hud_text,
          "malformed HUD_STATE JSON is silently ignored -- panel keeps its last good value")

    tab._apply_hud_state('{"n": 7, "count": 1, "rebuild_ms": 0.1, "lines": [], "running": false, "tempo_ms": 120}')
    hud_text_stopped = tab.hud_var.get()
    check(tab.T("rings.hud_status_stopped") in hud_text_stopped,
          f"a stopped/running=false state shows the stopped status text (got {hud_text_stopped!r})")

    # --- [ADDED Faza 11] end-to-end: a fake renderer emitting a real HUD_STATE line --
    fd, fake_hud_script = tempfile.mkstemp(suffix="_fake_renderer_hud.py")
    with os.fdopen(fd, "w") as f:
        f.write(
            "import sys\n"
            "print('fake renderer: loading magazyn...')\n"
            "print('HUD_STATE:{\"n\": 42, \"count\": 3, \"rebuild_ms\": 1.2, "
            "\"lines\": [\"N = 42\"], \"running\": false, \"tempo_ms\": 120}')\n"
            "sys.exit(0)\n"
        )
    rings_tab_module.RENDERER_SCRIPT = fake_hud_script
    tab._get_portal_folder = lambda: tmp_portal
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    shown.clear()
    tab._on_open()
    _pump(app, 3.0)
    hud_text2 = tab.hud_var.get()
    check("42" in hud_text2, f"HUD panel updated from a real subprocess's HUD_STATE stdout line (got {hud_text2!r})")
    console_text2 = tab.console.text.get("1.0", "end")
    check("HUD_STATE:" not in console_text2,
          f"HUD_STATE lines are routed to the panel, never appended to the scrolling console pane "
          f"(got console text: {console_text2!r})")
    check("fake renderer: loading magazyn..." in console_text2,
          f"ordinary (non-HUD_STATE) lines from the same process still reach the console normally "
          f"(got console text: {console_text2!r})")
    os.remove(fake_hud_script)

    # --- failure path: real subprocess, fake renderer script, exit 1 ----------------
    fake_fail_script = _write_fake_renderer(1)
    rings_tab_module.RENDERER_SCRIPT = fake_fail_script
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    tab._on_open()
    _pump(app, 3.0)
    check(str(tab.open_button["state"]) == "normal",
          "open button re-enabled after the fake renderer process exits nonzero")
    console_text = tab.console.text.get("1.0", "end")
    check(tab.status.get() == tab.T("rings.status_error"),
          f"status bar shows the error-path message after a nonzero exit "
          f"(got {tab.status.get()!r})")
    check(tab.T("rings.console_closed_error", code=1) in console_text,
          f"console pane shows the exit-code-1 message (got console text: "
          f"{console_text!r})")
    os.remove(fake_fail_script)

    # --- error path: portal folder missing -------------------------------------------
    tab._get_portal_folder = lambda: os.path.join(tmp_portal, "does_not_exist")
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    shown.clear()
    tab._on_open()
    check(len(shown) == 1 and shown[0][0] == "error",
          "opening with a nonexistent portal folder shows an error dialog instead of "
          "launching")
    check(tab._runner is None, "no runner was started for the missing-portal case")

    app.destroy()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
