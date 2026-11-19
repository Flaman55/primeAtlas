"""The target planner section of the Generation tab (target_planner_view.py through
target_planner_section.py).

Drives the real app (tkinter, temp storage folder seeded with v7 and Pseudosquares print
rows at floor 25, a fake 64 GB of free WSL RAM). Checks:
  - the section starts collapsed; Show reveals it and Hide collapses it; the how-to starts
    hidden and its button shows and hides it;
  - no targets: a message, no rows, Use disabled; a bad line: its line number and reason,
    no rows, Use disabled;
  - a dense range: one Atlas row with the selected engine and a summary; Use (enabled only
    with a row selected) switches Quick-gen to Floor mode with Floor, Start and Width of
    the group and storage writing on;
  - two isolated targets: two Pseudosquares rows and the note that Pseudosquares writes
    nothing; Use switches to Pseudosquares mode, print, with Floor, From and Width;
  - a stored window (the store listing faked) leaves its target out of the plan;
  - a small RAM budget keeps every Atlas row at or under run_ram.max_windows_in_budget();
    with no room for even one window, Pseudosquares takes the range uncut;
  - Load file reads a CRLF file into the targets field;
  - Insert example: an empty field gets the example with the cursor at its start and no
    question; the field already holding the example: no question, nothing changes; other
    text: a Yes/No question (No by default), No keeps it, Yes replaces it; the table and
    the message stay as they were (nothing is planned); a double click inserts once;
  - the example, planned, gives rows and no bad line;
  - Load file opens in the storage folder, where the example copy is written first when
    missing; that copy loaded gives the same text as Insert example;
  - Use on a group with a forced Atlas engine selects that engine in the Generation form
    and fills Quick-gen; Use on a free group or a forced Pseudosquares group leaves the
    form's engine as it was.
  - a new plan replaces the rows of the last one.
Windows, real display:
    python unitTests/test_target_planner_gui.py
"""
import csv
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_time_simulation import FAKE_FREE_RAM, check  # noqa: E402

W = 10_000_000
F25 = 10 ** 25


def _seed_log(portal):
    from benchmark_log_schema import BENCHMARK_FIELDNAMES, ENGINE_PSEUDOSQUARES_PRINT
    rows = []
    for engine, windows, seconds in (("v7", 1000, 263.0), ("v7", 2500, 343.0),
                                     (ENGINE_PSEUDOSQUARES_PRINT, 1, 6.0),
                                     (ENGINE_PSEUDOSQUARES_PRINT, 100, 230.0)):
        rows.append({"engine": engine, "base_exponent": "25", "windows_written": str(windows),
                     "numbers_processed": str(windows * W), "target_idx_start": "0",
                     "sieve_seconds": str(seconds), "total_seconds": str(seconds),
                     "write_files": "0", "run_status": "completed", "engine_version": "x"})
    with open(os.path.join(portal, "benchmark_log.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in BENCHMARK_FIELDNAMES})


def _mapped(widget):
    return widget.winfo_manager() != ""


def _plan(view, app, text):
    view.set_text(text)
    view.plan_button.invoke()
    app.update()
    return view.tree.get_children()


def _select_first(view, app):
    first = view.tree.get_children()[0]
    view.tree.selection_set(first)
    app.update()


def layout_checks(gen, app):
    passed = True
    view = gen._target_planner_view
    passed &= check(not _mapped(view.body), "the section starts collapsed")
    view.toggle_button.invoke()
    app.update()
    passed &= check(_mapped(view.body) and view.toggle_button.cget("text")
                    == gen.T("target_planner.hide"), "Show reveals the planner")
    passed &= check(not _mapped(view.howto_area), "the how-to starts hidden")
    view.howto_button.invoke()
    app.update()
    passed &= check(_mapped(view.howto_area)
                    and view.howto_label.cget("text") == gen.T("target_planner.howto"),
                    "its button shows the how-to")
    view.howto_button.invoke()
    app.update()
    passed &= check(not _mapped(view.howto_area), "and hides it again")
    view.toggle_button.invoke()
    app.update()
    passed &= check(not _mapped(view.body), "Hide collapses the planner")
    view.toggle_button.invoke()
    app.update()
    return passed


def message_checks(gen, app):
    passed = True
    view = gen._target_planner_view
    rows = _plan(view, app, "  \n# nothing\n")
    passed &= check(not rows and view.message_var.get() == gen.T("target_planner.no_targets")
                    and str(view.use_button.cget("state")) == "disabled",
                    "no targets: the message, no rows, Use disabled")
    rows = _plan(view, app, "10**25\nabc\n")
    message = view.message_var.get()
    passed &= check(not rows and "2" in message
                    and gen.T("target_planner.error_not_number") in message
                    and str(view.use_button.cget("state")) == "disabled",
                    f"a bad line: its number and reason, no rows ({message!r})")
    return passed


def atlas_checks(gen, app):
    passed = True
    view = gen._target_planner_view
    rows = _plan(view, app, f"{F25 + 100 * W} {100 * W}")
    values = [view.tree.item(r, "values") for r in rows]
    passed &= check(len(rows) == 1 and values[0][6] == gen.T("target_planner.method_atlas",
                                                             engine="v7"),
                    f"a dense range: one Atlas row with v7 ({values})")
    from primeatlas.generation.time_simulation_window import format_long_duration
    want = gen.T("target_planner.summary", groups=1,
                 time=format_long_duration(view.groups[0].seconds, gen.T))
    passed &= check(view.summary_var.get().startswith(want),
                    f"the summary starts with the plan's total ({view.summary_var.get()!r})")
    passed &= check(str(view.use_button.cget("state")) == "disabled",
                    "Use stays disabled until a row is selected")
    _select_first(view, app)
    passed &= check(str(view.use_button.cget("state")) == "normal", "a selected row enables Use")
    gen._loop_write_files_var.set(False)
    view.use_button.invoke()
    app.update()
    group = view.groups[0]
    passed &= check(gen.quick_mode_var.get() == "floor" and gen.quick_floor_var.get() == "25"
                    and gen.quick_floor_start_var.get() == str(group.lo)
                    and gen.quick_floor_width_var.get() == str(group.windows)
                    and gen._loop_write_files_var.get(),
                    f"Use: Floor mode, Floor 25, Start {group.lo}, Width {group.windows}, "
                    f"writing on ({gen.quick_mode_var.get()}, {gen.quick_floor_start_var.get()}, "
                    f"{gen.quick_floor_width_var.get()})")
    return passed


def pss_checks(gen, app):
    passed = True
    view = gen._target_planner_view
    rows = _plan(view, app, f"{F25 + 5}\n{F25 + 10 ** 24}")
    values = [view.tree.item(r, "values") for r in rows]
    passed &= check(len(rows) == 2 and all(v[6] == gen.T("target_planner.method_pss")
                                           for v in values),
                    f"two isolated targets: two Pseudosquares rows ({values})")
    passed &= check(gen.T("target_planner.pss_writes_nothing") in view.summary_var.get(),
                    "the note that Pseudosquares writes nothing")
    view.tree.selection_set(rows[1])
    app.update()
    view.use_button.invoke()
    app.update()
    group = view.groups[1]
    passed &= check(gen.quick_mode_var.get() == "pseudosquares"
                    and gen.quick_pseudosquares_mode_var.get() == "print"
                    and gen.quick_pseudosquares_floor_var.get() == "25"
                    and gen.quick_pseudosquares_from_var.get() == str(group.lo)
                    and gen.quick_pseudosquares_width_var.get() == str(group.windows),
                    f"Use: Pseudosquares mode, print, From {group.lo}, Width {group.windows}")
    rows = _plan(view, app, f"{F25 + 5}")
    passed &= check(len(rows) == 1, "a new plan replaces the rows of the last one")
    return passed


def stored_checks(gen, app):
    import storage_kinds
    passed = True
    view = gen._target_planner_view
    original = storage_kinds.engine_target_idxs
    storage_kinds.engine_target_idxs = lambda portal, floor, window_m, engine: (
        {0} if floor == 25 else set())
    try:
        rows = _plan(view, app, f"{F25 + 5}\n{F25 + 10 ** 24}")
    finally:
        storage_kinds.engine_target_idxs = original
    passed &= check(len(rows) == 1 and gen.T("target_planner.stored", count=1)
                    in view.summary_var.get(),
                    f"a stored window leaves its target out ({view.summary_var.get()!r})")
    return passed


def ram_checks(gen, app):
    from primeatlas.generation import engine_options, run_ram
    passed = True
    view = gen._target_planner_view
    fields = gen._engine_fields
    engine_cap = engine_options.max_windows_per_run("v7")
    for free in (4 * 10 ** 9, 2 * 10 ** 9):
        gen._set_engine_advice_ram(free)
        cap = run_ram.max_windows_in_budget(lambda w: fields.choice_for_engine("v7", w), free,
                                            engine_cap, W)
        _plan(view, app, f"{F25 + 3000 * W} {3000 * W}")
        groups = view.groups
        atlas = [g.windows for g in groups if g.method == "atlas"]
        if cap > 0:
            passed &= check(0 < cap < 6001 and atlas and max(atlas) <= cap,
                            f"{free / 1e9:.0f} GB free: Atlas rows of at most {cap} windows "
                            f"({[(g.method, g.windows) for g in groups]})")
        else:
            passed &= check(not atlas and len(groups) == 1 and groups[0].windows == 6001,
                            f"{free / 1e9:.0f} GB free, not one v7 window fits: one "
                            f"Pseudosquares run over the whole range, not cut into windows "
                            f"({[(g.method, g.windows) for g in groups][:5]})")
    gen._set_engine_advice_ram(FAKE_FREE_RAM)
    return passed


def load_checks(gen, app, portal):
    from tkinter import filedialog
    passed = True
    view = gen._target_planner_view
    path = os.path.join(portal, "targets.txt")
    with open(path, "wb") as f:
        f.write(b"10**25+3 1000\r\n# note\r\n10**26\r\n")
    original = filedialog.askopenfilename
    filedialog.askopenfilename = lambda **_k: path
    try:
        view.load_button.invoke()
        app.update()
    finally:
        filedialog.askopenfilename = original
    passed &= check(view.get_text().splitlines() == ["10**25+3 1000", "# note", "10**26"],
                    f"Load file reads a CRLF file ({view.get_text()!r})")
    return passed


def example_checks(gen, app, asked):
    from primeatlas.generation import target_planner_example as example
    passed = True
    view = gen._target_planner_view
    text = example.example_text().rstrip("\n")
    rows = _plan(view, app, f"{F25 + 5}")
    message = view.message_var.get()
    view.set_text("")
    asked.clear()
    view.example_button.invoke()
    view.example_button.invoke()
    app.update()
    passed &= check(view.get_text() == text and not asked
                    and view.text.index("insert") == "1.0",
                    f"empty field, double click: the example once, cursor at its start, no "
                    f"question ({len(asked)} asked)")
    passed &= check(view.tree.get_children() == rows and view.message_var.get() == message,
                    "inserting plans nothing: the table and the message stay")
    asked.clear()
    view.example_button.invoke()
    app.update()
    passed &= check(view.get_text() == text and not asked,
                    "the field already holds the example: no question")
    for answer, want in ((False, "10**20 5"), (True, text)):
        view.set_text("10**20 5")
        asked.clear()
        asked.append(answer)
        view.example_button.invoke()
        app.update()
        question = asked[1:] and asked[1]
        passed &= check(view.get_text() == want and question
                        and question.get("default") == "no",
                        f"other text, answer {'Yes' if answer else 'No'}: field "
                        f"{'replaced' if answer else 'kept'}, asked with No by default")
    rows = _plan(view, app, text)
    message = view.message_var.get()
    passed &= check(rows and gen.T("target_planner.errors_header") not in message,
                    f"the example planned: {len(rows)} rows, no bad line ({message!r})")
    return passed


def load_example_checks(gen, app, portal):
    from tkinter import filedialog
    from primeatlas.generation import target_planner_example as example
    passed = True
    view = gen._target_planner_view
    copy = os.path.join(portal, example.EXAMPLE_FILE_NAME)
    if os.path.exists(copy):
        os.remove(copy)
    seen = {}

    def dialog(**kwargs):
        seen.update(kwargs)
        seen["copy_there"] = os.path.isfile(copy)
        return copy
    original = filedialog.askopenfilename
    filedialog.askopenfilename = dialog
    try:
        view.set_text("")
        view.load_button.invoke()
        app.update()
    finally:
        filedialog.askopenfilename = original
    passed &= check(os.path.normcase(os.path.abspath(seen.get("initialdir", "")))
                    == os.path.normcase(os.path.abspath(portal)) and seen.get("copy_there"),
                    f"Load file opens in the storage folder, the example copy already there "
                    f"({seen.get('initialdir')})")
    passed &= check(view.get_text() == example.example_text().rstrip("\n"),
                    "the copy loaded: the same text as Insert example")
    return passed


def forced_use_checks(gen, app):
    passed = True
    view = gen._target_planner_view
    engine = gen._engine_fields.engine_var
    engine.set("v7")
    rows = _plan(view, app, "10**25+3 pt1.1")
    passed &= check(len(rows) == 1 and view.groups[0].engine == "pt1"
                    and view.groups[0].forced, f"a target forced to pt1.1: a pt1 row "
                                               f"({view.groups})")
    _select_first(view, app)
    view.use_button.invoke()
    app.update()
    passed &= check(engine.get() == "pt1" and gen.quick_mode_var.get() == "floor"
                    and gen.quick_floor_start_var.get() == str(view.groups[0].lo),
                    f"Use: the form's engine becomes pt1, Quick-gen filled ({engine.get()})")
    engine.set("v6")
    for text, what in ((f"{F25 + 100 * W} {100 * W}", "a free group"),
                       ("10**25+3 pss", "a forced Pseudosquares group")):
        _plan(view, app, text)
        _select_first(view, app)
        view.use_button.invoke()
        app.update()
        passed &= check(engine.get() == "v6", f"Use on {what}: the engine stays v6 "
                                              f"({engine.get()})")
    engine.set("v7")
    return passed


def main():
    import prime_atlas_v2
    from tkinter import messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    asked = []

    def ask(*_a, **kwargs):
        answer = asked[0] if asked else False
        asked.append(kwargs)
        return answer
    messagebox.askyesno = ask
    portal = tempfile.mkdtemp(prefix="primeatlas_planner_test_")
    _seed_log(portal)
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
        gen = app.generation_tab_widget
        gen._engine_fields.engine_var.set("v7")
        gen._set_engine_advice_ram(FAKE_FREE_RAM)
        passed = layout_checks(gen, app)
        passed &= message_checks(gen, app)
        passed &= atlas_checks(gen, app)
        passed &= pss_checks(gen, app)
        passed &= stored_checks(gen, app)
        passed &= ram_checks(gen, app)
        passed &= load_checks(gen, app, portal)
        passed &= example_checks(gen, app, asked)
        passed &= load_example_checks(gen, app, portal)
        passed &= forced_use_checks(gen, app)
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
