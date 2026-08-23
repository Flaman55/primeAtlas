"""
constellations_calc_tab.py -- ConstellationsCalcTab, the tkinter widgets for the
Constellations tab's "Kalkulator konstelacji" sub-tab: pick a k-tuple pattern from
pattern_catalog_v1.py (k dropdown -> variant dropdown, showing that variant's offsets
plus its pzktupel.de record info when tracked), enter exp/Offset, and Atlas computes
N = 10**exp + Offset plus every N + offset_i for the pattern -- shown in a results
table (not yet checked for primality; this is pure arithmetic, no file I/O, so it's
instant even for a large exp).

Extracted from prime_atlas_v1.py during the refactor branch's Faza 3 (tab-by-tab
backend/UI split, 2026-08-23). Unlike the Prime numbers tab, this one doesn't dispatch
searches itself -- the Search button reuses the SIBLING Magazyn tab's own search box
(ConstellationsHitsTab.search_constellation(), see that method's own docstring)
against whichever row is currently selected, since that search already covers BOTH
things the calculator needs to verify: is this number prime at all (offering to
generate the missing prime window if not) AND does it actually participate in a
tracked constellation pattern (offering to run constellation_finder_v1.py if the floor
has genuinely never been scanned). Searching all k numbers automatically in one click
was considered (matching the literal "one button searches every number" framing this
feature was requested with) but rejected: that search path already has its own async
worker-thread + generate-offer-dialog state machine, and chaining K of those end-to-end
would mean either blocking synchronously (defeating the point of the worker thread) or
bolting a second layer of completion-callback state onto an already-intricate flow.
One-row-at-a-time keeps every existing code path untouched and lets the user see each
result (or generate-offer dialog) before deciding whether to search the next number.

search_selected() ALSO does one thing beyond a plain "trigger the Magazyn search" call:
since the calculator already knows EXACTLY which catalog pattern (k, variant id) this
number was computed for (unlike the generic search box, which has no target pattern in
mind), it (1) proactively checks whether THAT SPECIFIC pattern already has a hit file
for this floor -- the generic search box's own "offer to generate" check only fires
when the floor has NO hit files at all, which silently stays quiet whenever the floor
already has hits for some OTHER pattern -- and offers to generate if not; and (2), once
the search actually completes, prime_atlas_v1.py's own _on_const_search_result()
auto-navigates the Magazyn tree straight to that specific (k, variant) node and jumps
the preview to this exact number (see this tab's own get_pending()/clear_pending(),
consumed by that app-level orchestration method) instead of leaving the user to find it
themselves among however many patterns the participation list turned up.

This is one of a few files in primeatlas/ that import tkinter -- see
primes_tab.py's own docstring for the general "pure logic elsewhere" convention this
package otherwise follows.
"""
import tkinter as tk
from tkinter import ttk, messagebox

import pattern_catalog_v1

from .storage import digit_count_floor, list_pietra
from .constellations import list_constellation_hits


class ConstellationsCalcTab(ttk.Frame):
    def __init__(self, parent, translator, eval_quick_number, get_portal_folder,
                 select_hits_view, set_hits_search_query, trigger_hits_search,
                 offer_generate_missing_constellation):
        """
        translator: same dependency-injection pattern as every other extracted tab --
        see primeatlas/primes_tab.py's own docstring.

        eval_quick_number: prime_atlas_v1.py's own _eval_quick_number() -- shared by
        every numeric field in the app (Quick generation panel, primesieve calculator,
        Testy pierwszosci, ...), so it stays a prime_atlas_v1.py-owned function rather
        than moving here just for this one tab's exp/Offset fields.

        get_portal_folder: same as every other tab's own parameter of this name.

        select_hits_view(): switches the main notebook to the Constellations tab AND
        its own sub-notebook to the Magazyn tab -- app-level (touches
        self.main_notebook/self.constellations_sub_notebook) because this tab has no
        business knowing about ITS SIBLING tab's own container hierarchy.

        set_hits_search_query(number)/trigger_hits_search(): the Magazyn tab's own
        ConstellationsHitsTab.set_search_query()/search_constellation(), injected as
        plain callables (deferred lambdas at construction time, see
        _build_constellations_section()'s own comment) rather than a direct widget
        reference, since which of the two sibling tabs gets built first doesn't matter
        as long as both exist by the time a search actually happens.

        offer_generate_missing_constellation(base_exponent, number): prime_atlas_v1.py's
        own _offer_generate_missing_constellation() -- stays at the app level because it
        can launch a generation run via the Generation tab's own methods, same reasoning
        as every other "offer_generate_missing_*" parameter in this refactor.
        """
        super().__init__(parent)
        self.T = translator
        self._eval_quick_number = eval_quick_number
        self._get_portal_folder = get_portal_folder
        self._select_hits_view = select_hits_view
        self._set_hits_search_query = set_hits_search_query
        self._trigger_hits_search = trigger_hits_search
        self._offer_generate_missing_constellation = offer_generate_missing_constellation

        # {"base_exponent", "number", "pattern"} while a calculator-initiated search is
        # in flight -- consumed by prime_atlas_v1.py's own _on_const_search_result() to
        # auto-navigate to the right variant once that search settles. Public
        # get_pending()/clear_pending() accessors below, rather than direct attribute
        # access, keep that coupling to exactly two small methods instead of the app
        # reaching into this tab's raw state.
        self._pending = None

        self._build_widgets()

    def get_pending(self):
        return self._pending

    def clear_pending(self):
        self._pending = None

    def _build_widgets(self):
        T = self.T
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=12, pady=12)

        pattern_row = ttk.Frame(container)
        pattern_row.pack(fill="x", pady=(0, 8))
        ttk.Label(pattern_row, text=T("const_calc.field_k")).pack(side="left")
        self._k_values = pattern_catalog_v1.all_k()
        self.k_combo = ttk.Combobox(
            pattern_row, state="readonly", width=6,
            values=[str(k) for k in self._k_values])
        self.k_combo.pack(side="left", padx=(6, 16))
        self.k_combo.bind("<<ComboboxSelected>>", self._on_k_changed)

        ttk.Label(pattern_row, text=T("const_calc.field_variant")).pack(side="left")
        self._variants = []
        self.variant_combo = ttk.Combobox(pattern_row, state="readonly", width=10)
        self.variant_combo.pack(side="left", padx=(6, 0))
        self.variant_combo.bind("<<ComboboxSelected>>", self._on_variant_changed)

        self.pattern_info_var = tk.StringVar(value="")
        ttk.Label(container, textvariable=self.pattern_info_var,
                  wraplength=760, justify="left", foreground="#555").pack(
            anchor="w", pady=(0, 8))

        input_row = ttk.Frame(container)
        input_row.pack(fill="x", pady=(0, 8))
        ttk.Label(input_row, text=T("const_calc.field_exp")).pack(side="left")
        self.exp_entry = ttk.Entry(input_row, width=10)
        self.exp_entry.pack(side="left", padx=(6, 16))
        ttk.Label(input_row, text=T("const_calc.field_offset")).pack(side="left")
        self.offset_entry = ttk.Entry(input_row, width=24)
        self.offset_entry.pack(side="left", padx=(6, 16))
        self.compute_button = ttk.Button(
            input_row, text=T("const_calc.compute_button"), command=self._on_compute)
        self.compute_button.pack(side="left")

        tree_frame = ttk.Frame(container)
        tree_frame.pack(fill="both", expand=True, pady=(0, 8))
        self.results_tree = ttk.Treeview(
            tree_frame, columns=("offset", "number"), show="headings",
            height=10, selectmode="browse")
        self.results_tree.heading("offset", text=T("const_calc.col_offset"))
        self.results_tree.heading("number", text=T("const_calc.col_number"))
        self.results_tree.column("offset", width=90, anchor="e")
        self.results_tree.column("number", width=440, anchor="w")
        self.results_tree.pack(side="left", fill="both", expand=True)
        cvsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.results_tree.yview)
        self.results_tree.configure(yscrollcommand=cvsb.set)
        cvsb.pack(side="left", fill="y")

        self.search_button = ttk.Button(
            container, text=T("const_calc.search_button"),
            command=self.search_selected, state="disabled")
        self.search_button.pack(anchor="w")

        self._numbers = []  # [(offset, number), ...], same order as the tree
        self._active_pattern = None  # the exact pattern dict last used by
                                      # _on_compute() -- read by search_selected() so a
                                      # variant-combo change AFTER computing doesn't
                                      # retroactively change what a search believes it's
                                      # looking for
        if self._k_values:
            self.k_combo.current(0)
            self._on_k_changed()

    def _on_k_changed(self, _event=None):
        k_str = self.k_combo.get()
        if not k_str:
            return
        self._variants = pattern_catalog_v1.patterns_for_k(int(k_str))
        self.variant_combo.configure(
            values=[self.T("const_calc.variant_label", id=w["id"]) for w in self._variants])
        if self._variants:
            self.variant_combo.current(0)
        else:
            self.variant_combo.set("")
        self._on_variant_changed()

    def _on_variant_changed(self, _event=None):
        T = self.T
        idx = self.variant_combo.current()
        if idx < 0 or idx >= len(self._variants):
            self.pattern_info_var.set("")
            return
        w = self._variants[idx]
        offsets_str = ", ".join(str(o) for o in w["offsets"])
        if w["record_digits"] is not None:
            self.pattern_info_var.set(T(
                "const_calc.pattern_info", offsets=offsets_str,
                record_digits=w["record_digits"], discoverer=w["discoverer"],
                date=w["date"]))
        else:
            self.pattern_info_var.set(T("const_calc.pattern_info_untracked", offsets=offsets_str))

    def _on_compute(self):
        T = self.T
        idx = self.variant_combo.current()
        if idx < 0 or idx >= len(self._variants):
            messagebox.showerror(T("const_calc.error_dialog_title"), T("const_calc.error_no_pattern"))
            return
        pattern = self._variants[idx]
        offsets = pattern["offsets"]
        exp = self._eval_quick_number(self.exp_entry.get())
        if exp is None or exp < 0:
            messagebox.showerror(T("const_calc.error_dialog_title"), T("const_calc.error_exp_invalid"))
            return
        offset_raw = self.offset_entry.get().strip()
        base_offset = self._eval_quick_number(offset_raw) if offset_raw else 0
        if base_offset is None or base_offset < 0:
            messagebox.showerror(T("const_calc.error_dialog_title"), T("const_calc.error_offset_invalid"))
            return
        n0 = 10 ** exp + base_offset
        self._active_pattern = pattern
        self._numbers = [(d, n0 + d) for d in offsets]
        self.results_tree.delete(*self.results_tree.get_children())
        for d, n in self._numbers:
            self.results_tree.insert("", "end", values=(f"+{d}", f"{n:,}"))
        self.search_button.configure(state="normal" if self._numbers else "disabled")

    def search_selected(self):
        T = self.T
        sel = self.results_tree.selection()
        if not sel:
            messagebox.showinfo(T("const_calc.error_dialog_title"), T("const_calc.error_select_row_first"))
            return
        idx = self.results_tree.index(sel[0])
        if idx < 0 or idx >= len(self._numbers) or self._active_pattern is None:
            return
        _offset, number = self._numbers[idx]
        pattern = self._active_pattern
        base_exponent = digit_count_floor(number)

        # Switch to Constellations -> Magazyn up front, before any dialog fires, so
        # generate-offer confirmations and the eventual result both land where the
        # user is already looking rather than behind the still-visible calculator tab.
        self._select_hits_view()
        self._set_hits_search_query(number)

        self._pending = {"base_exponent": base_exponent, "number": number, "pattern": pattern}

        portal_folder = self._get_portal_folder()
        if base_exponent in list_pietra(portal_folder):
            # Floor exists -- but has constellation_finder_v1.py ever recorded hits
            # for THIS SPECIFIC pattern here? The generic search box's own "offer to
            # generate" check only fires when list_constellation_hits() is empty --
            # i.e. NOTHING has ever been scanned for this floor -- which silently
            # stays quiet whenever the floor already has hits for some OTHER pattern
            # (e.g. the user already ran the finder here for twin primes). That's the
            # right level of caution for the generic search box (it has no specific
            # pattern in mind, so "maybe check everything" isn't a well-defined
            # offer), but the calculator DOES know exactly which pattern it's asking
            # about, so it can check precisely instead of guessing -- closing the gap
            # reported after searching a calculator number into a floor that had
            # unrelated constellation hits already.
            has_this_pattern = any(
                p["id"] == pattern["id"]
                for p, _path, _hdr in list_constellation_hits(portal_folder, base_exponent)
                if p["k"] == pattern["k"])
            if not has_this_pattern and self._offer_generate_missing_constellation(
                    base_exponent, number):
                return  # generation launched -- prime_atlas_v1.py's own
                        # _on_loop_finished()/_on_constellation_finished() re-runs the
                        # const search once it's done, landing back in
                        # _on_const_search_result() with self._pending still set, same
                        # as every other path below
        self._trigger_hits_search()
