"""
test_startup_dependency_check.py -- covers startup_dependency_check.py (repo root), the
pre-import check for native-Windows Python packages (numpy, moderngl, glfw) that runs from
prime_atlas_v2.py BEFORE `from primeatlas import ...` -- primeatlas/__init__.py itself pulls
in numpy (via research/goldbach_window.py), so on a fresh machine without numpy the app
used to die with a bare ImportError before any window was shown.

Written against the intended behavior (spec first), not the implementation. Sections:

  A. Pure logic -- requirements parsing, import-name mapping, pip argv, missing detection,
     language resolution, locale strings.
  B. ensure_dependencies() decision flow, every UI/subprocess boundary injected:
     fast path, declined (blocking / non-blocking), install success, install failure,
     install "success" that still leaves the package invisible.
  C. Wiring -- the module never imports primeatlas/numpy itself, and prime_atlas_v2.py
     runs it before its first `from primeatlas import`.

Usage:
    python unitTests/test_startup_dependency_check.py
"""
import json
import os
import subprocess
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))  # primeatlas/__init__ needs it

import startup_dependency_check as sdc  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


# ============================================================================================
# Section A -- pure logic
# ============================================================================================

def section_a():
    print("\n--- Section A: pure logic ---")

    parsed = sdc.parse_requirements(
        "# comment line\n"
        "\n"
        "numpy>=1.24\n"
        "  moderngl[extra]==5.8  # trailing comment\n"
        "glfw ; sys_platform == 'win32'\n"
        "-r other.txt\n"
        "Some-Pkg~=1.0\n"
    )
    check(parsed == ["numpy", "moderngl", "glfw", "Some-Pkg"],
          f"parse_requirements strips comments/blanks/specifiers/extras/markers/options "
          f"(got {parsed!r})")

    check(sdc.import_name_for("Some-Pkg") == "some_pkg",
          "import_name_for lowercases and maps '-' to '_'")
    check(sdc.import_name_for("numpy") == "numpy", "import_name_for('numpy') == 'numpy'")

    req_path = os.path.join(_REPO_ROOT, "requirements.txt")
    check(os.path.isfile(req_path), "requirements.txt exists at the repo root (the installer "
                                    "and the startup check both read it)")
    reqs = sdc.load_requirements(req_path)
    for name in ("numpy", "moderngl", "glfw"):
        check(name in reqs, f"requirements.txt lists {name}")
    for name in sdc.REQUIRED_FOR_STARTUP:
        check(name in reqs, f"every startup-blocking package ({name}) is in requirements.txt")

    missing_path = os.path.join(tempfile.gettempdir(), "definitely_missing_requirements.txt")
    check(sdc.load_requirements(missing_path) == list(sdc.DEFAULT_REQUIREMENTS),
          "load_requirements falls back to DEFAULT_REQUIREMENTS when the file is missing")

    present = {"numpy", "some_pkg"}
    fake_find_spec = lambda name: object() if name in present else None
    check(sdc.find_missing(["numpy", "Some-Pkg", "glfw"], find_spec=fake_find_spec) == ["glfw"],
          "find_missing checks the IMPORT name and keeps requirement order")

    def raising_find_spec(name):
        raise ValueError("broken spec")
    check(sdc.find_missing(["numpy"], find_spec=raising_find_spec) == ["numpy"],
          "find_missing treats a find_spec exception as 'missing', never crashes")

    check(sdc.is_blocking(["glfw", "numpy"]) is True, "numpy missing => blocking")
    check(sdc.is_blocking(["moderngl", "glfw"]) is False, "only viz deps missing => not blocking")
    check(sdc.is_blocking([]) is False, "nothing missing => not blocking")

    # No --user: pip itself falls back to a user install when the interpreter's own
    # site-packages isn't writable (system Python), while the installer's private Python
    # and venvs get the packages in their own site-packages -- a forced --user would put
    # them into %APPDATA%\Python\PythonXY, shared with every other Python of that version.
    # --no-warn-script-location: pip's "is Scripts\ on PATH?" check calls Path.resolve()
    # on EVERY PATH entry, and a redirection (reparse) point among them can make Windows
    # raise WinError 448 "untrusted mount point" and pip abort the whole install. The flag
    # skips that scan -- the installer uses it too.
    argv = sdc.build_pip_argv("C:\\Py\\python.exe", ["numpy", "glfw"])
    check(argv == ["C:\\Py\\python.exe", "-m", "pip", "install", "--disable-pip-version-check",
                   "--no-warn-script-location", "numpy", "glfw"],
          f"pip argv never forces --user and never scans PATH (got {argv!r})")
    from primeatlas.generation.generation import build_pip_install_argv
    sympy_argv = build_pip_install_argv("sympy")
    check("--no-warn-script-location" in sympy_argv and "--user" not in sympy_argv
          and sympy_argv[-1] == "sympy",
          f"the Settings tab's sympy installer skips the PATH scan too (got {sympy_argv!r})")

    with tempfile.TemporaryDirectory() as tmp:
        saved = os.path.join(tmp, "language_settings.json")
        check(sdc.resolve_language(saved, "pl_PL") == "pl",
              "no saved language + Polish OS locale => pl")
        check(sdc.resolve_language(saved, "Polish_Poland") == "pl",
              "no saved language + Windows-style 'Polish_Poland' locale => pl")
        check(sdc.resolve_language(saved, "de_DE") == "en",
              "no saved language + other locale => en (app default)")
        check(sdc.resolve_language(saved, None) == "en", "no saved language + no locale => en")
        with open(saved, "w", encoding="utf-8") as f:
            json.dump({"language": "en"}, f)
        check(sdc.resolve_language(saved, "pl_PL") == "en",
              "a saved language always wins over the OS locale")
        with open(saved, "w", encoding="utf-8") as f:
            f.write("{not json")
        check(sdc.resolve_language(saved, "pl_PL") == "pl",
              "an unreadable saved-language file falls back to the OS locale")

        strings = sdc.load_strings("en", locales_dir=tmp)
        check(set(strings) == set(sdc.FALLBACK_STRINGS),
              "load_strings with no locale file falls back to the built-in English strings")

    locales_dir = os.path.join(_REPO_ROOT, "primeatlas", "core", "locales")
    for lang in ("pl", "en"):
        with open(os.path.join(locales_dir, f"strings_{lang}.json"), encoding="utf-8") as f:
            data = json.load(f)
        for key in sdc.FALLBACK_STRINGS:
            check(key in data, f"strings_{lang}.json defines {key}")
    pl = sdc.load_strings("pl", locales_dir=locales_dir)
    check(pl["depcheck.title"] != sdc.FALLBACK_STRINGS["depcheck.title"],
          "load_strings('pl') actually returns the Polish text")


# ============================================================================================
# Section B -- ensure_dependencies() flow
# ============================================================================================

class Recorder:
    def __init__(self, ask_answer=True, install_rc=0, installed_effect=None):
        self.present = set()
        self.ask_answer = ask_answer
        self.install_rc = install_rc
        self.installed_effect = installed_effect  # set of import names that appear after install
        self.calls = []

    def find_spec(self, name):
        return object() if name in self.present else None

    def ask_user(self, strings, missing, blocking):
        self.calls.append(("ask", tuple(missing), blocking))
        return self.ask_answer

    def run_install(self, strings, argv):
        self.calls.append(("install", tuple(argv)))
        if self.install_rc == 0 and self.installed_effect:
            self.pending = set(self.installed_effect)
        return self.install_rc

    def refresh_paths(self):
        self.calls.append(("refresh",))
        self.present |= getattr(self, "pending", set())

    def show_error(self, strings, message):
        self.calls.append(("error", message))

    def run(self, reqs=("numpy", "moderngl", "glfw")):
        return sdc.ensure_dependencies(
            requirements=list(reqs), strings=dict(sdc.FALLBACK_STRINGS),
            find_spec=self.find_spec, ask_user=self.ask_user, run_install=self.run_install,
            refresh_paths=self.refresh_paths, show_error=self.show_error,
            executable="PY")

    def kinds(self):
        return [c[0] for c in self.calls]


def section_b():
    print("\n--- Section B: ensure_dependencies() flow ---")

    r = Recorder()
    r.present = {"numpy", "moderngl", "glfw"}
    check(r.run() is True and r.calls == [],
          "fast path: nothing missing => True with NO dialog/install/refresh at all")

    r = Recorder(ask_answer=False)
    r.present = {"numpy"}
    check(r.run() is True, "only viz deps missing + declined => app still starts")
    check(r.kinds() == ["ask"], f"declined => no install attempted (calls {r.kinds()})")
    check(r.calls[0][1:] == (("moderngl", "glfw"), False),
          "the dialog is told exactly what's missing and that it is NOT blocking")

    r = Recorder(ask_answer=False)
    check(r.run() is False, "numpy missing + declined => app does not start")
    check(r.calls[0][2] is True, "the dialog is told the missing set IS blocking")
    check(r.kinds()[-1] == "error", "declining a blocking install shows an explanation")

    r = Recorder(ask_answer=True, install_rc=0, installed_effect={"numpy", "moderngl", "glfw"})
    check(r.run() is True, "accepted + pip succeeds => app starts")
    check(r.kinds() == ["ask", "install", "refresh"],
          f"install then refresh import paths BEFORE re-checking (calls {r.kinds()})")
    check(r.calls[1][1] == ("PY", "-m", "pip", "install", "--disable-pip-version-check",
                            "--no-warn-script-location", "numpy", "moderngl", "glfw"),
          f"only the missing packages are installed, with the running interpreter "
          f"(got {r.calls[1][1]!r})")

    r = Recorder(ask_answer=True, install_rc=0, installed_effect={"moderngl", "glfw"})
    r.present = {"numpy"}
    r.run()
    check(r.calls[1][1][-2:] == ("moderngl", "glfw"), "already-present packages are not reinstalled")

    r = Recorder(ask_answer=True, install_rc=1)
    check(r.run() is False, "pip fails + numpy missing => app does not start")
    check(r.kinds()[-1] == "error", "pip failure shows an error")
    err = r.calls[-1][1]
    check("PY -m pip install --disable-pip-version-check --no-warn-script-location "
          "numpy moderngl glfw" in err,
          f"the error contains the exact manual command to run (got {err!r})")

    r = Recorder(ask_answer=True, install_rc=1)
    r.present = {"numpy"}
    check(r.run() is True, "pip fails but only viz deps were missing => app still starts")
    check(r.kinds()[-1] == "error", "... and the failure is still reported")

    r = Recorder(ask_answer=True, install_rc=0, installed_effect=set())
    check(r.run() is False,
          "pip reports success but numpy is still not importable => app does not start")
    check(r.kinds()[-1] == "error", "... with an error instead of a later ImportError crash")


# ============================================================================================
# Section C -- wiring
# ============================================================================================

def section_c():
    print("\n--- Section C: wiring ---")

    code = ("import sys; sys.path.insert(0, %r); import startup_dependency_check; "
            "print(sorted(m for m in sys.modules if m == 'numpy' or m.startswith('primeatlas')))"
            % _REPO_ROOT)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    check(out.returncode == 0 and out.stdout.strip() == "[]",
          f"importing startup_dependency_check pulls in neither numpy nor primeatlas "
          f"(stdout {out.stdout.strip()!r}, stderr {out.stderr.strip()[-200:]!r})")

    with open(os.path.join(_REPO_ROOT, "prime_atlas_v2.py"), encoding="utf-8") as f:
        src = f.read()
    call_idx = src.find("startup_dependency_check.ensure_dependencies(")
    import_idx = src.find("from primeatlas import (")
    check(call_idx != -1, "prime_atlas_v2.py calls startup_dependency_check.ensure_dependencies")
    check(call_idx != -1 and call_idx < import_idx,
          "the check runs BEFORE prime_atlas_v2.py's first `from primeatlas import`")
    guard_idx = src.rfind('if __name__ == "__main__":', 0, call_idx)
    check(guard_idx != -1 and guard_idx < call_idx and src.count("\n", guard_idx, call_idx) <= 3,
          "the check is guarded by __name__ == '__main__' so importing prime_atlas_v2 "
          "(tests) never pops a dialog")


if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
