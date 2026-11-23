"""The remembered layout (primeatlas/core/layout_memory.py) on plain Tk widgets.

Every height grip, terminal, remembered sash and the main window keep their layout in the
remembered-fields store (ui_state.json) under "layout." keys, saved on the person's own
action and restored when the widget is built; "reset" brings back the defaults of
primeatlas/core/layout_const.py. Checks:
  1. a grip with a place starts at its default from layout_const (lines, or px for a chart);
  2. a drag changes the height by whole steps from the first step on, both ways, clamped
     to [min, max]; a chart (Canvas) steps by CHART_STEP_PX pixels;
  3. the value is saved on release under layout.grip.<place>; a drag ending on the value it
     started from saves nothing;
  4. a new grip of the same place restores the saved value; a value out of [min, max] is
     clamped, a value of another type or a corrupt file gives the default;
  5. a grip whose target is rebuilt (callable target) gives the new widget its value
     (apply());
  6. a terminal's shown/hidden state is saved when the person toggles it and restored when
     it is built again; showing it from code (a run starting) saves nothing;
  7. a remembered sash keeps the share saved on release; a share outside (0, 1) or of
     another type gives the default;
  8. the main window: no saved state opens it maximized; a normal window's size and
     position and a maximized state are saved on the window's own <Configure>, no timer;
     minimized saves nothing; a saved size larger than the screen is clamped, narrower
     than the minimum width is widened, a position off every screen opens it at the
     default place; a corrupt value gives the default;
  9. reset_layout(): removes every layout.* key and no other, puts every live grip,
     terminal, sash and the window back to its default at once; a second reset with
     nothing changed writes nothing;
 10. the store's remove_prefix() removes only keys starting with the prefix and writes
     only when it removed one.
Windows, real display:
    python unitTests/test_layout_memory.py
"""
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "prime_sieve"), os.path.join(ROOT, "constellation")]

import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402

from primeatlas.core import layout_const, layout_memory, ui_state_dynamic  # noqa: E402
from primeatlas.core.ui_state_store import UiStateStore  # noqa: E402
from primeatlas.core.widgets import HeightGrip, keep_sash_share  # noqa: E402
from primeatlas.generation.generation_console import GenerationConsole  # noqa: E402

failures = []
WORK = tempfile.mkdtemp(prefix="primeatlas_layout_memory_")


def check(condition, message):
    if condition:
        print(f"ok:   {message}")
    else:
        failures.append(message)
        print(f"FAIL: {message}")


class FakeEvent:
    def __init__(self, y_root):
        self.y_root = y_root


def pump(root, seconds=0.2):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def new_store(name, data=None):
    path = os.path.join(WORK, name)
    if data is not None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))
    store = UiStateStore(path)
    ui_state_dynamic.STORE = store
    return store


def file_data(store):
    store.flush()
    if not os.path.exists(store.path):
        return {}
    with open(store.path, encoding="utf-8") as f:
        return json.load(f)


def drag(grip, steps):
    """Press, move by `steps` grip steps, release."""
    unit = grip.line_height()
    grip._on_press(FakeEvent(1000))
    grip._on_drag(FakeEvent(1000 + steps * unit))
    grip._on_release(FakeEvent(1000 + steps * unit))


def height(widget):
    return int(widget.cget("height"))


def test_grip_lines(root):
    print("\n--- grips on lines: default, drag, save, restore ---")
    place = "test.list"
    layout_const.GRIPS[place] = (7, 3, 20)
    store = new_store("grips.json")
    box = tk.Listbox(root)
    box.pack()
    grip = HeightGrip(root, box, place=place, after=box)
    check(height(box) == 7, f"1: starts at the default 7 lines (got {height(box)})")
    unit = grip.line_height()
    grip._on_press(FakeEvent(500))
    grip._on_drag(FakeEvent(500 + unit))
    check(height(box) == 8, f"2: one step down = +1 line at once (got {height(box)})")
    grip._on_drag(FakeEvent(500 - 2 * unit))
    check(height(box) == 5, f"2: two steps up from the start = -2 lines (got {height(box)})")
    grip._on_drag(FakeEvent(500 - 100 * unit))
    check(height(box) == 3, f"2: far up clamps to min 3 (got {height(box)})")
    grip._on_drag(FakeEvent(500 + 100 * unit))
    check(height(box) == 20, f"2: far down clamps to max 20 (got {height(box)})")
    grip._on_release(FakeEvent(0))
    check(file_data(store).get(f"layout.grip.{place}") == 20,
          "3: release saves the value under layout.grip.<place>")
    store.dirty = False
    drag(grip, 0)
    check(not store.dirty and store.get(f"layout.grip.{place}") == 20,
          "3: a drag ending where it started saves nothing")
    drag(grip, 7 - 20)
    check(not file_data(store).get(f"layout.grip.{place}"),
          "3: a drag back to the default removes the key (a default is never stored)")
    drag(grip, 13)

    box2 = tk.Listbox(root)
    box2.pack()
    HeightGrip(root, box2, place=place, after=box2)
    check(height(box2) == 20, f"4: a new grip of the place restores 20 (got {height(box2)})")
    for stored, expected, what in ((99, 20, "above max clamps to max"),
                                   (1, 3, "below min clamps to min"),
                                   ("12", 7, "a string gives the default"),
                                   (4.5, 7, "a float gives the default"),
                                   (True, 7, "a bool gives the default")):
        store.set(f"layout.grip.{place}", stored)
        other = tk.Listbox(root)
        other.pack()
        HeightGrip(root, other, place=place, after=other)
        check(height(other) == expected, f"4: {what} ({stored!r} -> {height(other)})")
    corrupt = new_store("corrupt.json", "{not json")
    other = tk.Listbox(root)
    other.pack()
    HeightGrip(root, other, place=place, after=other)
    check(height(other) == 7 and not corrupt.dirty,
          "4: a corrupt file gives the default and is not rewritten by building a grip")

    new_store("rebuild.json")
    holder = {"w": tk.Listbox(root)}
    holder["w"].pack()
    rebuilt = HeightGrip(root, lambda: holder["w"], place=place)
    drag(rebuilt, 4)
    holder["w"].destroy()
    holder["w"] = tk.Listbox(root, height=3)
    holder["w"].pack()
    rebuilt.apply()
    check(height(holder["w"]) == 11,
          f"5: a rebuilt target gets the grip's value from apply() (got {height(holder['w'])})")


def test_grip_chart(root):
    print("\n--- grips on charts (Canvas, pixels) ---")
    place = "test.chart"
    layout_const.GRIPS[place] = (layout_const.CHART_HEIGHT_PX, layout_const.CHART_MIN_PX,
                                 layout_const.CHART_MAX_PX)
    store = new_store("chart.json")
    canvas = tk.Canvas(root, height=50)
    canvas.pack()
    grip = HeightGrip(root, canvas, place=place, after=canvas)
    check(height(canvas) == layout_const.CHART_HEIGHT_PX,
          f"1: a chart starts at CHART_HEIGHT_PX (got {height(canvas)})")
    check(grip.line_height() == layout_const.CHART_STEP_PX,
          "2: a chart grip steps by CHART_STEP_PX")
    drag(grip, 3)
    check(height(canvas) == layout_const.CHART_HEIGHT_PX + 3 * layout_const.CHART_STEP_PX,
          f"2: three steps = +{3 * layout_const.CHART_STEP_PX} px (got {height(canvas)})")
    drag(grip, -10_000)
    check(height(canvas) == layout_const.CHART_MIN_PX, "2: far up clamps to CHART_MIN_PX")
    drag(grip, 10_000)
    check(height(canvas) == layout_const.CHART_MAX_PX, "2: far down clamps to CHART_MAX_PX")
    check(store.get(f"layout.grip.{place}") == layout_const.CHART_MAX_PX,
          "3: the chart height is saved in px")


def test_console(root):
    print("\n--- terminal shown/hidden ---")
    place = "test.console"
    layout_const.GRIPS[f"console.{place}"] = (10, 3, 200)
    store = new_store("console.json")
    T = lambda key, **_k: key  # noqa: E731
    frame = ttk.Frame(root)
    frame.pack()
    console = GenerationConsole(frame, T, place=place)
    check(not console._visible, "6: a terminal with nothing saved starts hidden")
    console.show()
    check(not store.has(f"layout.console.{place}"), "6: show() from code saves nothing")
    console.hide()
    console.toggle()
    check(store.get(f"layout.console.{place}") is True, "6: the person's toggle saves shown")
    again = GenerationConsole(ttk.Frame(root), T, place=place)
    check(again._visible, "6: a terminal built again comes back shown")
    again.toggle()
    check(not store.has(f"layout.console.{place}"),
          "6: toggling back to the start state (hidden) removes the key")
    third = GenerationConsole(ttk.Frame(root), T, place=place, start_visible=True)
    check(third._visible, "6: with nothing saved start_visible=True shows it")
    third.toggle()
    check(store.get(f"layout.console.{place}") is False,
          "6: hiding a terminal that starts shown saves hidden")
    fourth = GenerationConsole(ttk.Frame(root), T, place=place, start_visible=True)
    check(not fourth._visible, "6: a saved hidden state wins over start_visible")
    drag(third.height_grip, 2)
    check(store.get(f"layout.grip.console.{place}") == 12,
          "6: the terminal's grip saves under layout.grip.console.<place>")


def test_sash(root):
    print("\n--- remembered sash ---")
    place = "test.paned"
    layout_const.SASH_SHARES[place] = 0.4
    store = new_store("sash.json")
    win = tk.Toplevel(root)
    win.geometry("800x200+0+0")

    def build():
        paned = ttk.Panedwindow(win, orient="horizontal")
        paned.pack(fill="both", expand=True)
        paned.add(ttk.Frame(paned, width=100), weight=1)
        paned.add(ttk.Frame(paned, width=100), weight=1)
        keep_sash_share(paned, None, 50, place=place)
        return paned

    paned = build()
    pump(root, 0.5)
    check(abs(paned.sashpos(0) - 0.4 * paned.winfo_width()) <= 3,
          f"7: starts at the default share 0.4 ({paned.sashpos(0)} of {paned.winfo_width()})")
    paned.sashpos(0, 600)
    paned.event_generate("<ButtonRelease-1>")
    pump(root, 0.3)
    saved = store.get(f"layout.sash.{place}")
    check(isinstance(saved, float) and abs(saved - 600 / paned.winfo_width()) < 0.01,
          f"7: release saves the share ({saved})")
    paned.destroy()
    paned = build()
    pump(root, 0.5)
    check(abs(paned.sashpos(0) - 600) <= 3, f"7: built again at the saved share ({paned.sashpos(0)})")
    for stored in (1.5, 0.0, -0.2, "0.5", True):
        store.set(f"layout.sash.{place}", stored)
        paned.destroy()
        paned = build()
        pump(root, 0.4)
        check(abs(paned.sashpos(0) - 0.4 * paned.winfo_width()) <= 3,
              f"7: a saved {stored!r} gives the default share")
    win.destroy()


def root_width():
    return tk._default_root.winfo_screenwidth()


def _window(store_name, data=None):
    store = new_store(store_name, data)
    win = tk.Toplevel()
    layout_memory.remember_window(win, min_width=800)
    pump(win, 0.6)
    return store, win


def test_window():
    print("\n--- main window ---")
    store, win = _window("window_default.json")
    check(win.state() == "zoomed", f"8: no saved state opens maximized (got {win.state()})")
    check(not store.has("layout.window.state") and not store.has("layout.window.geometry"),
          "8: opening at the default saves nothing (a default value is never stored)")
    win.state("normal")
    win.geometry("900x600+40+50")
    pump(win, 0.6)
    check(store.get("layout.window.state") == "normal"
          and store.get("layout.window.geometry") == "900x600+40+50",
          f"8: a normal window saves size and position ({store.get('layout.window.geometry')})")
    win.state("zoomed")
    pump(win, 0.6)
    check(not store.has("layout.window.state")
          and store.get("layout.window.geometry") == "900x600+40+50",
          "8: maximizing saves the state (the default: no key) and keeps the last normal "
          "geometry")
    win.state("normal")
    pump(win, 0.6)
    store.dirty = False
    win.iconify()
    pump(win, 0.6)
    check(store.get("layout.window.state") == "normal", "8: minimizing saves nothing")
    jobs = set(win.tk.call("after", "info"))
    check(not jobs, f"8: no timer runs for the window ({len(jobs)} after jobs)")
    file_data(store)
    win.destroy()

    _store, win = _window("window_saved.json", {"layout.window.state": "normal",
                                               "layout.window.geometry": "900x600+40+50"})
    check(win.state() == "normal" and win.winfo_width() == 900 and win.winfo_height() == 600
          and abs(win.winfo_x() - 40) <= 10, f"8: restored as saved ({win.wm_geometry()})")
    win.destroy()

    big = f"{root_width() * 3}x{root_width() * 3}+0+0"
    _store, win = _window("window_big.json", {"layout.window.state": "normal",
                                             "layout.window.geometry": big})
    _x, _y, area_w, area_h = layout_memory.screen_area(win)
    check(win.winfo_width() <= area_w and win.winfo_height() <= area_h,
          f"8: a size larger than the screen is clamped ({win.wm_geometry()}, screen "
          f"{area_w}x{area_h})")
    win.destroy()

    _store, win = _window("window_narrow.json", {"layout.window.state": "normal",
                                                "layout.window.geometry": "300x400+10+10"})
    check(win.winfo_width() >= 800, f"8: narrower than the minimum is widened ({win.winfo_width()})")
    win.destroy()

    _store, win = _window("window_off.json", {"layout.window.state": "normal",
                                             "layout.window.geometry": "900x600+60000+60000"})
    check(win.winfo_x() < 20000 and win.winfo_y() < 20000,
          f"8: a position off every screen opens at the default place ({win.wm_geometry()})")
    win.destroy()

    for data in ({"layout.window.state": "iconic"}, {"layout.window.state": 7},
                 {"layout.window.state": "normal", "layout.window.geometry": "big"}):
        _store, win = _window("window_bad.json", data)
        ok = win.state() == "zoomed" if data.get("layout.window.state") != "normal" else (
            win.winfo_width() == layout_const.WINDOW_SIZE[0])
        check(ok, f"8: a corrupt value {data} gives the default ({win.state()} {win.wm_geometry()})")
        win.destroy()


def test_reset(root):
    print("\n--- reset_layout ---")
    layout_const.GRIPS["test.reset"] = (6, 3, 30)
    layout_const.GRIPS["console.test.reset"] = (10, 3, 200)
    layout_const.SASH_SHARES["test.reset"] = 0.3
    store = new_store("reset.json", {"form.field": "keep me"})
    box = tk.Listbox(root)
    box.pack()
    grip = HeightGrip(root, box, place="test.reset", after=box)
    T = lambda key, **_k: key  # noqa: E731
    console = GenerationConsole(ttk.Frame(root), T, place="test.reset")
    win = tk.Toplevel(root)
    win.geometry("700x200+0+0")
    paned = ttk.Panedwindow(win, orient="horizontal")
    paned.pack(fill="both", expand=True)
    paned.add(ttk.Frame(paned, width=100), weight=1)
    paned.add(ttk.Frame(paned, width=100), weight=1)
    keep_sash_share(paned, None, 50, place="test.reset")
    main = tk.Toplevel(root)
    layout_memory.remember_window(main, min_width=800)
    pump(root, 0.5)
    drag(grip, 9)
    console.toggle()
    paned.sashpos(0, 500)
    paned.event_generate("<ButtonRelease-1>")
    main.state("normal")
    main.geometry("900x600+40+50")
    pump(root, 0.6)
    check(len([k for k in store._data if k.startswith("layout.")]) >= 4,
          "9: (precondition) grip, terminal, sash and window were saved")
    layout_memory.reset_layout()
    pump(root, 0.6)
    data = file_data(store)
    check(not [k for k in data if k.startswith("layout.")],
          f"9: every layout.* key is removed and the defaults put back store nothing "
          f"({sorted(data)})")
    check(data.get("form.field") == "keep me", "9: other keys stay")
    check(height(box) == 6, f"9: the grip is back at its default 6 (got {height(box)})")
    check(not console._visible, "9: the terminal is back hidden")
    check(abs(paned.sashpos(0) - 0.3 * paned.winfo_width()) <= 3,
          f"9: the sash is back at 0.3 ({paned.sashpos(0)} of {paned.winfo_width()})")
    check(main.state() == "zoomed", f"9: the window is back maximized ({main.state()})")
    store.flush()
    store.dirty = False
    before = os.path.getmtime(store.path)
    layout_memory.reset_layout()
    pump(root, 0.6)
    store.flush()
    check(not store.dirty and os.path.getmtime(store.path) == before,
          "9: a second reset with nothing changed writes nothing")
    win.destroy()
    main.destroy()


def test_remove_prefix():
    print("\n--- store.remove_prefix ---")
    store = UiStateStore(os.path.join(WORK, "prefix.json"))
    store.set("layout.a", 1)
    store.set("layoutx", 2)
    store.set("b", 3)
    store.flush()
    check(store.remove_prefix("layout.") == 1 and not store.has("layout.a")
          and store.has("layoutx") and store.has("b"), "10: removes only layout.* keys")
    store.flush()
    store.dirty = False
    check(store.remove_prefix("layout.") == 0 and not store.dirty,
          "10: nothing to remove writes nothing")


def main():
    root = tk.Tk()
    root.geometry("400x300+0+0")
    try:
        test_grip_lines(root)
        test_grip_chart(root)
        test_console(root)
        test_sash(root)
        test_window()
        test_reset(root)
        test_remove_prefix()
    finally:
        root.destroy()
        shutil.rmtree(WORK, ignore_errors=True)
    print("=" * 78)
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
