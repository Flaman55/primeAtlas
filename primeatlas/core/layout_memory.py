"""
layout_memory.py -- the remembered layout: grip heights, terminals shown or hidden, sash
shares and the main window, kept in the remembered-fields store (ui_state.json,
ui_state_dynamic.STORE) under "layout." keys.

A value is saved on the person's own action (a grip or sash released, a terminal toggled,
the window resized, moved, maximized) and restored when its widget is built. A value
equal to its default is never stored (its key is removed), so a layout back at the
defaults leaves no key and reset_layout() has nothing to write the second time. Defaults
live in layout_const.py. Nothing polls: the window is saved from its own <Configure>.

HeightGrip (widgets.py), GenerationConsole and keep_sash_share() take a `place` naming
their layout_const entry; each registers itself here so reset_layout() can put every live
one back to its default.
"""
import re
import sys
import tkinter as tk
import weakref

from primeatlas.core import layout_const

PREFIX = "layout."
KEY_WINDOW_STATE = "layout.window.state"
KEY_WINDOW_GEOMETRY = "layout.window.geometry"

_live = weakref.WeakSet()
_GEOMETRY = re.compile(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$")
# A saved position counts as on screen while this much of the window's top-left corner
# area lies inside the screen. Arbitrary: enough to grab the title bar.
_ON_SCREEN_MARGIN = (120, 40)


def _store():
    from primeatlas.core import ui_state_dynamic
    return ui_state_dynamic.STORE


def register(item):
    """`item.reset_layout()` is called by reset_layout() while `item` lives."""
    _live.add(item)


def grip_key(place):
    return f"{PREFIX}grip.{place}"


def console_key(place):
    return f"{PREFIX}console.{place}"


def sash_key(place):
    return f"{PREFIX}sash.{place}"


def save(key, value, default):
    """Stores `value`, or removes the key when it is the default."""
    if type(value) is type(default) and value == default:
        _store().remove(key)
    else:
        _store().set(key, value)


def load_int(key, default, low, high):
    """The stored int clamped to [low, high]; the default when missing or of another type."""
    value = _store().get(key)
    if type(value) is not int:
        return default
    return max(low, min(high, value))


def load_bool(key, default):
    value = _store().get(key)
    return value if type(value) is bool else default


def load_share(key, default):
    """A stored float strictly between 0 and 1, else the default."""
    value = _store().get(key)
    return value if type(value) is float and 0.0 < value < 1.0 else default


def reset_layout():
    """Removes every layout.* key and puts every live grip, terminal, sash and the window
    back to its default."""
    _store().remove_prefix(PREFIX)
    for item in list(_live):
        try:
            item.reset_layout()
        except tk.TclError:  # its widget is destroyed
            _live.discard(item)


def screen_area(widget):
    """(x, y, width, height) of the whole desktop, every monitor included on Windows."""
    if sys.platform == "win32":
        try:
            import ctypes
            metrics = ctypes.windll.user32.GetSystemMetrics
            area = tuple(metrics(i) for i in (76, 77, 78, 79))  # SM_*VIRTUALSCREEN
            if area[2] > 0 and area[3] > 0:
                return area
        except (AttributeError, OSError):
            pass
    return 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()


def remember_window(win, min_width):
    """Restores the main window's saved size, position and state (or the default: maximized)
    and saves them from the window's <Configure> from then on."""
    keeper = _WindowKeeper(win, min_width)
    win._layout_window = keeper
    register(keeper)
    return keeper


class _WindowKeeper:
    def __init__(self, win, min_width):
        self.win = win
        self.min_width = min_width
        geometry = _store().get(KEY_WINDOW_GEOMETRY)
        state = _store().get(KEY_WINDOW_STATE)
        self._apply(self._normal_geometry(geometry), "normal" if state == "normal"
                    else layout_const.WINDOW_STATE)
        win.bind("<Configure>", self._on_configure, add="+")

    def _normal_geometry(self, saved):
        """The normal geometry: "WxH+X+Y" from the saved value clamped to the screen, "WxH" without a usable
        position, the default size without a usable value."""
        width, height = layout_const.WINDOW_SIZE
        position = None
        match = _GEOMETRY.match(saved) if isinstance(saved, str) else None
        if match:
            width, height, x, y = (int(g) for g in match.groups())
            position = (x, y)
        ax, ay, aw, ah = screen_area(self.win)
        width = max(min(self.min_width, aw), min(width, aw))
        height = min(height, ah)
        if position is not None:
            x, y = position
            mx, my = _ON_SCREEN_MARGIN
            if ax - mx <= x <= ax + aw - mx and ay - my <= y <= ay + ah - my:
                return f"{width}x{height}+{x}+{y}"
        return f"{width}x{height}"

    def _apply(self, geometry, state):
        """Maximizes before the geometry, so it becomes the size the window returns to and
        no normal-state <Configure> saves it."""
        if state == "zoomed":
            self.win.state("zoomed")
            self.win.geometry(geometry)
        else:
            self.win.geometry(geometry)
            self.win.state("normal")

    def _on_configure(self, event):
        if event.widget is not self.win:
            return
        state = self.win.state()
        if state == "zoomed":
            save(KEY_WINDOW_STATE, "zoomed", layout_const.WINDOW_STATE)
        elif state == "normal":
            save(KEY_WINDOW_STATE, "normal", layout_const.WINDOW_STATE)
            _store().set(KEY_WINDOW_GEOMETRY, self.win.wm_geometry())

    def reset_layout(self):
        self._apply(self._normal_geometry(None), layout_const.WINDOW_STATE)
