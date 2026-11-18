"""The Windows field of Generation Section D (generation/verify_section.py) and the width the
switch from Hybrid to primesieve writes (generation/hybrid_controls.py).

The Windows field picks how many of the floor's P windows a run proves (1..N, "of N" next
to it): all of them, or only the first ones, the rest another time. With no P window at the
chosen floor and width there is nothing to pick, so there is no number either. Checks, in the
real app (temp storage holding three P windows on floor 29 at offsets 1, 2 and 3 x 10^7, so
none of them lies on the 10^9 grid):
  1. no P window: the field is empty and greyed out, not red; next to it "no P windows of
     this width" instead of "of N";
  2. P windows: the field works, holds N, "of N" next to it, a smaller count can be typed;
  3. there and back (windows, none, windows again, by floor and by width): every state
     as in 1 and 2, never red;
  4. with P windows, "0", "abc", "1,5" turn the field red;
  5. the app started on a floor without P windows: empty at once, never a problem (red);
  6. Run without P windows: the "no P windows" error, the field stays empty;
  7. a run that proved every window: the recount after it empties the field.
Hybrid -> primesieve: a range narrower than 10^7 gives the width 1, never 0 (the field's
minimum is 1).
Windows, real display:
    python unitTests/test_verify_windows_field.py
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

from test_time_simulation import check  # noqa: E402

FLOOR = 29
EMPTY_FLOOR = 31
M7 = 10 ** 7


def _touch_p(portal, offset):
    import storage_kinds
    path = storage_kinds.window_path(portal, FLOOR, offset, M7,
                                     f"{offset // 1_000_000}M",
                                     storage_kinds.KIND_P)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()
    return path


def _wait(app, condition, ms=3000):
    for _ in range(ms // 50):
        app.update()
        if condition():
            return True
        app.after(50)
    return condition()


def _red(box):
    from primeatlas.core import number_field
    return str(box.cget("style")) == number_field.INVALID_SPINBOX_STYLE


def _problem(gen):
    from primeatlas.core import number_field
    return number_field.problem_field([gen._verify_vars["max_windows"]])


def _settle(app):
    from primeatlas.core import number_field
    app.after(number_field.SETTLE_MS + 200)
    app.update()


def _state(gen):
    box = gen._verify_windows_box
    return (gen._verify_vars["max_windows"].get(), str(box.cget("state")),
            gen._verify_total_text.get())


def _check_none(app, gen, what):
    _settle(app)
    value, state, beside = _state(gen)
    none_text = gen.T("gen.verify_windows_none")
    return check(value == "" and state == "disabled" and beside == none_text
                 and not _red(gen._verify_windows_box) and _problem(gen) is None,
                 f"{what}: empty, greyed out, not red, '{none_text}' beside "
                 f"({value!r}, {state}, {beside!r}, red={_red(gen._verify_windows_box)})")


def _check_some(app, gen, total, what):
    _settle(app)
    value, state, beside = _state(gen)
    want = gen.T("gen.verify_windows_total", total=f"{total:,}")
    return check(value == str(total) and state != "disabled" and beside == want
                 and not _red(gen._verify_windows_box) and _problem(gen) is None,
                 f"{what}: holds {total}, works, '{want}' beside "
                 f"({value!r}, {state}, {beside!r}, red={_red(gen._verify_windows_box)})")


def _move(app, gen, key, value):
    """Sets the floor or the width and waits for the recount it schedules."""
    gen._verify_vars[key].set(str(value))
    _wait(app, lambda: gen._verify_count_after_id is None)
    app.update()


def startup_checks(app, gen):
    passed = check(_problem(gen) is None and gen._verify_vars["max_windows"].get() == "",
                   "5: started on a floor without P windows, the field is empty and no "
                   f"problem at once ({gen._verify_vars['max_windows'].get()!r})")
    return passed & _check_none(app, gen, "5: after startup")


def field_checks(app, gen):
    passed = True
    _move(app, gen, "base_exponent", FLOOR)
    passed &= _check_some(app, gen, 3, "2: floor with three P windows")
    box = gen._verify_windows_box
    box.delete(0, "end")
    box.insert(0, "2")
    _settle(app)
    passed &= check(gen._verify_vars["max_windows"].get() == "2" and not _red(box),
                    "2: a smaller count can be typed")
    for bad in ("0", "abc", "1,5"):
        box.delete(0, "end")
        box.insert(0, bad)
        box.event_generate("<FocusOut>")
        _settle(app)
        passed &= check(_red(box) and _problem(gen) is not None,
                        f"4: with P windows {bad!r} turns the field red")
    _move(app, gen, "base_exponent", EMPTY_FLOOR)
    passed &= _check_none(app, gen, "3: back to a floor without P windows")
    _move(app, gen, "base_exponent", FLOOR)
    passed &= _check_some(app, gen, 3, "3: windows again")
    _move(app, gen, "width_exp", 9)
    passed &= _check_none(app, gen, "3: a width with no P window on its grid")
    _move(app, gen, "width_exp", 7)
    passed &= _check_some(app, gen, 3, "3: the width back")
    return passed


def run_checks(app, gen, portal, paths, errors):
    passed = True
    _move(app, gen, "base_exponent", EMPTY_FLOOR)
    errors.clear()
    gen._on_run_verify()
    app.update()
    passed &= check(errors == [gen.T("gen.verify_error_no_windows")],
                    f"6: Run without P windows shows the no-windows error ({errors})")
    passed &= _check_none(app, gen, "6: after the refused Run")

    _move(app, gen, "base_exponent", FLOOR)
    passed &= _check_some(app, gen, 3, "7: before the run")
    for path in paths:
        os.remove(path)
    gen._on_verify_finished()
    app.update()
    passed &= _check_none(app, gen, "7: every window proved")
    return passed


def hybrid_checks(gen):
    from tkinter import messagebox
    messagebox.askyesno = lambda *a, **k: True
    launches = []
    gen._on_quick_generate_clicked = lambda: launches.append(gen.quick_primesieve_width_var.get())
    start = 10 ** 30
    gen._offer_hybrid_primesieve(start, start + 5_000_000)
    width = gen.quick_primesieve_width_var.get()
    passed = check(width == "1", f"Hybrid -> primesieve below 10^7: width 1 ({width!r})")
    gen._offer_hybrid_primesieve(start, start + 3 * M7)
    width = gen.quick_primesieve_width_var.get()
    passed &= check(width == "3", f"Hybrid -> primesieve: 3 * 10^7 gives 3 ({width!r})")
    passed &= check(launches == ["1", "3"], f"each switch launches with its width ({launches})")
    return passed


def main():
    from tkinter import messagebox
    errors = []
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showwarning = lambda *a, **k: None
    messagebox.showerror = lambda title, text, **k: errors.append(text)
    messagebox.askyesno = lambda *a, **k: True
    messagebox.askokcancel = lambda *a, **k: True
    portal = tempfile.mkdtemp(prefix="primeatlas_verify_windows_test_")
    paths = [_touch_p(portal, offset) for offset in (M7, 2 * M7, 3 * M7)]
    app = None
    passed = False
    try:
        from app_sandbox import isolate_app
        prime_atlas_v2, _portal = isolate_app(portal)
        from primeatlas.core import ui_state_dynamic
        store = ui_state_dynamic.STORE
        store.set("generation.verify.base_exponent", str(EMPTY_FLOOR))
        store.set("generation.verify.width_exp", "7")
        app = prime_atlas_v2._build_gui()()
        gen = app.generation_tab_widget
        passed = startup_checks(app, gen)
        passed &= field_checks(app, gen)
        passed &= run_checks(app, gen, portal, paths, errors)
        errors.clear()
        passed &= hybrid_checks(gen)
        passed &= check(not errors, f"no other error dialogs ({errors[:1]})")
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
