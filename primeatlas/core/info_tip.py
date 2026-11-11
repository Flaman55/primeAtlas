"""InfoTip -- the app-wide "i" marker next to a field: hovering it shows what the field does.

A small label with the "i" glyph; on <Enter> a borderless Toplevel next to the pointer shows
the text, wrapped to WRAP_PX, until <Leave>. The text is a callable so a language change is
picked up on the next hover. With `anchor` the tip hangs on that widget instead of its own
glyph (e.g. why a greyed-out field cannot be changed), and an empty text shows nothing.
"""
import tkinter as tk
from tkinter import ttk

GLYPH = "ⓘ"       # circled small i
WRAP_PX = 420
OFFSET_PX = 14


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
        x = self.label.winfo_rootx() + OFFSET_PX
        y = self.label.winfo_rooty() + OFFSET_PX
        popup.wm_geometry(f"+{x}+{y}")
        tk.Label(popup, text=self.text(), justify="left", wraplength=WRAP_PX,
                 background="#ffffe0", foreground="#000000", relief="solid",
                 borderwidth=1, padx=6, pady=4).pack()
        self.popup = popup

    def hide(self):
        if self.popup is not None:
            try:
                self.popup.destroy()
            except tk.TclError:
                pass
            self.popup = None
