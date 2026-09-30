"""
startup_dependency_check.py -- checks the native-Windows Python packages PrimeAtlas needs
(requirements.txt: numpy, moderngl, glfw) BEFORE prime_atlas_v1.py imports the primeatlas
package, and offers to pip-install whatever is missing.

Why this lives at the repo root and not inside primeatlas/: primeatlas/__init__.py itself
imports numpy (via research/goldbach_window.py), so on a fresh machine without numpy ANY
`import primeatlas.<anything>` dies with a bare ImportError before a single window is shown.
This module therefore must not import primeatlas at all -- it reads the language choice and
its locale strings straight from primeatlas/core/locales/*.json with plain json, and
re-implements the one-line pip argv instead of reusing generation.py's
build_pip_install_argv().

Only numpy is startup-blocking (REQUIRED_FOR_STARTUP); moderngl/glfw are needed only by the
Ring visualization renderer, so declining them (or a failed install) still lets the app
start. Nothing missing => no Tk window is created at all, so a normal launch pays only a
few importlib.util.find_spec() calls.

The decision flow (ensure_dependencies) takes every UI/subprocess boundary as an injectable
callable, same "thin, separately named I/O wrappers" split as primeatlas/settings/
env_setup.py, so unitTests/test_startup_dependency_check.py exercises it without Tk or pip.
"""
import importlib
import importlib.util
import json
import locale
import os
import re
import site
import subprocess
import sys
import threading

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS_PATH = os.path.join(_REPO_ROOT, "requirements.txt")
LOCALES_DIR = os.path.join(_REPO_ROOT, "primeatlas", "core", "locales")
LANGUAGE_SETTINGS_PATH = os.path.join(LOCALES_DIR, "language_settings.json")

# Used only if requirements.txt is missing (e.g. a partial copy of the repo).
DEFAULT_REQUIREMENTS = ("numpy", "moderngl", "glfw")
# Without these the primeatlas package cannot even be imported.
REQUIRED_FOR_STARTUP = ("numpy",)

# English fallback, also the canonical key list -- both strings_*.json files must define
# every key here (checked by the unit test).
FALLBACK_STRINGS = {
    "depcheck.title": "PrimeAtlas -- missing Python packages",
    "depcheck.ask_blocking": "PrimeAtlas cannot start without these Python packages:\n\n"
                             "{packages}\n\nInstall them now? (requires internet access)",
    "depcheck.ask_optional": "These Python packages are needed for the Ring "
                             "visualization:\n\n{packages}\n\nInstall them now? "
                             "(requires internet access; PrimeAtlas starts either way)",
    "depcheck.installing": "Installing: {packages}",
    "depcheck.install_failed": "Installation failed (pip exit code {code}).\n\n"
                               "You can install manually from a terminal:\n{command}",
    "depcheck.still_missing": "Installation finished, but these packages still cannot be "
                              "imported: {packages}\n\nTry manually from a terminal:\n{command}",
    "depcheck.declined_blocking": "PrimeAtlas cannot start without: {packages}\n\n"
                                  "Install from a terminal:\n{command}",
    "depcheck.close": "Close",
}


# ------------------------------------------------------------------------------------------
# Pure logic
# ------------------------------------------------------------------------------------------

_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def parse_requirements(text):
    """Requirement NAMES (pip spelling) from requirements.txt text, in file order.
    Drops comments, blank lines, pip options (-r, -e, --index-url...), and any
    version specifier / extras / environment marker after the name."""
    names = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = _NAME_RE.match(line)
        if m:
            names.append(m.group(1))
    return names


def load_requirements(path=REQUIREMENTS_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return parse_requirements(f.read())
    except OSError:
        return list(DEFAULT_REQUIREMENTS)


def import_name_for(pip_name):
    return pip_name.lower().replace("-", "_")


def find_missing(pip_names, find_spec=importlib.util.find_spec):
    """pip names whose import name cannot be found. find_spec only locates the module,
    it doesn't import it -- a launch with everything present stays cheap."""
    missing = []
    for name in pip_names:
        try:
            found = find_spec(import_name_for(name)) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append(name)
    return missing


def is_blocking(missing):
    return any(import_name_for(name) in REQUIRED_FOR_STARTUP for name in missing)


def in_virtualenv():
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def build_pip_argv(executable, packages, in_venv):
    """Same interpreter that runs the app (never a bare "python" from PATH); --user so no
    admin rights are needed, except inside a venv where pip rejects --user."""
    argv = [executable, "-m", "pip", "install"]
    if not in_venv:
        argv.append("--user")
    return argv + list(packages)


def resolve_language(saved_path=LANGUAGE_SETTINGS_PATH, os_locale=None):
    """The app's saved language if set, else Polish for a Polish OS locale, else English.
    (The app itself defaults to English, but on a fresh machine nothing is saved yet and
    this dialog is the very first thing a user sees.)"""
    try:
        with open(saved_path, encoding="utf-8") as f:
            lang = json.load(f).get("language")
        if lang in ("pl", "en"):
            return lang
    except (OSError, ValueError, AttributeError):
        pass
    if os_locale and os_locale.lower().startswith(("pl", "polish")):
        return "pl"
    return "en"


def _os_locale():
    try:
        return locale.getlocale()[0]
    except (ValueError, TypeError):
        return None


def load_strings(language, locales_dir=LOCALES_DIR):
    strings = dict(FALLBACK_STRINGS)
    try:
        with open(os.path.join(locales_dir, f"strings_{language}.json"), encoding="utf-8") as f:
            data = json.load(f)
        strings.update({k: v for k, v in data.items() if k in FALLBACK_STRINGS})
    except (OSError, ValueError, AttributeError):
        pass
    return strings


def refresh_import_paths():
    """A --user install into a user site-packages directory that did not exist when this
    interpreter started is NOT on sys.path (site.py only adds it if present at startup) --
    add it now so the freshly installed packages are importable in this same process."""
    try:
        user_site = site.getusersitepackages()
        if os.path.isdir(user_site) and user_site not in sys.path:
            site.addsitedir(user_site)
    except (AttributeError, OSError):
        pass
    importlib.invalidate_caches()


# ------------------------------------------------------------------------------------------
# Decision flow
# ------------------------------------------------------------------------------------------

def ensure_dependencies(requirements=None, strings=None, find_spec=importlib.util.find_spec,
                        ask_user=None, run_install=None, refresh_paths=refresh_import_paths,
                        show_error=None, executable=None, in_venv=None):
    """True if the app may continue starting, False if it must exit."""
    requirements = load_requirements() if requirements is None else requirements
    missing = find_missing(requirements, find_spec=find_spec)
    if not missing:
        return True

    strings = strings or load_strings(resolve_language(os_locale=_os_locale()))
    ask_user = ask_user or _tk_ask_user
    run_install = run_install or _tk_run_install
    show_error = show_error or _tk_show_error
    executable = executable or sys.executable
    in_venv = in_virtualenv() if in_venv is None else in_venv

    blocking = is_blocking(missing)
    argv = build_pip_argv(executable, missing, in_venv)
    command = " ".join(f'"{a}"' if " " in a else a for a in argv)
    packages = ", ".join(missing)

    if not ask_user(strings, missing, blocking):
        if blocking:
            show_error(strings, strings["depcheck.declined_blocking"].format(
                packages=packages, command=command))
            return False
        return True

    code = run_install(strings, argv)
    if code != 0:
        show_error(strings, strings["depcheck.install_failed"].format(code=code, command=command))
        return not blocking

    refresh_paths()
    still_missing = find_missing(missing, find_spec=find_spec)
    if still_missing:
        show_error(strings, strings["depcheck.still_missing"].format(
            packages=", ".join(still_missing), command=command))
        return not is_blocking(still_missing)
    return True


# ------------------------------------------------------------------------------------------
# Tk UI (thin; not unit-tested)
# ------------------------------------------------------------------------------------------

def _hidden_root():
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    return root


def _tk_ask_user(strings, missing, blocking):
    try:
        from tkinter import messagebox
        root = _hidden_root()
    except Exception:
        return False
    try:
        key = "depcheck.ask_blocking" if blocking else "depcheck.ask_optional"
        text = strings[key].format(packages="\n".join(f"  - {m}" for m in missing))
        return bool(messagebox.askyesno(strings["depcheck.title"], text, parent=root))
    finally:
        root.destroy()


def _tk_show_error(strings, message):
    try:
        from tkinter import messagebox
        root = _hidden_root()
    except Exception:
        print(message, file=sys.stderr)
        return
    try:
        messagebox.showerror(strings["depcheck.title"], message, parent=root)
    finally:
        root.destroy()


def _no_window_kwargs():
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def _tk_run_install(strings, argv):
    """Runs pip with its output streamed live into a small Tk window; closing the window is
    disabled until pip finishes. Returns pip's exit code (or -1 if it could not start)."""
    import queue
    import tkinter as tk

    root = tk.Tk()
    root.title(strings["depcheck.title"])
    root.geometry("720x360")
    packages = ", ".join(a for a in argv[4:] if a != "--user")
    tk.Label(root, text=strings["depcheck.installing"].format(packages=packages),
             anchor="w").pack(fill="x", padx=8, pady=(8, 4))
    log = tk.Text(root, height=16, wrap="word")
    log.pack(fill="both", expand=True, padx=8)
    close_btn = tk.Button(root, text=strings["depcheck.close"], state="disabled",
                          command=root.destroy)
    close_btn.pack(pady=8)
    root.protocol("WM_DELETE_WINDOW", lambda: None)

    out = queue.Queue()
    result = {"code": -1}

    def worker():
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, text=True, errors="replace",
                                    **_no_window_kwargs())
            for line in proc.stdout:
                out.put(line)
            result["code"] = proc.wait()
        except OSError as exc:
            out.put(f"{exc}\n")
        out.put(None)

    def poll():
        try:
            while True:
                line = out.get_nowait()
                if line is None:
                    if result["code"] == 0:
                        root.destroy()
                        return
                    close_btn.config(state="normal")
                    root.protocol("WM_DELETE_WINDOW", root.destroy)
                    return
                log.insert("end", line)
                log.see("end")
        except queue.Empty:
            pass
        root.after(100, poll)

    threading.Thread(target=worker, daemon=True).start()
    root.after(100, poll)
    root.mainloop()
    return result["code"]
