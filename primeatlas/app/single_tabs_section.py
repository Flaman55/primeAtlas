"""
single_tabs_section.py -- SingleTabsSectionMixin of PortalBrowserApp: the main tabs
without a sub-notebook (Generation, Benchmark, About), each a thin wrapper around its
own tab class.
"""
from primeatlas.app import app_dynamic as _dyn
from primeatlas.app.paging import update_nav_controls


class SingleTabsSectionMixin:
    # --- Tab 3: Generation (launch orchestrator_loop_v2 / constellation_finder) --

    def _build_generation_tab(self):
        """Thin wrapper -- the whole tab (Quick-gen panel, Section A/B/C forms,
        launch/poll/finish handlers) lives in primeatlas/generation/generation_tab.py's
        GenerationTab -- see that module's own docstring for the full design,
        including why research_goldbach_tab_widget
        is injected directly (Research tab is built before this one, see this
        file's own __init__ tab-build order) and which three pieces of cross-tab
        state (_pending_search_after_prime_gen/_pending_search_after_const_gen/
        _pending_goldbach_retry_op, plus the quick-gen launch methods) app-level
        code below reaches into via self.generation_tab_widget.X instead."""
        from primeatlas.generation.generation_tab import GenerationTab

        self.generation_tab_widget = GenerationTab(
            self.generation_tab, get_portal_folder=lambda: _dyn.PORTAL_FOLDER,
            status_var=self.status, translator=_dyn.TRANSLATOR,
            totals_progress=self.totals_progress,
            reload_primes_tree=self.reload_primes_tree,
            reload_constellations_tree=self.reload_constellations_tree,
            research_goldbach_tab_widget=self.research_goldbach_tab_widget)
        self.generation_tab_widget.pack(fill="both", expand=True)

    # --- Tab 4: Benchmark ---------------------------------------------------------

    def _build_benchmark_tab(self):
        """Thin wrapper -- all of the Benchmark tab's actual widgets/logic live in
        primeatlas/benchmark/benchmark_tab.py's BenchmarkTab class (see that module's own
        docstring). Local import, not module-level, for the same lazy-tkinter-import
        reason SettingsTab/GenerationConsole are imported inside _build_gui() rather
        than at this file's top.

        update_nav_controls is passed in explicitly rather than BenchmarkTab
        importing it back from this file -- that would be circular (this file
        imports BenchmarkTab from primeatlas.benchmark.benchmark_tab) -- see BenchmarkTab's
        own docstring for why this ONE shared helper stays here instead of moving
        into primeatlas/ alongside everything else this tab needed."""
        from primeatlas.benchmark.benchmark_tab import BenchmarkTab
        self.benchmark_tab_widget = BenchmarkTab(
            self._scroll_body("benchmark_tab"), get_portal_folder=lambda: _dyn.PORTAL_FOLDER,
            status_var=self.status, translator=_dyn.TRANSLATOR,
            update_nav_controls=update_nav_controls,
            theme_palette=self._palette)
        self.benchmark_tab_widget.pack(fill="both", expand=True)

    def _build_about_tab(self):
        """The last main tab, see primeatlas/about/about_tab.py."""
        from primeatlas.about.about_tab import AboutTab
        self.about_tab_widget = AboutTab(self._scroll_body("about_tab"), repo_root=_dyn.REPO_DIR,
                                         translator=_dyn.TRANSLATOR)
        self.about_tab_widget.pack(fill="both", expand=True)
