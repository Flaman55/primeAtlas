"""
test_primecount_settings_integration.py -- covers Settings -> Aktualizacje's primecount
installer section (settings_tab.py) and the generation.py plumbing it's built on
(build_primecount_query_argv, run_primecount_wsl_blocking, run_primecount_install_wsl_
blocking). The "primecount" data-source mode's install mechanism lives in Settings,
alongside every other optional-component installer (sympy, CUDASieve), rather than on
the Badania -> Przyblizenia pi(x) tab where the mode itself is used.

Same "test the SYNCHRONOUS result-handler methods directly, never the real
threading.Thread()+self.after() round trip" convention as test_cudasieve_integration.py's
own Section F (see that file's own module docstring) -- self.after() called from a
background thread needs a REAL Tk mainloop() to work; this test suite (like every other
one in this project) drives the Tk event loop via manual app.update() polling instead,
which does NOT count as "in mainloop" and makes a background thread's self.after() call
raise "main thread is not in main loop" -- a well-understood Tkinter testing limitation,
not a bug in the code under test (confirmed live: the exact same real WSL
round-trip works correctly when driven through the tab's own worker-thread-based
PersistentWorker machinery in test_research_pi_approx_tab.py, and works live in the real
app under a real mainloop() -- only the settings_tab.py bare threading.Thread(daemon=
True).start() + self.after() pattern, which CUDASieve's own status/build checks already
established, hits this specific test-harness artifact). So: test _on_primecount_status_
result/_on_primecount_install_result directly (the synchronous halves), and separately
prove the wsl_helpers dict wiring is correct, without ever spawning the real background
thread.

Usage (Windows, real display):
    python unitTests\\test_primecount_settings_integration.py
"""
import os
import sys
import tempfile

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


def _test_build_primecount_query_argv():
    from primeatlas.generation.generation import build_primecount_query_argv

    argv = build_primecount_query_argv("pi_batch", 1000, 1000000)
    check(argv[0] == "python3" and argv[1] == "-u",
          f"argv starts with an unbuffered python3 invocation (got {argv[:2]!r})")
    check(argv[3] == "pi_batch", f"the op is passed through verbatim (got {argv[3]!r})")
    check(argv[4:] == ["1000", "1000000"],
          f"every extra arg is stringified in order (got {argv[4:]!r})")


def _test_run_primecount_wsl_blocking_contract():
    """Exercises the Popen()+poll() timeout path directly (same idea as
    test_cudasieve_integration.py's own Section B) -- no real wsl.exe involved, a fake
    Popen stands in, proving the timeout branch returns the documented {"message",
    "kind": None} shape rather than hanging or crashing."""
    import primeatlas.generation.generation as gen

    class _FakeNeverEndingProc:
        def poll(self):
            return None  # never exits on its own

        def kill(self):
            pass

    orig_popen = gen.subprocess.Popen
    gen.subprocess.Popen = lambda *a, **k: _FakeNeverEndingProc()
    portal = tempfile.mkdtemp(prefix="primecount_settings_test_")
    try:
        ok, result = gen.run_primecount_wsl_blocking(["python3", "-c", "pass"], portal, timeout=0.3)
        check(not ok, "a process that never exits is reported as a failure, not a hang")
        check(isinstance(result, dict) and "message" in result and "kind" in result,
              f"the failure payload has the documented {{'message','kind'}} shape "
              f"(got {result!r})")
        check(result.get("kind") is None,
              f"a timeout's kind is None, not 'not_installed' (got {result.get('kind')!r})")
        check("Timed out" in result.get("message", ""),
              f"the message names the timeout explicitly (got {result!r})")
    finally:
        gen.subprocess.Popen = orig_popen
        import shutil
        shutil.rmtree(portal, ignore_errors=True)


def _test_settings_tab_primecount_status_and_install():
    print("\n--- SettingsTab primecount installer section ---")
    import tkinter.messagebox as messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None

    import prime_atlas_v1

    portal = tempfile.mkdtemp(prefix="primecount_settingstab_test_")
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

        # --- wsl_helpers wiring: the three primecount entries must actually be there --
        for key in ("build_primecount_query_argv", "run_primecount_wsl_blocking",
                    "run_primecount_install_wsl_blocking"):
            check(key in settings_tab.wsl and callable(settings_tab.wsl[key]),
                  f"wsl_helpers must expose a callable {key!r}")

        # --- attribution: GitHub links for primecount AND primesieve (neither is --------
        # authored by this project -- both are Kim Walisch's own independent BSD-
        # licensed libraries, see settings_tab.py's own PRIMECOUNT_REPO_URL/
        # PRIMESIEVE_REPO_URL comment) --------------------------------------------------
        import webbrowser
        import primeatlas.settings.settings_tab as settings_tab_mod
        opened_urls = []
        webbrowser.open = lambda url: opened_urls.append(url)

        settings_tab._on_open_primecount_github_clicked()
        check(opened_urls == [settings_tab_mod.PRIMECOUNT_REPO_URL],
              f"the primecount GitHub button opens primecount's own real repo URL "
              f"(got {opened_urls!r}, expected {[settings_tab_mod.PRIMECOUNT_REPO_URL]!r})")

        opened_urls.clear()
        settings_tab._on_open_primesieve_github_clicked()
        check(opened_urls == [settings_tab_mod.PRIMESIEVE_REPO_URL],
              f"the primesieve GitHub button (on the generic environment-setup section, "
              f"since primesieve has no dedicated installer section of its own) opens "
              f"primesieve's own real repo URL (got {opened_urls!r}, expected "
              f"{[settings_tab_mod.PRIMESIEVE_REPO_URL]!r})")

        # --- initial state: not checked yet, install button enabled from the start ----
        check("nie sprawdzono" in settings_tab.primecount_status_var.get()
              or "not checked" in settings_tab.primecount_status_var.get().lower(),
              f"the initial status is 'not checked yet' (got "
              f"{settings_tab.primecount_status_var.get()!r})")
        check(str(settings_tab.install_primecount_btn["state"]) == "normal",
              "the install button starts enabled (no precondition to gate it, unlike "
              "CUDASieve's own GPU-detection gate)")

        # --- _on_primecount_status_result: installed branch --------------------------
        settings_tab._on_primecount_status_result(True, "8.1")
        check("8.1" in settings_tab.primecount_status_var.get(),
              f"an installed result shows the real version string "
              f"(got {settings_tab.primecount_status_var.get()!r})")
        check(str(settings_tab.install_primecount_btn["state"]) == "disabled",
              "once installed, the install button is disabled (nothing left to do)")

        # --- _on_primecount_status_result: not-installed branch ----------------------
        settings_tab._primecount_install_running = False
        settings_tab._on_primecount_status_result(
            False, {"message": "Could not load libprimecount (fake)", "kind": "not_installed"})
        check("niezainstalowane" in settings_tab.primecount_status_var.get()
              or "not installed" in settings_tab.primecount_status_var.get().lower(),
              f"a not-installed result shows the plain 'missing' status, not the raw "
              f"message (got {settings_tab.primecount_status_var.get()!r})")
        check(str(settings_tab.install_primecount_btn["state"]) == "normal",
              "a not-installed result leaves the install button enabled")

        # --- _on_primecount_status_result: some OTHER failure (kind=None) ------------
        settings_tab._primecount_install_running = False
        settings_tab._on_primecount_status_result(
            False, {"message": "WSL cold-start hiccup (fake)", "kind": None})
        check("WSL cold-start hiccup" in settings_tab.primecount_status_var.get(),
              f"a generic failure surfaces its own real error text "
              f"(got {settings_tab.primecount_status_var.get()!r})")
        check(str(settings_tab.install_primecount_btn["state"]) == "normal",
              "a generic status-probe failure still allows the user to try Install anyway")

        # --- _on_primecount_install_result: success re-triggers the status check -----
        recheck_calls = []
        orig_check = settings_tab._on_check_primecount_status
        settings_tab._on_check_primecount_status = lambda: recheck_calls.append(True)
        settings_tab._primecount_install_running = True
        settings_tab._on_primecount_install_result(True, None)
        check(settings_tab._primecount_install_running is False,
              "a finished install (success or failure) clears the running guard flag")
        check(recheck_calls == [True],
              "a successful install re-runs the status check, so the label reflects "
              "reality without a second manual click")

        # --- _on_primecount_install_result: failure also re-triggers the status check
        recheck_calls.clear()
        settings_tab._primecount_install_running = True
        settings_tab._on_primecount_install_result(False, "apt-get install failed (fake)")
        check(recheck_calls == [True],
              "a FAILED install also re-runs the status check (the button must not stay "
              "disabled forever after a failed attempt)")
        settings_tab._on_check_primecount_status = orig_check

        app.destroy()
    finally:
        import shutil
        shutil.rmtree(portal, ignore_errors=True)


def main():
    _test_build_primecount_query_argv()
    _test_run_primecount_wsl_blocking_contract()
    _test_settings_tab_primecount_status_and_install()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
