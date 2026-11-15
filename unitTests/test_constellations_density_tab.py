"""
test_constellations_density_tab.py -- the Constellations tab's Density sub-tab
(primeatlas/constellations/constellations_density_tab.py) in the real app, over a portal
scanned by the real constellation_finder_v2_3.py (built as in test_constellations_density.py):

  - it is the fourth Constellations sub-tab; en and pl hold the same const_density keys;
  - before a scan the chart says there is nothing to draw and Stop is disabled;
  - a k=2 scan fills the table with exactly scan_density()'s rows, names the windows in the
    notes and draws one point per scanned floor with the line at 1;
  - k=7 adds a sum row per floor, charts the sum first and the selected variant after a
    click;
  - a floor range limits the rows; a range without finder progress says so and leaves the
    chart empty; a reversed range is an error and starts nothing;
  - Stop during a scan: the button is live, the progress bar shows floors done, the
    finished floors are shown with the stopped status, the buttons come back;
  - a failing scan shows an error and leaves the tab usable;
  - k and the floor range are remembered and restored by a new tab.

Usage:
    python unitTests\\test_constellations_density_tab.py
"""
import json
import os
import shutil
import sys
import tempfile
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "constellation"))

sys.stdout.reconfigure(errors="backslashreplace")

import test_constellations_density as fixture  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _pump(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def _pump_until(app, condition, seconds=60):
    deadline = time.time() + seconds
    while time.time() < deadline and not condition():
        app.update()
        time.sleep(0.02)
    app.update()


def _set(entry, value):
    entry.delete(0, "end")
    entry.insert(0, value)


def _scan(app, tab, k, floor_from="", floor_to=""):
    tab.k_combo.set(str(k))
    _set(tab.floor_from_entry, floor_from)
    _set(tab.floor_to_entry, floor_to)
    tab.scan_button.invoke()
    _pump_until(app, lambda: not tab._busy)


def _locale_keys(language):
    path = os.path.join(_REPO_ROOT, "primeatlas", "core", "locales", f"strings_{language}.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {k for k in data if k.startswith("const_density.")} | (
        {"tabs.constellations_density"} & set(data))


def test_wiring(app, T):
    from primeatlas.core.i18n import Translator
    sub = app.constellations_sub_notebook
    texts = [sub.tab(t, "text") for t in sub.tabs()]
    check(len(texts) == 4 and texts[-1] == T("tabs.constellations_density"),
          f"Density is the fourth Constellations sub-tab ({texts})")
    en, pl = _locale_keys("en"), _locale_keys("pl")
    check(en == pl and len(en) > 15, f"en and pl hold the same keys (only en: {sorted(en - pl)}, "
                                     f"only pl: {sorted(pl - en)})")
    for lang in ("en", "pl"):
        tr = Translator(lang)
        missing = [k for k in en if tr(k) == k]
        check(not missing, f"{lang}: every key translates ({missing})")


def test_scans(app, tab, T, portal):
    from primeatlas.constellations import density_scan
    from primeatlas.constellations.constellations_density_tab import format_row
    check(tab.canvas.find_withtag("empty") and str(tab.stop_button.cget("state")) == "disabled",
          "before a scan: empty chart, Stop disabled")

    _scan(app, tab, 2)
    want, notes, _stopped = density_scan.scan_density(portal, 2)
    items = tab.tree.get_children()
    got = [tab.tree.item(i, "values") for i in items]
    expected = [(c[0], T("const_calc.variant_label", id=r["variant_id"])) + c[1:]
                for r, c in ((r, format_row(r)) for r in want)]
    check([tuple(map(str, g)) for g in got] == [tuple(map(str, e)) for e in expected],
          f"k=2: the table holds scan_density()'s rows ({got})")
    done = sum(info["done"] for _f, info in notes)
    check(str(done) in tab.notes_var.get(), f"notes name the scanned windows ({tab.notes_var.get()!r})")
    check(tab.status.get() == T("const_density.status_done", rows=2, floors=2),
          f"status after the scan ({tab.status.get()!r})")
    check(len(tab.canvas.find_withtag("point")) == 2 and len(tab.canvas.find_withtag("ref")) == 1
          and not tab.canvas.find_withtag("empty"), "chart: a point per floor and the line at 1")

    _scan(app, tab, 7)
    keys = [tab._row_keys[i] for i in tab.tree.get_children()]
    check(keys.count((7, None)) == 2 and len(keys) == 2 * (len(set(keys)) - 1) + 2,
          f"k=7: a row per variant and a sum row on both floors ({keys})")
    check(tab.series_key == (7, None) and T("const_density.sum_label", k=7) in
          tab.canvas.itemcget(tab.canvas.find_withtag("title")[0], "text"),
          "the chart starts on the sum")
    variant_item = next(i for i in tab.tree.get_children() if tab._row_keys[i][1] == 2)
    tab.tree.selection_set(variant_item)
    app.update()
    check(tab.series_key == (7, 2) and len(tab.canvas.find_withtag("point")) == 2,
          "selecting a variant row charts that variant")

    _scan(app, tab, 2, "5", "5")
    check([tab.tree.set(i, "floor") for i in tab.tree.get_children()] == ["10p5"],
          "the floor range limits the rows")
    _scan(app, tab, 2, "6", "6")
    check(tab.tree.get_children() == () and tab.notes_var.get() == T("const_density.no_rows")
          and tab.canvas.find_withtag("empty"), "a range without finder progress says so")


def test_errors_and_stop(app, tab, T, shown):
    from primeatlas.constellations import constellations_density_tab as mod
    shown.clear()
    tab.k_combo.set("2")
    _set(tab.floor_from_entry, "6")
    _set(tab.floor_to_entry, "4")
    tab.scan_button.invoke()
    app.update()
    check(len(shown) == 1 and not tab._busy, "a reversed range is an error and starts nothing")
    _set(tab.floor_from_entry, "")
    _set(tab.floor_to_entry, "")

    real_scan = mod.scan_density
    row = {"base_exponent": 4, "k": 2, "variant_id": 1, "width": 10, "hits": 3,
           "expected": 4.0, "ratio": 0.75, "sigma": -0.5}
    info = {"windows": 1, "done": 1, "decoded": 1, "unreadable": 0}

    def slow_scan(portal, k, floor_min, floor_max, stop_event=None, report_progress=None):
        report_progress((1, 3))
        stop_event.wait(20)
        return [row], [(4, info)], True

    mod.scan_density = slow_scan
    try:
        tab.scan_button.invoke()
        _pump(app, 0.5)
        check(tab._busy and str(tab.stop_button.cget("state")) == "normal"
              and str(tab.scan_button.cget("state")) == "disabled", "during a scan only Stop is live")
        check(float(tab.totals_progress.cget("value")) == 1
              and float(tab.totals_progress.cget("maximum")) == 3, "the bar shows 1 of 3 floors")
        tab.stop_button.invoke()
        _pump_until(app, lambda: not tab._busy, 10)
        check(not tab._busy and tab.status.get() == T("const_density.status_stopped", floors=1)
              and len(tab.tree.get_children()) == 1, "Stop shows the finished floor")
        check(str(tab.scan_button.cget("state")) == "normal"
              and str(tab.stop_button.cget("state")) == "disabled", "buttons come back after Stop")

        def failing_scan(*_a, **_k):
            raise OSError("disk gone")

        mod.scan_density = failing_scan
        shown.clear()
        tab.scan_button.invoke()
        _pump_until(app, lambda: not tab._busy, 10)
        check(len(shown) == 1 and "disk gone" in str(shown[0])
              and tab.status.get() == T("const_records.status_error")
              and str(tab.scan_button.cget("state")) == "normal",
              "a failing scan shows the error and leaves Scan usable")
    finally:
        mod.scan_density = real_scan


def test_remembered(app, tab, translator):
    from primeatlas.app import app_dynamic as _dyn
    from primeatlas.core import ui_state_dynamic
    from primeatlas.constellations.constellations_density_tab import ConstellationsDensityTab
    tab.k_combo.set("7")
    _set(tab.floor_from_entry, "5")
    _set(tab.floor_to_entry, "9")
    store = ui_state_dynamic.STORE
    check(store.get("constellations.density.k") == "7"
          and store.get("constellations.density.floor_from") == "5"
          and store.get("constellations.density.floor_to") == "9", "fields are remembered")
    second = ConstellationsDensityTab(app, get_portal_folder=lambda: _dyn.PORTAL_FOLDER,
                                      status_var=tab.status, translator=translator,
                                      eval_quick_number=tab._eval_quick_number,
                                      totals_progress=tab.totals_progress)
    check(second.k_combo.get() == "7" and second.floor_from_entry.get() == "5"
          and second.floor_to_entry.get() == "9", "a new tab restores them")
    second.destroy()


def main():
    import tkinter.messagebox
    shown = []
    tkinter.messagebox.showerror = lambda *a, **k: shown.append(a)

    portal = tempfile.mkdtemp(prefix="primeatlas_density_tab_")
    try:
        fixture._write_windows(portal)
        check(fixture._run_finder(portal, 4) == 0 and fixture._run_finder(portal, 5) == 0,
              "fixture: the finder scans 10^4 and 10^5")
        from app_sandbox import isolate_app
        prime_atlas_v2, _portal = isolate_app(portal)
        app = prime_atlas_v2._build_gui()()
        # The start-up totals scan writes the shared status line; it ends before the tests.
        _pump(app, 5.0)
        try:
            from primeatlas.app import app_dynamic as _dyn
            T = _dyn.T
            tab = app.constellations_density_tab_widget
            test_wiring(app, T)
            test_scans(app, tab, T, portal)
            test_errors_and_stop(app, tab, T, shown)
            test_remembered(app, tab, _dyn.TRANSLATOR)
        finally:
            app.destroy()
    finally:
        shutil.rmtree(portal, ignore_errors=True)
    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
