"""
irreducibility_cases_window.py -- the window that lists every case of a Research ->
Irreducibility self-test (the 1000 comparisons, the 450 operations): one row per case with the
result read from residues next to the integer result, an 'only errors' filter, and the moduli
and residues of the selected case below the list.

show_cases(view, ...) opens the window for a view, or refreshes and raises the one it already
has open; the window is kept as view.cases_window.
"""
import tkinter as tk
from tkinter import ttk

from ..core.widgets import StripedTreeview
from .irreducibility_widgets import OutputText, wrapped_label

OK_MARK, ERR_MARK = "✓", "✗"


class CasesWindow(tk.Toplevel):
    """columns: (id, heading, width, stretch) tuples; the id 'ok' is filled from each case's
    ok flag. set_cases(title, summary, all_ok, columns, rows, hint) replaces the content; rows
    are (values, ok, detail) with values in column order without 'ok'."""

    def __init__(self, master, T, palette):
        super().__init__(master)
        self.T = T
        self.configure(background=palette["bg"])
        self.geometry("1100x640")
        self.bind("<Escape>", lambda _e: self.destroy())
        self._rows = []
        self._columns = ()

        self.summary_var = tk.StringVar()
        self.summary_label = ttk.Label(self, textvariable=self.summary_var,
                                       font=("TkDefaultFont", 14, "bold"))
        self.summary_label.pack(anchor="w", padx=10, pady=(10, 2))
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=(0, 4))
        self.only_errors_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text=self.T("research_irreducibility.cases_only_errors"),
                        variable=self.only_errors_var, command=self.refill).pack(side="left")
        self.shown_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.shown_var, style="Hint.TLabel").pack(side="left",
                                                                             padx=(12, 0))

        pane = ttk.PanedWindow(self, orient="vertical")
        pane.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        top = ttk.Frame(pane)
        self.tree = StripedTreeview(top, show="headings", selectmode="browse")
        self.tree.tag_configure("err", foreground="#c0392b")
        yscroll = ttk.Scrollbar(top, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(top, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        xscroll.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        pane.add(top, weight=3)

        bottom = ttk.Frame(pane)
        self.hint_label = wrapped_label(bottom, style="Hint.TLabel", pady=(6, 2))
        self.detail = OutputText(bottom, palette, height=6)
        self.detail.configure(wrap="none", font=("Consolas", 10))
        self.detail.pack(fill="both", expand=True)
        pane.add(bottom, weight=1)

    def set_cases(self, title, summary, all_ok, columns, rows, hint):
        self.title(title)
        self.summary_var.set(summary)
        self.summary_label.configure(foreground="#2ca02c" if all_ok else "#c0392b")
        self.hint_label.configure(text=hint)
        self._columns = tuple(c[0] for c in columns)
        self.tree.configure(columns=self._columns)
        for cid, heading, width, stretch in columns:
            self.tree.heading(cid, text=heading)
            self.tree.column(cid, width=width, stretch=stretch,
                             anchor="w" if stretch else "center")
        self._rows = rows
        self.refill()

    def refill(self):
        """Fills the list from the stored rows, only the failed ones while the filter is on."""
        self.tree.delete(*self.tree.get_children())
        self.detail.clear()
        only_errors = self.only_errors_var.get()
        shown = 0
        for i, (values, ok, _detail) in enumerate(self._rows):
            if only_errors and ok:
                continue
            cells = list(values)
            cells.insert(self._columns.index("ok"), OK_MARK if ok else ERR_MARK)
            self.tree.insert("", "end", iid=str(i), values=cells,
                             tags=() if ok else ("err",))
            shown += 1
        self.shown_var.set(self.T("research_irreducibility.cases_shown", shown=shown,
                                  count=len(self._rows)))

    def _on_select(self, _event=None):
        sel = self.tree.selection()
        self.detail.clear()
        if sel:
            self.detail.write(self._rows[int(sel[0])][2])


def show_cases(view, palette, title, summary, all_ok, columns, rows, hint):
    """Opens view.cases_window, or refreshes and raises it when it is still open."""
    w = getattr(view, "cases_window", None)
    if w is None or not w.winfo_exists():
        w = CasesWindow(view.winfo_toplevel(), view.T, palette)
        view.cases_window = w
    w.set_cases(title, summary, all_ok, columns, rows, hint)
    w.deiconify()
    w.lift()
    return w
