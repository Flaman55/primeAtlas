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
     exclusion is left to that widget.
B. The app: every page uses it -- Primes (Storage, primesieve, Primality), Constellations
   (Storage, Calculator, Records), Research (five sub-tabs), Benchmark, About, the three
   Settings sub-tabs, Generation and the visualization tabs; the three old copies of the
   canvas/scrollbar code are gone; at 1050x680 each shown page has its scrollbar exactly
   when its content is taller than the viewport, and the Benchmark page fits; in a short
   window the About page scrolls and keeps the NOTICE box at its natural height.

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


def _test_app():
    print("\n--- B2. the app ---")
    import tkinter.messagebox as messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    import prime_atlas_v2
    sys.argv = ["prime_atlas_v2.py"]
    app = prime_atlas_v2._build_gui()()
    try:
        deadline = time.time() + 8
        while not app.main_notebook.winfo_ismapped() and time.time() < deadline:
            app.update()
            time.sleep(0.05)
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
            check(not bench.scrolls(), "Benchmark fits the default 1050x680 window "
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


def main():
    _test_page()
    _test_sources()
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
