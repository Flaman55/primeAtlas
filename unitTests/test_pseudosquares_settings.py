"""
test_pseudosquares_settings.py -- Settings > Updates's Pseudosquares Prime Sieve block on the
real Settings tab (isolated app, no WSL).

The synchronous halves are tested directly, never the worker thread + after() round trip
(manual app.update() polling is not a mainloop; see test_primecount_settings_integration.py).

Checks: status texts (installed at the pin, another commit, source not built, not installed,
missing build tools, probe error); the section is built with its buttons and starts "not
checked"; the WSL helper bundle carries the status/build argv builder and both blocking
calls; the install preparation installs the build tools only when the probe names missing
ones, and a probe or tool failure stops before the build; the build runs
pseudosquares_install.py --build on the shared runner; its exit releases the buttons and
re-checks the status; the strings exist in English and Polish.

Usage (Windows, real display):
    python unitTests/test_pseudosquares_settings.py
"""
import json
import os
import sys
import tkinter.messagebox

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, _SCRIPT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def T(key, **kw):
    return key + ("" if not kw else " " + json.dumps(kw, sort_keys=True))


def status_checks():
    from primeatlas.settings.pseudosquares_section import status_text
    base = {"ok": True, "tools_missing": [], "cloned": True, "commit": "fccb96e",
            "pinned": "fccb96e", "at_pin": True, "binary_path": "/b", "version": "1.2"}
    check(status_text(True, base, T).startswith("settings.pseudosquares_status_installed"),
          "status: installed at the pin")
    other = dict(base, commit="1234567", at_pin=False)
    text = status_text(True, other, T)
    check(text.startswith("settings.pseudosquares_status_other_commit") and "1234567" in text,
          "status: installed on another commit names it")
    text = status_text(True, dict(base, binary_path=None), T)
    check(text.startswith("settings.pseudosquares_status_not_built"), "status: source not built")
    missing = dict(base, cloned=False, commit=None, at_pin=False, binary_path=None,
                   tools_missing=["cmake", "g++"])
    text = status_text(True, missing, T)
    check(text.startswith("settings.pseudosquares_status_missing")
          and "settings.pseudosquares_status_tools" in text and "cmake, g++" in text,
          "status: not installed, names the missing build tools")
    check(status_text(False, "boom", T).startswith("settings.pseudosquares_status_error"),
          "status: probe error")


def locale_checks():
    from primeatlas.settings import pseudosquares_section
    import re
    with open(pseudosquares_section.__file__, encoding="utf-8") as f:
        keys = set(re.findall(r'"(settings\.pseudosquares_[a-z_]+)"', f.read()))
    for lang in ("en", "pl"):
        with open(os.path.join(_REPO_ROOT, "primeatlas", "core", "locales",
                               f"strings_{lang}.json"), encoding="utf-8") as f:
            strings = json.load(f)
        missing = sorted(k for k in keys if not strings.get(k))
        check(not missing, f"{lang}: every section string exists ({missing})")
        check("BSD 2-Clause" in strings.get("settings.pseudosquares_hint", ""),
              f"{lang}: hint names the license")


def main():
    tkinter.messagebox.showinfo = lambda *a, **k: None
    tkinter.messagebox.showerror = lambda *a, **k: None
    status_checks()
    locale_checks()

    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    app = prime_atlas_v2._build_gui()()
    app.update()
    tab = app.settings_tab
    try:
        check(tab.pseudosquares_status_var.get() == tab.T("settings.pseudosquares_status_not_checked"),
              "section starts 'not checked'")
        check(str(tab.pseudosquares_install_btn.cget("state")) == "normal", "Install usable")
        for key in ("build_pseudosquares_install_argv", "run_pseudosquares_status_wsl_blocking",
                    "run_pseudosquares_tools_install_wsl_blocking"):
            check(callable(tab.wsl.get(key)), f"wsl helper {key}")
        argv = tab.wsl["build_pseudosquares_install_argv"]("--status")
        check(argv[2].endswith("prime_sieve/pseudosquares_install.py") and argv[3] == "--status",
              "status argv runs pseudosquares_install.py --status")

        saved = dict(tab.wsl)
        calls = []
        probe = {"ok": True, "tools_missing": ["cmake"], "cloned": False}

        tab.wsl["run_pseudosquares_status_wsl_blocking"] = lambda argv, t=60: (True, dict(probe))
        tab.wsl["run_pseudosquares_tools_install_wsl_blocking"] = \
            lambda t=600: calls.append("apt") or (True, None)
        tools, error = tab._prepare_pseudosquares_install()
        check(tools == ["cmake"] and error is None and calls == ["apt"],
              "missing tool: build tools installed as root")
        probe["tools_missing"] = []
        calls.clear()
        tools, error = tab._prepare_pseudosquares_install()
        check(tools == [] and error is None and not calls, "tools present: no root install")
        probe["tools_missing"] = ["git"]
        tab.wsl["run_pseudosquares_tools_install_wsl_blocking"] = lambda t=600: (False, "E: no net")
        tools, error = tab._prepare_pseudosquares_install()
        check(error and "no net" in error, "tool install failure: error, no build")
        tab.wsl["run_pseudosquares_status_wsl_blocking"] = lambda argv, t=60: (False, "wsl down")
        tools, error = tab._prepare_pseudosquares_install()
        check(error and "wsl down" in error, "probe failure: error, no build")

        started = []

        class _FakeRunner:
            def __init__(self, cmd, log, exit_, q, kill_pattern=None):
                started.append((cmd, kill_pattern))
                self.q = q

            def start(self):
                pass

        tab.wsl["WslLoggedRunner"] = _FakeRunner
        tab.wsl["build_wsl_logged_command"] = lambda argv, *a, **k: argv
        rechecks = []
        orig_check = tab._on_check_pseudosquares_status
        tab._on_check_pseudosquares_status = lambda: rechecks.append(1)
        try:
            tab._pseudosquares_set_busy(True)
            tab._after_pseudosquares_prepare([], "an error")
            check(not started and not tab._pseudosquares_busy, "error: no build, buttons back")
            tab._pseudosquares_set_busy(True)
            tab._after_pseudosquares_prepare(["cmake"], None)
            check(len(started) == 1 and started[0][0][-1] == "--build"
                  and started[0][1] == "pseudosquares_install.py",
                  "build: pseudosquares_install.py --build on the runner")
            check(str(tab.pseudosquares_install_btn.cget("state")) == "disabled",
                  "Install disabled while building")
            tab._pseudosquares_queue.put("[*] cmake ...\n")
            tab._pseudosquares_queue.put(("__exit__", 0))
            tab._poll_pseudosquares_queue()
            check(not tab._pseudosquares_busy and rechecks == [1],
                  "build exit: buttons back, status re-checked")
        finally:
            tab._on_check_pseudosquares_status = orig_check
            tab.wsl.clear()
            tab.wsl.update(saved)

        tab._on_pseudosquares_status(True, {"ok": True, "binary_path": "/b", "at_pin": True,
                                            "version": "1.2", "commit": "fccb96e"})
        check("1.2" in tab.pseudosquares_status_var.get(), "status result shown")
    finally:
        app.destroy()

    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
