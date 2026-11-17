"""
elided_choice.py -- ElidedRadiobutton, a radio whose name shortens to the room it gets.

A FlowRow item (core/widgets.py): FlowRow calls fit_width(row width) before it measures the
item, so an item that would be wider than the whole row is shortened with an ellipsis and an
"i" marker appears beside it; hovering the shortened name or the marker shows the full name.
A name that fits shows in full, with no marker and no tip.
"""
from tkinter import ttk

from .info_tip import GLYPH, InfoTip

ELLIPSIS = "…"
TIP_DELAY_MS = 300
"""Pause on a shortened name before its tip shows (passing over it shows nothing)."""


class ElidedRadiobutton(ttk.Frame):
    """ttk.Radiobutton with `text`, plus `radio_kw` (value, variable, command, ...)."""

    def __init__(self, parent, text, **radio_kw):
        super().__init__(parent)
        self.full_text = text
        self.is_elided = False
        self.radio = ttk.Radiobutton(self, text=text, **radio_kw)
        self.radio.pack(side="left")
        self.icon = ttk.Label(self, text=GLYPH, cursor="question_arrow")
        self.name_tip = InfoTip(self, self.tip_text, anchor=self.radio, delay_ms=TIP_DELAY_MS)
        self.icon_tip = InfoTip(self, lambda: self.full_text, anchor=self.icon)

    def tip_text(self):
        return self.full_text if self.is_elided else ""

    def fit_width(self, room):
        """Shows the full name when the item fits `room` pixels, else the longest prefix
        that fits with an ellipsis and the marker (at least the ellipsis alone). Widths are
        the radio's and the marker's requested widths, which ttk updates as soon as the text
        changes: no idle pass per try (each would lay out the whole app again)."""
        self.radio.configure(text=self.full_text)
        self.is_elided = self.radio.winfo_reqwidth() > room
        if not self.is_elided:
            self.icon.pack_forget()
            return
        if not self.icon.winfo_manager():
            self.icon.pack(side="left")
        room -= self.icon.winfo_reqwidth()
        low, high = 0, len(self.full_text) - 1
        while low < high:
            mid = (low + high + 1) // 2
            self.radio.configure(text=self._shortened(mid))
            if self.radio.winfo_reqwidth() <= room:
                low = mid
            else:
                high = mid - 1
        self.radio.configure(text=self._shortened(low))

    def _shortened(self, length):
        return self.full_text[:length].rstrip() + ELLIPSIS
