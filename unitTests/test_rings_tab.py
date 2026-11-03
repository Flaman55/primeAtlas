"""
test_rings_tab.py -- tests for primeatlas/visualization/rings/rings_tab.py's RingsTab
widget. build_renderer_argv(), the pure argv construction (no tkinter), is checked in
test_rings_tab_argv.py.

The RingsTab widget itself is exercised against a REAL local subprocess, not a
mocked LocalLoggedRunner -- monkeypatching primeatlas.visualization.rings.rings_tab.RENDERER_SCRIPT to
point at a tiny fixture script (written to a temp file) that just prints a couple
of lines and exits 0 or 1, instead of the real primeatlas/visualization/shared/renderer.py
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
# needed to import primeatlas.visualization.rings.rings_tab at all.
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


_LAUNCHED_ARGV = []


def _patch_app_settings(app_settings):
    """Neuters persistence so this test's many _on_open() calls (each now also writing
    ring_viz_params, see rings_tab.py's own doc-comment) never touch the real
    primeatlas/locales/app_settings.json -- same convention as every other tab test
    file's own _patch_app_settings (e.g. test_primes_tab.py).

    Also drops the in-memory ring_viz_params READ from that real file: RingsTab
    pre-fills its fields (Track P, Auto orbit, load range...) from them, so whatever was
    last used in the real app would leak into this test's "empty field -> no flag"
    checks. Nothing is written back -- save() is neutered above."""
    app_settings.save = lambda: None
    app_settings._data.pop("ring_viz_params", None)


def _stub_app_update_check():
    """Settings > Updates starts a background `check_for_update()` (GitHub API / git
    fetch) when the app is built. In this test that meant network access, and its worker
    thread's self.after() raised "main thread is not in main loop" -- this test drives Tk
    with update() instead of mainloop(), and Tkinter only accepts calls from other threads
    while mainloop() runs. The check is unrelated to the Rings tab, so it is not started."""
    from primeatlas.settings.settings_tab import SettingsTab
    SettingsTab._check_for_app_update = lambda self, *a, **k: None


def _write_fake_renderer(exit_code, linger_seconds=0.5):
    """A stand-in for primeatlas/visualization/shared/renderer.py that never touches moderngl/glfw
    -- just proves the real subprocess round trip (launch, live stdout lines, exit
    code) works, independent of anything GPU/display-related. Ignores its argv
    entirely (real renderer.py's own argv contract is covered separately by
    _test_build_renderer_argv above).

    It lingers linger_seconds before exiting, like a real renderer window staying open:
    a fake that exited instantly could finish -- and have its exit drained by
    _on_open()'s own synchronous _poll_queue() -- before _on_open() even returned under
    CPU load, so "button disabled right after launch" and "argv of tab._runner" checks
    would see an already-reset tab."""
    fd, path = tempfile.mkstemp(suffix="_fake_renderer.py")
    with os.fdopen(fd, "w") as f:
        f.write(
            "import sys, time\n"
            "print('fake renderer: loading archive...', flush=True)\n"
            "print('fake renderer: ready', flush=True)\n"
            f"time.sleep({linger_seconds})\n"
            f"sys.exit({exit_code})\n"
        )
    return path


def _pump(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def _install_launch_recorder(rings_tab_module):
    """Records each renderer argv the moment RingsTab creates its LocalLoggedRunner.
    Reading tab._runner.cmd AFTER _on_open() returned raced the fake renderer: under
    heavy CPU load the process could exit and _on_open()'s own synchronous
    _poll_queue() drain it -- resetting tab._runner to None -- before the test looked,
    so these argv checks saw [] at random. Recording at construction time does not
    depend on how long the process lives."""
    real_runner = rings_tab_module.LocalLoggedRunner

    class _RecordingRunner(real_runner):
        def __init__(self, cmd, *args, **kwargs):
            _LAUNCHED_ARGV.append(list(cmd))
            super().__init__(cmd, *args, **kwargs)

    rings_tab_module.LocalLoggedRunner = _RecordingRunner


def _open_and_capture(tab):
    """tab._on_open(), returning the argv it launched ([] if it launched nothing)."""
    _LAUNCHED_ARGV.clear()
    tab._on_open()
    return _LAUNCHED_ARGV[-1] if _LAUNCHED_ARGV else []


def _pump_until_idle(app, tab, timeout=30.0):
    """Pumps Tk until the launched (fake) renderer has exited and its exit has been
    drained (tab._runner back to None), then a short settle. Replaces a fixed 3 s wait,
    which under CPU load (full suite, parallel runs) ended before a fake process had even
    started up."""
    deadline = time.time() + timeout
    while tab._runner is not None and time.time() < deadline:
        app.update()
        time.sleep(0.02)
    _pump(app, 0.2)


def _test_empty_storage_offer(app, tab, rings_tab_module, tmp_portal, shown):
    """Spec: Start with an EMPTY storage (no prime window anywhere) does not open the
    renderer; it asks for a range to generate, prefilled from the form -- sequential:
    from empty (= 2), to = N; range: From/To. Generate hands (from, to) to the app's
    storage-fill offer; once that reports success the visualization starts by itself;
    failure only reports. Cancel launches nothing. Without an offer callable (or with
    data in storage) Start launches directly as before."""
    print("\n--- empty storage: offer to generate ---")
    rings_tab_module.find_highest_populated_floor = lambda portal: None
    tab._get_portal_folder = lambda: tmp_portal
    asked = []
    offered = []
    answer = {"value": None}

    def fake_ask(default_from, default_to):
        asked.append((default_from, default_to))
        return answer["value"]

    def fake_offer(start, end_inclusive, on_finished):
        offered.append((start, end_inclusive, on_finished))
        return True

    tab._ask_generate_range = fake_ask
    tab._offer_generate_storage = fake_offer
    tab.mode_var.set("sequential")
    tab._on_mode_changed()
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "5000")
    shown.clear()
    argv = _open_and_capture(tab)
    check(asked == [("", "5000")], f"sequential: asked with from empty and to = N (got {asked})")
    check(argv == [] and tab._runner is None and not offered, "Cancel launches nothing")

    answer["value"] = (2, 5000)
    asked.clear()
    argv = _open_and_capture(tab)
    check(argv == [] and len(offered) == 1 and offered[0][:2] == (2, 5000),
          f"Generate hands (2, 5000) to the storage-fill offer and does not open the renderer (got {offered})")
    check(tab.status.get() == tab.T("rings.status_generating_storage", start="2", end="5,000"),
          f"the status bar says the storage is being generated (got {tab.status.get()!r})")

    fake_ok = _write_fake_renderer(0)
    rings_tab_module.RENDERER_SCRIPT = fake_ok
    rings_tab_module.find_highest_populated_floor = lambda portal: 0
    _LAUNCHED_ARGV.clear()
    offered[0][2](True)
    check(_LAUNCHED_ARGV and "--upto" in _LAUNCHED_ARGV[-1],
          "a successful fill starts the visualization by itself")
    _pump_until_idle(app, tab)
    os.remove(fake_ok)

    rings_tab_module.find_highest_populated_floor = lambda portal: None
    _LAUNCHED_ARGV.clear()
    offered[0][2](False)
    check(not _LAUNCHED_ARGV and tab.status.get() == tab.T("rings.status_storage_fill_failed"),
          f"a failed fill only reports (got {tab.status.get()!r})")

    tab.mode_var.set("range")
    tab._on_mode_changed()
    tab.load_range_from_entry.delete(0, "end")
    tab.load_range_from_entry.insert(0, "100")
    tab.load_range_to_entry.delete(0, "end")
    tab.load_range_to_entry.insert(0, "900")
    asked.clear()
    answer["value"] = None
    _open_and_capture(tab)
    check(asked == [("100", "900")], f"range mode: asked with the range's From/To (got {asked})")
    tab.mode_var.set("sequential")
    tab._on_mode_changed()

    tab._offer_generate_storage = None
    asked.clear()
    fake_ok = _write_fake_renderer(0)
    rings_tab_module.RENDERER_SCRIPT = fake_ok
    argv = _open_and_capture(tab)
    check(not asked and argv, "without an offer callable Start launches directly")
    _pump_until_idle(app, tab)
    os.remove(fake_ok)
    rings_tab_module.find_highest_populated_floor = lambda portal: 0


def main():

    import tkinter.messagebox
    shown = []
    tkinter.messagebox.showerror = lambda *a, **k: shown.append(("error", a, k))

    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    from primeatlas.app import app_dynamic
    import primeatlas.visualization.rings.rings_tab as rings_tab_module
    _patch_app_settings(app_dynamic.APP_SETTINGS)
    _stub_app_update_check()
    _install_launch_recorder(rings_tab_module)
    # The launch flows below use an empty temp folder as the portal; they test what
    # happens with data in storage, so storage reads as populated unless a section
    # (the empty-storage offer at the end) says otherwise.
    rings_tab_module.find_highest_populated_floor = lambda portal: 0
    app_cls = prime_atlas_v2._build_gui()
    app = app_cls()
    app.update()
    tab = app.rings_tab_widget

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_rings_tab_test_portal_")

    # --- placement: Visualization top-level tab -> Rings sub-tab -------------------
    T = app_dynamic.TRANSLATOR.t
    main_tabs = [app.main_notebook.tab(t, "text") for t in app.main_notebook.tabs()]
    check(T("tabs.visualization") in main_tabs and T("tabs.visualization_rings") not in main_tabs,
          f"the main notebook has a Visualization tab and no top-level Rings tab (got {main_tabs})")
    viz_sub = app.visualization_sub_notebook
    check(str(viz_sub.master) == str(app.visualization_tab),
          "the Visualization tab holds its own sub-notebook")
    sub_tabs = [viz_sub.tab(t, "text") for t in viz_sub.tabs()]
    check(sub_tabs[:1] == [T("tabs.visualization_rings")],
          f"the first Visualization sub-tab is Rings (got {sub_tabs})")
    check(str(tab.master) == str(app.visualization_rings_tab),
          "RingsTab is built inside the Visualization > Rings sub-tab")

    # --- layout: Start/Reset are the first thing in the tab ------------------------
    # The launch buttons must sit above the intro and every option section, not below
    # Audio: launching is the tab's primary action.
    button_row = tab.open_button.master
    container = button_row.master
    packed = container.pack_slaves()
    check(tab.stop_button.master is button_row and packed and packed[0] is button_row,
          f"Start/Reset button row is the first packed widget of the tab "
          f"(found at index {packed.index(button_row) if button_row in packed else None})")


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
    _pump_until_idle(app, tab)
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

    # --- Track P field + Auto orbit checkbox wiring ---
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
    launched_cmd = _open_and_capture(tab)
    check("--track-primes" in launched_cmd and
          launched_cmd[launched_cmd.index("--track-primes") + 1] == "2,3,5",
          f"Track P field's comma-separated value reaches the launched argv, "
          f"whitespace stripped (got argv: {launched_cmd!r})")
    check("--auto-orbit" in launched_cmd,
          f"checked Auto orbit checkbox adds --auto-orbit to the launched argv "
          f"(got argv: {launched_cmd!r})")
    _pump_until_idle(app, tab)
    os.remove(fake_ok_script2)
    tab.track_primes_entry.delete(0, "end")
    tab.auto_orbit_var.set(False)

    # --- Mode switch enable/disable wiring --------------------------------
    check(tab.mode_var.get() == "sequential", "mode defaults to sequential")
    check(str(tab.n_entry["state"]) == "normal", "N field starts enabled in sequential mode")
    check(str(tab.load_range_from_entry["state"]) == "disabled",
          "Load Range From field starts disabled in sequential mode")
    check(str(tab.load_range_to_entry["state"]) == "disabled",
          "Load Range To field starts disabled in sequential mode")
    check(str(tab.max_load_count_entry["state"]) == "disabled",
          "Max load count field starts disabled in sequential mode")

    tab.mode_var.set("range")
    tab._on_mode_changed()
    check(str(tab.n_entry["state"]) == "disabled", "N field is disabled once range mode is selected")
    check(str(tab.load_range_from_entry["state"]) == "normal",
          "Load Range From field is enabled once range mode is selected")
    check(str(tab.load_range_to_entry["state"]) == "normal",
          "Load Range To field is enabled once range mode is selected")
    check(str(tab.max_load_count_entry["state"]) == "normal",
          "Max load count field is enabled once range mode is selected")

    tab.mode_var.set("sequential")
    tab._on_mode_changed()
    check(str(tab.n_entry["state"]) == "normal", "N field is re-enabled switching back to sequential mode")
    check(str(tab.load_range_from_entry["state"]) == "disabled",
          "Load Range From field is disabled again switching back to sequential mode")

    # --- Load Range From/To field wiring -- gated on mode_var == "range"
    # (set + _on_mode_changed() to actually enable the fields, mirroring a
    # real Radiobutton click) rather than "both fields happen to be filled
    # in".
    tab.mode_var.set("range")
    tab._on_mode_changed()
    fake_ok_script3 = _write_fake_renderer(0)
    rings_tab_module.RENDERER_SCRIPT = fake_ok_script3
    tab.load_range_from_entry.delete(0, "end")
    tab.load_range_from_entry.insert(0, "100")
    tab.load_range_to_entry.delete(0, "end")
    tab.load_range_to_entry.insert(0, "500")
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    shown.clear()
    launched_cmd = _open_and_capture(tab)
    check("--load-range" in launched_cmd and
          launched_cmd[launched_cmd.index("--load-range") + 1] == "100,500",
          f"range mode with both From/To fields filled in reaches the launched argv as "
          f"--load-range FROM,TO (got argv: {launched_cmd!r})")
    _pump_until_idle(app, tab)
    os.remove(fake_ok_script3)

    # Range mode with one field blank/invalid now fails LOUDLY (an error
    # dialog, no launch at all) instead of falling back to sequential --
    # explicit mode means explicit validation.
    tab.load_range_from_entry.delete(0, "end")
    tab.load_range_from_entry.insert(0, "100")
    tab.load_range_to_entry.delete(0, "end")  # To left blank
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    shown.clear()
    tab._on_open()
    check(len(shown) == 1 and shown[0][0] == "error",
          "range mode with To left blank shows an error dialog instead of launching")
    check(tab._runner is None, "no runner was started for the half-filled-range-mode case")
    tab.load_range_from_entry.delete(0, "end")
    tab.load_range_to_entry.delete(0, "end")

    # Switching BACK to sequential mode must not resurrect a stale
    # From/To -- confirms _on_open reads mode_var, not field contents.
    tab.mode_var.set("sequential")
    tab._on_mode_changed()
    fake_ok_script3b = _write_fake_renderer(0)
    rings_tab_module.RENDERER_SCRIPT = fake_ok_script3b
    tab.load_range_from_entry.configure(state="normal")
    tab.load_range_from_entry.delete(0, "end")
    tab.load_range_from_entry.insert(0, "100")
    tab.load_range_to_entry.configure(state="normal")
    tab.load_range_to_entry.delete(0, "end")
    tab.load_range_to_entry.insert(0, "500")
    tab._on_mode_changed()  # re-disable, as a real mode switch back would
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    shown.clear()
    launched_cmd = _open_and_capture(tab)
    check("--load-range" not in launched_cmd,
          f"sequential mode ignores a leftover From/To in the (now disabled) range fields "
          f"entirely -- no --load-range (got argv: {launched_cmd!r})")
    _pump_until_idle(app, tab)
    os.remove(fake_ok_script3b)
    tab.load_range_from_entry.configure(state="normal")
    tab.load_range_from_entry.delete(0, "end")
    tab.load_range_to_entry.configure(state="normal")
    tab.load_range_to_entry.delete(0, "end")

    # --- Sliding-window checkbox wiring -- gated on mode_var == "range",
    # same as Load Range From/To above. _on_mode_changed() only greys out the
    # checkbox WIDGET, it never clears the underlying BooleanVar -- so a value
    # checked while in range mode (or loaded from a persisted settings file saved
    # during an earlier range-mode session) stays True after switching back to
    # sequential, and must not be forwarded: renderer.py's argparse rejects
    # --slide-load-range without --load-range.
    tab.mode_var.set("range")
    tab._on_mode_changed()
    tab.load_range_from_entry.delete(0, "end")
    tab.load_range_from_entry.insert(0, "100")
    tab.load_range_to_entry.delete(0, "end")
    tab.load_range_to_entry.insert(0, "500")
    tab.slide_load_range_var.set(True)
    fake_ok_script_slide1 = _write_fake_renderer(0)
    rings_tab_module.RENDERER_SCRIPT = fake_ok_script_slide1
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    shown.clear()
    launched_cmd = _open_and_capture(tab)
    check("--slide-load-range" in launched_cmd,
          f"range mode with the sliding-window checkbox checked reaches the launched argv as "
          f"--slide-load-range (got argv: {launched_cmd!r})")
    _pump_until_idle(app, tab)
    os.remove(fake_ok_script_slide1)

    # Switch BACK to sequential mode WITHOUT touching the checkbox itself
    # (mirrors a real leftover value, whether from a real Load Range click
    # earlier in the same run or a persisted settings file) -- must not
    # resurrect --slide-load-range, since renderer.py hard-fails without a
    # --load-range alongside it.
    tab.mode_var.set("sequential")
    tab._on_mode_changed()
    fake_ok_script_slide2 = _write_fake_renderer(0)
    rings_tab_module.RENDERER_SCRIPT = fake_ok_script_slide2
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    shown.clear()
    launched_cmd = _open_and_capture(tab)
    check("--slide-load-range" not in launched_cmd,
          f"sequential mode ignores a leftover checked sliding-window checkbox entirely -- "
          f"no --slide-load-range (got argv: {launched_cmd!r})")
    _pump_until_idle(app, tab)
    os.remove(fake_ok_script_slide2)
    tab.slide_load_range_var.set(False)
    tab.load_range_from_entry.configure(state="normal")
    tab.load_range_from_entry.delete(0, "end")
    tab.load_range_to_entry.configure(state="normal")
    tab.load_range_to_entry.delete(0, "end")

    # --- General Law mode combobox: rigid 'bertrand'/'legendre' values lock the
    # theta entry to a fixed display value instead of leaving it showing a stale
    # editable number. ---------
    check(list(tab.general_law_mode_combo["values"]) == ["stepped", "sliding", "bertrand", "legendre"],
          f"General Law mode combobox offers the two new rigid choices alongside stepped/sliding "
          f"(got {list(tab.general_law_mode_combo['values'])!r})")

    tab.general_law_mode_combo.set("bertrand")
    tab._on_general_law_mode_changed()
    check(tab.general_law_theta_entry.get() == "1",
          f"bertrand mode: theta entry snaps to '1' (got {tab.general_law_theta_entry.get()!r})")
    check(str(tab.general_law_theta_entry["state"]) == "disabled",
          f"bertrand mode: theta entry is disabled (got {tab.general_law_theta_entry['state']!r})")

    tab.general_law_mode_combo.set("sliding")
    tab._on_general_law_mode_changed()
    check(str(tab.general_law_theta_entry["state"]) == "normal",
          f"switching back to sliding: theta entry is editable again (got {tab.general_law_theta_entry['state']!r})")

    tab.general_law_mode_combo.set("legendre")
    tab._on_general_law_mode_changed()
    check(tab.general_law_theta_entry.get() == "0.5",
          f"legendre mode: theta entry snaps to '0.5' (got {tab.general_law_theta_entry.get()!r})")
    check(str(tab.general_law_theta_entry["state"]) == "disabled",
          f"legendre mode: theta entry is disabled (got {tab.general_law_theta_entry['state']!r})")

    tab.general_law_mode_combo.set("stepped")
    tab._on_general_law_mode_changed()
    check(str(tab.general_law_theta_entry["state"]) == "normal",
          f"switching back to stepped: theta entry is editable again (got {tab.general_law_theta_entry['state']!r})")

    # Launching with 'bertrand' selected forwards --general-law-mode bertrand
    # and the locked "1" theta value, same as any other launch-time field.
    tab.general_law_var.set(True)
    tab.general_law_mode_combo.set("bertrand")
    tab._on_general_law_mode_changed()
    fake_ok_script_gl = _write_fake_renderer(0)
    rings_tab_module.RENDERER_SCRIPT = fake_ok_script_gl
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    shown.clear()
    launched_cmd = _open_and_capture(tab)
    check("--general-law-mode" in launched_cmd and launched_cmd[launched_cmd.index("--general-law-mode") + 1] == "bertrand",
          f"General Law set to bertrand reaches the launched argv as --general-law-mode bertrand "
          f"(got argv: {launched_cmd!r})")
    check("--general-law-theta" in launched_cmd and launched_cmd[launched_cmd.index("--general-law-theta") + 1] == "1.0",
          f"General Law set to bertrand forwards the locked theta=1 (got argv: {launched_cmd!r})")
    _pump_until_idle(app, tab)
    os.remove(fake_ok_script_gl)
    tab.general_law_mode_combo.set("stepped")
    tab._on_general_law_mode_changed()
    tab.general_law_var.set(False)

    # --- Max load count field wiring (range mode) ---------
    tab.mode_var.set("range")
    tab._on_mode_changed()
    tab.load_range_from_entry.delete(0, "end")
    tab.load_range_from_entry.insert(0, "100")
    tab.load_range_to_entry.delete(0, "end")
    tab.load_range_to_entry.insert(0, "500")
    fake_ok_script5 = _write_fake_renderer(0)
    rings_tab_module.RENDERER_SCRIPT = fake_ok_script5
    tab.max_load_count_entry.delete(0, "end")
    tab.max_load_count_entry.insert(0, "1000")
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    shown.clear()
    launched_cmd = _open_and_capture(tab)
    check("--max-load-count" in launched_cmd and
          launched_cmd[launched_cmd.index("--max-load-count") + 1] == "1000",
          f"Max load count field reaches the launched argv as --max-load-count "
          f"(got argv: {launched_cmd!r})")
    _pump_until_idle(app, tab)
    os.remove(fake_ok_script5)

    # A non-numeric value must NOT crash the GUI thread -- silent fallback to
    # renderer.py's own argparse default, same convention as every other
    # empty-or-invalid launch-time field.
    fake_ok_script6 = _write_fake_renderer(0)
    rings_tab_module.RENDERER_SCRIPT = fake_ok_script6
    tab.max_load_count_entry.delete(0, "end")
    tab.max_load_count_entry.insert(0, "not-a-number")
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    shown.clear()
    launched_cmd = _open_and_capture(tab)
    check("--max-load-count" not in launched_cmd,
          f"a non-numeric Max load count value omits --max-load-count entirely, "
          f"does not raise (got argv: {launched_cmd!r})")
    _pump_until_idle(app, tab)
    os.remove(fake_ok_script6)
    tab.max_load_count_entry.delete(0, "end")
    tab.load_range_from_entry.delete(0, "end")
    tab.load_range_to_entry.delete(0, "end")
    tab.mode_var.set("sequential")
    tab._on_mode_changed()

    # --- Tempo field wiring -------------------------------------------------
    fake_ok_script7 = _write_fake_renderer(0)
    rings_tab_module.RENDERER_SCRIPT = fake_ok_script7
    tab.tempo_ms_entry.delete(0, "end")
    tab.tempo_ms_entry.insert(0, "250")
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    shown.clear()
    launched_cmd = _open_and_capture(tab)
    check("--tempo-ms" in launched_cmd and launched_cmd[launched_cmd.index("--tempo-ms") + 1] == "250",
          f"Tempo field reaches the launched argv as --tempo-ms (got argv: {launched_cmd!r})")
    _pump_until_idle(app, tab)
    os.remove(fake_ok_script7)

    fake_ok_script8 = _write_fake_renderer(0)
    rings_tab_module.RENDERER_SCRIPT = fake_ok_script8
    tab.tempo_ms_entry.delete(0, "end")
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    shown.clear()
    launched_cmd = _open_and_capture(tab)
    check("--tempo-ms" not in launched_cmd,
          f"an empty Tempo field omits --tempo-ms entirely, does not raise "
          f"(got argv: {launched_cmd!r})")
    _pump_until_idle(app, tab)
    os.remove(fake_ok_script8)
    tab.tempo_ms_entry.insert(0, "120")

    # --- HUD panel: direct _apply_hud_state unit test ---
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

    # --- End-to-end: a fake renderer emitting a real HUD_STATE line ---
    fd, fake_hud_script = tempfile.mkstemp(suffix="_fake_renderer_hud.py")
    with os.fdopen(fd, "w") as f:
        f.write(
            "import sys\n"
            "print('fake renderer: loading archive...')\n"
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
    _pump_until_idle(app, tab)
    hud_text2 = tab.hud_var.get()
    check("42" in hud_text2, f"HUD panel updated from a real subprocess's HUD_STATE stdout line (got {hud_text2!r})")
    console_text2 = tab.console.text.get("1.0", "end")
    check("HUD_STATE:" not in console_text2,
          f"HUD_STATE lines are routed to the panel, never appended to the scrolling console pane "
          f"(got console text: {console_text2!r})")
    check("fake renderer: loading archive..." in console_text2,
          f"ordinary (non-HUD_STATE) lines from the same process still reach the console normally "
          f"(got console text: {console_text2!r})")
    os.remove(fake_hud_script)

    # --- Start/Resume: a clean exit after a HUD_STATE line updates the N
    # field to the last-seen N, so clicking the Start/Resume button again
    # reopens right there instead of at whatever the field said at launch
    # time (launched above with N=500, HUD_STATE said n=42).
    check(tab._last_hud_n == 42,
          f"the tab remembers the last N seen in a HUD_STATE line (got {tab._last_hud_n!r})")
    check(tab.n_entry.get() == "42",
          f"a clean process exit rewrites the N field to that last-seen N, powering "
          f"resume on the next Start/Resume click (got {tab.n_entry.get()!r})")

    # --- Reset: discards the resume state, even while a process is still
    # running (Reset is only enabled while running, same as the old Stop
    # button it replaced) -- but does NOT touch the N field's own contents;
    # unlocking fields on Reset is intentional, silently discarding what was
    # typed is not -- see _on_reset's own doc-comment in rings_tab.py.
    fake_hud_script2 = _write_fake_renderer(0)
    rings_tab_module.RENDERER_SCRIPT = fake_hud_script2
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "777")
    tab._on_open()
    tab._last_hud_n = 999  # simulate a HUD_STATE line having arrived mid-run
    tab._on_reset()
    check(tab._last_hud_n is None,
          "Reset discards the remembered resume N")
    check(tab.n_entry.get() == "777",
          f"Reset does NOT overwrite the N field -- the user's own last-entered "
          f"value survives a Reset click (got {tab.n_entry.get()!r})")
    _pump_until_idle(app, tab)
    check(str(tab.open_button["state"]) == "normal",
          "Reset also stops the running process, same as the old Stop button")
    check(tab.n_entry.get() == "777",
          "the process's own exit (triggered by Reset) does NOT re-apply a "
          "stale last-seen N over the user's own typed value -- _last_hud_n was "
          "already None by the time the exit was processed")

    # --- Live pause/resume: a fake renderer that immediately reports itself
    # paused (simulating the real renderer.py's
    # own window-close interception -- see that file's own doc-comment on
    # start_stdin_command_reader), then blocks on stdin until "RESUME"
    # arrives, then reports resumed and exits cleanly. Exercises the actual
    # stdin pipe end-to-end (LocalLoggedRunner.send_line -> the subprocess's
    # own sys.stdin), not a mock -- same real-subprocess philosophy as the
    # rest of this file (see module docstring).
    # Deliberately sleeps a couple seconds AFTER printing RESUMED, rather than
    # exiting right away -- otherwise, on a fast sandbox, the __exit__
    # sentinel can land in the SAME _poll_queue drain batch as the
    # RING_VIZ_RESUMED line (both process._read_loop and the OS process exit
    # can outrun a single _pump() window), which would make the "resumed but
    # still running" state below unobservable as a distinct moment.
    fd, fake_pause_script = tempfile.mkstemp(suffix="_fake_renderer_pause.py")
    with os.fdopen(fd, "w") as f:
        f.write(
            "import sys, time\n"
            "print('fake renderer: ready')\n"
            "print('RING_VIZ_PAUSED')\n"
            "sys.stdout.flush()\n"
            "for line in sys.stdin:\n"
            "    if line.strip() == 'RESUME':\n"
            "        print('RING_VIZ_RESUMED')\n"
            "        sys.stdout.flush()\n"
            "        time.sleep(3)\n"
            "        break\n"
            "sys.exit(0)\n"
        )
    rings_tab_module.RENDERER_SCRIPT = fake_pause_script
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "321")
    tab._on_open()
    # The lock must already be active right after opening the window --
    # checked BEFORE the first _pump() call below, i.e. before the process
    # has even had a chance to report itself paused, to prove the lock
    # isn't waiting on that signal at all.
    check(str(tab.n_entry["state"]) == "disabled",
          f"N field is locked immediately on launch, before any pause/resume "
          f"signal arrives (got {tab.n_entry['state']!r})")
    _pump(app, 1.5)
    check(tab._paused is True,
          f"_paused flips True once the RING_VIZ_PAUSED line is drained from the queue "
          f"(got {tab._paused!r})")
    check(str(tab.open_button["state"]) == "normal",
          "open_button is re-enabled while paused, so Start/Resume is clickable again")
    check(str(tab.stop_button["state"]) == "normal",
          "stop_button STAYS enabled while paused -- Reset must still be able to kill "
          "a paused (window-hidden, but very much alive) process")
    check(tab.status.get() == tab.T("rings.status_paused"),
          f"status bar shows the paused message (got {tab.status.get()!r})")
    paused_runner = tab._runner
    check(paused_runner is not None and paused_runner.is_running(),
          "the OS process is still alive while paused -- pausing hides the window, it "
          "does not exit the subprocess (that's the whole point of the pause/resume feature)")

    # Every launch-time-only field must still read as disabled/readonly
    # once paused -- editing them would silently do nothing until the NEXT
    # fresh launch, which would be a misleading state. Spot-check one
    # widget from each of the three state-spelling groups rather than
    # every single one -- _set_launch_params_readonly applies the same two
    # states uniformly, so this is enough to catch a wiring mistake.
    check(str(tab.n_entry["state"]) == "disabled",
          f"N field is still read-only once paused (got {tab.n_entry['state']!r})")
    check(str(tab._bertrand_check["state"]) == "disabled",
          f"window-highlight checkboxes are still read-only once paused (got {tab._bertrand_check['state']!r})")
    check(str(tab.general_law_mode_combo["state"]) == "disabled",
          f"dropdowns are read-only (not just 'readonly') once paused "
          f"(got {tab.general_law_mode_combo['state']!r})")

    # Clicking Start/Resume while paused must send "RESUME" down the existing
    # pipe, NOT launch a second subprocess.
    tab._on_open()
    check(tab._runner is paused_runner,
          "clicking Start/Resume while paused reuses the SAME runner/process -- it "
          "does not launch a brand new one (that would be the old bookmark-only "
          "behavior this feature replaces)")
    _pump(app, 1.5)
    check(tab._paused is False,
          f"_paused flips back False once the RING_VIZ_RESUMED line is drained "
          f"(got {tab._paused!r})")
    check(str(tab.open_button["state"]) == "disabled",
          "open_button is disabled again once resumed (back to the normal "
          "while-running state)")
    check(tab.status.get() == tab.T("rings.status_running"),
          f"status bar shows the running message after resume (got {tab.status.get()!r})")
    # Fields unlock only after Reset -- resuming is still not a fresh
    # launch, so the fields stay LOCKED here, unlike the earlier
    # (superseded) design where resume re-enabled them.
    check(str(tab.n_entry["state"]) == "disabled",
          f"N field STAYS locked after resume -- only Reset unlocks it "
          f"(got {tab.n_entry['state']!r})")
    check(str(tab._bertrand_check["state"]) == "disabled",
          f"checkboxes STAY locked after resume too (got {tab._bertrand_check['state']!r})")
    check(str(tab.general_law_mode_combo["state"]) == "disabled",
          f"dropdowns STAY locked after resume too (got {tab.general_law_mode_combo['state']!r})")

    # The fake script sleeps 3s after RESUMED, then exits -- confirm the
    # normal __exit__ path still fires correctly afterwards, and that it
    # leaves no stale _paused=True behind for the next launch. A real exit
    # (crash, or the process ending on its own) is the one other case
    # besides Reset that unlocks the fields -- there's genuinely no live
    # process left afterward for them to (mis)represent.
    _pump(app, 4.0)
    check(str(tab.open_button["state"]) == "normal",
          "open_button re-enabled once the (now-resumed) process actually exits")
    check(str(tab.stop_button["state"]) == "disabled",
          "stop_button disabled once the process actually exits")
    check(tab._paused is False,
          "_paused stays False after a real exit (no stale pause flag left behind "
          "for the next Start/Resume click)")
    check(str(tab.n_entry["state"]) == "normal",
          f"fields unlock again once the process actually exits, same as Reset "
          f"(got {tab.n_entry['state']!r})")

    # Reset must re-enable the fields IMMEDIATELY, not wait for the async
    # __exit__ queue item -- launch fresh, let it pause, then Reset while
    # still paused and check the fields are already editable before any
    # _pump() call processes the exit.
    rings_tab_module.RENDERER_SCRIPT = fake_pause_script
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "654")
    tab._on_open()
    _pump(app, 1.5)
    check(tab._paused is True, "sanity: paused again for the Reset-while-paused check")
    check(str(tab.n_entry["state"]) == "disabled", "sanity: read-only again before Reset")
    tab._on_reset()
    check(str(tab.n_entry["state"]) == "normal",
          "Reset re-enables the N field synchronously, without waiting for the "
          "subprocess's own (async) exit to be drained from the queue")
    check(str(tab._bertrand_check["state"]) == "normal",
          "Reset re-enables checkboxes synchronously too")
    _pump_until_idle(app, tab)  # drain the exit so the next launch starts from a clean queue
    os.remove(fake_pause_script)

    # --- failure path: real subprocess, fake renderer script, exit 1 ----------------
    fake_fail_script = _write_fake_renderer(1)
    rings_tab_module.RENDERER_SCRIPT = fake_fail_script
    tab.n_entry.delete(0, "end")
    tab.n_entry.insert(0, "500")
    tab._on_open()
    _pump_until_idle(app, tab)
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

    _test_empty_storage_offer(app, tab, rings_tab_module, tmp_portal, shown)

    app.destroy()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
