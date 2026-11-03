"""
test_prime_atlas_app_layout.py -- the layout of prime_atlas_v2.py (entry point) and
primeatlas/app/ (PortalBrowserApp split by tab):

  A. every file stays under the 1000-line ceiling;
  B. shared values live only in app_const.py (fixed) and app_dynamic.py (computed at
     startup): no other app module and not prime_atlas_v2.py assigns a module-level value
     (prime_atlas_v2.py's own _SCRIPT_DIR, used for its sys.path setup, aside);
  C. no method is defined in two of PortalBrowserApp's mixins, so none silently shadows
     another through the MRO; every mixin is a base of PortalBrowserApp, with tk.Tk last;
  D. importing prime_atlas_v2 loads no tkinter (the window classes load in _build_gui());
  E. _set_portal_folder() rebinds app_dynamic.PORTAL_FOLDER, the value every tab's
     `lambda: _dyn.PORTAL_FOLDER` getter reads, and reloads both trees only on a change.

Run:
    python unitTests\\test_prime_atlas_app_layout.py
"""
import ast
import glob
import os
import subprocess
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
_APP_DIR = os.path.join(_REPO_ROOT, "primeatlas", "app")
_ENTRY = os.path.join(_REPO_ROOT, "prime_atlas_v2.py")
MAX_LINES = 1000
SHARED_VALUE_MODULES = ("app_const.py", "app_dynamic.py")

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _sources():
    paths = sorted(glob.glob(os.path.join(_APP_DIR, "*.py"))) + [_ENTRY]
    return {path: open(path, encoding="utf-8").read() for path in paths}


def module_level_assignments(source):
    names = []
    for node in ast.parse(source).body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names += [t.id for t in targets if isinstance(t, ast.Name)]
    return names


def section_a(sources):
    print("\n--- A. line ceiling ---")
    check(len(sources) > 10, f"primeatlas/app/ holds the split modules (found {len(sources) - 1})")
    for path, source in sources.items():
        n = source.count("\n")
        check(n <= MAX_LINES, f"{os.path.relpath(path, _REPO_ROOT)} has {n} lines (<= {MAX_LINES})")


def section_b(sources):
    print("\n--- B. shared values only in app_const / app_dynamic ---")
    stray = {}
    for path, source in sources.items():
        name = os.path.basename(path)
        if name in SHARED_VALUE_MODULES:
            continue
        values = [v for v in module_level_assignments(source)
                  if not (path == _ENTRY and v == "_SCRIPT_DIR")]
        if values:
            stray[name] = values
    check(not stray, f"no other module assigns a module-level value (found {stray})")
    for name in SHARED_VALUE_MODULES:
        source = sources[os.path.join(_APP_DIR, name)]
        check(module_level_assignments(source), f"{name} holds shared values")
    dynamic = module_level_assignments(sources[os.path.join(_APP_DIR, "app_dynamic.py")])
    check({"APP_SETTINGS", "PORTAL_FOLDER", "TRANSLATOR", "T"} <= set(dynamic),
          f"app_dynamic.py owns APP_SETTINGS, PORTAL_FOLDER, TRANSLATOR and T (has {dynamic})")


def section_c():
    print("\n--- C. mixins ---")
    sys.path.insert(0, _REPO_ROOT)
    sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
    sys.path.insert(0, os.path.join(_REPO_ROOT, "constellation"))
    import tkinter as tk
    from primeatlas.app.app_window import PortalBrowserApp

    owners = {}
    duplicates = []
    for path in sorted(glob.glob(os.path.join(_APP_DIR, "*.py"))):
        for node in ast.parse(open(path, encoding="utf-8").read()).body:
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        if item.name in owners:
                            duplicates.append(f"{item.name}: {owners[item.name]} and {node.name}")
                        owners[item.name] = node.name
    check(not duplicates, f"no method is defined in two app classes ({duplicates})")
    mixin_names = sorted(set(owners.values()) - {"PortalBrowserApp"})
    bases = [base.__name__ for base in PortalBrowserApp.__bases__]
    check(set(mixin_names) <= set(bases),
          f"every mixin is a base of PortalBrowserApp (mixins {mixin_names}, bases {bases})")
    check(PortalBrowserApp.__bases__[-1] is tk.Tk, "tk.Tk is PortalBrowserApp's last base")


def section_d():
    print("\n--- D. importing prime_atlas_v2 needs no tkinter ---")
    code = ("import sys; sys.path.insert(0, %r); sys.argv = ['prime_atlas_v2.py']; "
            "import prime_atlas_v2; "
            "print(sorted(m for m in sys.modules if m.split('.')[0] == 'tkinter'))" % _REPO_ROOT)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    check(out.returncode == 0 and out.stdout.strip() == "[]",
          f"import prime_atlas_v2 loads no tkinter module (stdout {out.stdout.strip()!r}, "
          f"stderr {out.stderr.strip()[-200:]!r})")


def section_e():
    print("\n--- E. _set_portal_folder ---")
    from primeatlas.app import app_dynamic
    from primeatlas.app.settings_wiring import SettingsWiringMixin

    class _Var:
        def set(self, value):
            self.value = value

    class _Fake:
        def __init__(self):
            self.status = _Var()
            self.reloads = []

        def reload_primes_tree(self):
            self.reloads.append("primes")

        def reload_constellations_tree(self):
            self.reloads.append("constellations")

    saved = app_dynamic.PORTAL_FOLDER
    try:
        getter = lambda: app_dynamic.PORTAL_FOLDER  # the shape every tab receives
        fake = _Fake()
        new_path = os.path.join(saved, "elsewhere_for_test")
        SettingsWiringMixin._set_portal_folder(fake, new_path)
        check(app_dynamic.PORTAL_FOLDER == new_path and getter() == new_path,
              "a new path rebinds app_dynamic.PORTAL_FOLDER and the tab getters see it")
        check(fake.reloads == ["primes", "constellations"], f"both trees reload (got {fake.reloads})")
        check(new_path in fake.status.value, "the status line names the new folder")
        fake.reloads.clear()
        SettingsWiringMixin._set_portal_folder(fake, new_path)
        check(fake.reloads == [], f"the same path again reloads nothing (got {fake.reloads})")
    finally:
        app_dynamic.PORTAL_FOLDER = saved


def main():
    sources = _sources()
    section_a(sources)
    section_b(sources)
    section_c()
    section_d()
    section_e()
    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
