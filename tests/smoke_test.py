"""
smoke_test.py -- regression safety net for the refactor branch.

Constructs the real PortalBrowserApp (against a throwaway, empty portal folder so it
never touches real generated data) and selects every top-level tab plus every inner
sub-notebook tab, under a virtual display (Xvfb) or a real one. Any exception raised
while building the app or selecting a tab is a failure -- this is meant to be run after
every extraction step in the refactor, before committing, so a broken import or a
tkinter wiring mistake never survives to the next step.

Usage (Windows, real display):
    python tests\\smoke_test.py

Usage (Linux/WSL, headless):
    xvfb-run -a python3 tests/smoke_test.py

This does NOT require WSL or any generated prime data to be present -- CONSTELLATION_
PORTAL_DIR is overridden to a fresh temp folder for the duration of the run, so it
always exercises the "empty storage" code path regardless of what's on the real machine.
Exit code 0 = every tab selected cleanly, 1 = at least one exception.
"""
import os
import shutil
import sys
import tempfile
import traceback

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)

_tmp_portal = tempfile.mkdtemp(prefix="primeatlas_smoketest_")
os.environ["CONSTELLATION_PORTAL_DIR"] = _tmp_portal
sys.argv = ["prime_atlas_v1.py"]

failures = []


def report(where, exc):
    failures.append(where)
    print(f"--- EXCEPTION during {where} ---")
    traceback.print_exception(type(exc), exc, exc.__traceback__)


def find_notebooks(widget):
    """Recursively finds every ttk.Notebook under `widget` -- the app nests a
    sub-notebook per top-level tab (Liczby pierwsze / Konstelacje / Badania / Ustawienia),
    while Generowanie/Benchmark are flat -- this walk doesn't need to know which is
    which, it just finds whatever's there."""
    found = []
    for child in widget.winfo_children():
        if child.winfo_class() == "TNotebook":
            found.append(child)
        found.extend(find_notebooks(child))
    return found


def main():
    try:
        import prime_atlas_v1
    except Exception as exc:
        report("import prime_atlas_v1", exc)
        return 1

    try:
        app_cls = prime_atlas_v1._build_gui()
    except Exception as exc:
        report("_build_gui()", exc)
        return 1

    try:
        app = app_cls()
    except Exception as exc:
        report("PortalBrowserApp()", exc)
        return 1

    app.update()

    try:
        notebook = app.main_notebook
        tab_ids = notebook.tabs()
        print(f"Top-level tabs found: {len(tab_ids)}")
        for tab_id in tab_ids:
            name = notebook.tab(tab_id, "text")
            try:
                notebook.select(tab_id)
                app.update()
                print(f"  selected top tab: {name!r} OK")
            except Exception as exc:
                report(f"selecting top tab {name!r}", exc)
                continue

            for inner in find_notebooks(notebook.nametowidget(tab_id)):
                for inner_tab_id in inner.tabs():
                    inner_name = inner.tab(inner_tab_id, "text")
                    try:
                        inner.select(inner_tab_id)
                        app.update()
                        print(f"    selected inner tab: {inner_name!r} OK")
                    except Exception as exc:
                        report(f"selecting inner tab {inner_name!r} (under {name!r})", exc)
    except Exception as exc:
        report("tab walk", exc)

    try:
        app.destroy()
    except Exception as exc:
        report("app.destroy()", exc)

    shutil.rmtree(_tmp_portal, ignore_errors=True)

    if failures:
        print(f"\nSMOKE TEST FAILED -- {len(failures)} failure(s): {failures}")
        return 1
    print("\nSMOKE TEST PASSED -- every tab selected with no exception.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
