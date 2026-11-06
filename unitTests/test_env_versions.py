"""
test_env_versions.py -- covers Settings -> WSL environment's component versions: the
WSL-side probe's pure parsers and report (prime_sieve/env_versions.py), the GUI-side
text it renders into (primeatlas/settings/env_versions_view.py), and the Settings tab's
button/result handler (updates_section.py). The real WSL round trip is not run here;
the parsers are fed text captured from a real WSL install with two libprimesieve copies.

Usage (Windows, real display):
    python unitTests\\test_env_versions.py
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


LDCONFIG = """\
1234 libs found in cache `/etc/ld.so.cache'
\tlibprimesieve.so.12 (libc6,x86-64) => /usr/local/lib/libprimesieve.so.12
\tlibprimesieve.so.12 (libc6,x86-64) => /usr/lib/x86_64-linux-gnu/libprimesieve.so.12
\tlibprimesieve.so (libc6,x86-64) => /usr/local/lib/libprimesieve.so
\tlibprimesieve.so (libc6,x86-64) => /usr/lib/x86_64-linux-gnu/libprimesieve.so
\tlibprimecount.so.8 (libc6,x86-64) => /usr/lib/x86_64-linux-gnu/libprimecount.so.8
\tlibprimecount.so (libc6,x86-64) => /usr/lib/x86_64-linux-gnu/libprimecount.so
\tlibprimesieve_extra.so.1 (libc6,x86-64) => /opt/x/libprimesieve_extra.so.1
"""

REALPATHS = {
    "/usr/local/lib/libprimesieve.so.12": "/usr/local/lib/libprimesieve.so.12.15",
    "/usr/local/lib/libprimesieve.so": "/usr/local/lib/libprimesieve.so.12.15",
    "/usr/lib/x86_64-linux-gnu/libprimesieve.so.12":
        "/usr/lib/x86_64-linux-gnu/libprimesieve.so.12.12.0",
    "/usr/lib/x86_64-linux-gnu/libprimesieve.so":
        "/usr/lib/x86_64-linux-gnu/libprimesieve.so.12.12.0",
    "/usr/lib/x86_64-linux-gnu/libprimecount.so.8":
        "/usr/lib/x86_64-linux-gnu/libprimecount.so.8.1",
    "/usr/lib/x86_64-linux-gnu/libprimecount.so":
        "/usr/lib/x86_64-linux-gnu/libprimecount.so.8.1",
}

MAPS = """\
55d0c0000000-55d0c0001000 r--p 00000000 08:20 1 /usr/bin/python3.14
7f00aa000000-7f00aa010000 r--p 00000000 08:20 2 /usr/local/lib/libprimesieve.so.12.15
7f00aa010000-7f00aa020000 r-xp 00010000 08:20 2 /usr/local/lib/libprimesieve.so.12.15
"""

LDD = """\
\tlinux-vdso.so.1 (0x00007ffd)
\tlibprimesieve.so.12 => /usr/local/lib/libprimesieve.so.12 (0x00007d2a7ec75000)
\tlibstdc++.so.6 => /lib/x86_64-linux-gnu/libstdc++.so.6 (0x00007d2a7e800000)
"""


def _test_parsers():
    print("\n--- env_versions parsers ---")
    import env_versions as ev

    check(ev.parse_os_release('NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 26.04 LTS"\n')
          == "Ubuntu 26.04 LTS", "PRETTY_NAME is read without its quotes")
    check(ev.parse_os_release("NAME=Ubuntu\n") == "",
          "no PRETTY_NAME gives an empty distro name")

    paths = ev.ldconfig_paths(LDCONFIG, "primesieve")
    check(paths == ["/usr/local/lib/libprimesieve.so.12",
                    "/usr/lib/x86_64-linux-gnu/libprimesieve.so.12",
                    "/usr/local/lib/libprimesieve.so",
                    "/usr/lib/x86_64-linux-gnu/libprimesieve.so"],
          f"ldconfig_paths lists every libprimesieve entry in cache order and skips "
          f"libprimesieve_extra (got {paths!r})")
    check(ev.ldconfig_paths(LDCONFIG, "cudasieve") == [],
          "a library absent from the cache gives no paths")

    copies = ev.distinct_copies(paths, realpath=REALPATHS.get)
    check(copies == ["/usr/lib/x86_64-linux-gnu/libprimesieve.so.12.12.0",
                     "/usr/local/lib/libprimesieve.so.12.15"],
          f"symlinks to one file count as one copy (got {copies!r})")
    check(ev.version_from_filename("/usr/local/lib/libprimesieve.so.12.15") == "12.15",
          "the version comes from the file name after .so.")
    check(ev.version_from_filename("/usr/lib/libprimesieve.so") is None,
          "an unversioned .so has no file-name version")

    check(ev.loaded_from_maps(MAPS, "primesieve") == "/usr/local/lib/libprimesieve.so.12.15",
          "the loaded copy is read from /proc/self/maps")
    check(ev.loaded_from_maps(MAPS, "primecount") is None,
          "a library not mapped gives None")
    check(ev.ldd_path(LDD, "primesieve") == "/usr/local/lib/libprimesieve.so.12",
          "ldd's resolved path is read after =>")
    check(ev.ldd_path(LDD, "primecount") is None, "a library ldd does not list gives None")


def _test_report():
    print("\n--- env_versions report ---")
    import env_versions as ev

    libs = {
        "primesieve": ev.lib_entry(
            "12.15", "/usr/local/lib/libprimesieve.so.12.15",
            ["/usr/lib/x86_64-linux-gnu/libprimesieve.so.12.12.0",
             "/usr/local/lib/libprimesieve.so.12.15"],
            {"prime_sieve_engine_v6.so": "/usr/local/lib/libprimesieve.so.12.15",
             "prime_sieve_engine_v5.so": "/usr/local/lib/libprimesieve.so.12.15"}),
        "primecount": ev.lib_entry(
            "8.1", "/usr/lib/x86_64-linux-gnu/libprimecount.so.8.1",
            ["/usr/lib/x86_64-linux-gnu/libprimecount.so.8.1"], {}),
    }
    entry = libs["primesieve"]
    check([c["version"] for c in entry["copies"]] == ["12.12.0", "12.15"],
          "every copy carries its file-name version")
    check(ev.duplicates(libs) == ["primesieve"],
          "only a library with two distinct files is a duplicate")
    check(ev.engines_differ(entry) is False,
          "engines loading the same file as Python do not differ")
    entry2 = ev.lib_entry("12.15", "/usr/local/lib/libprimesieve.so.12.15",
                          ["/a/libprimesieve.so.12.12", "/usr/local/lib/libprimesieve.so.12.15"],
                          {"prime_sieve_engine_v6.so": "/a/libprimesieve.so.12.12"})
    check(ev.engines_differ(entry2) is True,
          "an engine that resolves a different file than Python is flagged")
    missing = ev.lib_entry(None, None, [], {})
    check(ev.duplicates({"primecount": missing}) == [], "a missing library is no duplicate")


def _test_view():
    print("\n--- env_versions_view ---")
    import env_versions as ev
    from primeatlas.core.i18n import Translator
    from primeatlas.settings.env_versions_view import format_report

    for lang in ("en", "pl"):
        T = Translator(lang)
        report = {
            "ok": True, "distro": "Ubuntu 26.04 LTS", "python": "3.14.4", "numpy": "2.5.1",
            "gcc": "15.2.0",
            "libs": {
                "primesieve": ev.lib_entry(
                    "12.15", "/usr/local/lib/libprimesieve.so.12.15",
                    ["/usr/lib/x86_64-linux-gnu/libprimesieve.so.12.12.0",
                     "/usr/local/lib/libprimesieve.so.12.15"],
                    {"prime_sieve_engine_v6.so": "/usr/local/lib/libprimesieve.so.12.15"}),
                "primecount": ev.lib_entry(None, None, [], {}),
            },
        }
        report["duplicates"] = ev.duplicates(report["libs"])
        text, warning = format_report(report, T)
        for needle in ("Ubuntu 26.04 LTS", "3.14.4", "2.5.1", "12.15",
                       "/usr/local/lib/libprimesieve.so.12.15", "15.2.0"):
            check(needle in text, f"[{lang}] the versions text names {needle!r}")
        check(T("settings.env_versions_missing") in text,
              f"[{lang}] a missing primecount says 'not installed'")
        check("12.12.0" in warning and "/usr/lib/x86_64-linux-gnu/libprimesieve.so.12.12.0"
              in warning, f"[{lang}] the duplicate warning lists the other copy and its version")
        check("{" not in text and "{" not in warning,
              f"[{lang}] no unfilled placeholder is left")

        report["numpy"] = None
        report["gcc"] = None
        report["libs"]["primesieve"] = ev.lib_entry(
            "12.15", "/usr/local/lib/libprimesieve.so.12.15",
            ["/usr/local/lib/libprimesieve.so.12.15"],
            {"prime_sieve_engine_v6.so": "/usr/local/lib/libprimesieve.so.12.15"})
        report["duplicates"] = ev.duplicates(report["libs"])
        text, warning = format_report(report, T)
        check(warning == "", f"[{lang}] one copy each gives no warning")
        check(text.count(T("settings.env_versions_missing")) == 3,
              f"[{lang}] missing numpy, gcc and primecount each say 'not installed'")

        report["libs"]["primesieve"] = ev.lib_entry(
            "12.15", "/usr/local/lib/libprimesieve.so.12.15",
            ["/a/libprimesieve.so.12.12", "/usr/local/lib/libprimesieve.so.12.15"],
            {"prime_sieve_engine_v6.so": "/a/libprimesieve.so.12.12"})
        report["duplicates"] = ev.duplicates(report["libs"])
        text, warning = format_report(report, T)
        check("prime_sieve_engine_v6.so" in warning and "/a/libprimesieve.so.12.12" in warning,
              f"[{lang}] an engine loading another copy than Python is named in the warning")


def _test_argv_and_wiring():
    print("\n--- argv, wsl_helpers and the Settings handler ---")
    from primeatlas.generation.engine_argv import build_env_versions_argv
    argv = build_env_versions_argv()
    check(argv[0] == "python3" and argv[-1].endswith("prime_sieve/env_versions.py"),
          f"the probe runs prime_sieve/env_versions.py under python3 (got {argv!r})")

    import tkinter.messagebox as messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    import prime_atlas_v2

    portal = tempfile.mkdtemp(prefix="env_versions_test_")
    try:
        sys.argv = ["prime_atlas_v2.py"]
        from app_sandbox import isolate_app
        isolate_app(portal)
        app = prime_atlas_v2._build_gui()()
        app.update()
        tab = app.settings_tab
        for key in ("build_env_versions_argv", "run_env_versions_wsl_blocking"):
            check(key in tab.wsl and callable(tab.wsl[key]),
                  f"wsl_helpers exposes a callable {key!r}")
        check(tab.T("settings.env_versions_not_checked") in tab.env_versions_var.get(),
              "the versions line starts as 'not checked yet'")

        import env_versions as ev
        payload = {"ok": True, "distro": "Ubuntu 26.04 LTS", "python": "3.14.4",
                   "numpy": "2.5.1", "gcc": "15.2.0",
                   "libs": {"primesieve": ev.lib_entry(
                       "12.15", "/usr/local/lib/libprimesieve.so.12.15",
                       ["/x/libprimesieve.so.12.12", "/usr/local/lib/libprimesieve.so.12.15"],
                       {}),
                       "primecount": ev.lib_entry("8.1", "/y/libprimecount.so.8.1",
                                                  ["/y/libprimecount.so.8.1"], {})}}
        payload["duplicates"] = ev.duplicates(payload["libs"])
        tab._env_versions_running = True
        tab._on_env_versions_result(True, payload)
        check(tab._env_versions_running is False, "a result clears the running guard")
        check("Ubuntu 26.04 LTS" in tab.env_versions_var.get(),
              "a result fills the versions text")
        check("/x/libprimesieve.so.12.12" in tab.env_versions_warning_var.get(),
              "duplicates show the warning line")

        tab._on_env_versions_result(False, "WSL hiccup (fake)")
        check("WSL hiccup" in tab.env_versions_var.get(), "a failure shows its error text")
        check(tab.env_versions_warning_var.get() == "", "a failure clears the warning")
        app.destroy()
    finally:
        import shutil
        shutil.rmtree(portal, ignore_errors=True)


def main():
    _test_parsers()
    _test_report()
    _test_view()
    _test_argv_and_wiring()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
