"""
constellations_section.py -- ConstellationsSectionMixin of PortalBrowserApp: the
'Constellations' tab (Storage / Constellation calculator / Records table sub-tabs), the
jumps between those sub-tabs, the constellations-tree reload delegate and the app-level
completion handler of a "const" search.
"""
from tkinter import ttk

from primeatlas.app import app_const as _const
from primeatlas.app import app_dynamic as _dyn
from primeatlas.app.paging import render_page, update_nav_controls
from primeatlas.constellations.constellations import list_constellation_hits
from primeatlas.generation.quick_number import _eval_quick_number


class ConstellationsSectionMixin:
    # --- Tab 2: Constellations (constellation hits) ---------------------------------

    def _build_constellations_section(self):
        """Thin wrapper -- all three of the Constellations tab's actual widgets/logic
        live in primeatlas/constellations/constellations_hits_tab.py (ConstellationsHitsTab, the
        "Storage" sub-tab), primeatlas/constellations/constellations_calc_tab.py
        (ConstellationsCalcTab, "Constellation calculator"), and
        primeatlas/constellations/constellations_records_tab.py (ConstellationsRecordsTab, "Records
        table") -- see each module's own docstring. Local imports, not
        module-level, for the same lazy-tkinter-import reason
        SettingsTab/BenchmarkTab/PrimesTab are imported inside their own
        _build_*_tab() methods rather than at this file's top.

        Construction order below doesn't matter for any of the deferred-lambda
        callables passed in -- none of them are resolved until actually CALLED, so
        it's safe for the calculator/records tabs to reference
        self.constellations_hits_tab_widget even though it's constructed first, and
        safe for anything to reference either sibling regardless of build order (see
        primeatlas/primes/primes_tab.py's own docstring for the general construction-order
        hazard this avoids)."""
        from primeatlas.constellations.constellations_hits_tab import ConstellationsHitsTab
        from primeatlas.constellations.constellations_calc_tab import ConstellationsCalcTab
        from primeatlas.constellations.constellations_records_tab import ConstellationsRecordsTab

        sub = ttk.Notebook(self.constellations_tab)
        sub.pack(fill="both", expand=True)
        # Saved for the same reason as self.primes_sub_notebook -- the constellation
        # calculator's Search button needs to switch to THIS sub-notebook's own
        # Storage tab (not just the top-level Constellations tab).
        self.constellations_sub_notebook = sub
        self.constellations_storage_tab = ttk.Frame(sub)
        self.constellations_calculator_tab = ttk.Frame(sub)
        self.constellations_records_tab = ttk.Frame(sub)
        sub.add(self.constellations_storage_tab, text=_dyn.T("tabs.constellations_storage"))
        sub.add(self.constellations_calculator_tab, text=_dyn.T("tabs.constellations_calculator"))
        sub.add(self.constellations_records_tab, text=_dyn.T("tabs.constellations_records"))

        self.constellations_hits_tab_widget = ConstellationsHitsTab(
            self._scroll_body("constellations_storage_tab"),
            get_portal_folder=lambda: _dyn.PORTAL_FOLDER, status_var=self.status,
            translator=_dyn.TRANSLATOR, update_nav_controls=update_nav_controls,
            render_page=render_page, page_size=_const.PAGE_SIZE,
            reload_constellations_tree=self.reload_constellations_tree,
            start_search_job=lambda *a: self._totals_search.start_search_job(*a),
            is_search_busy=lambda: self._totals_search.search_busy,
            offer_generate_missing_prime_window=lambda be, num:
                self._offer_generate_missing_prime_window("const", be, num))
        self.constellations_hits_tab_widget.pack(fill="both", expand=True)

        self.constellations_calc_tab_widget = ConstellationsCalcTab(
            self._scroll_body("constellations_calculator_tab"), translator=_dyn.TRANSLATOR,
            eval_quick_number=_eval_quick_number, get_portal_folder=lambda: _dyn.PORTAL_FOLDER,
            select_hits_view=self._select_constellations_hits_view,
            set_hits_search_query=lambda number:
                self.constellations_hits_tab_widget.set_search_query(number),
            trigger_hits_search=lambda:
                self.constellations_hits_tab_widget.search_constellation(),
            offer_generate_missing_constellation=self._offer_generate_missing_constellation)
        self.constellations_calc_tab_widget.pack(fill="both", expand=True)

        self.constellations_records_tab_widget = ConstellationsRecordsTab(
            self._scroll_body("constellations_records_tab"), get_portal_folder=lambda: _dyn.PORTAL_FOLDER,
            status_var=self.status, translator=_dyn.TRANSLATOR,
            update_nav_controls=update_nav_controls, render_page=render_page,
            page_size=_const.PAGE_SIZE, eval_quick_number=_eval_quick_number,
            totals_progress=self.totals_progress)
        self.constellations_records_tab_widget.bind_jump_to_hits(
            self._jump_records_detail_to_hits)
        self.constellations_records_tab_widget.pack(fill="both", expand=True)

        self.constellations_hits_tab_widget.bind_export_to_records(
            self._jump_hits_to_records_export)

    def _select_constellations_hits_view(self):
        """Switches the main notebook to the Constellations tab AND its own
        sub-notebook to the Storage tab -- injected into ConstellationsCalcTab as
        select_hits_view (see that class's own docstring) and used directly by
        _jump_records_detail_to_hits below; app-level because it touches
        self.main_notebook/self.constellations_sub_notebook, neither of which any one
        sub-tab has (or should have) direct knowledge of."""
        self.main_notebook.select(self.constellations_tab)
        self.constellations_sub_notebook.select(self.constellations_storage_tab)

    def _jump_records_detail_to_hits(self, base_exponent, pattern, hit_base, position):
        """Registered with ConstellationsRecordsTab.bind_jump_to_hits() -- double-
        clicking a hit in the Records table drill-down list jumps to the Storage
        tab's own tree/preview, landing on this exact number. Thin app-level glue
        between two sibling tabs, same shape as _on_const_search_result below."""
        self._select_constellations_hits_view()
        self.constellations_hits_tab_widget.select_pattern_in_tree(base_exponent, pattern)
        self.constellations_hits_tab_widget.load_preview()
        self.constellations_hits_tab_widget.jump_preview_to_row(hit_base, position)

    def _select_constellations_records_view(self):
        """Switches the main notebook to the Constellations tab AND its own
        sub-notebook to the Records table tab -- mirror of
        _select_constellations_hits_view() above, for the opposite direction."""
        self.main_notebook.select(self.constellations_tab)
        self.constellations_sub_notebook.select(self.constellations_records_tab)

    def _jump_hits_to_records_export(self, base_exponent, pattern, page_index):
        """Registered with ConstellationsHitsTab.bind_export_to_records() --
        Storage's "Export" button jumps to the Records table tab with this
        exact pattern's currently-viewed hit-file page pre-loaded as its export
        range (see ConstellationsRecordsTab.activate_pattern_for_export()'s own
        docstring for why Storage hands off here instead of exporting locally).
        Thin app-level glue, same shape as _jump_records_detail_to_hits above."""
        self._select_constellations_records_view()
        self.constellations_records_tab_widget.activate_pattern_for_export(
            base_exponent, pattern, page_index)

    def reload_constellations_tree(self):
        """Rebuilds the constellation-hits floor list from disk. This tab's own
        Refresh button can be clicked without reload_primes_tree() ever running in
        the same gesture (e.g. right after constellation-finding finishes), so its
        own prune/scan is dispatched independently rather than relying on the OTHER
        tree's refresh to have already covered it.

        One-line delegate to primeatlas/constellations/constellations_tree_coordinator.py's
        ConstellationsTreeCoordinator (see that module's own docstring, and
        primeatlas/primes/primes_tree_coordinator.py's own docstring for why this stays a
        plain class METHOD rather than an instance attribute)."""
        self._constellations_tree_coord.reload()

    def _on_const_search_result(self, base_exponent, number, prime_result, participation):
        """Thin app-level orchestrator for a "const" search job's completion --
        unlike Primes tab's fully self-contained on_prime_search_result, this stays
        at the app level because it coordinates a genuine three-way handoff: the
        search worker's raw result, the Storage (hits) tab's display (see
        ConstellationsHitsTab.show_missing_result/show_search_participation/
        jump_to_search_match), and the Constellation calculator tab's pending-search
        state (calc.get_pending()/clear_pending()) -- neither sibling tab should own
        that coupling alone.

        calc_pending/calc_match: when this completion is for a search the
        constellation calculator itself kicked off, and this call is the one that
        actually reaches a final answer (not a "launched a generation run, wait for
        the re-search" detour), the matching pattern's node gets auto-selected in
        the Storage tree and the preview jumped straight to this number -- see the
        tail of this method. calc_pending is only ever CLEARED on a genuinely final
        outcome (declined/composite/no-participation/found) so it survives across
        however many generate-then-re-search hops a single calculator search needs;
        comparing against the LOCAL `calc_pending` copy captured at entry (rather
        than re-reading calc.get_pending() after clearing it) keeps the
        match/pattern lookup valid even after the pending state is gone."""
        hits = self.constellations_hits_tab_widget
        calc = self.constellations_calc_tab_widget
        calc_pending = calc.get_pending()
        calc_match = (calc_pending is not None
                      and calc_pending["base_exponent"] == base_exponent
                      and calc_pending["number"] == number)

        if prime_result is None:
            outcome = self._offer_generate_missing_prime_window("const", base_exponent, number)
            if outcome != "launched":
                if calc_match:
                    calc.clear_pending()
                hits.show_missing_result(base_exponent, number, outcome)
            return

        if not participation:
            # Empty result is genuinely ambiguous -- see
            # _offer_generate_missing_constellation()'s own docstring: no hit FILES at
            # all for this floor means constellation_finder_v2_3.py simply never ran
            # here, not that this specific number was checked and excluded.
            if (not list_constellation_hits(_dyn.PORTAL_FOLDER, base_exponent)
                    and self._offer_generate_missing_constellation(base_exponent, number)):
                return
            if calc_match:
                calc.clear_pending()
        else:
            if calc_match:
                calc.clear_pending()

        hits.show_search_participation(base_exponent, number, prime_result, participation)

        if calc_match and participation:
            # Jump straight to the SPECIFIC (k, variant) node the calculator computed
            # this number for -- same helper ConstellationsHitsTab's own
            # _on_search_result_activate() uses for a double-clicked result row, just
            # triggered automatically instead of requiring that extra click. If the
            # number happens to ALSO participate in some other pattern (shown in the
            # results list either way), this still lands on the one the user actually
            # asked about.
            match = next(
                (rec for rec in participation
                 if rec["pattern"]["k"] == calc_pending["pattern"]["k"]
                 and rec["pattern"]["id"] == calc_pending["pattern"]["id"]), None)
            if match is not None:
                hits.jump_to_search_match(base_exponent, calc_pending["pattern"], match)
