"""
test_scrollable_page.py -- one shared page container (widgets.ScrollablePage) whose
vertical scrollbar and ScrollPad appear only while the page's content does not fit.

A. ScrollablePage alone:
   - content taller than the viewport: scrollbar and pad are packed, left to right
     canvas | pad | scrollbar; the inner frame keeps its natural height; the pad and the
     wheel scroll the page;
   - content that fits: scrollbar and pad are hidden, the inner frame is stretched to the
     viewport height (expand=True children fill it), the view stays at the top and
     nothing scrolls;
   - re-checked on every change, both ways: content growing/shrinking (e.g. a larger font)
     and the window resizing;
   - the wheel over a self-scrolling widget (Text, Listbox, Treeview) or a registered
     exclusion is left to that widget;
   - scroll_to(widget) brings a widget in the middle to the top of the view (also one inside
     a nested frame) and keeps it there after a re-check; a widget near the end scrolls to
     the end with the widget in view; back to the first widget returns to the top; on a
     page that fits it scrolls nothing.
   - a show/hide loop settles: content that gets taller when the page widens (a layout
     following the width a moment late) leaves the scrollbar shown instead of showing
     and hiding it for ever; the content shrinking to another height then hides it.
B. The app: every page uses it -- Primes (Storage, primesieve, Primality), Constellations
   (Storage, Calculator, Records), Research (five sub-tabs), Benchmark, About, the three
   Settings sub-tabs, Generation and the visualization tabs; the three old copies of the
   canvas/scrollbar code are gone; at 1050x680 each shown page has its scrollbar exactly
   when its content is taller than the viewport, and the Benchmark page (three charts one
   under another) scrolls; in a short
   window the About page scrolls and keeps the NOTICE box at its natural height.
C. The wheel never switches notebook tabs (Tk 9 binds it to cycle them): after
   widgets.disable_notebook_wheel no TNotebook wheel binding is left, the wheel over the tab
   strip in every direction (down, up, Shift, Alt, touchpad) keeps the selected tab, and the
   wheel over a notebook inside a page still scrolls the page; the app does this at start.
D. The wheel is routed by the widget under the pointer, through one app-wide binding made
   once, never by <Enter>/<Leave> history:
   - D1 a page scrolls with no <Enter> ever seen, after an <Enter>/<Leave> pair on its
     canvas (a dialog or a rebuild under the pointer), after another page's <Leave>, and
     over a widget rebuilt in place (Run, Generate);
   - D2 over the pad and the page scrollbar the wheel scrolls that page, also after a
     <Leave> on them;
   - D3 over a Text, an enabled spinbox or a registered exclusion the page stays; over a
     disabled spinbox it scrolls;
   - D4 nested pages: the inner one scrolls, the outer stays; an inner page that fits
     passes the wheel to the outer one;
   - D5 a Toplevel created with a master inside a page never scrolls that page; one with
     its own page scrolls only its own;
   - D6 a page that fits does not move; of two pages in a notebook only the shown one
     scrolls;
   - D7 a destroyed page or pad raises nothing;
   - D8 a notch is 3 units (60px) per 120 delta, up and down, and Button-4/5; the binding
     exists right after the first page is built and <Enter>/<Leave> do not change it.

Usage:
    python unitTests/test_scrollable_page.py
"""
import os
import sys
import time
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.core import widgets  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


class FakeEvent:
    def __init__(self, widget=None, delta=-120, num=0):
        self.widget = widget
        self.delta = delta
        self.num = num


def _settle(root, rounds=4):
    for _ in range(rounds):
        root.update()


def _shown(page):
    return (page.scrollbar.winfo_manager() == "pack"
            and page.pad.frame.winfo_manager() == "pack")


def _hidden(page):
    return page.scrollbar.winfo_manager() == "" and page.pad.frame.winfo_manager() == ""


def _window_height(page):
    return page.body.winfo_height()


def _test_page():
    print("\n--- A. ScrollablePage ---")
    cls = getattr(widgets, "ScrollablePage", None)
    check(cls is not None, "widgets.ScrollablePage exists")
    if cls is None:
        return
    root = tk.Tk()
    root.geometry("500x400")
    try:
        page = cls(root, pad_text="Scroll")
        check(page.pad.text == "Scroll", "the pad gets its label")
        block = tk.Frame(page.body, height=900, width=200)
        block.pack(fill="both", expand=True)
        _settle(root)
        canvas_h = page.canvas.winfo_height()
        check(_shown(page), f"tall content: scrollbar and pad shown (canvas {canvas_h}px)")
        check(page.scrolls(), "scrolls() is True while they are shown")
        xs = [page.canvas.winfo_x(), page.pad.frame.winfo_x(), page.scrollbar.winfo_x()]
        check(xs == sorted(xs), f"order is canvas | pad | scrollbar (x {xs})")
        check(_window_height(page) == page.body.winfo_reqheight(),
              f"tall content keeps its natural height ({_window_height(page)})")
        page.pad.wheel(FakeEvent(delta=-120))
        _settle(root)
        check(page.canvas.yview()[0] > 0.0, f"the pad scrolls the page ({page.canvas.yview()})")
        page.canvas.yview_moveto(0.0)
        label = ttk.Label(block, text="x")
        page.on_mousewheel(FakeEvent(label))
        _settle(root)
        check(page.canvas.yview()[0] > 0.0, "the wheel over plain content scrolls the page")
        page.canvas.yview_moveto(0.0)
        text = ScrolledText(block)
        page.on_mousewheel(FakeEvent(text))
        tree = ttk.Treeview(block)
        page.on_mousewheel(FakeEvent(tree))
        _settle(root)
        check(page.canvas.yview()[0] == 0.0, "the wheel over a Text/Treeview is left to it")
        own = ttk.Frame(block)
        inside = ttk.Label(own, text="y")
        page.register_exclude(own)
        page.on_mousewheel(FakeEvent(inside))
        _settle(root)
        check(page.canvas.yview()[0] == 0.0, "a registered exclusion is left alone")
        try:
            page.on_mousewheel(FakeEvent("string-widget"))
            page.on_mousewheel(FakeEvent(None))
            raised = False
        except Exception:
            raised = True
        check(not raised, "a string/None event.widget (Tk-internal popdowns) never raises")

        page.pad.wheel(FakeEvent(delta=-360))
        block.configure(height=100)
        _settle(root)
        canvas_h = page.canvas.winfo_height()
        check(_hidden(page), "shrinking content hides scrollbar and pad")
        check(not page.scrolls(), "scrolls() is False then")
        check(_window_height(page) == canvas_h,
              f"content that fits is stretched to the viewport ({_window_height(page)} vs {canvas_h})")
        check(block.winfo_height() >= canvas_h - 2, "an expand=True child fills the viewport")
        check(page.canvas.yview()[0] == 0.0, "the view returns to the top")
        page.pad.wheel(FakeEvent(delta=-120))
        page.on_mousewheel(FakeEvent(label))
        _settle(root)
        check(page.canvas.yview()[0] == 0.0, "a page that fits does not scroll")

        big = ttk.Label(page.body, text="Large", font=("TkDefaultFont", 9))
        big.pack()
        _settle(root)
        check(_hidden(page), "a small font still fits")
        big.configure(font=("TkDefaultFont", -500))
        _settle(root)
        check(_shown(page), "a larger font that overflows brings the scrollbar back")
        big.configure(font=("TkDefaultFont", 9))
        _settle(root)
        check(_hidden(page), "and it goes away again with the smaller font")
        big.destroy()

        block.configure(height=600)
        _settle(root)
        check(_shown(page), "600px of content in a 400px window scrolls")
        root.geometry("500x900")
        _settle(root, 8)
        check(_hidden(page), "a taller window hides the scrollbar")
        root.geometry("500x400")
        _settle(root, 8)
        check(_shown(page), "a shorter window shows it again")
    finally:
        root.destroy()


def _test_scroll_to():
    print("\n--- A. ScrollablePage.scroll_to ---")
    root = tk.Tk()
    root.geometry("500x400")
    try:
        page = widgets.ScrollablePage(root)
        rows = []
        for i in range(40):
            row = tk.Frame(page.body, height=50, width=200)
            row.pack(fill="x")
            rows.append(row)
        inner = tk.Frame(rows[25], height=10, width=10)
        inner.place(x=0, y=20)
        _settle(root)

        def top_of(widget):
            return widget.winfo_rooty() - page.canvas.winfo_rooty()

        page.scroll_to(rows[20])
        _settle(root)
        check(abs(top_of(rows[20])) < 20, f"row 20 at the top of the view ({top_of(rows[20])})")
        _settle(root, 8)
        check(abs(top_of(rows[20])) < 20, "it stays there after a re-check")
        page.scroll_to(inner)
        _settle(root)
        check(abs(top_of(inner)) < 20, f"a nested widget at the top ({top_of(inner)})")
        page.scroll_to(rows[39])
        _settle(root)
        canvas_h = page.canvas.winfo_height()
        check(page.canvas.yview()[1] == 1.0 and 0 <= top_of(rows[39]) < canvas_h,
              f"the last row: the view at the end, the row in view ({top_of(rows[39])})")
        page.scroll_to(rows[0])
        _settle(root)
        check(page.canvas.yview()[0] == 0.0, "back to the first row: the top")
        for row in rows[2:]:
            row.destroy()
        _settle(root)
        page.scroll_to(rows[1])
        _settle(root)
        check(page.canvas.yview()[0] == 0.0, "a page that fits scrolls nothing")
    finally:
        root.destroy()


def _test_show_hide_loop():
    print("\n--- A. ScrollablePage show/hide loop ---")
    root = tk.Tk()
    root.geometry("500x400")
    try:
        page = widgets.ScrollablePage(root)
        block = tk.Frame(page.body, width=100, height=100)
        block.pack(fill="x")
        _settle(root)
        view = page.canvas.winfo_height()
        wide = page.canvas.winfo_width()
        # Taller than the view while wide (scrollbar hidden), shorter while narrow (shown),
        # set a moment after each width change: the inverse of what wrapping gives.
        state = {"height": view - 10}

        def follow(_event):
            target = view + 15 if block.winfo_width() >= wide - 2 else view - 10
            if target != state["height"]:
                state["height"] = target
                root.after(30, lambda: block.configure(height=target))
        block.bind("<Configure>", follow, add="+")
        toggles = {"n": 0}
        original = page._set_shown

        def counting(shown):
            if shown != page._shown:
                toggles["n"] += 1
            original(shown)
        page._set_shown = counting
        block.configure(height=view + 15)
        end = time.time() + 2
        while time.time() < end:
            root.update()
            time.sleep(0.01)
        check(toggles["n"] <= 3, f"the loop settles ({toggles['n']} show/hide changes)")
        check(page.scrolls(), "it settles with the scrollbar shown")
        block.unbind("<Configure>")
        end = time.time() + 0.5  # the last delayed height change lands
        while time.time() < end:
            root.update()
            time.sleep(0.01)
        block.configure(height=view // 2)
        end = time.time() + 0.5
        while time.time() < end:
            root.update()
            time.sleep(0.01)
        check(not page.scrolls(), f"content shrinking to another height hides it "
                                  f"({page.body.winfo_reqheight()} in {page.canvas.winfo_height()})")
    finally:
        root.destroy()


def _show_tab(widget):
    """Selects every notebook tab on the way from `widget` up to the root."""
    child, parent = widget, widget.master
    while parent is not None:
        if isinstance(parent, ttk.Notebook):
            parent.select(child)
        child, parent = parent, parent.master


def _all_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _all_widgets(child)


APP_PAGES = ("primes_storage_tab", "primes_primesieve_tab", "primes_primality_tab",
             "constellations_storage_tab", "constellations_calculator_tab",
             "constellations_records_tab", "research_squares_tab",
             "research_polynomials_tab", "research_goldbach_tab", "research_gaps_tab",
             "research_pi_approx_tab", "benchmark_tab", "about_tab")


def _test_sources():
    print("\n--- B1. one implementation ---")
    for rel in (("primeatlas", "settings", "settings_tab.py"),
                ("primeatlas", "generation", "generation_tab.py"),
                ("primeatlas", "visualization", "shared", "viz_tab_base.py")):
        with open(os.path.join(_REPO_ROOT, *rel), encoding="utf-8") as f:
            src = f.read()
        check("create_window" not in src and "ScrollablePage" in src,
              f"{rel[-1]} uses ScrollablePage instead of its own canvas copy")


_NOTEBOOK_WHEEL_EVENTS = ("<MouseWheel>", "<Shift-MouseWheel>", "<Alt-MouseWheel>",
                          "<Shift-Alt-MouseWheel>", "<TouchpadScroll>", "<Button-4>",
                          "<Button-5>")


def _notebook_wheel_bindings(root):
    return [s for s in root.bind_class("TNotebook") if s in _NOTEBOOK_WHEEL_EVENTS]


def _test_notebook_wheel():
    print("\n--- C. the wheel never switches notebook tabs ---")
    root = tk.Tk()
    root.geometry("400x300")
    try:
        disable = getattr(widgets, "disable_notebook_wheel", None)
        check(disable is not None, "widgets.disable_notebook_wheel exists")
        if disable is None:
            return
        disable(root)
        check(_notebook_wheel_bindings(root) == [],
              f"no TNotebook wheel binding left ({_notebook_wheel_bindings(root)})")
        page = widgets.ScrollablePage(root)
        nb = ttk.Notebook(page.body)
        nb.pack(fill="x")
        for i in range(4):
            nb.add(ttk.Frame(nb, height=40), text=f"tab {i}")
        ttk.Frame(page.body, height=1200).pack()
        nb.select(1)
        _settle(root)
        x, y = 20, 8
        for seq, delta in (("<MouseWheel>", -120), ("<MouseWheel>", 120),
                           ("<Shift-MouseWheel>", -120), ("<Alt-MouseWheel>", 120),
                           ("<MouseWheel>", -1200)):
            nb.event_generate(seq, x=x, y=y, delta=delta)
            _settle(root, 2)
            check(nb.index("current") == 1, f"{seq} delta {delta} over the tabs keeps tab 1")
        before = page.canvas.yview()[0]
        widgets.route_wheel(FakeEvent(widget=nb, delta=-120))
        _settle(root)
        check(page.canvas.yview()[0] > before, "the wheel over a notebook still scrolls the page")
        check(nb.index("current") == 1, "and the tab stays")
    finally:
        root.destroy()


def _test_app():
    print("\n--- B2. the app ---")
    import tkinter.messagebox as messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    app = prime_atlas_v2._build_gui()()
    try:
        deadline = time.time() + 8
        while not app.main_notebook.winfo_ismapped() and time.time() < deadline:
            app.update()
            time.sleep(0.05)
        check(_notebook_wheel_bindings(app) == [],
              f"the app leaves no TNotebook wheel binding ({_notebook_wheel_bindings(app)})")
        cls = getattr(widgets, "ScrollablePage", None)
        pages = dict(getattr(app, "scroll_pages", {}))
        for name in APP_PAGES:
            check(isinstance(pages.get(name), cls) if cls else False,
                  f"{name} is a ScrollablePage")
        settings_pages = getattr(app.settings_tab, "_scroll_pages", [])
        check(len(settings_pages) == 3 and all(isinstance(p, cls) for p in settings_pages)
              if cls else False, "the three Settings sub-tabs are ScrollablePages")
        others = {"generation": app.generation_tab_widget}
        for name in ("rings_tab_widget", "tree_tab_widget", "sphere_tab_widget"):
            if getattr(app, name, None) is not None:
                others[name] = getattr(app, name)
        for name, tab in others.items():
            page = getattr(tab, "_scroll_page", None)
            check(cls is not None and isinstance(page, cls), f"{name} is a ScrollablePage")
            if cls is not None and isinstance(page, cls):
                check(tab._scroll_pad is page.pad, f"{name}: _scroll_pad is the page's pad")
                pages[name] = page
        for i, page in enumerate(settings_pages):
            pages[f"settings_{i}"] = page
        if cls is None:
            return
        for name, page in pages.items():
            _show_tab(page.frame)
            _settle(app)
            canvas_h = page.canvas.winfo_height()
            need = page.body.winfo_reqheight()
            overflow = need > canvas_h
            check(page.scrolls() == overflow and (_shown(page) if overflow else _hidden(page)),
                  f"{name}: scrollbar {'shown' if page.scrolls() else 'hidden'} "
                  f"(content {need}px, viewport {canvas_h}px)")
        bench = pages.get("benchmark_tab")
        if bench is not None:
            _show_tab(bench.frame)
            _settle(app)
            check(bench.scrolls(), "Benchmark's three stacked charts scroll at 1050x680 "
                  f"(content {bench.body.winfo_reqheight()}px, viewport {bench.canvas.winfo_height()}px)")
        about = pages.get("about_tab")
        if about is not None:
            app.geometry("1050x380")
            _show_tab(about.frame)
            _settle(app, 8)
            notice = app.about_tab_widget.notice_text
            check(about.scrolls(), "a short window makes the About page scroll")
            check(notice.winfo_height() >= notice.winfo_reqheight() - 2,
                  f"the NOTICE box keeps its natural height ({notice.winfo_height()} of "
                  f"{notice.winfo_reqheight()}px)")
            app.geometry("1050x680")
            _settle(app, 8)
    finally:
        app.destroy()


def _wheel(root, widget, delta=-120):
    widget.event_generate("<MouseWheel>", x=2, y=2, delta=delta)
    _settle(root, 2)


def _top_px(page):
    return int(page.canvas.canvasy(0))


def _tall_page(parent, height=1200):
    page = widgets.ScrollablePage(parent)
    block = tk.Frame(page.body, height=height, width=200)
    block.pack(fill="both", expand=True)
    label = ttk.Label(block, text="row")
    label.place(x=10, y=10)
    return page, block, label


def _test_wheel_routing():
    print("\n--- D. the wheel is routed by the widget under the pointer ---")
    root = tk.Tk()
    root.geometry("500x400")
    errors = []
    root.report_callback_exception = lambda *a: errors.append(a[1])
    try:
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True)
        tab_a, tab_b = ttk.Frame(nb), ttk.Frame(nb)
        nb.add(tab_a, text="a")
        nb.add(tab_b, text="b")
        page, block, label = _tall_page(tab_a)
        other, _other_block, other_label = _tall_page(tab_b)
        _settle(root)
        bound = root.bind_all("<MouseWheel>")
        check(bound != "", "D8 the binding exists after the first page")

        _wheel(root, label)
        check(_top_px(page) == 60, f"D1/D8 no <Enter> seen: one notch scrolls 60px ({_top_px(page)})")
        _wheel(root, label, delta=120)
        check(_top_px(page) == 0, f"D8 one notch up scrolls back ({_top_px(page)})")
        page.canvas.event_generate("<Enter>")
        page.canvas.event_generate("<Leave>")
        _settle(root, 2)
        _wheel(root, label)
        check(_top_px(page) == 60, f"D1 after an <Enter>/<Leave> pair the page scrolls ({_top_px(page)})")
        check(root.bind_all("<MouseWheel>") == bound, "D8 <Enter>/<Leave> leave the binding alone")
        other.canvas.event_generate("<Enter>")
        other.canvas.event_generate("<Leave>")
        _settle(root, 2)
        _wheel(root, label)
        check(_top_px(page) == 120, f"D1 another page's <Leave> does not stop it ({_top_px(page)})")
        label.destroy()
        label = ttk.Label(block, text="rebuilt")
        label.place(x=10, y=10)
        _settle(root)
        _wheel(root, label)
        check(_top_px(page) == 180, f"D1 a widget rebuilt in place scrolls the page ({_top_px(page)})")
        # Tk 9 reports X11 buttons 4/5 as <MouseWheel> and renumbers them elsewhere, so
        # the X11 event is fed to the router directly.
        widgets.route_wheel(FakeEvent(widget=label, num=4))
        _settle(root, 2)
        check(_top_px(page) == 120, f"D8 Button-4 scrolls 3 units up ({_top_px(page)})")
        widgets.route_wheel(FakeEvent(widget=label, num=5))
        _settle(root, 2)
        check(_top_px(page) == 180, f"D8 Button-5 scrolls 3 units down ({_top_px(page)})")
        page.canvas.yview_moveto(0.0)

        page.pad.frame.event_generate("<Leave>")
        _wheel(root, page.pad.frame)
        check(_top_px(page) == 60, f"D2 the pad scrolls its page after a <Leave> ({_top_px(page)})")
        page.scrollbar.event_generate("<Leave>")
        _wheel(root, page.scrollbar)
        check(_top_px(page) == 120, f"D2 the page scrollbar scrolls its page ({_top_px(page)})")
        page.canvas.yview_moveto(0.0)

        text = ScrolledText(block, height=4)
        text.place(x=10, y=40)
        spin = ttk.Spinbox(block, from_=0, to=10)
        spin.place(x=10, y=200)
        own = ttk.Frame(block, width=50, height=50)
        own.place(x=10, y=260)
        inside = ttk.Label(own, text="own")
        inside.place(x=0, y=0)
        page.register_exclude(own)
        _settle(root)
        for name, widget in (("a Text", text), ("an enabled spinbox", spin),
                             ("a registered exclusion", inside)):
            _wheel(root, widget)
            check(_top_px(page) == 0, f"D3 over {name} the page stays ({_top_px(page)})")
        spin.state(["disabled"])
        _wheel(root, spin)
        check(_top_px(page) == 60, f"D3 over a disabled spinbox the page scrolls ({_top_px(page)})")
        page.canvas.yview_moveto(0.0)

        holder = tk.Frame(block)
        holder.place(x=0, y=320, width=300, height=150)
        inner, inner_block, inner_label = _tall_page(holder, height=900)
        _settle(root, 6)
        _wheel(root, inner_label)
        check(_top_px(inner) == 60 and _top_px(page) == 0,
              f"D4 nested: the inner page scrolls, the outer stays ({_top_px(inner)}, {_top_px(page)})")
        inner_block.configure(height=50)
        _settle(root, 6)
        _wheel(root, inner_label)
        check(_top_px(inner) == 0 and _top_px(page) == 60,
              f"D4 an inner page that fits passes the wheel out ({_top_px(inner)}, {_top_px(page)})")
        page.canvas.yview_moveto(0.0)

        popup = tk.Toplevel(block)
        popup.geometry("200x150+40+40")
        popup_label = ttk.Label(popup, text="dialog")
        popup_label.pack()
        _settle(root)
        _wheel(root, popup_label)
        check(_top_px(page) == 0, f"D5 a Toplevel under a page does not scroll it ({_top_px(page)})")
        popup_page, _pb, popup_page_label = _tall_page(popup)
        _settle(root, 6)
        _wheel(root, popup_page_label)
        check(_top_px(popup_page) == 60 and _top_px(page) == 0,
              f"D5 a Toplevel's own page scrolls alone ({_top_px(popup_page)}, {_top_px(page)})")
        popup.destroy()

        _wheel(root, label)
        check(_top_px(other) == 0, "D6 the page of a hidden tab never scrolls")
        page.canvas.yview_moveto(0.0)
        nb.select(tab_b)
        _settle(root)
        _wheel(root, other_label)
        check(_top_px(other) == 60, f"D6 the shown page scrolls ({_top_px(other)})")
        nb.select(tab_a)
        small_holder = tk.Frame(block)
        small_holder.place(x=0, y=500, width=100, height=100)
        small = widgets.ScrollablePage(small_holder)
        small_label = ttk.Label(small.body, text="s")
        small_label.pack()
        _settle(root, 6)
        _wheel(root, small.pad.frame)
        check(_top_px(small) == 0, "D6 a page that fits does not move")

        gone, _gb, _gl = _tall_page(tab_a)
        gone.frame.destroy()
        _settle(root)
        _wheel(root, label)
        _wheel(root, page.pad.frame)
        check(not errors, f"D7 a destroyed page raises nothing ({errors[:1]})")
    finally:
        root.destroy()


def main():
    _test_page()
    _test_scroll_to()
    _test_show_hide_loop()
    _test_sources()
    _test_notebook_wheel()
    _test_wheel_routing()
    _test_app()


if __name__ == "__main__":
    main()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  FAIL: {f}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
