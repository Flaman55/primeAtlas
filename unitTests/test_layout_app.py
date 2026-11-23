"""Height grips and the remembered layout in the real app (layout_memory.py, layout_const.py).

The app is built on an empty temp storage at 1280 x 720, every notebook tab (nested ones
too) is selected in turn. Polish at 100 % and English at 125 %, each in its own process.
Checks:
  4. every shown Text, Listbox, Treeview and chart (a Canvas at least CHART_MIN_HEIGHT tall
     that is not a page's own canvas or scroll pad) is the target of a grip with a place
     from layout_const.GRIPS; the two storage panes (Primes, Constellations) have one grip
     under the pane with both lists;
  1, 8. every grip target is exactly as tall as it asks (never squeezed, never stretched);
  2. with every grip at its maximum the targets are still exactly as tall as they ask,
     every tab showing one scrolls, and the wheel over a grip scrolls the page;
  3. after reset_layout() a tab that fitted before fits again;
 17. the three Benchmark charts start at the same height, CHART_HEIGHT_PX;
  7. the Records table rebuilt after a drag keeps the grip's height;
 15. Settings > General has the Default layout button; it removes every layout.* key and
     puts the grips back.
Restart (own process, store on a temp file): a dragged grip, a toggled terminal, the
Constellations storage sash and a normal window's geometry come back after the app is
closed and built again (9-12); a store with no layout keys opens the window maximized.
Windows, real display:
    python unitTests/test_layout_app.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIDTH, HEIGHT = 1280, 720
CONFIGS = [("pl", 100), ("en", 125)]
CHILD_TIMEOUT_S = 900
# A Canvas at least this tall is a chart. Arbitrary.
CHART_MIN_HEIGHT = 100
# Canvases whose drawing sets their height to fit what it draws (irreducibility_draw.py):
# the Irreducibility radices strip and compare dials, not charts. Matched by the path of
# the view holding them.
CONTENT_SIZED = ("radicesview", "compareview")


def _setup(lang, font_scale):
    sys.path[:0] = [ROOT, os.path.join(ROOT, "prime_sieve"), os.path.join(ROOT, "constellation"),
                    os.path.dirname(os.path.abspath(__file__))]
    from tkinter import messagebox
    for name in ("showinfo", "showerror", "showwarning"):
        setattr(messagebox, name, lambda *a, **k: None)
    from primeatlas.core import app_settings, i18n
    i18n.save_language = lambda *_a, **_k: None
    app_settings.save_language = i18n.save_language
    app_settings.load_saved_language = lambda: lang
    from app_sandbox import isolate_app
    prime_atlas_v2, portal = isolate_app()
    from primeatlas.app import app_dynamic
    app_dynamic.APP_SETTINGS.set_font_scale(font_scale)
    return prime_atlas_v2, portal


def _show(app):
    deadline = time.time() + 60
    while not app.main_notebook.winfo_ismapped() and time.time() < deadline:
        app.update()
        time.sleep(0.05)


def _settle(app, seconds=0.4):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.01)


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def _shown(widget):
    import tkinter as tk
    try:
        return bool(widget.winfo_ismapped() and widget.winfo_viewable())
    except tk.TclError:
        return False


def _tabs(app):
    """(trail, select) for every notebook tab, nested ones included, depth first."""
    from tkinter import ttk

    def outer_book(widget, container):
        parent = widget.master
        while parent is not None and parent is not container:
            if isinstance(parent, ttk.Notebook):
                return parent
            parent = parent.master
        return None

    def visit(container, trail):
        books = [w for w in _walk(container)
                 if isinstance(w, ttk.Notebook) and outer_book(w, container) is None]
        for book in books:
            for tab in book.tabs():
                key = trail + (book.tab(tab, "text"),)
                yield key, (lambda b=book, t=tab: b.select(t))
                yield from visit(book.nametowidget(tab), key)

    return list(visit(app, ()))


def _page_of(widget):
    from primeatlas.core.widgets import ScrollablePage
    while widget is not None:
        target = getattr(widget, "wheel_target", None)
        if isinstance(target, ScrollablePage):
            return target
        widget = widget.master
    return None


def _pages_on(app):
    from primeatlas.core.widgets import ScrollablePage
    return [w.wheel_target for w in _walk(app)
            if isinstance(getattr(w, "wheel_target", None), ScrollablePage) and _shown(w)]


def _child_layout(lang, font_scale):
    prime_atlas_v2, _portal = _setup(lang, font_scale)
    import tkinter as tk
    from tkinter import ttk
    from primeatlas.core import layout_const, layout_memory, ui_state_dynamic
    from primeatlas.core.widgets import HeightGrip, ScrollPad, route_wheel

    grips = []
    original = HeightGrip.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        grips.append(self)
    HeightGrip.__init__ = init

    app = prime_atlas_v2._build_gui()()
    app.state("normal")
    app.geometry(f"{WIDTH}x{HEIGHT}+0+0")
    _show(app)
    tabs = _tabs(app)
    out = []

    def say(ok, message):
        out.append(("ok:   " if ok else "FAIL: ") + message)

    def targets_of():
        found = {}
        for grip in grips:
            if grip.place is None:
                continue
            for target in grip.targets():
                found.setdefault(str(target), grip)
        return found

    def scan(trail, phase):
        """Problems on the selected tab: unknown big widgets, wrong heights."""
        _settle(app)
        by_target = targets_of()
        name = " > ".join(trail)
        shown_targets = []
        for widget in _walk(app):
            if not _shown(widget):
                continue
            big = isinstance(widget, (tk.Text, tk.Listbox, ttk.Treeview))
            if isinstance(widget, tk.Canvas) and not isinstance(
                    getattr(widget, "wheel_target", None), (ScrollPad,)) and not hasattr(
                    widget, "wheel_target"):
                big = (widget.winfo_reqheight() >= CHART_MIN_HEIGHT
                       and not any(f".!{v}." in str(widget) for v in CONTENT_SIZED))
            if not big:
                continue
            grip = by_target.get(str(widget))
            if grip is None:
                if phase == "default":
                    say(False, f"4: [{name}] {widget.winfo_class()} {widget} has no grip")
                continue
            shown_targets.append((widget, grip))
            if abs(widget.winfo_height() - widget.winfo_reqheight()) > 1:
                say(False, f"1/8 ({phase}): [{name}] {widget.winfo_class()} shown "
                           f"{widget.winfo_height()} px, asks {widget.winfo_reqheight()} "
                           f"({grip.place})")
        return shown_targets

    fits_before = {}
    for trail, select in tabs:
        select()
        scan(trail, "default")
        pages = _pages_on(app)
        fits_before[trail] = [p.scrolls() for p in pages]
    say(True, f"4, 1, 8: scanned {len(tabs)} tabs at the defaults")

    places = {}
    for grip in grips:
        if grip.place is not None:
            places.setdefault(grip.place, []).append(grip)
    for place, same in places.items():
        targets = {tuple(sorted(str(t) for t in g.targets())) for g in same}
        if len(targets) > 1:
            say(False, f"4: place {place} is used by grips of different widgets")
    for place in ("primes.storage", "constellations.storage"):
        grip = places.get(place, [None])[0]
        kinds = sorted(t.winfo_class() for t in grip.targets()) if grip else []
        say(kinds == ["Listbox", "Treeview"],
            f"5: {place} has one grip with the tree and the preview list ({kinds})")

    bench = getattr(app, "benchmark_tab_widget", None)
    charts = [getattr(bench, n, None) for n in ("benchmark_chart2", "benchmark_chart",
                                                 "benchmark_chart3")]
    heights = [int(c.cget("height")) for c in charts if c is not None]
    say(heights == [layout_const.CHART_HEIGHT_PX] * 3,
        f"17: the three Benchmark charts start at CHART_HEIGHT_PX ({heights})")

    for grip in grips:
        if grip.place is not None:
            grip.value = grip.max_lines
            grip.apply()
    wheel_checked = False
    for trail, select in tabs:
        select()
        shown_targets = scan(trail, "max")
        if not shown_targets:
            continue
        page = _page_of(shown_targets[0][0])
        if page is None:
            continue
        _settle(app, 0.3)
        say(page.scrolls(), f"2: [{' > '.join(trail)}] with every grip at max the page scrolls")
        if not wheel_checked:
            grip = shown_targets[0][1]
            page.canvas.yview_moveto(0.0)
            event = tk.Event()
            event.widget, event.delta, event.num = grip.frame, -120, 0
            route_wheel(event)
            _settle(app, 0.2)
            say(page.canvas.yview()[0] > 0.0, "2: the wheel over a grip scrolls the page")
            wheel_checked = True

    layout_memory.reset_layout()
    # The reset also maximizes the window; the comparison is at the same size as before.
    _settle(app, 0.5)
    app.state("normal")
    app.geometry(f"{WIDTH}x{HEIGHT}+0+0")
    _settle(app, 0.5)
    # A tab holding a notebook shows whichever of its tabs was selected last, which differs
    # between the two visits: only tabs without nested tabs are compared.
    parents = {trail[:-1] for trail, _select in tabs}
    for trail, select in tabs:
        select()
        if trail in parents:
            continue
        _settle(app, 0.3)
        now = [p.scrolls() for p in _pages_on(app)]
        if now != fits_before[trail] and not any(fits_before[trail]):
            sizes = [(p.canvas.winfo_height(), p.body.winfo_reqheight()) for p in _pages_on(app)]
            say(False, f"3: [{' > '.join(trail)}] fitted before, scrolls after the reset "
                       f"(viewport/content {sizes})")
    say(True, "3: tabs checked after reset_layout()")

    records = getattr(app, "constellations_records_tab_widget", None)
    if records is not None:
        grip = records.tree_grip
        records._rebuild_tree([1, 2], row_count=4)
        grip._on_press(type("E", (), {"y_root": 0})())
        grip._on_drag(type("E", (), {"y_root": 5 * grip.line_height()})())
        grip._on_release(type("E", (), {"y_root": 0})())
        records._rebuild_tree([1, 2], row_count=4)
        say(int(records.tree.cget("height")) == 9 == grip.value,
            f"7: the rebuilt Records table keeps the grip's 9 rows (4 rows + 5 dragged) "
            f"({records.tree.cget('height')})")

    store = ui_state_dynamic.STORE
    button = getattr(app.settings_tab, "layout_reset_button", None)
    say(button is not None, "15: Settings > General has the Default layout button")
    if button is not None:
        grip = places["primes.storage"][0]
        grip._on_press(type("E", (), {"y_root": 0})())
        grip._on_drag(type("E", (), {"y_root": 5 * grip.line_height()})())
        grip._on_release(type("E", (), {"y_root": 0})())
        had = store.has("layout.grip.primes.storage")
        button.invoke()
        _settle(app, 0.3)
        keys = [k for k in store._data if k.startswith("layout.") and k != "layout.window.state"]
        say(had and not keys and grip.value == layout_const.GRIPS["primes.storage"][0],
            f"15: the button removes the layout keys and puts the grips back ({keys})")
    app.destroy()
    for line in out:
        print(line)


def _child_restart(work):
    prime_atlas_v2, portal = _setup("en", 100)
    from primeatlas.core import ui_state_dynamic
    from primeatlas.core.ui_state_store import UiStateStore
    import tkinter as tk
    path = os.path.join(work, "ui_state.json")
    out = []

    def say(ok, message):
        out.append(("ok:   " if ok else "FAIL: ") + message)

    def build():
        ui_state_dynamic.STORE = UiStateStore(path)
        app = prime_atlas_v2._build_gui()()
        _show(app)
        _settle(app, 1.0)
        return app

    app = build()
    say(app.state() == "zoomed", f"12: with nothing remembered the window opens maximized "
                                 f"({app.state()})")
    app.state("normal")
    app.geometry("1300x700+30+40")
    _settle(app, 0.5)
    gen = app.generation_tab_widget
    console = gen.loop_console
    console.toggle()
    want_console = console._visible
    grip = app.primes_tab_widget.storage_grip
    start = int(grip.targets()[0].cget("height"))
    event = type("E", (), {})
    for y in (0, 4 * grip.line_height()):
        e = event()
        e.y_root = y
        (grip._on_press if y == 0 else grip._on_drag)(e)
    grip._on_release(event())
    paned = app.constellations_hits_tab_widget.hits_paned
    app.main_notebook.select(app.constellations_tab)
    _settle(app, 0.5)
    paned.sashpos(0, 500)
    paned.event_generate("<ButtonRelease-1>")
    _settle(app, 0.5)
    share = ui_state_dynamic.STORE.get("layout.sash.constellations.storage")
    app.destroy()

    app = build()
    say(app.state() == "normal" and app.winfo_width() == 1300 and app.winfo_height() == 700,
        f"12: the window comes back normal 1300x700 ({app.state()} {app.wm_geometry()})")
    grip = app.primes_tab_widget.storage_grip
    say(int(grip.targets()[0].cget("height")) == start + 4,
        f"9: the Primes storage grip comes back at {start + 4} lines")
    say(app.generation_tab_widget.loop_console._visible == want_console,
        "10: the Generation terminal comes back as toggled")
    app.main_notebook.select(app.constellations_tab)
    _settle(app, 1.0)
    paned = app.constellations_hits_tab_widget.hits_paned
    say(isinstance(share, float) and abs(paned.sashpos(0) - share * paned.winfo_width()) <= 3,
        f"11: the Constellations storage sash comes back at share {share}")
    app.destroy()
    for line in out:
        print(line)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) >= 2 and sys.argv[1] == "--layout":
        _child_layout(sys.argv[2], int(sys.argv[3]))
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "--restart":
        _child_restart(sys.argv[2])
        return 0
    failures = []
    work = tempfile.mkdtemp(prefix="primeatlas_layout_app_")
    runs = [["--layout", lang, str(scale)] for lang, scale in CONFIGS] + [["--restart", work]]
    try:
        for args in runs:
            print(f"--- {' '.join(args)} ---", flush=True)
            proc = subprocess.run([sys.executable, __file__, *args], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=CHILD_TIMEOUT_S)
            lines = [l for l in proc.stdout.splitlines() if l.startswith(("ok:", "FAIL"))]
            print("\n".join(lines))
            failures += [l for l in lines if l.startswith("FAIL")]
            if proc.returncode != 0 or not lines:
                print(proc.stderr[-3000:])
                failures.append(f"{' '.join(args)} ran")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("=" * 78)
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
