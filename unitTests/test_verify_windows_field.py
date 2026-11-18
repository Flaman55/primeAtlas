"""The Width and Windows fields of Generation Section D (generation/verify_section.py,
verify_width.py) and the width the switch from Hybrid to primesieve writes
(generation/hybrid_controls.py).

Section D verifies the floor's first island of P files (from the smallest n): the Width field
sets how many numbers one verification window takes (whole files, from one file up to the
island, for the v7.3 sieve up to its RAM cap too), the Split field how many windows the island
splits into (the island's size next to it): a change of one recounts the other. "Verify now"
sets how many of those windows a run proves (1..N, "of N" next to it). Checks, in the real app (temp
storage holding three P files on floor 29 at offsets 1, 2 and 3 x 10^7 and one on floor 30;
the free-RAM reading faked):
  1. no P file: Verify now empty and greyed out, not red, "no P windows" beside it; Width,
     Split and Auto greyed out;
  2. a floor with an island and an empty stored width: Auto's width, every window, the
     island's size beside;
  3. a typed width: any notation, shown short after (1e7, 2.5e8); below one file -> one file, above the island -> the island,
     between -> whole files; Split and Verify now follow (N = ceil(island / width)); never red;
 3b. a typed split gives the width (ceil(files / split) files each), outside its range the
     nearest end; its arrows step the split and stop at both ends; Verify now follows;
  4. text that is no number turns Width and Split red; Verify now "0", "abc" red too;
  5. the arrows step by one file and stop at both ends;
  6. Auto: pt1.1 one file; v7.3 reads the free RAM and splits the island evenly under the
     cap; twice the same; the width is remembered;
  7. a method switch only clips the width to the new range; a floor switch the same;
  8. the app started on a floor without P files: empty at once, never a problem (red);
  9. Run without P files: the "no P windows" error;
 10. a run that proved the whole island: the recount shows none; part of it: the rest.
Hybrid -> primesieve: a range narrower than 10^7 gives the width 1, never 0.
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
SMALL_FLOOR = 30
EMPTY_FLOOR = 31
M7 = 10 ** 7
# Free RAM whose v7.3 cap (half of it x 30, whole files) is two files.
TWO_FILES_RAM = 1_333_334


def _touch_p(portal, floor, offset):
    import storage_kinds
    path = storage_kinds.window_path(portal, floor, offset, M7,
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
    return number_field.problem_field([gen._verify_vars["max_windows"],
                                       gen._verify_vars["width"], gen._verify_split_var])


def _settle(app):
    from primeatlas.core import number_field
    app.after(number_field.SETTLE_MS + 200)
    app.update()


def _idle(app, gen):
    _wait(app, lambda: gen._verify_count_after_id is None)
    app.update()


def _state(gen):
    box = gen._verify_windows_box
    return (gen._verify_vars["max_windows"].get(), str(box.cget("state")),
            gen._verify_total_text.get())


def _check_none(app, gen, what):
    _settle(app)
    value, state, beside = _state(gen)
    none_text = gen.T("gen.verify_windows_none")
    greyed = (str(gen._verify_width_box.cget("state")) == "disabled"
              and str(gen._verify_split_box.cget("state")) == "disabled"
              and str(gen._verify_auto_btn.cget("state")) == "disabled")
    return check(value == "" and state == "disabled" and beside == none_text and greyed
                 and gen._verify_split_var.get() == "" and gen._verify_island_text.get() == ""
                 and not _red(gen._verify_windows_box) and _problem(gen) is None,
                 f"{what}: Windows empty, greyed, not red, '{none_text}' beside; Width and Auto "
                 f"greyed ({value!r}, {state}, {beside!r}, greyed={greyed})")


def _short(width):
    from primeatlas.generation import verify_width
    return verify_width.width_text(width)


def _check_some(app, gen, width, windows, files, what, high=None):
    """width numbers per window, `windows` of them, an island of `files` files of 10^7; the
    widest window `high` (default: the island). Widths are shown short (1e7, 2.5e8)."""
    _settle(app)
    value, state, beside = _state(gen)
    want = gen.T("gen.verify_windows_total", total=f"{windows:,}")
    want_island = gen.T("gen.verify_island", numbers=_short(files * M7), files=f"{files:,}",
                        low=_short(M7), high=_short(high or files * M7))
    want_width = gen.T("gen.verify_width_files", files=f"{width // M7:,}",
                       file_width=_short(M7))
    shown_width = gen._verify_vars["width"].get()
    split = gen._verify_split_var.get()
    works = (state != "disabled" and str(gen._verify_width_box.cget("state")) != "disabled"
             and str(gen._verify_split_box.cget("state")) != "disabled"
             and str(gen._verify_auto_btn.cget("state")) != "disabled")
    return check(value == str(windows) and shown_width == _short(width)
                 and split == str(windows)
                 and works and beside == want and gen._verify_width_text.get() == want_width
                 and gen._verify_island_text.get() == want_island
                 and not _red(gen._verify_windows_box) and not _red(gen._verify_width_box)
                 and not _red(gen._verify_split_box) and _problem(gen) is None,
                 f"{what}: width {width}, split {windows}, {windows} of {windows} windows, "
                 f"'{want}', '{want_width}', '{want_island}' beside ({shown_width!r}, "
                 f"{split!r}, {value!r}, {state}, {beside!r}, {gen._verify_width_text.get()!r}, "
                 f"{gen._verify_island_text.get()!r})")


def _move(app, gen, key, value):
    """Sets the floor and waits for the recount it schedules."""
    gen._verify_vars[key].set(str(value))
    _idle(app, gen)


def _type(app, gen, box, text):
    box.delete(0, "end")
    box.insert(0, text)
    box.event_generate("<FocusOut>")
    _idle(app, gen)


def _type_width(app, gen, text):
    _type(app, gen, gen._verify_width_box, text)


def _type_split(app, gen, text):
    _type(app, gen, gen._verify_split_box, text)


def _arrow(app, gen, event, box=None):
    (box or gen._verify_width_box).event_generate(event)
    _idle(app, gen)


def _pick_method(app, gen, method):
    gen._verify_method_text.set(gen._verify_method_names[method])
    gen._on_verify_method_chosen()
    _idle(app, gen)


def startup_checks(app, gen):
    passed = check(_problem(gen) is None and gen._verify_vars["max_windows"].get() == "",
                   "8: started on a floor without P files, Windows empty and no problem at "
                   f"once ({gen._verify_vars['max_windows'].get()!r})")
    return passed & _check_none(app, gen, "1/8: after startup")


def width_checks(app, gen):
    passed = True
    _move(app, gen, "base_exponent", FLOOR)
    passed &= _check_some(app, gen, M7, 3, 3, "2: an empty stored width takes Auto's (pt1.1)")
    for text, width, windows, what in (
            ("2e7", 2 * M7, 2, "3: 2e7, the last window holds the rest"),
            ("100 000 000", 3 * M7, 1, "3: above the island -> the island"),
            ("1000", M7, 3, "3: below one file -> one file"),
            ("25000000", 2 * M7, 2, "3: between -> whole files (2)"),
            ("10^7", M7, 3, "3: 10^7")):
        _type_width(app, gen, text)
        passed &= _check_some(app, gen, width, windows, 3, what)
    for bad in ("abc", "0", "1,5"):
        _type_width(app, gen, bad)
        _settle(app)
        passed &= check(_red(gen._verify_width_box) and _problem(gen) is not None,
                        f"4: Width {bad!r} turns red")
    _type_width(app, gen, "1e7")
    passed &= _check_some(app, gen, M7, 3, 3, "4: a width again clears the red")
    for bad in ("abc", "0"):
        _type_split(app, gen, bad)
        _settle(app)
        passed &= check(_red(gen._verify_split_box) and _problem(gen) is not None,
                        f"4: Split {bad!r} turns red")
    _type_split(app, gen, "3")
    passed &= _check_some(app, gen, M7, 3, 3, "4: a split again clears the red")
    box = gen._verify_windows_box
    for bad in ("0", "abc"):
        box.delete(0, "end")
        box.insert(0, bad)
        box.event_generate("<FocusOut>")
        _settle(app)
        passed &= check(_red(box) and _problem(gen) is not None, f"4: Windows {bad!r} turns red")
    box.delete(0, "end")
    box.insert(0, "2")
    _settle(app)
    passed &= check(gen._verify_vars["max_windows"].get() == "2" and not _red(box),
                    "a smaller window count can be typed")

    for event, width in (("<<Increment>>", 2 * M7), ("<<Increment>>", 3 * M7),
                         ("<<Increment>>", 3 * M7), ("<<Decrement>>", 2 * M7),
                         ("<<Decrement>>", M7), ("<<Decrement>>", M7)):
        _arrow(app, gen, event)
        shown = gen._verify_vars["width"].get()
        passed &= check(shown == _short(width), f"5: {event} -> {width} ({shown!r})")
    for box, delta, width in ((gen._verify_width_box, 120, 2 * M7),
                              (gen._verify_width_box, -120, M7),
                              (gen._verify_width_box, -120, M7),
                              (gen._verify_split_box, -120, 2 * M7),
                              (gen._verify_split_box, 120, M7),
                              (gen._verify_split_box, 120, M7)):
        box.event_generate("<MouseWheel>", delta=delta)
        _idle(app, gen)
        shown = gen._verify_vars["width"].get()
        which = "Width" if box is gen._verify_width_box else "Split"
        passed &= check(shown == _short(width),
                        f"5: the wheel ({delta:+}) over {which} steps like its arrows -> {width} "
                        f"({shown!r})")
    box = gen._verify_width_box
    box.delete(0, "end")
    box.insert(0, "30000000")
    _idle(app, gen)
    passed &= check(gen._verify_split_var.get() == "1" and box.get() == "30000000",
                    f"3: typing a width (still in the field) recounts the split "
                    f"({gen._verify_split_var.get()!r})")
    box.delete(0, "end")
    box.insert(0, "10000000")
    _idle(app, gen)
    passed &= check(gen._verify_split_var.get() == "3",
                    f"3: deleting a zero gives more windows ({gen._verify_split_var.get()!r})")
    box.event_generate("<FocusOut>")
    _idle(app, gen)
    return passed


def split_checks(app, gen):
    passed = True
    for text, width, windows, what in (
            ("2", 2 * M7, 2, "3b: split 2 of 3 files: 2 files each (2 + 1)"),
            ("1", 3 * M7, 1, "3b: split 1: the whole island"),
            ("5", M7, 3, "3b: split above the files: one file each"),
            ("1e0", 3 * M7, 1, "3b: any notation")):
        _type_split(app, gen, text)
        passed &= _check_some(app, gen, width, windows, 3, what)
    for event, width, windows in (("<<Increment>>", 2 * M7, 2), ("<<Increment>>", M7, 3),
                                  ("<<Increment>>", M7, 3), ("<<Decrement>>", 2 * M7, 2),
                                  ("<<Decrement>>", 3 * M7, 1), ("<<Decrement>>", 3 * M7, 1)):
        _arrow(app, gen, event, gen._verify_split_box)
        passed &= _check_some(app, gen, width, windows, 3, f"3b: split {event}")
    _type_width(app, gen, "1e7")
    box = gen._verify_windows_box
    box.delete(0, "end")
    box.insert(0, "1")
    _settle(app)
    passed &= check(gen._verify_vars["max_windows"].get() == "1" and not _red(box)
                    and gen._verify_split_var.get() == "3",
                    "3b: Verify now 1 of 3 leaves the split as it is")
    _type_split(app, gen, "2")
    passed &= _check_some(app, gen, 2 * M7, 2, 3, "3b: a new split resets Verify now to all")
    _type_width(app, gen, "1e7")
    return passed


def auto_checks(app, gen, ram, store):
    passed = True
    _type_width(app, gen, "3e7")
    gen._verify_auto_btn.invoke()
    _idle(app, gen)
    passed &= _check_some(app, gen, M7, 3, 3, "6: Auto with pt1.1: one file")
    gen._verify_auto_btn.invoke()
    _idle(app, gen)
    passed &= _check_some(app, gen, M7, 3, 3, "6: Auto twice: the same")
    passed &= check(not ram, f"6: pt1.1's Auto reads no RAM ({len(ram)})")

    _pick_method(app, gen, "sieve")
    passed &= _check_some(app, gen, M7, 3, 3, "7: switch to v7.3: one file stays")
    gen._verify_auto_btn.invoke()
    _idle(app, gen)
    passed &= check(len(ram) == 1, f"6: v7.3's Auto reads the free RAM ({len(ram)})")
    passed &= _check_some(app, gen, 2 * M7, 2, 3,
                          "6: v7.3 Auto, a cap of 2 files: 2 windows (2 + 1)", high=2 * M7)
    passed &= check(store.get("generation.verify.width") == "2e7",
                    f"6: the width is remembered ({store.get('generation.verify.width')!r})")
    _type_width(app, gen, "3e7")
    passed &= _check_some(app, gen, 2 * M7, 2, 3, "3: v7.3 above the cap -> the cap",
                          high=2 * M7)
    _type_split(app, gen, "1")
    passed &= _check_some(app, gen, 2 * M7, 2, 3,
                          "3b: v7.3 split 1 -> the fewest the cap allows (2)", high=2 * M7)

    _pick_method(app, gen, "proof")
    passed &= _check_some(app, gen, 2 * M7, 2, 3, "7: back to pt1.1: the width stays")
    _type_width(app, gen, "3e7")
    passed &= _check_some(app, gen, 3 * M7, 1, 3, "7: pt1.1 takes the whole island")
    _pick_method(app, gen, "sieve")
    passed &= _check_some(app, gen, 2 * M7, 2, 3, "7: switch to v7.3 clips to the cap",
                          high=2 * M7)
    _pick_method(app, gen, "proof")
    _type_width(app, gen, "3e7")
    _move(app, gen, "base_exponent", SMALL_FLOOR)
    passed &= _check_some(app, gen, M7, 1, 1, "7: a floor with a one-file island clips the width")
    _move(app, gen, "base_exponent", FLOOR)
    passed &= _check_some(app, gen, M7, 3, 3, "7: back: the clipped width stays")
    _move(app, gen, "base_exponent", EMPTY_FLOOR)
    passed &= _check_none(app, gen, "1: a floor without P files")
    _move(app, gen, "base_exponent", FLOOR)
    passed &= _check_some(app, gen, M7, 3, 3, "1: P files again")
    return passed


def run_checks(app, gen, paths, errors):
    passed = True
    _move(app, gen, "base_exponent", EMPTY_FLOOR)
    errors.clear()
    gen._on_run_verify()
    app.update()
    passed &= check(errors == [gen.T("gen.verify_error_no_windows")],
                    f"9: Run without P files shows the no-windows error ({errors})")
    passed &= _check_none(app, gen, "9: after the refused Run")

    _move(app, gen, "base_exponent", FLOOR)
    passed &= _check_some(app, gen, M7, 3, 3, "10: before the run")
    for path in paths[:2]:
        os.remove(path)
    gen._on_verify_finished()
    _idle(app, gen)
    passed &= _check_some(app, gen, M7, 1, 1, "10: two files proved, one left")
    os.remove(paths[2])
    gen._on_verify_finished()
    _idle(app, gen)
    passed &= _check_none(app, gen, "10: the whole island proved")
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
    paths = [_touch_p(portal, FLOOR, offset) for offset in (M7, 2 * M7, 3 * M7)]
    _touch_p(portal, SMALL_FLOOR, 0)
    app = None
    passed = False
    try:
        from app_sandbox import isolate_app
        prime_atlas_v2, _portal = isolate_app(portal)
        from primeatlas.core import ui_state_dynamic
        from primeatlas.generation import wsl_resources
        ram = []
        wsl_resources.estimate_free_ram_bytes = lambda timeout=10: ram.append(1) or TWO_FILES_RAM
        store = ui_state_dynamic.STORE
        store.set("generation.verify.base_exponent", str(EMPTY_FLOOR))
        store.set("generation.verify.width", "")
        store.set("generation.verify.method", "proof")
        app = prime_atlas_v2._build_gui()()
        gen = app.generation_tab_widget
        passed = startup_checks(app, gen)
        passed &= width_checks(app, gen)
        passed &= split_checks(app, gen)
        passed &= auto_checks(app, gen, ram, store)
        passed &= run_checks(app, gen, paths, errors)
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
