"""
primes_section.py -- PrimesSectionMixin of PortalBrowserApp: the 'Prime numbers' tab
(Storage / primesieve / Primality tests sub-tabs), the primes-tree reload delegate and
the "generate the missing fragment" delegates.
"""
from tkinter import ttk

from primeatlas.app import app_const as _const
from primeatlas.app import app_dynamic as _dyn
from primeatlas.app.paging import render_page, update_nav_controls


class PrimesSectionMixin:
    # --- Tab 1: Prime numbers (source primes) ---------------------------------

    def _build_primes_section(self):
        """The top-level 'Prime numbers' notebook tab is itself a small ttk.Notebook,
        not a single flat frame -- 'Storage' (Storage) holds the floor/file browser +
        search (built by _build_primes_tab() below into self.primes_storage_tab),
        alongside two
        sibling tabs: self.primes_primesieve_tab (a standalone libprimesieve
        calculator -- count/nth/next/prev prime, no on-disk storage involved) and
        self.primes_primality_tab (probabilistic primality testing + factorization
        for a single entered number). See _build_constellations_section() for the
        SAME nested-notebook pattern applied to the Constellations tab -- deliberately
        identical structure between the two so the app has one consistent way of
        giving a top-level section its own sub-tabs, not two diverging ones.

        All three sub-tabs are thin wrappers around their own primeatlas/*.py
        classes (PrimesTab / PrimesieveCalcTab / PrimalityTab) -- see those two
        modules' own docstrings for why status_var/translator/totals_progress are
        the only three things injected into each."""
        sub = ttk.Notebook(self.primes_tab)
        sub.pack(fill="both", expand=True)
        # Saved for the same reason as self.main_notebook above -- the constellation
        # calculator's Search button needs to switch to this sub-notebook's own
        # Storage tab, not just the top-level Prime numbers tab.
        self.primes_sub_notebook = sub
        self.primes_storage_tab = ttk.Frame(sub)
        self.primes_primesieve_tab = ttk.Frame(sub)
        self.primes_primality_tab = ttk.Frame(sub)
        sub.add(self.primes_storage_tab, text=_dyn.T("tabs.primes_storage"))
        sub.add(self.primes_primesieve_tab, text=_dyn.T("tabs.primes_primesieve"))
        sub.add(self.primes_primality_tab, text=_dyn.T("tabs.primes_primality"))
        self._build_primes_tab()

        from primeatlas.primality.primesieve_calc_tab import PrimesieveCalcTab
        self.primesieve_calc_tab_widget = PrimesieveCalcTab(
            self._scroll_body("primes_primesieve_tab"), status_var=self.status, translator=_dyn.TRANSLATOR,
            totals_progress=self.totals_progress)
        self.primesieve_calc_tab_widget.pack(fill="both", expand=True)

        from primeatlas.primality.primality_tab import PrimalityTab
        self.primality_tab_widget = PrimalityTab(
            self._scroll_body("primes_primality_tab"), status_var=self.status, translator=_dyn.TRANSLATOR,
            totals_progress=self.totals_progress)
        self.primality_tab_widget.pack(fill="both", expand=True)

    def _build_primes_tab(self):
        """Thin wrapper -- all of the Primes tab's actual widgets/logic live in
        primeatlas/primes/primes_tab.py's PrimesTab class (see that module's own
        docstring). Local import, not module-level, for the same lazy-tkinter-import
        reason SettingsTab/BenchmarkTab are imported inside _build_gui() rather than
        at this file's top."""
        from primeatlas.primes.primes_tab import PrimesTab
        self.primes_tab_widget = PrimesTab(
            self._scroll_body("primes_storage_tab"), get_portal_folder=lambda: _dyn.PORTAL_FOLDER,
            status_var=self.status, translator=_dyn.TRANSLATOR,
            update_nav_controls=update_nav_controls, render_page=render_page,
            page_size=_const.PAGE_SIZE, floor_page_size=_const.FLOOR_PAGE_SIZE,
            reload_primes_tree=self.reload_primes_tree,
            start_search_job=lambda *a: self._totals_search.start_search_job(*a),
            is_search_busy=lambda: self._totals_search.search_busy,
            offer_generate_missing_prime_window=lambda be, num:
                self._offer_generate_missing_prime_window("prime", be, num),
            submit_totals_job=lambda be: self._totals_search.submit_totals_job(be),
            verify_all_totals=lambda: self._totals_search.compute_all_floor_totals())
        self.primes_tab_widget.pack(fill="both", expand=True)

    def reload_primes_tree(self):
        """Rebuilds the floor list from disk (picks up newly created/removed 10pN
        folders) AND re-runs the totals scan for every floor -- so pressing Refresh
        after generating new windows is enough to see updated totals, no separate
        button needed.

        One-line delegate to primeatlas/primes/primes_tree_coordinator.py's
        PrimesTreeCoordinator (see that module's own docstring for the full
        scan/reload/caching/coalescing/staleness design). Kept as a plain class
        METHOD (not an instance attribute reassigned in __init__) so every caller
        that holds a self.reload_primes_tree reference (PrimesTab, GenerationTab,
        _set_portal_folder, the startup kickoff in __init__) resolves it late, at
        call time -- self._primes_tree_coord only
        needs to exist by the time this is actually CALLED, not by the time some
        other constructor captures this method as a callable."""
        self._primes_tree_coord.reload()
    # --- Search worker: lives in primeatlas/core/totals_search_coordinator.py's
    # TotalsSearchCoordinator alongside the totals worker (see this file's own
    # __init__ / that module's docstring). self._on_const_search_result below is the
    # one deliberate seam left here -- see TotalsSearchCoordinator's own docstring on
    # its on_const_search_result constructor parameter for why that specific
    # completion handler stays app-level. ------------------------------------

    def _offer_generate_missing_prime_window(self, kind, base_exponent, number):
        """One-line delegate to primeatlas/generation/generation_offer_coordinator.py's
        GenerationOfferCoordinator (see that module's own docstring for the full
        "offer to generate this missing fragment, then re-check" design and the
        3-way "launched"/"composite"/"skipped" return contract). Kept as a plain
        class METHOD (not an instance attribute) for the same late-binding reason
        reload_primes_tree()/reload_constellations_tree() are -- see
        primeatlas/primes/primes_tree_coordinator.py's own docstring."""
        return self._generation_offer_coord.offer_generate_missing_prime_window(
            kind, base_exponent, number)

    def _offer_generate_missing_constellation(self, base_exponent, number):
        """One-line delegate to GenerationOfferCoordinator -- see
        _offer_generate_missing_prime_window()'s own docstring just above and
        primeatlas/generation/generation_offer_coordinator.py's module docstring."""
        return self._generation_offer_coord.offer_generate_missing_constellation(
            base_exponent, number)
