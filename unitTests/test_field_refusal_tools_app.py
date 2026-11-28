"""Every action of the Constellations, Primality, Prime numbers and Benchmark tabs that reads
number fields refuses a red one first (core/number_field.refuse_problem), with the fields it
reads and no others; so does every page pager's Go.

Drives the real app (temp storage, launches stubbed) with test_field_refusal_app's Harness:
  - Constellations: Records Scan (floor from/to), Records PDF and CSV export (export pages
    from/to), Density Scan (floor from/to), the calculator's Compute (exponent, offset),
    Storage Search; Primality Check and Factorize (N); the primesieve calculator's Compute
    with only the selected operation's fields (count: lo/hi, nth: n/start, next and prev: x);
    Prime numbers Search;
  - Go and Enter of every pager (Prime numbers floor and preview, Storage hits and hit file,
    Records detail and detail file, Benchmark) ask about their own page field only; a refused
    page changes nothing, a valid page is shown as before, an empty one does nothing;
  - an empty search field still shows the "enter an integer" error;
  - each field's minimum is the lower bound its action checks: Primality N 2, primesieve n 1
    and start 0, a and x 0, b 1, calculator exponent and offset 0; searches 0, export pages
    and every Go 1;
  - the primesieve calculator's fields stop at libprimesieve's uint64 range: a, start and x at
    2^64 - 1, b at 2^64, n at pi(2^64); one past is red and Compute refuses it;
  - the constellation calculator's exponent stops at number_text's ceiling, 99 999 (10^e has
    MAX_DIGITS digits), and the offset at 9*10^e - 1 (10^e + offset stays on floor e); one
    past is red and Compute refuses it at once; at both tops Compute lists every number with
    all its digits and Search selected raises nothing;
  - Factorize shows a number and factors past 4300 digits whole, the factors copyable.
Windows, real display:
    python unitTests/test_field_refusal_tools_app.py
"""
import os
import shutil
import sys
import tempfile

# Refusals of long bounds hold · and −, which a cp1250 console cannot print.
sys.stdout.reconfigure(errors="backslashreplace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_field_refusal_app import Harness, _enter, _fields_of, _set_text  # noqa: E402
from test_time_simulation import FAKE_FREE_RAM, check  # noqa: E402


def _wait_loaded(app, seconds=60):
    """Waits until the loading screen gives way to the tabs (Enter needs a shown field)."""
    import time
    end = time.monotonic() + seconds
    while not app.main_notebook.winfo_manager() and time.monotonic() < end:
        app.update()
        time.sleep(0.02)
    return check(bool(app.main_notebook.winfo_manager()), "the tabs are shown after loading")


def _go_button(entry):
    """The Go button beside a pager's page field."""
    return [c for c in entry.master.winfo_children() if c.winfo_class() == "TButton"][0]


def constellation_cases(h, app):
    rec = app.constellations_records_tab_widget
    den = app.constellations_density_tab_widget
    calc = app.constellations_calc_tab_widget
    hits = app.constellations_hits_tab_widget
    rec_floors = [rec.floor_from_entry, rec.floor_to_entry]
    rec_export = [rec.detail_export_from_entry, rec.detail_export_to_entry]
    den_floors = [den.floor_from_entry, den.floor_to_entry]
    calc_fields = [calc.exp_entry, calc.offset_entry]
    passed = True
    for name, action, fields, foreign in (
            ("Records Scan", rec.scan_button.invoke, rec_floors, rec_export + den_floors),
            ("Records PDF export", rec._export_pdf, rec_export, rec_floors),
            ("Records CSV export", rec._export_csv, rec_export, rec_floors),
            ("Density Scan", den.scan_button.invoke, den_floors, rec_floors),
            ("Calculator Compute", calc.compute_button.invoke, calc_fields,
             [hits.hits_search_entry]),
            ("Storage Search", hits.hits_search_button.invoke, [hits.hits_search_entry],
             calc_fields)):
        passed &= h.case(name, action, fields, foreign=foreign)
    calls, _shown, _launched = h.asked(_enter(hits.hits_search_entry))
    passed &= check(len(calls) == 1 and _fields_of(calls[0]) == _fields_of(
        [hits.hits_search_entry]), "Storage Search: Enter asks like its button")
    return passed


def primality_cases(h, app):
    pri = app.primality_tab_widget
    ps = app.primesieve_calc_tab_widget
    passed = True
    for name, button in (("Primality Check", pri.primality_check_button),
                         ("Primality Factorize", pri.primality_factorize_button)):
        passed &= h.case(name, button.invoke, [pri.primality_number_entry],
                         foreign=[ps.primesieve_calc_n_entry])
    lo_hi = [ps.primesieve_calc_lo_entry, ps.primesieve_calc_hi_entry]
    n_start = [ps.primesieve_calc_n_entry, ps.primesieve_calc_start_entry]
    x = [ps.primesieve_calc_x_entry]
    codes = [code for code, _label in ps._primesieve_calc_ops]
    saved = ps.primesieve_calc_op_combo.current()
    for code, fields, foreign in (("count", lo_hi, n_start + x), ("nth", n_start, lo_hi + x),
                                  ("next", x, lo_hi + n_start), ("prev", x, lo_hi + n_start)):
        ps.primesieve_calc_op_combo.current(codes.index(code))
        ps._on_primesieve_calc_operation_changed()
        passed &= h.case(f"primesieve Compute ({code})", ps.primesieve_calc_button.invoke,
                         fields, foreign=foreign + [pri.primality_number_entry])
    ps.primesieve_calc_op_combo.current(saved)
    ps._on_primesieve_calc_operation_changed()
    return passed


def primes_cases(h, app):
    primes = app.primes_tab_widget
    hits = app.constellations_hits_tab_widget
    passed = h.case("Prime numbers Search", primes.search_button.invoke, [primes.search_entry],
                    foreign=[hits.hits_search_entry])
    calls, _shown, _launched = h.asked(_enter(primes.search_entry))
    passed &= check(len(calls) == 1 and _fields_of(calls[0]) == _fields_of(
        [primes.search_entry]), "Prime numbers Search: Enter asks like its button")

    T = app.generation_tab_widget.T
    invalid = T("common.error_invalid_number")
    for name, entry, button in (("Prime numbers", primes.search_entry, primes.search_button),
                                ("Storage", hits.hits_search_entry, hits.hits_search_button)):
        old = _set_text(entry, "")
        h.app.update()
        h.errors.clear()
        h.dialogs.clear()
        button.invoke()
        h.app.update()
        passed &= check(h.errors == [invalid] and not h.dialogs,
                        f"{name} Search: an empty field shows the integer error as before "
                        f"({h.errors[:1]})")
        _set_text(entry, old)
    h.errors.clear()
    return passed


def _pagers(app):
    primes = app.primes_tab_widget
    hits = app.constellations_hits_tab_widget
    rec = app.constellations_records_tab_widget
    return [("Prime numbers floor", primes.floor_goto_entry),
            ("Prime numbers preview", primes.preview_goto_entry),
            ("Storage hits", hits.hits_goto_entry),
            ("Storage hit file", hits.hits_file_goto_entry),
            ("Records detail", rec.detail_goto_entry),
            ("Records detail file", rec.detail_file_goto_entry),
            ("Benchmark", app.benchmark_tab_widget.benchmark_goto_entry)]


def pager_cases(h, app):
    """Go of every pager in the app; Enter where the pager is shown (the preview and hit
    pagers show only with a loaded file, and their Enter is the shared one that
    pager_unit_checks presses)."""
    pagers = _pagers(app)
    passed = True
    for index, (name, entry) in enumerate(pagers):
        other = pagers[(index + 1) % len(pagers)][1]
        passed &= h.case(f"{name} Go", _go_button(entry).invoke, [entry], foreign=[other])
        _enter(entry)()
        if not entry.winfo_viewable():
            continue
        calls, _shown, _launched = h.asked(_enter(entry))
        passed &= check(len(calls) == 1 and _fields_of(calls[0]) == _fields_of([entry]),
                        f"{name}: Enter asks like Go")
    return passed


def pager_unit_checks(h, app):
    """A pager built alone and shown: what Go and Enter pass to its page callback for each
    kind of text, and the errors shown."""
    import tkinter as tk
    from tkinter import ttk
    from primeatlas.core import widgets
    T = app.generation_tab_widget.T
    refusal = T("number_field.fix_field", reason="").split("\n")[0]
    passed = True
    for build in ("group", "row"):
        window = tk.Toplevel(app)
        holder = ttk.Frame(window)
        holder.pack(fill="both", expand=True)
        reached = []
        if build == "group":
            flow = widgets.FlowRow(holder)
            flow.frame.pack(fill="x")
            _p, _n, entry = widgets.add_page_nav_group(
                flow, T, tk.StringVar(app), lambda: None, lambda: None,
                on_goto=lambda: reached.append(entry.get()))
        else:
            row, _p, _n, entry = widgets.add_page_nav_row(
                holder, T, tk.StringVar(app), lambda: None, lambda: None,
                on_goto=lambda: reached.append(entry.get()))
            row.pack(fill="x")
        window.update()
        go = _go_button(entry)
        for how, press in (("Go", go.invoke), ("Enter", _enter(entry))):
            for text, expect in (("2", ["2"]), ("", [""]), ("0", []), ("abc", []),
                                 ("3,000", [])):
                _set_text(entry, text)
                entry.number_field.refresh(at_once=True)
                reached.clear()
                h.errors.clear()
                h.dialogs.clear()
                press()
                window.update()
                refused = len(h.errors) == 1 and refusal in h.errors[0]
                errors_ok = refused if not expect else not h.errors
                passed &= check(reached == expect and errors_ok and not h.dialogs,
                                f"pager {build}: {how} with {text!r} passes {expect} to the "
                                f"page callback ({reached}, errors {h.errors[:1]})")
        window.destroy()
    h.errors.clear()
    return passed


def _problem(entry, text):
    _set_text(entry, text)
    entry.number_field.refresh(at_once=True)
    return entry.number_field.problem


def minimum_checks(app):
    pri = app.primality_tab_widget
    ps = app.primesieve_calc_tab_widget
    calc = app.constellations_calc_tab_widget
    rec = app.constellations_records_tab_widget
    lows = [("primality N", pri.primality_number_entry, 2),
            ("primesieve n", ps.primesieve_calc_n_entry, 1),
            ("primesieve start", ps.primesieve_calc_start_entry, 0),
            ("primesieve a", ps.primesieve_calc_lo_entry, 0),
            ("primesieve b", ps.primesieve_calc_hi_entry, 1),
            ("primesieve x", ps.primesieve_calc_x_entry, 0),
            ("calculator exponent", calc.exp_entry, 0),
            ("calculator offset", calc.offset_entry, 0),
            ("Prime numbers search", app.primes_tab_widget.search_entry, 0),
            ("Storage search", app.constellations_hits_tab_widget.hits_search_entry, 0),
            ("Records export from", rec.detail_export_from_entry, 1),
            ("Records export to", rec.detail_export_to_entry, 1)]
    lows += [(f"{name} Go", entry, 1) for name, entry in _pagers(app)]
    passed = True
    for label, entry, low in lows:
        old = entry.get()
        below = _problem(entry, str(low - 1)) == "range"
        at = _problem(entry, str(low)) is None
        _problem(entry, old)
        passed &= check(below and at, f"{label}: minimum {low}")
    app.update()
    return passed


PI_OF_2_64 = 425_656_284_035_217_743


def primesieve_bound_checks(h, app):
    """The primesieve calculator's fields stop where libprimesieve's uint64 does: a, start and
    x at 2^64 - 1, b (an open end) at 2^64, n at pi(2^64); one past is red and Compute refuses
    it with every field's text kept."""
    ps = app.primesieve_calc_tab_widget
    passed = True
    tops = [("primesieve a", ps.primesieve_calc_lo_entry, "2^64-1", "2^64"),
            ("primesieve b", ps.primesieve_calc_hi_entry, "2^64", "2^64+1"),
            ("primesieve start", ps.primesieve_calc_start_entry, "2^64-1", "2^64"),
            ("primesieve x", ps.primesieve_calc_x_entry, "2^64-1", "2^64"),
            ("primesieve n", ps.primesieve_calc_n_entry, str(PI_OF_2_64), str(PI_OF_2_64 + 1)),
            ("primesieve a in digits", ps.primesieve_calc_lo_entry, str(2 ** 64 - 1),
             str(2 ** 64))]
    for label, entry, top, past in tops:
        old = entry.get()
        at = _problem(entry, top) is None
        over = _problem(entry, past) == "range"
        _problem(entry, old)
        passed &= check(at and over, f"{label}: {top} passes, {past} is red")

    T = ps.T
    refusal = T("number_field.fix_field", reason="").split("\n")[0]
    codes = [code for code, _label in ps._primesieve_calc_ops]
    saved = ps.primesieve_calc_op_combo.current()
    for code, texts in (("count", {ps.primesieve_calc_lo_entry: "2^64",
                                   ps.primesieve_calc_hi_entry: "2^64+5"}),
                        ("count", {ps.primesieve_calc_lo_entry: "0",
                                   ps.primesieve_calc_hi_entry: "10^30"}),
                        ("count", {ps.primesieve_calc_lo_entry: "-5",
                                   ps.primesieve_calc_hi_entry: "100"}),
                        ("next", {ps.primesieve_calc_x_entry: "-5"}),
                        ("nth", {ps.primesieve_calc_n_entry: str(PI_OF_2_64 + 1),
                                 ps.primesieve_calc_start_entry: "0"}),
                        ("nth", {ps.primesieve_calc_n_entry: "1",
                                 ps.primesieve_calc_start_entry: "10^30"}),
                        ("next", {ps.primesieve_calc_x_entry: "10^30"}),
                        ("prev", {ps.primesieve_calc_x_entry: "10^30"})):
        ps.primesieve_calc_op_combo.current(codes.index(code))
        ps._on_primesieve_calc_operation_changed()
        olds = {entry: _set_text(entry, text) for entry, text in texts.items()}
        app.update()
        h.errors.clear()
        h.dialogs.clear()
        launched = h._guarded(ps.primesieve_calc_button.invoke)
        app.update()
        kept = all(entry.get() == text for entry, text in texts.items())
        passed &= check(len(h.errors) == 1 and refusal in h.errors[0] and not h.dialogs
                        and not launched and kept and not ps._primesieve_calc_busy,
                        f"primesieve Compute ({code}) {list(texts.values())}: refused, "
                        f"nothing launched, the text kept ({h.errors[:1]} launched {launched})")
        for entry, old in olds.items():
            _set_text(entry, old)
    ps.primesieve_calc_op_combo.current(saved)
    ps._on_primesieve_calc_operation_changed()
    h.errors.clear()
    app.update()
    return passed


def _recording_callback_errors(app):
    errors = []
    app.report_callback_exception = lambda *a: errors.append(a[1])
    return errors


def calc_bound_checks(h, app):
    calc = app.constellations_calc_tab_widget
    errors = _recording_callback_errors(app)
    passed = True
    olds = {calc.exp_entry: calc.exp_entry.get(), calc.offset_entry: calc.offset_entry.get()}
    for label, exp, offset, red in (
            ("exponent 99999", "99999", "0", None),
            ("exponent 100000", "100000", "0", calc.exp_entry),
            ("exponent 10^30", "10^30", "0", calc.exp_entry),
            ("offset 8999 on exponent 3", "3", "8999", None),
            ("offset 9000 on exponent 3", "3", "9000", calc.offset_entry),
            ("offset 9*10^99999-1 on exponent 99999", "99999", "9*10^99999-1", None),
            ("offset 9*10^99999 on exponent 99999", "99999", "9*10^99999", calc.offset_entry)):
        _set_text(calc.exp_entry, exp)
        _set_text(calc.offset_entry, offset)
        problems = {e: (e.number_field.refresh(at_once=True), e.number_field.problem)[1]
                    for e in (calc.exp_entry, calc.offset_entry)}
        ok = all((problems[e] == "range") == (e is red) for e in problems)
        shown = {("exponent" if e is calc.exp_entry else "offset"): p for e, p in problems.items()}
        passed &= check(ok, f"calculator {label}: {'red' if red else 'passes'} ({shown})")
        if red is None or problems[red] != "range":
            continue  # an unbounded exponent of 10^30 would hang the Compute below
        h.errors.clear()
        calc.compute_button.invoke()
        app.update()
        passed &= check(len(h.errors) == 1 and not errors,
                        f"calculator {label}: Compute refuses it ({h.errors[:1]}, {errors[:1]})")
    for exp, offset in (("99999", "9*10^99999-1"), ("35", "0")):
        _set_text(calc.exp_entry, exp)
        _set_text(calc.offset_entry, offset)
        errors.clear()
        h.errors.clear()
        calc.compute_button.invoke()
        app.update()
        rows = [calc.results_tree.item(i, "values") for i in calc.results_tree.get_children()]
        digits = int(exp) + 1
        whole = bool(rows) and all(sum(c.isdigit() for c in str(r[1])) >= digits for r in rows)
        passed &= check(whole and not errors and not h.errors,
                        f"calculator Compute at exponent {exp}, offset {offset}: every number "
                        f"with all its digits ({len(rows)} rows, {errors[:1]} {h.errors[:1]})")
        if rows:
            calc.results_tree.selection_set(calc.results_tree.get_children()[0])
            errors.clear()
            try:
                calc.search_selected()
                app.update()
            except Exception as error:  # noqa: BLE001
                errors.append(error)
            passed &= check(not errors, f"calculator Search selected at exponent {exp} raises "
                                        f"nothing ({errors[:1]})")
    for entry, old in olds.items():
        _set_text(entry, old)
    h.errors.clear()
    h.dialogs.clear()
    del app.report_callback_exception
    return passed


def big_factor_checks(h, app):
    import time
    pri = app.primality_tab_widget
    errors = _recording_callback_errors(app)
    passed = True
    old = _set_text(pri.primality_number_entry, "2*10^4999")
    pri.primality_factor_result_var.set("")
    pri.primality_factorize_button.invoke()
    deadline = time.monotonic() + 60
    while pri._primality_busy and time.monotonic() < deadline:
        app.update()
        time.sleep(0.02)
    app.update()
    text = pri.primality_factor_result_var.get()
    passed &= check(pri.primality_factors_only_var.get() == "2^5000 x 5^4999"
                    and sum(c.isdigit() for c in text.split("=")[0]) == 5000
                    and not errors and not h.errors,
                    f"Factorize 2*10^4999: the 5000-digit number in full and its factors "
                    f"({text[-60:]!r}, {errors[:1]} {h.errors[:1]})")
    big = 10 ** 4999 + 9
    errors.clear()
    try:
        pri._primality_show_factorize_result(
            2 * big, {"pairs": [(2, 1), (big, 1)], "method": "sympy", "complete": False,
                      "seconds": 0.5})
        app.update()
    except Exception as error:  # noqa: BLE001
        errors.append(error)
    passed &= check(not errors and pri.primality_factors_only_var.get() == "2 x " + str(big)
                    if not errors else False,
                    f"a 5000-digit factor is shown and copyable in full ({errors[:1]})")
    _set_text(pri.primality_number_entry, old)
    pri.primality_factor_result_var.set("")
    pri.primality_factors_only_var.set("")
    h.errors.clear()
    del app.report_callback_exception
    return passed


def main():
    import prime_atlas_v2
    from tkinter import messagebox
    errors, dialogs = [], []
    messagebox.showinfo = lambda title, text="", **k: dialogs.append(text)
    messagebox.showwarning = lambda title, text="", **k: dialogs.append(text)
    messagebox.showerror = lambda title, text="", **k: errors.append(text)
    messagebox.askyesno = lambda *a, **k: dialogs.append("askyesno") or False
    messagebox.askokcancel = lambda *a, **k: dialogs.append("askokcancel") or False
    portal = tempfile.mkdtemp(prefix="primeatlas_field_refusal_tools_")
    app = None
    passed = False
    try:
        sys.argv = ["prime_atlas_v2.py"]
        from app_sandbox import isolate_app
        isolate_app(portal)
        from primeatlas.generation import time_simulation_controls
        time_simulation_controls.estimate_free_ram_bytes = lambda **_k: FAKE_FREE_RAM
        app = prime_atlas_v2._build_gui()()
        app.update()
        h = Harness(app, errors, dialogs)
        passed = _wait_loaded(app)
        passed &= constellation_cases(h, app)
        passed &= primality_cases(h, app)
        passed &= primes_cases(h, app)
        passed &= pager_cases(h, app)
        passed &= pager_unit_checks(h, app)
        passed &= minimum_checks(app)
        passed &= primesieve_bound_checks(h, app)
        passed &= calc_bound_checks(h, app)
        passed &= big_factor_checks(h, app)
    finally:
        if app is not None:
            try:
                app.destroy()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(portal, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
