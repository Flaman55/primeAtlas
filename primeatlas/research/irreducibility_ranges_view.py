"""
irreducibility_ranges_view.py -- Research -> Irreducibility -> Ranges: the ranges W(D), W(K)
and W of a block layout, how W jumps when one parameter moves by -3..+3
(irreducibility_layout.sweep), and layouts fitted to any number n for block sizes 1..5
(irreducibility_layout.fit_for), each of which can be used for A or B.

The layout here has its own fields; Take from A / B copies a side's layout into them. Use for
A / B sets that side's number to n and its layout to the selected row, then shows the
Comparison sub-tab.
"""
import tkinter as tk
from tkinter import ttk

from ..core.base_tab import BaseTab
from ..core.widgets import StripedTreeview
from . import irreducibility_layout as layout
from .irreducibility_draw import COLOR_B, GOLD_BG
from .irreducibility_numbers import DEFAULTS, blocks_text, layout_info, parse_params
from .irreducibility_widgets import entry, wrapped_label

FIT_SIZES = (1, 2, 3, 4, 5)

_DOWN = "#c0392b"


class RangesView(BaseTab):
    def __init__(self, parent, translator, palette, numbers, show_compare):
        super().__init__(parent, translator)
        T = self.T
        self.palette = palette
        self.numbers = numbers
        self._show_compare = show_compare
        self._fits = []
        self.sweep_cells = []
        wrapped_label(self, text=T("research_irreducibility.ranges_desc"), style="Hint.TLabel",
                      padx=6, pady=(8, 4))
        self.param_entries = {}
        for prefix, title in (("d", "blocks_row"), ("k", "quot_row")):
            row = ttk.Frame(self)
            row.pack(fill="x", padx=6, pady=1)
            ttk.Label(row, text=T(f"research_irreducibility.{title}")).pack(side="left",
                                                                           padx=(0, 6))
            for suffix, lab in (("s", "start_label"), ("z", "size_label"), ("c", "count_label")):
                key = prefix + suffix
                self.param_entries[key] = entry(
                    row, T(f"research_irreducibility.{lab}"), str(DEFAULTS["A"][1][key]),
                    f"research.irreducibility.ranges_{key}", width=5, on_return=self.show)
        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=(4, 4))
        ttk.Button(row, text=T("research_irreducibility.show_ranges"),
                   command=self.show).pack(side="left")
        self.from_a_button = ttk.Button(row, text=T("research_irreducibility.take_from_a"),
                                        command=lambda: self.take_from("A"))
        self.from_a_button.pack(side="left", padx=(8, 0))
        self.from_b_button = ttk.Button(row, text=T("research_irreducibility.take_from_b"),
                                        command=lambda: self.take_from("B"))
        self.from_b_button.pack(side="left", padx=(8, 0))
        self.message_var = tk.StringVar()
        wrapped_label(self, textvariable=self.message_var, padx=6)
        self.ranges_var = tk.StringVar()
        wrapped_label(self, textvariable=self.ranges_var, padx=6, pady=(0, 4))
        self.sweep_frame = ttk.Frame(self)
        self.sweep_frame.pack(anchor="w", padx=6, pady=(0, 2))
        wrapped_label(self, text=T("research_irreducibility.sweep_note"), style="Hint.TLabel",
                      padx=6, pady=(0, 8))

        ttk.Label(self, text=T("research_irreducibility.fit_title"),
                  font=("TkDefaultFont", 10, "bold")).pack(anchor="w", padx=6, pady=(8, 2))
        wrapped_label(self, text=T("research_irreducibility.fit_desc"), style="Hint.TLabel",
                      padx=6, pady=(0, 4))
        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=(0, 4))
        self.n_entry = entry(row, "n", "1" + "0" * 24, "research.irreducibility.fit_n", width=34,
                             on_return=self.find)
        ttk.Button(row, text=T("research_irreducibility.find"), command=self.find).pack(
            side="left")
        self.fit_note_var = tk.StringVar()
        wrapped_label(self, textvariable=self.fit_note_var, style="Hint.TLabel", padx=6)
        frame = ttk.Frame(self)
        frame.pack(fill="x", padx=6, pady=(0, 4))
        cols = ("size", "blocks", "quot", "w_blocks", "w", "max_block")
        self.fit_tree = StripedTreeview(frame, columns=cols, show="headings", height=5,
                                        selectmode="browse")
        for c in cols:
            self.fit_tree.heading(c, text=T(f"research_irreducibility.fit_col_{c}"))
            self.fit_tree.column(c, width=150, anchor="e")
        self.fit_tree.tag_configure("heavy", foreground=_DOWN)
        self.fit_tree.pack(fill="x")
        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=(0, 8))
        self.use_a_button = ttk.Button(row, text=T("research_irreducibility.use_for_a"),
                                       command=lambda: self.use_for("A"))
        self.use_a_button.pack(side="left")
        self.use_b_button = ttk.Button(row, text=T("research_irreducibility.use_for_b"),
                                       command=lambda: self.use_for("B"))
        self.use_b_button.pack(side="left", padx=(8, 0))
        self.show()
        self.find()

    def _params(self):
        return parse_params({k: e.get() for k, e in self.param_entries.items()})

    def take_from(self, side):
        for key, e in self.param_entries.items():
            e.delete(0, "end")
            e.insert(0, self.numbers.layout_var(side, key).get())
        self.show()

    def show(self):
        T = self.T
        for w in self.sweep_frame.winfo_children():
            w.destroy()
        self.sweep_cells = []
        try:
            params = self._params()
        except ValueError:
            self.ranges_var.set("")
            self.message_var.set(T("research_irreducibility.layout_invalid"))
            return
        self.message_var.set("")
        D, K = layout.layout_of(params)
        self.ranges_var.set(layout_info(T, D, K) + "\n" + blocks_text(D, K, T))
        p = self.palette
        for j, d in enumerate(layout.SWEEP_STEPS):
            text = T("research_irreducibility.sweep_now") if d == 0 else f"{d:+d}"
            ttk.Label(self.sweep_frame, text=text, anchor="center").grid(
                row=0, column=j + 1, sticky="ew", padx=1)
        for i, row in enumerate(layout.sweep(params)):
            ttk.Label(self.sweep_frame, text=T(f"research_irreducibility.param_{row['key']}"),
                      anchor="w").grid(row=i + 1, column=0, sticky="w", padx=(0, 6))
            for j, cell in enumerate(row["cells"]):
                if cell is None:
                    text, fg, bg = "", p["console_fg"], p["console_bg"]
                else:
                    if cell["delta"] == 0:
                        jump = ""
                    elif not (cell["up"] or cell["down"]):
                        jump = T("research_irreducibility.sweep_same")
                    else:
                        jump = ("×" if cell["up"] else "÷") + layout.fmt_big(cell["ratio"])
                    text = T("research_irreducibility.sweep_cell", value=cell["value"],
                             digits=cell["digits"]) + ("\n" + jump if jump else "\n ")
                    fg = (COLOR_B if cell["up"] else _DOWN if cell["down"]
                          else p["console_fg"])
                    bg = GOLD_BG if cell["delta"] == 0 else p["console_bg"]
                    if cell["delta"] == 0:
                        fg = "#1d1d1f"
                lab = tk.Label(self.sweep_frame, text=text, justify="center", foreground=fg,
                               background=bg, padx=6, pady=2, relief="groove", borderwidth=1)
                lab.grid(row=i + 1, column=j + 1, sticky="nsew", padx=1, pady=1)
                self.sweep_cells.append(lab)

    def find(self):
        T = self.T
        self.fit_tree.delete(*self.fit_tree.get_children())
        self._fits = []
        try:
            n = int(self.n_entry.get().strip())
            if n < 1:
                raise ValueError("n")
        except ValueError:
            self.fit_note_var.set("")
            self.message_var.set(T("research_irreducibility.n_invalid"))
            return
        self.message_var.set("")
        self._n = n
        self.fit_note_var.set(T("research_irreducibility.fit_note", n=layout.fmt_big(n),
                                digits=len(str(n))))
        f = layout.fmt_big
        for z in FIT_SIZES:
            fit = layout.fit_for(n, z, z)
            r = layout.ranges(fit["D"], fit["K"])
            self._fits.append(fit)
            self.fit_tree.insert("", "end", values=(
                z, f"{fit['ds']}…{fit['ds'] + fit['dz'] * fit['dc'] - 1} ({fit['dc']})",
                f"{fit['ks']}…{fit['ks'] + fit['kz'] * fit['kc'] - 1} ({fit['kc']})",
                f(r["w_blocks"]), f(r["w"]), f(r["max_block"])),
                tags=("heavy",) if r["max_block"] > layout.LIMIT_BLOCK else ())

    def use_for(self, side):
        sel = self.fit_tree.selection()
        if not sel or not self._fits:
            self.message_var.set(self.T("research_irreducibility.select_row"))
            return
        fit = self._fits[self.fit_tree.index(sel[0])]
        self.message_var.set("")
        self.numbers.number_var(side).set(str(self._n))
        self.numbers.set_params(side, fit)
        self._show_compare()
