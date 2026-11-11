"""InfoTip -- the app-wide "i" marker next to a field: hovering it shows what the field does.

A small label with the "i" glyph; on <Enter> a borderless Toplevel next to the pointer shows
the text, wrapped to WRAP_PX, until <Leave>, kept inside the app window (moved left, or above
the marker, where it would cross an edge). The text is a callable so a language change is
picked up on the next hover. With `anchor` the tip hangs on that widget instead of its own
glyph (e.g. why a greyed-out field cannot be changed), and an empty text shows nothing.
"""
import tkinter as tk
from tkinter import ttk

GLYPH = "ⓘ"       # circled small i
WRAP_PX = 420
OFFSET_PX = 14
GAP_PX = 4         # between a popup moved above its marker and the marker


class InfoTip:
    def __init__(self, parent, text, anchor=None):
        self._text = text if callable(text) else (lambda: text)
        self.label = anchor or ttk.Label(parent, text=GLYPH, cursor="question_arrow")
        self.label.bind("<Enter>", lambda _e: self.show())
        self.label.bind("<Leave>", lambda _e: self.hide())
        self.popup = None

    def text(self):
        return self._text()

    def show(self):
        self.hide()
        if not self.text():
            return
        popup = tk.Toplevel(self.label)
        popup.wm_overrideredirect(True)
        tk.Label(popup, text=self.text(), justify="left", wraplength=WRAP_PX,
                 background="#ffffe0", foreground="#000000", relief="solid",
                 borderwidth=1, padx=6, pady=4).pack()
        popup.update_idletasks()
        popup.wm_geometry("+{}+{}".format(*self._place(popup.winfo_reqwidth(),
                                                       popup.winfo_reqheight())))
        self.popup = popup

    def _place(self, width, height):
        """Top-left corner of a width x height popup: OFFSET_PX right of and below the marker,
        moved left to keep within the window's right edge (never past its left edge) and above
        the marker when it would cross the bottom. The window, not the screen, bounds it: with
        several monitors the screen size names only the primary one."""
        label, top = self.label, self.label.winfo_toplevel()
        left, right = top.winfo_rootx(), top.winfo_rootx() + top.winfo_width()
        bottom = top.winfo_rooty() + top.winfo_height()
        x = max(left, min(label.winfo_rootx() + OFFSET_PX, right - width))
        y = label.winfo_rooty() + OFFSET_PX
        if y + height > bottom:
            y = max(top.winfo_rooty(), label.winfo_rooty() - height - GAP_PX)
        return x, y

    def hide(self):
        if self.popup is not None:
            try:
                self.popup.destroy()
            except tk.TclError:
                pass
            self.popup = None
