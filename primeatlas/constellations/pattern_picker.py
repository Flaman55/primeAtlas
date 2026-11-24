"""
pattern_picker.py -- PatternPicker, the app's one control for choosing a k-tuple pattern
from constellation/pattern_catalog_v1.py: a k dropdown, a variant dropdown holding that
k's variants, and an info line with the selected pattern's offsets and its pzktupel.de
record (or a note that the pattern is not tracked there). Used by Constellations >
Calculator, Generation's k-tuple section and Rings' line mode.

The picker builds `row` (labels and dropdowns) and `info_label` in the parent it is
given; the caller packs or grids both. A change of k selects that k's first variant.
"""
import tkinter as tk
from tkinter import ttk

import pattern_catalog_v1

from ..core.wrap_label import WrapLabel


def pattern_info(T, pattern):
    """The info line for one catalog pattern: its offsets, and its record when tracked."""
    offsets = ", ".join(str(o) for o in pattern["offsets"])
    if pattern["record_digits"] is None:
        return T("const_calc.pattern_info_untracked", offsets=offsets)
    return T("const_calc.pattern_info", offsets=offsets, record_digits=pattern["record_digits"],
             discoverer=pattern["discoverer"], date=pattern["date"])


class PatternPicker:
    def __init__(self, parent, T, k_label_key, variant_label_key, on_change=None):
        """on_change(pattern) runs after every selection, made in a dropdown or by select()."""
        self.T = T
        self._on_change = on_change
        self.k_values = pattern_catalog_v1.all_k()
        self.variants = []

        self.row = ttk.Frame(parent)
        ttk.Label(self.row, text=T(k_label_key)).pack(side="left")
        self.k_combo = ttk.Combobox(self.row, state="readonly", width=6,
                                    values=[str(k) for k in self.k_values])
        self.k_combo.pack(side="left", padx=(6, 16))
        self.k_combo.bind("<<ComboboxSelected>>", lambda _e: self.select(k=self.k_combo.get()))
        ttk.Label(self.row, text=T(variant_label_key)).pack(side="left")
        self.variant_combo = ttk.Combobox(self.row, state="readonly", width=10)
        self.variant_combo.pack(side="left", padx=(6, 0))
        self.variant_combo.bind("<<ComboboxSelected>>", lambda _e: self._changed())

        self.info_var = tk.StringVar(master=self.row, value="")
        self.info_label = WrapLabel(parent, textvariable=self.info_var, style="Hint.TLabel")

    def select(self, k=None, variant_id=None):
        """Selects catalog pattern (k, variant_id); k and id may be text. A k not in the
        catalog selects the first k, an id not under k selects k's first variant."""
        try:
            k = int(k)
        except (TypeError, ValueError):
            k = None
        if not self.k_values:
            return
        if k not in self.k_values:
            k = self.k_values[0]
        self.k_combo.current(self.k_values.index(k))
        self.variants = pattern_catalog_v1.patterns_for_k(k)
        self.variant_combo.configure(
            values=[self.T("const_calc.variant_label", id=w["id"]) for w in self.variants])
        index = next((i for i, w in enumerate(self.variants) if str(w["id"]) == str(variant_id)), 0)
        self.variant_combo.current(index)
        self._changed()

    def pattern(self):
        """The selected catalog pattern (a pattern_catalog_v1 entry), or None."""
        index = self.variant_combo.current()
        if 0 <= index < len(self.variants):
            return self.variants[index]
        return None

    def _changed(self):
        pattern = self.pattern()
        self.info_var.set(pattern_info(self.T, pattern) if pattern else "")
        if pattern and self._on_change:
            self._on_change(pattern)
