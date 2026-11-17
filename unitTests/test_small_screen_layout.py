"""Every tab fits a small screen: FHD 13" at 150 % gives the app a 1280 x 720 window.

For Polish and English, at font scale 100 % and 125 %, the real app (empty temp storage,
each configuration in its own process, since the language is read once at import) is sized
to 1280 x 720 and every notebook tab, nested ones too, is selected in turn. No control on a
selected tab may:
  - end past the window's right edge, or past the right edge of the canvas it scrolls in;
  - be narrower than it asks for (its text cut by the geometry manager);
  - be packed but left unmapped while its parent is shown (squeezed out of its row).
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
CONFIGS = [("pl", 100), ("pl", 125), ("en", 100), ("en", 125)]
CHILD_TIMEOUT_S = 600


def _child(lang, font_scale):
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
    app.geometry(f"{WIDTH}x{HEIGHT}+0+0")
    deadline = time.time() + 60
    while not app.main_notebook.winfo_ismapped() and time.time() < deadline:
        app.update()
        time.sleep(0.05)
    for _ in range(20):
        app.update()
    right = app.winfo_rootx() + app.winfo_width()
    problems = {}

    def scan(trail):
        app.update()
        for w in walk(app):
            if not isinstance(w, leaves):
                continue
            if not shown(w):
                try:
                    squeezed_out = (w.winfo_manager() == "pack" and shown(w.master)
                                    and w in w.master.pack_slaves())
                except tk.TclError:
                    squeezed_out = False
                if squeezed_out:
                    problems.setdefault(str(w), (trail, text_of(w), "hidden"))
                continue
            edge, p = right, w.master
            while p is not None:
                if isinstance(p, tk.Canvas):
                    edge = min(edge, p.winfo_rootx() + p.winfo_width())
                    break
                p = p.master
            over = w.winfo_rootx() + w.winfo_width() - edge
            cut = w.winfo_reqwidth() - w.winfo_width()
            if over > 0:
                problems.setdefault(str(w), (trail, text_of(w), f"{over} px past the edge"))
            elif cut > 2:
                problems.setdefault(str(w), (trail, text_of(w), f"{cut} px cut"))

    def outer_book(w, container):
        p = w.master
        while p is not None and p is not container:
            if isinstance(p, ttk.Notebook):
                return p
            p = p.master
        return None

    visited = []

    def visit(container, trail):
        books = [w for w in walk(container)
                 if isinstance(w, ttk.Notebook) and outer_book(w, container) is None]
        for nb in books:
            for tab in nb.tabs():
                key = trail + (nb.tab(tab, "text"),)
                visited.append(key)
                nb.select(tab)
                for _ in range(5):
                    app.update()
                scan(key)
                visit(nb.nametowidget(tab), key)

    visit(app, ())
    print(f"TABS {len(visited)}")
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
    for lang, font_scale in CONFIGS:
        label = f"{lang}, font {font_scale} %, {WIDTH}x{HEIGHT}"
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", lang,
                               str(font_scale)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env,
                              timeout=CHILD_TIMEOUT_S)
        lines = proc.stdout.splitlines()
        tabs = [int(line.split()[1]) for line in lines if line.startswith("TABS ")]
        check(proc.returncode == 0 and tabs and tabs[0] > 20,
              f"{label}: the app ran and every tab was visited ({tabs[0] if tabs else 0})")
        if proc.returncode != 0:
            print(proc.stderr[-2000:])
        found = [line[len("PROBLEM "):] for line in lines if line.startswith("PROBLEM ")]
        for item in found:
            print("      " + item.encode("ascii", "backslashreplace").decode("ascii"))
        check(not found, f"{label}: no control past the edge, cut or squeezed out")
    print("=" * 78)
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        _child(sys.argv[2], int(sys.argv[3]))
    else:
        raise SystemExit(main())
