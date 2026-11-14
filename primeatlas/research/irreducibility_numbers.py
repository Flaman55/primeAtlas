"""
irreducibility_numbers.py -- the numbers A and B of Research -> Irreducibility and their block
layouts, shared by the Comparison, Ranges and Arithmetic sub-tabs: one StringVar per field
(remembered), parsing and validation, Fit to number, and the text describing a layout's
ranges.
"""
import tkinter as tk

from ..core.ui_state import remember
from . import irreducibility_layout as layout

SIDES = ("A", "B")

DEFAULTS = {
    "A": ("12345678", dict(ds=2, dz=3, dc=3, ks=11, kz=3, kc=3)),
    "B": ("12345679", dict(ds=2, dz=4, dc=2, ks=13, kz=3, kc=3)),
}

MAX_START = 10 ** 6
"""Largest accepted first modulus of D or K; arbitrary."""

MAX_SIZE = 50
"""Largest accepted block size; arbitrary."""

MAX_COUNT = 400
"""Largest accepted block count (Fit to number reaches 300 quotient blocks); arbitrary."""


def parse_params(values):
    """Layout parameters from a dict of strings: ints, starts 2..MAX_START, sizes
    1..MAX_SIZE, counts 1..MAX_COUNT. Raises ValueError."""
    out = {}
    for key in layout.PARAMS:
        v = int(str(values[key]).strip())
        lo, hi = ((2, MAX_START) if key in ("ds", "ks") else
                  (1, MAX_SIZE) if key in ("dz", "kz") else (1, MAX_COUNT))
        if not lo <= v <= hi:
            raise ValueError(key)
        out[key] = v
    return out


def parse_number(text):
    """A whole number >= 0 from text. Raises ValueError."""
    t = (text or "").strip()
    if not t.isdigit():
        raise ValueError("number")
    return int(t)


class IrreducibilityNumbers:
    def __init__(self, master):
        self._numbers = {}
        self._layouts = {}
        for side in SIDES:
            number, params = DEFAULTS[side]
            var = tk.StringVar(master=master, value=number)
            remember(f"research.irreducibility.number_{side.lower()}", var)
            self._numbers[side] = var
            self._layouts[side] = {}
            for key in layout.PARAMS:
                lv = tk.StringVar(master=master, value=str(params[key]))
                remember(f"research.irreducibility.layout_{side.lower()}_{key}", lv)
                self._layouts[side][key] = lv

    def number_var(self, side):
        return self._numbers[side]

    def layout_var(self, side, key):
        return self._layouts[side][key]

    def on_change(self, callback):
        """Calls callback(side) whenever a field of that side changes."""
        for side in SIDES:
            for var in [self._numbers[side], *self._layouts[side].values()]:
                var.trace_add("write", lambda *_a, s=side: callback(s))

    def number(self, side):
        return parse_number(self._numbers[side].get())

    def params(self, side):
        return parse_params({k: v.get() for k, v in self._layouts[side].items()})

    def layout(self, side):
        """(D, K) of the side's layout. Raises ValueError."""
        return layout.layout_of(self.params(side))

    def set_params(self, side, params):
        for key in layout.PARAMS:
            self._layouts[side][key].set(str(params[key]))

    def fit(self, side):
        """Sets the side's layout to fit_for(its number), keeping its block sizes when they
        are valid (else 3). Raises ValueError for an invalid number."""
        n = self.number(side)

        def size(key):
            try:
                v = int(self._layouts[side][key].get())
            except ValueError:
                return 3
            return v if 1 <= v <= MAX_SIZE else 3
        self.set_params(side, layout.fit_for(n, size("dz"), size("kz")))


def layout_info(T, D, K, n=None):
    """The lines describing a layout: W(D), W(K), W with its digits, the redundancy of K, and
    warnings when n does not fit or a block modulus exceeds LIMIT_BLOCK."""
    r = layout.ranges(D, K)
    f = layout.fmt_big
    lines = [T("research_irreducibility.ranges_line", w_blocks=f(r["w_blocks"]),
               w_quot=f(r["w_quot"])),
             T("research_irreducibility.capacity_line", w=f(r["w"]),
               digits=layout.digit_count(r["w"]))]
    if r["nominal"] > r["w"]:
        lines.append(T("research_irreducibility.redundant_line",
                       ratio=f(r["nominal"] // r["w"])))
    if n is not None and n >= r["w"]:
        lines.append(T("research_irreducibility.does_not_fit"))
    if r["max_block"] > layout.LIMIT_BLOCK:
        lines.append(T("research_irreducibility.block_too_large", block=f(r["max_block"])))
    return "\n".join(lines)


def blocks_text(D, K, T):
    """'D: {2,3,4} {5,6,7} · K: {11,12,13}' for a layout."""
    f = lambda bs: " ".join("{" + ",".join(map(str, b)) + "}" for b in bs)
    return T("research_irreducibility.blocks_line", blocks=f(D), quot=f(K))
