"""
pattern_source.py -- PatternSource, the Rings tab's choice of the k-tuple pattern that line
mode slides along its row of primes: From the list (a catalog pattern, picked with
constellations/pattern_picker.PatternPicker and sent as --pattern-offsets), Manual (k
consecutive primes from p0, sent as --pattern-seed-k/--pattern-seed-start, with a how-to
line and a live preview of the offsets) or None. Only the chosen mode's controls show.

The tab packs `frame`, reads launch_pattern() and saved_params() when it launches and locks
lock_widgets() while the renderer is paused.
"""
import tkinter as tk
from tkinter import ttk

import pattern_catalog_v1

from ...constellations.pattern_picker import PatternPicker
from ...core import number_field
from ...core.widgets import FlowRow
from ...core.wrap_label import WrapLabel
from ...generation.quick_number import _eval_quick_number
from .line.line_geometry import pattern_offsets_from_seed

SOURCES = ("list", "manual", "none")

# The preview runs on every keystroke and finds primes by trial division; past these the
# Manual mode's offsets are computed by the renderer at launch only. Arbitrary bounds that
# keep a keystroke well under a tenth of a second.
PREVIEW_P0_MAX = 10 ** 9
PREVIEW_K_MAX = 100


def _initial_source(saved):
    """The saved mode; a save without one (older versions) is Manual when it holds a k or
    a p0, else From the list."""
    source = saved.get("pattern_source")
    if source in SOURCES:
        return source
    if saved.get("pattern_k") or saved.get("pattern_p0"):
        return "manual"
    return "list"


def _manual_seed(k_text, p0_text):
    """(k, p0) when both fields hold a valid seed (k >= 2, p0 > 2), else None."""
    k = _eval_quick_number(k_text) if k_text else None
    p0 = _eval_quick_number(p0_text) if p0_text else None
    if k is None or p0 is None or k < 2 or p0 <= 2:
        return None
    return k, p0


class PatternSource:
    def __init__(self, parent, T, saved):
        self.T = T
        self.frame = ttk.Frame(parent)

        source_row = FlowRow(self.frame)
        source_row.frame.pack(fill="x")
        self.source_var = tk.StringVar(master=self.frame, value=_initial_source(saved))
        source_row.add(ttk.Label(source_row.frame, text=T("rings.pattern_source_label")))
        self.radios = []
        for value in SOURCES:
            radio = ttk.Radiobutton(source_row.frame, text=T(f"rings.pattern_source_{value}"),
                                    variable=self.source_var, value=value)
            source_row.add(radio, padx_left=6)
            self.radios.append(radio)

        self.list_frame = ttk.Frame(self.frame)
        self.picker = PatternPicker(self.list_frame, T, "const_calc.field_k", "const_calc.field_variant")
        self.picker.row.pack(fill="x", pady=(4, 0))
        self.picker.info_label.pack(anchor="w")
        self.picker.select(k=saved.get("pattern_list_k"), variant_id=saved.get("pattern_list_id"))

        self.manual_frame = ttk.Frame(self.frame)
        self.hint_var = tk.StringVar(master=self.frame, value=T("rings.pattern_manual_hint"))
        WrapLabel(self.manual_frame, textvariable=self.hint_var, style="Hint.TLabel").pack(
            anchor="w", pady=(4, 0))
        fields = FlowRow(self.manual_frame)
        fields.frame.pack(fill="x")
        self._k_var = tk.StringVar(master=self.frame, value=saved.get("pattern_k", ""))
        self._p0_var = tk.StringVar(master=self.frame, value=saved.get("pattern_p0", ""))
        self.k_entry = self._field(fields, "rings.pattern_k_label", self._k_var, 6,
                                   "field_tip.rings_pattern_k", padx_left=0, minimum=2)
        self.p0_entry = self._field(fields, "rings.pattern_p0_label", self._p0_var, 16,
                                    "field_tip.rings_pattern_p0", padx_left=16, minimum=3)
        self.preview_var = tk.StringVar(master=self.frame, value="")
        WrapLabel(self.manual_frame, textvariable=self.preview_var, style="Hint.TLabel").pack(anchor="w")

        self._k_var.trace_add("write", self._update_preview)
        self._p0_var.trace_add("write", self._update_preview)
        self.source_var.trace_add("write", self._show_source)
        self._update_preview()
        self._show_source()

    def _field(self, row, label_key, var, width, tip_key, padx_left, minimum):
        group = ttk.Frame(row.frame)
        ttk.Label(group, text=self.T(label_key)).pack(side="left")
        entry = ttk.Entry(group, textvariable=var, width=width)
        number_field.attach(entry, self.T, tip_key, minimum=minimum)
        entry.pack(side="left", padx=(6, 0))
        row.add(group, padx_left=padx_left)
        return entry

    def _show_source(self, *_):
        source = self.source_var.get()
        for frame, shown in ((self.list_frame, source == "list"), (self.manual_frame, source == "manual")):
            if shown:
                frame.pack(fill="x")
            else:
                frame.pack_forget()

    def _update_preview(self, *_):
        seed = _manual_seed(self._k_var.get().strip(), self._p0_var.get().strip())
        if seed is None:
            self.preview_var.set("")
            return
        k, p0 = seed
        if k > PREVIEW_K_MAX or p0 > PREVIEW_P0_MAX:
            self.preview_var.set(self.T("rings.pattern_preview_at_start"))
            return
        offsets = pattern_offsets_from_seed(k, p0)
        text = ", ".join(str(o) for o in offsets)
        match = pattern_catalog_v1.find_pattern(k, offsets)
        if match:
            self.preview_var.set(self.T("rings.pattern_preview_catalog", offsets=text, k=k, id=match["id"]))
        else:
            self.preview_var.set(self.T("rings.pattern_preview_other", offsets=text))

    def launch_pattern(self):
        """The renderer's pattern arguments for the chosen mode, or None when Manual's
        fields do not hold a valid seed."""
        pattern = {"pattern_seed_k": None, "pattern_seed_start": None, "pattern_offsets": None}
        source = self.source_var.get()
        if source == "list":
            chosen = self.picker.pattern()
            pattern["pattern_offsets"] = list(chosen["offsets"]) if chosen else None
        elif source == "manual":
            seed = _manual_seed(self._k_var.get().strip(), self._p0_var.get().strip())
            if seed is None:
                return None
            pattern["pattern_seed_k"], pattern["pattern_seed_start"] = seed
        return pattern

    def read_fields(self):
        """The number fields launch_pattern() reads: Manual's k and p0, none otherwise."""
        return [self.k_entry, self.p0_entry] if self.source_var.get() == "manual" else []

    def saved_params(self):
        """Each mode's own values, as typed or chosen, for the launch-parameter save."""
        chosen = self.picker.pattern()
        return {
            "pattern_source": self.source_var.get(),
            "pattern_k": self._k_var.get().strip(),
            "pattern_p0": self._p0_var.get().strip(),
            "pattern_list_k": str(chosen["k"]) if chosen else "",
            "pattern_list_id": str(chosen["id"]) if chosen else "",
        }

    def lock_widgets(self):
        """(entries, radio buttons, dropdowns) that are read at launch only."""
        return ([self.k_entry, self.p0_entry], list(self.radios),
                [self.picker.k_combo, self.picker.variant_combo])
