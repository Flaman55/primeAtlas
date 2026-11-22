"""Every tab fits a small screen: FHD 13" at 150 % gives the app a 1280 x 720 window.

For Polish and English, at font scale 100 % and 125 %, the real app (empty temp storage,
each configuration in its own process, since the language is read once at import) is sized
to 1280 x 720 and every notebook tab, nested ones too, is selected in turn. Polish at 100 %
and English at 125 % (the longest texts) also go through the widths of the layout map,
1920, 1280, 1000 and 800 px, and back to 1920: each tab then shows every control where it
was at the first 1920 px visit (every tab is shown once before, so the reads a tab starts
when first shown have finished; a tab whose texts still changed between the visits is
listed and left out of that comparison). The app's window can be made as narrow as
NARROWEST, the narrowest width of the layout map, and no narrower, and it takes every width
of the map it is given (one over the screen's is capped at about the screen's). No control
on a selected tab may:
  - end past the window's right edge, or past the right edge of the canvas it scrolls in;
  - be narrower than it asks for (its text cut by the geometry manager);
  - be packed but left unmapped while its parent is shown (squeezed out of its row);
and no pane of a shown panedwindow may be narrower than MIN_PANE_PX (squeezed out of view).
Closed collapsible sections, separate windows and views that appear only with data in the
storage are not visited.
Windows, real display:
    python unitTests/test_small_screen_layout.py
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIDTH, HEIGHT = 1280, 720
CONFIGS = [("pl", 100, (WIDTH,)), ("pl", 125, (WIDTH,)), ("en", 100, (WIDTH,)),
           ("en", 125, (WIDTH,)), ("pl", 100, (1920, 1280, 1000, 800, 1920)),
           ("en", 125, (1920, 1280, 1000, 800, 1920))]
CHILD_TIMEOUT_S = 900
# Narrowest width of the layout map: the app window's minimum width.
NARROWEST = 800
# Narrowest pane counted as in view; arbitrary, a few characters.
MIN_PANE_PX = 40


def _child(lang, font_scale, widths):
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
    sys.path.insert(0, os.path.join(ROOT, "constellation"))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import tkinter as tk
    from tkinter import messagebox, ttk
    for name in ("showinfo", "showerror", "showwarning"):
        setattr(messagebox, name, lambda *a, **k: None)
    from primeatlas.core import app_settings, i18n
    i18n.save_language = lambda *_a, **_k: None
    app_settings.save_language = i18n.save_language
    app_settings.load_saved_language = lambda: lang
    sys.argv = ["prime_atlas_v2.py"]
    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    from primeatlas.app import app_dynamic
    app_dynamic.APP_SETTINGS.set_font_scale(font_scale)
    leaves = (ttk.Label, ttk.Button, ttk.Radiobutton, ttk.Checkbutton, ttk.Entry,
              ttk.Combobox, ttk.Spinbox, tk.Label, tk.Button, ttk.Scale, ttk.Progressbar)

    def walk(w):
        for c in w.winfo_children():
            yield c
            yield from walk(c)

    def shown(w):
        try:
            return bool(w.winfo_ismapped() and w.winfo_viewable())
        except tk.TclError:
            return False

    def text_of(w):
        for opt in ("text", "textvariable"):
            try:
                v = w.cget(opt)
            except tk.TclError:
                continue
            if v:
                return str(w.getvar(str(v)) if opt == "textvariable" else v)[:60]
        return f"<{w.winfo_class()}>"

    app = prime_atlas_v2._build_gui()()
    from primeatlas.core import responsive

    def settle():
        end = time.time() + 2 * responsive.DEBOUNCE_MS / 1000
        app.update()
        while time.time() < end:
            app.update()
            time.sleep(0.01)
        app.update()

    print(f"MINSIZE {app.minsize()[0]} {min(NARROWEST, app.winfo_screenwidth())}")
    app.geometry(f"{widths[0]}x{HEIGHT}+0+0")
    deadline = time.time() + 60
    while not app.main_notebook.winfo_ismapped() and time.time() < deadline:
        app.update()
        time.sleep(0.05)
    for _ in range(20):
        app.update()
    problems = {}
    places = {}

    def scan(trail, width):
        settle()
        right = app.winfo_rootx() + app.winfo_width()
        if str(width).split(":")[-1].isdigit():
            print(f"WIDTH {str(width).split(':')[-1]} {app.winfo_width()} {app.maxsize()[0]}")
        place = places.setdefault(trail, {})
        for w in walk(app):
            if isinstance(w, ttk.Panedwindow) and shown(w):
                for pane in map(w.nametowidget, w.panes()):
                    if pane.winfo_width() < MIN_PANE_PX:
                        problems.setdefault(str(pane), (trail, f"<pane of {w.winfo_class()}>",
                                                        f"{width} px: pane squeezed to "
                                                        f"{pane.winfo_width()} px"))
            if not isinstance(w, leaves):
                continue
            if not shown(w):
                try:
                    squeezed_out = (w.winfo_manager() == "pack" and shown(w.master)
                                    and w in w.master.pack_slaves())
                except tk.TclError:
                    squeezed_out = False
                if squeezed_out:
                    problems.setdefault(str(w), (trail, text_of(w), f"{width} px: hidden"))
                continue
            place.setdefault(width, {})[str(w)] = (w.winfo_x(), w.winfo_y(), w.winfo_width(),
                                                   w.winfo_height(), text_of(w))
            edge, p = right, w.master
            while p is not None:
                if isinstance(p, tk.Canvas):
                    edge = min(edge, p.winfo_rootx() + p.winfo_width())
                    break
                p = p.master
            over = w.winfo_rootx() + w.winfo_width() - edge
            cut = w.winfo_reqwidth() - w.winfo_width()
            if over > 0:
                problems.setdefault(str(w), (trail, text_of(w),
                                             f"{width} px: {over} px past the edge"))
            elif cut > 2:
                problems.setdefault(str(w), (trail, text_of(w), f"{width} px: {cut} px cut"))

    def outer_book(w, container):
        p = w.master
        while p is not None and p is not container:
            if isinstance(p, ttk.Notebook):
                return p
            p = p.master
        return None

    visited = []

    def visit(container, trail, width):
        books = [w for w in walk(container)
                 if isinstance(w, ttk.Notebook) and outer_book(w, container) is None]
        for nb in books:
            for tab in nb.tabs():
                key = trail + (nb.tab(tab, "text"),)
                visited.append(key)
                nb.select(tab)
                scan(key, width)
                visit(nb.nametowidget(tab), key, width)

    if len(widths) > 1:
        visit(app, (), "warm-up")
        end = time.time() + 5
        while time.time() < end:
            app.update()
            time.sleep(0.05)
        visited.clear()
        places.clear()
        problems.clear()
    for step, width in enumerate(widths):
        if step:
            app.geometry(f"{width}x{HEIGHT}")
            settle()
        visit(app, (), str(step) + ":" + str(width))
    print(f"TABS {len(visited) // len(widths)}")
    if len(widths) > 1:
        first, last = "0:" + str(widths[0]), str(len(widths) - 1) + ":" + str(widths[-1])
        for trail, by_width in places.items():
            before, after = by_width.get(first, {}), by_width.get(last, {})
            # Only controls shown at both visits: an outer tab shows whichever sub-tab
            # was selected last, which differs between the first and the last visit.
            common = sorted(set(before) & set(after))
            if any(before[path][4] != after[path][4] for path in common):
                print(f"CONTENT CHANGED [{' > '.join(trail)}]: not compared")
                continue
            for path in common:
                if before[path] != after[path]:
                    print(f"UNSTABLE [{' > '.join(trail)}] {before.get(path)} -> "
                          f"{after.get(path)} ({path})")
    for path, (trail, text, what) in problems.items():
        print(f"PROBLEM [{' > '.join(trail)}] {text!r}: {what} ({path})")
    app.destroy()


failures = []


def check(condition, message):
    if condition:
        print(f"ok:   {message}")
    else:
        failures.append(message)
        print(f"FAIL: {message}")


def main():
    for lang, font_scale, widths in CONFIGS:
        label = f"{lang}, font {font_scale} %, {' -> '.join(map(str, widths))} x {HEIGHT}"
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            proc = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", lang,
                                   str(font_scale), ",".join(map(str, widths))],
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", env=env, timeout=CHILD_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            check(False, f"{label}: finished within {CHILD_TIMEOUT_S} s")
            continue
        lines = proc.stdout.splitlines()
        tabs = [int(line.split()[1]) for line in lines if line.startswith("TABS ")]
        sizes = [line.split()[1:] for line in lines if line.startswith("MINSIZE ")]
        check(bool(sizes) and sizes[0][0] == sizes[0][1],
              f"{label}: the window's minimum width is {NARROWEST} px (got {sizes})")
        # A width over the screen's is capped by the window manager at about the screen's.
        widths_got = sorted({tuple(map(int, line.split()[1:])) for line in lines
                             if line.startswith("WIDTH ")})
        check(bool(widths_got) and all(got == asked or asked > cap <= got
                                       for asked, got, cap in widths_got),
              f"{label}: the window takes every width of the map (asked, got, screen cap: "
              f"{widths_got})")
        check(proc.returncode == 0 and tabs and tabs[0] > 20,
              f"{label}: the app ran and every tab was visited ({tabs[0] if tabs else 0})")
        if proc.returncode != 0:
            print(proc.stderr[-2000:])
        found = [line[len("PROBLEM "):] for line in lines if line.startswith("PROBLEM ")]
        for item in found:
            print("      " + item.encode("ascii", "backslashreplace").decode("ascii"))
        check(not found, f"{label}: no control past the edge, cut or squeezed out")
        if len(widths) > 1:
            for line in lines:
                if line.startswith("CONTENT CHANGED "):
                    print("      " + line.encode("ascii", "backslashreplace").decode("ascii"))
            moved = [line for line in lines if line.startswith("UNSTABLE ")]
            for item in moved[:40]:
                print("      " + item.encode("ascii", "backslashreplace").decode("ascii"))
            check(not moved, f"{label}: back at {widths[-1]} px every control is where it was")
    print("=" * 78)
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--child":
        _child(sys.argv[2], int(sys.argv[3]), [int(w) for w in sys.argv[4].split(",")])
    else:
        raise SystemExit(main())
