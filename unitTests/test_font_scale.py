"""The font scale kept across display changes (primeatlas/core/font_scale.py).

The font scale multiplies `tk scaling` (pixels per point). Tk sets `tk scaling` back to the
system's value when Windows sends WM_DISPLAYCHANGE (a monitor woken up, a resolution change),
so widgets measured after it come out smaller. Checks:
  1. apply(root, percent) remembers the base read from the system and sets base * percent;
  2. after a reset nothing runs while the app gets no event: no scheduled job, the scaling
     stays as Tk left it;
     a layout pass (responsive.py), activating a window, and a key or mouse press check it;
  3. a check after a reset reads the base again and sets new base * percent: a ttk widget
     built during the reset (measured under the system's scaling) gets the size of one built
     before the reset; a reset to another
     base (a real DPI change) gives that base * percent;
  4. the pass that finds the reset lays out under the restored scaling: a widget built in
     that pass has the size of one built before the reset;
  5. named fonts have the same pixel size after the restore as before the reset;
  6. a window built after a press that found the reset has widgets of the sizes of one built
     before the reset;
  7. a check with nothing changed touches nothing (no theme change event);
  8. repeated resets are each restored once, the scaling never multiplied twice;
  9. at 100 % nothing is set up and a check does nothing.
Windows, real display (check 2's WM_DISPLAYCHANGE is skipped elsewhere, a reset is set by
hand there):
    python unitTests/test_font_scale.py
"""
import ctypes
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from primeatlas.core import font_scale, responsive

failures = []
CHILD_TIMEOUT_S = 120


def check(condition, message):
    if condition:
        print(f"ok:   {message}")
    else:
        failures.append(message)
        print(f"FAIL: {message}")


def scaling(root):
    return float(root.tk.call("tk", "scaling"))


def close(a, b):
    """Tk keeps `tk scaling` rounded, so a set value reads back a little different."""
    return abs(a - b) <= 0.005 * b


def pump(root, seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def reset(root, base):
    """What Tk does on a display change: `tk scaling` back to the system's value."""
    if sys.platform == "win32":
        ctypes.windll.user32.SendMessageW(int(root.wm_frame(), 16), 0x7E, 0, 0)  # WM_DISPLAYCHANGE
        pump(root, 0.1)
        if close(scaling(root), base):
            return
    root.tk.call("tk", "scaling", base)


def new_root():
    root = tk.Tk()
    root.geometry("400x300+0+0")
    ttk.Style(root).theme_use("clam")
    return root


def sizes(widgets):
    return [(w.winfo_reqwidth(), w.winfo_reqheight()) for w in widgets]


def build(parent):
    """A ttk radiobutton, spinbox and a label with a point-sized tuple font."""
    widgets = [ttk.Radiobutton(parent, text="Floor only", value=1),
               ttk.Spinbox(parent, from_=0, to=9, width=6),
               ttk.Label(parent, text="Threads:", font=("Segoe UI", 9))]
    for w in widgets:
        w.pack()
    return widgets


def test_apply_and_idle():
    root = new_root()
    base = scaling(root)
    font_scale.apply(root, 125)
    check(close(scaling(root), base * 1.25), "1: apply sets base * 125 %")
    jobs = set(root.tk.call("after", "info"))
    reset(root, base)
    pump(root, 0.6)
    check(close(scaling(root), base), "2: with no event after the reset the scaling stays")
    check(set(root.tk.call("after", "info")) == jobs, "2: no job is scheduled for it")
    root.destroy()


def test_triggers():
    root = new_root()
    base = scaling(root)
    font_scale.apply(root, 125)
    entry = ttk.Entry(root)
    entry.pack()
    entry.focus_force()
    pump(root)
    for name, fire in (("activating the window", lambda: root.event_generate("<Activate>")),
                       ("a key press", lambda: entry.event_generate("<KeyPress>", keysym="a")),
                       ("a mouse press", lambda: entry.event_generate("<ButtonPress-1>",
                                                                      x=2, y=2))):
        reset(root, base)
        fire()
        pump(root, 0.1)
        check(close(scaling(root), base * 1.25), f"2: {name} restores the scaling")
    root.destroy()


def test_restore_sizes_and_fonts():
    root = new_root()
    base = scaling(root)
    font_scale.apply(root, 125)
    before = sizes(build(root))
    pump(root)
    fonts = {n: tkfont.nametofont(n, root=root).metrics("linespace") for n in tkfont.names(root)}
    reset(root, base)
    widgets = build(root)
    pump(root, 0.1)
    shrunk = sizes(widgets)
    font_scale.check(root)
    pump(root, 0.1)
    check(shrunk != before, "3: (precondition) widgets measured during the reset shrank")
    check(sizes(widgets) == before,
          f"3: after the check they have their size back ({before} -> {sizes(widgets)})")
    after = {n: tkfont.nametofont(n, root=root).metrics("linespace") for n in tkfont.names(root)}
    check(after == fonts, "5: named fonts keep their pixel size")
    other = base * 1.5
    root.tk.call("tk", "scaling", other)
    font_scale.check(root)
    check(close(scaling(root), other * 1.25), "3: a reset to another base gives that base * 125 %")
    root.destroy()


def test_layout_pass():
    root = new_root()
    base = scaling(root)
    font_scale.apply(root, 125)
    frame = ttk.Frame(root)
    frame.pack(fill="x")
    seen = []

    def layout(_width):
        for child in frame.winfo_children():
            child.destroy()
        seen.append(sizes(build(frame)))

    item = responsive.coordinator(root).add(frame, layout, key=lambda: len(seen))
    pump(root)
    before = seen[-1]
    seen.clear()
    reset(root, base)
    item.last = None
    item.request()
    pump(root)
    check(close(scaling(root), base * 1.25), "2: a layout pass restores the scaling")
    check(bool(seen) and seen[0] == before,
          f"4: the pass that finds the reset measures as before ({before} -> {seen[:1]})")
    root.destroy()


def test_new_window():
    root = new_root()
    base = scaling(root)
    font_scale.apply(root, 125)
    entry = ttk.Entry(root)
    entry.pack()
    first = tk.Toplevel(root)
    before = sizes(build(first))
    pump(root)
    reset(root, base)
    entry.event_generate("<ButtonPress-1>", x=2, y=2)
    second = tk.Toplevel(root)
    built = build(second)
    pump(root)
    check(sizes(built) == before,
          f"6: a window built after the press has the sizes of one built before "
          f"({before} -> {sizes(built)})")
    root.destroy()


def test_nothing_changed_and_repeats():
    root = new_root()
    base = scaling(root)
    font_scale.apply(root, 125)
    label = ttk.Label(root, text="x")
    label.pack()
    events = []
    label.bind("<<ThemeChanged>>", lambda _e: events.append(1))
    pump(root)
    events.clear()
    font_scale.check(root)
    pump(root, 0.1)
    check(not events and close(scaling(root), base * 1.25),
          "7: a check with nothing changed touches nothing")
    for _ in range(3):
        reset(root, base)
        font_scale.check(root)
        font_scale.check(root)
    check(close(scaling(root), base * 1.25), "8: repeated resets end at base * 125 %, not more")
    root.destroy()


def test_hundred_percent():
    root = new_root()
    base = scaling(root)
    font_scale.apply(root, 100)
    check(close(scaling(root), base), "9: at 100 % the scaling is not changed")
    check(not root.bind_class("Tk", "<Activate>"), "9: at 100 % nothing is bound")
    root.tk.call("tk", "scaling", base * 0.9)
    font_scale.check(root)
    check(close(scaling(root), base * 0.9), "9: at 100 % a check does nothing")
    root.destroy()


TESTS = [test_apply_and_idle, test_triggers, test_restore_sizes_and_fonts, test_layout_pass,
         test_new_window, test_nothing_changed_and_repeats, test_hundred_percent]


def main():
    # Each test in its own process: `tk scaling` and Tk's fonts carry over between roots.
    for test in TESTS:
        proc = subprocess.run([sys.executable, __file__, "--one", test.__name__],
                              capture_output=True, text=True, timeout=CHILD_TIMEOUT_S)
        print(proc.stdout, end="")
        failures.extend(line for line in proc.stdout.splitlines() if line.startswith("FAIL"))
        if proc.returncode != 0:
            print(proc.stderr[-2000:])
            failures.append(f"{test.__name__} ran")
    print("=" * 78)
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--one":
        globals()[sys.argv[2]]()
    else:
        raise SystemExit(main())
