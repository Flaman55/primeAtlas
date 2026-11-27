"""Every action of the Visualization tabs that reads number fields refuses a red one first
(core/number_field.refuse_problem), with the fields it reads and no others.

Drives the real app (temp storage, launches stubbed) with test_field_refusal_app's Harness:
  - Start of Rings, Sphere and Tree/Assembly asks about exactly the number fields it reads,
    before the resume of a paused renderer, the portal check and the empty-storage offer:
    Rings N and its optional fields always, theta unless the law mode is bertrand/legendre,
    From/To and max load only in range mode, k and p0 only in line mode with a Manual
    pattern; Sphere N and its fields, the fiber ones only in the fibers mode; Tree N, the
    common fields and the active mode's own;
  - the empty-storage generate dialog's Generate and Enter refuse a red From/To and stay
    open with what was typed; From > To is still reported inside the dialog;
  - each field's minimum is the lower bound its action checks: Rings N 2, From/To and max
    load 0, k 2, p0 3; Sphere N 1; Tree N 0; the generate dialog's From 0 and To 2.
Windows, real display:
    python unitTests/test_field_refusal_viz_app.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_field_refusal_app import Harness, Launched, _enter, _fields_of, _set_text  # noqa: E402
from test_time_simulation import FAKE_FREE_RAM, check  # noqa: E402


def _start(tab):
    """Start of `tab` as an action for Harness.case: resuming a paused renderer and the
    empty-storage offer count as getting past the refusal (an exception raised inside a
    button's callback does not leave invoke(), so they are recorded and raised after it)."""
    reached = []
    tab._resume_if_paused = lambda *_a, **_k: reached.append("resume")
    tab._offer_storage_fill = lambda *_a, **_k: reached.append("offer")

    def start():
        reached.clear()
        tab.open_button.invoke()
        if reached:
            raise Launched()
    return start


def rings_cases(h, app):
    tab = app.rings_tab_widget
    start = _start(tab)
    source = tab.pattern_source
    always = [tab.n_entry, tab.tempo_ms_entry, tab.point_size_entry, tab.hit_point_size_entry,
              tab.hud_font_size_entry]
    theta = tab.general_law_theta_entry
    ranged = [tab.load_range_from_entry, tab.load_range_to_entry, tab.max_load_count_entry]
    pattern = [source.k_entry, source.p0_entry]
    saved = (tab.mode_var.get(), tab.line_mode_var.get(), source.source_var.get(),
             tab.general_law_mode_combo.get())

    def setup(mode, line, src, law):
        tab.mode_var.set(mode)
        tab._on_mode_changed()
        tab.line_mode_var.set(line)
        source.source_var.set(src)
        tab.general_law_mode_combo.set(law)
        tab._on_general_law_mode_changed()
        _set_text(source.k_entry, "3")
        _set_text(source.p0_entry, "5")
        h.app.update()

    passed = True
    cases = [("sequential", False, "manual", "sliding", always + [theta], ranged + pattern),
             ("range", False, "manual", "sliding", always + [theta] + ranged, pattern),
             ("range", True, "manual", "stepped", always + [theta] + ranged + pattern, []),
             ("range", True, "list", "sliding", always + [theta] + ranged, pattern),
             ("sequential", True, "manual", "sliding", always + [theta] + pattern, ranged),
             ("sequential", False, "manual", "legendre", always, [theta]),
             ("range", False, "manual", "bertrand", always + ranged, [theta])]
    for mode, line, src, law, fields, foreign in cases:
        setup(mode, line, src, law)
        name = f"Rings Start ({mode}, line {line}, {src}, {law})"
        if mode == "range":
            fields = [tab.load_range_from_entry] + [f for f in fields
                                                    if f is not tab.load_range_from_entry]
        passed &= h.case(name, start, fields, foreign=foreign)
    mode, line, src, law = saved
    setup(mode, line, src, law or "sliding")
    return passed


def sphere_cases(h, app):
    from primeatlas.visualization.sphere import sphere_tab as st
    tab = app.sphere_tab_widget
    start = _start(tab)
    common = [tab.n_entry] + [getattr(tab, attr) for attr, *_ in st._ALL_FIELDS]
    fibers = [getattr(tab, attr) for attr, *_ in st._ALL_FIBER_FIELDS]
    saved = tab.mode_combo.current()
    passed = True
    tab.mode_combo.current(st.MODES.index(st.MODE_RINGS))
    passed &= h.case("Sphere Start (rings)", start, common, foreign=fibers)
    tab.mode_combo.current(st.MODES.index(st.MODE_FIBERS))
    passed &= h.case("Sphere Start (fibers)", start, common + fibers,
                     foreign=[app.rings_tab_widget.n_entry])
    tab.mode_combo.current(saved)
    return passed


def tree_cases(h, app):
    from primeatlas.visualization.tree import tree_tab as tt
    tab = app.tree_tab_widget
    start = _start(tab)

    def entries(fields):
        return [getattr(tab, attr) for attr, *_rest, kind in fields if kind != "text"]
    common = [tab.n_entry] + entries(tt._COMMON_FIELDS)
    tree = entries(tt._TREE_FIELDS + tt._TREE_APPEARANCE_FIELDS)
    assembly = entries(tt._ASSEMBLY_FIELDS)
    saved = tab.current_mode()
    passed = True
    tab.set_mode(tt.MODE_TREE)
    passed &= h.case("Tree Start", start, common + tree, foreign=assembly)
    tab.set_mode(tt.MODE_ASSEMBLY)
    passed &= h.case("Assembly Start", start, common + assembly, foreign=tree)
    tab.set_mode(saved)
    return passed


def _dialog_parts(dialog):
    """The generate dialog's From and To entries and its Generate button."""
    found = {"TEntry": [], "TButton": []}

    def walk(widget):
        for child in widget.winfo_children():
            if child.winfo_class() in found:
                found[child.winfo_class()].append(child)
            walk(child)
    walk(dialog)
    from_entry, to_entry = found["TEntry"]
    return from_entry, to_entry, found["TButton"][0]


def _run_dialog(tab, default_from, default_to, script):
    """Opens the generate dialog with `script(dialog, from, to, generate)` run in place of
    waiting for the person; returns (dialog result, what the script returned)."""
    out = {}

    def scripted(dialog):
        out["value"] = script(dialog, *_dialog_parts(dialog))
        if dialog.winfo_exists():
            dialog.destroy()
    tab.wait_window = scripted
    try:
        result = tab._ask_generate_range(default_from, default_to)
    finally:
        del tab.wait_window
    return result, out.get("value")


def generate_dialog_cases(h, app):
    T = app.generation_tab_widget.T
    refusal = T("number_field.fix_field", reason="").split("\n")[0]
    passed = True
    for tab in (app.rings_tab_widget, app.sphere_tab_widget, app.tree_tab_widget):
        name = type(tab).__name__
        for label, red, how in (("To", 1, "Generate"), ("From", 0, "Generate"),
                                ("To", 1, "Enter"), ("From", 0, "Enter")):
            def script(dialog, from_entry, to_entry, generate):
                _set_text((from_entry, to_entry)[red], "abc")
                dialog.update()
                h.errors.clear()
                h.dialogs.clear()
                if how == "Generate":
                    generate.invoke()
                else:
                    _enter((from_entry, to_entry)[red])()
                dialog.update()
                return (list(h.errors), list(h.dialogs), dialog.winfo_exists(),
                        from_entry.get(), to_entry.get())
            result, (errors, dialogs, open_, got_from, got_to) = _run_dialog(
                tab, "10", "1000", script)
            kept = (got_from, got_to) == (("abc", "1000") if red == 0 else ("10", "abc"))
            passed &= check(len(errors) == 1 and refusal in errors[0] and not dialogs and open_
                            and kept and result is None,
                            f"{name} generate dialog: {how} with a red {label} is refused, the "
                            f"dialog stays open with what was typed ({errors[:1]} {dialogs[:1]} "
                            f"open {open_} kept {kept} result {result})")

        def asked_script(dialog, from_entry, to_entry, generate):
            calls, shown, _launched = h.asked(generate.invoke)
            return calls, shown, dialog.winfo_exists()
        _result, (calls, shown, open_) = _run_dialog(tab, "10", "1000", asked_script)
        got = _fields_of(calls[0]) if calls else set()
        passed &= check(len(calls) == 1 and len(got) == 2 and not shown and open_,
                        f"{name} generate dialog: Generate asks about From and To first "
                        f"(calls {len(calls)}, fields {len(got)}, shown {shown[:1]})")

        def order_script(dialog, from_entry, to_entry, generate):
            h.errors.clear()
            generate.invoke()
            dialog.update()
            return list(h.errors), dialog.winfo_exists()
        result, (errors, open_) = _run_dialog(tab, "500", "100", order_script)
        passed &= check(not errors and open_ and result is None,
                        f"{name} generate dialog: From > To is reported inside the dialog")

        def valid_script(dialog, from_entry, to_entry, generate):
            generate.invoke()
            return None
        result, _ = _run_dialog(tab, "", "1000", valid_script)
        passed &= check(result == (2, 1000), f"{name} generate dialog: valid values generate "
                                             f"as before ({result})")
    h.errors.clear()
    app.update()
    return passed


def _problem(entry, text):
    _set_text(entry, text)
    entry.number_field.refresh(at_once=True)
    return entry.number_field.problem


def minimum_checks(app):
    rings, sphere, tree = app.rings_tab_widget, app.sphere_tab_widget, app.tree_tab_widget
    lows = [("rings N", rings.n_entry, 2), ("rings From", rings.load_range_from_entry, 0),
            ("rings To", rings.load_range_to_entry, 0),
            ("rings max load", rings.max_load_count_entry, 0),
            ("rings pattern k", rings.pattern_source.k_entry, 2),
            ("rings pattern p0", rings.pattern_source.p0_entry, 3),
            ("sphere N", sphere.n_entry, 1), ("tree N", tree.n_entry, 0)]
    passed = True
    for label, entry, low in lows:
        old = entry.get()
        below = _problem(entry, str(low - 1)) == "range"
        at = _problem(entry, str(low)) is None
        _problem(entry, old)
        passed &= check(below and at, f"{label}: minimum {low}")

    def dialog_script(dialog, from_entry, to_entry, generate):
        return [(f"generate dialog {label}", _problem(entry, str(low - 1)) == "range"
                 and _problem(entry, str(low)) is None)
                for label, entry, low in (("From", from_entry, 0), ("To", to_entry, 2))]
    _result, checks = _run_dialog(rings, "", "1000", dialog_script)
    for label, ok in checks:
        passed &= check(ok, f"{label}: minimum {'0' if 'From' in label else '2'}")
    app.update()
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
    portal = tempfile.mkdtemp(prefix="primeatlas_field_refusal_viz_")
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
        passed = rings_cases(h, app)
        passed &= sphere_cases(h, app)
        passed &= tree_cases(h, app)
        passed &= generate_dialog_cases(h, app)
        passed &= minimum_checks(app)
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
