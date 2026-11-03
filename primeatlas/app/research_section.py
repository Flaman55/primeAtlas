"""
research_section.py -- ResearchSectionMixin of PortalBrowserApp: the 'Research' tab
(Square intervals / Polynomials / Goldbach / Gaps / pi(x) approximations sub-tabs).
"""
from tkinter import ttk

from primeatlas.app import app_const as _const
from primeatlas.app import app_dynamic as _dyn
from primeatlas.app.paging import update_nav_controls
from primeatlas.generation.quick_number import _eval_quick_number


class ResearchSectionMixin:
    # --- Research tab: nested notebook, all five sub-tabs now have real logic ------
    # (Goldbach, Squares, Polynomials, Gaps, pi(x) approximations) -------------------

    def _build_research_section(self):
        """Same nested-notebook pattern as _build_primes_section() /
        _build_constellations_section() (see either's own docstring for the full
        rationale) -- a new top-level 'Research' tab, positioned between
        Constellations and Generation.

        Sub-tabs are grouped by SHARED QUESTION SHAPE, not by conjecture name, so one
        engine/analysis serves several classical conjectures via parameter presets
        instead of duplicating near-identical code:
          - Square intervals: 'does [a(n), b(n)] contain enough primes?' -- Legendre
            ([n^2, (n+1)^2]) and Oppermann ([n^2, n^2+n] and [n^2+n, (n+1)^2]) ask
            '>=1'; Brocard ([p_n^2, p_(n+1)^2], prime-indexed) asks '>=4', its actual
            conjectured threshold -- three presets plus a custom formula, ONE tab
            (primeatlas/research/research_squares_tab.py's ResearchSquaresTab).
          - Prime-generating polynomials: 'are there infinitely many primes among
            f(n)'s values?' -- Landau's n^2+1 is one instance of this, alongside Euler's
            n^2+n+41 and a custom polynomial (Bunyakovsky conjecture in general) --
            primeatlas/research/research_polynomials_tab.py's ResearchPolynomialsTab, with the
            same data-source toggle + CSV export as Squares.
          - Goldbach: additive representation (strong: n=p+q even; weak: n=p+q+r odd,
            proven) -- genuinely a different question shape, stays its own tab
            (ResearchGoldbachTab, see primeatlas/research/research_goldbach_tab.py).
          - Gaps: consecutive-prime growth family -- raw gaps PLUS the inequalities that
            are really just different statistics on the same p_n/p_(n+1) sequence
            (Andrica: sqrt(p_(n+1))-sqrt(p_n)<1; Firoozbakht: p_(n+1)^(1/(n+1)) <
            p_n^(1/n); Cramer: gap vs (log p)^2 as a theoretical ceiling) -- selectable
            overlays on ONE tab, not separate tabs -- primeatlas/research/research_gaps_tab.py's
            ResearchGapsTab, with the same data-source toggle + CSV export as
            Squares/Polynomials; Cramer's overlay reports a plain ratio measurement
            (max seen in range), not a covered/counterexamples verdict, since it's an
            asymptotic (limsup) statement, not a per-n inequality -- see
            gaps_window.py's own module docstring.
          - pi(x) approximations: accuracy of li(x)/R(x) against the real count -- a
            measurement-quality question, not a yes/no conjecture check, stays its own
            tab -- primeatlas/research/research_pi_approx_tab.py's ResearchPiApproxTab, with the
            same data-source toggle + CSV export as Squares/Polynomials/Gaps; li(x)/R(x)
            computed via this project's own pure-Python Ei/Gram-series implementations
            (no scipy/mpmath dependency) -- see pi_approx_window.py's own module
            docstring.
        Hardy-Littlewood / twin-prime / Polignac density questions are NOT a sub-tab
        here -- they're the same computation the EXISTING Constellations tab already
        does (pattern hit-counting), so that family becomes a future density-comparison
        VIEW added to Constellations (actual hits vs Hardy-Littlewood asymptotic
        prediction) instead of a duplicate engine here.

        ResearchGoldbachTab is constructed via dependency injection (same pattern as
        every other extracted tab -- see primeatlas/primes/primes_tab.py's own docstring),
        local import for the same lazy-tkinter-import reason SettingsTab/BenchmarkTab/
        PrimesTab are imported inside their own _build_*_tab() methods rather than at
        this file's top. offer_generate_missing_range is the ONE callback that stays
        app-level -- see _goldbach_offer_generate_missing_range's own docstring and
        primeatlas/research/research_goldbach_tab.py's module docstring for why."""
        from primeatlas.research.research_goldbach_tab import ResearchGoldbachTab

        sub = ttk.Notebook(self.research_tab)
        sub.pack(fill="both", expand=True)
        self.research_sub_notebook = sub
        self.research_squares_tab = ttk.Frame(sub)
        self.research_polynomials_tab = ttk.Frame(sub)
        self.research_goldbach_tab = ttk.Frame(sub)
        self.research_gaps_tab = ttk.Frame(sub)
        self.research_pi_approx_tab = ttk.Frame(sub)
        sub.add(self.research_squares_tab, text=_dyn.T("tabs.research_squares"))
        sub.add(self.research_polynomials_tab, text=_dyn.T("tabs.research_polynomials"))
        sub.add(self.research_goldbach_tab, text=_dyn.T("tabs.research_goldbach"))
        sub.add(self.research_gaps_tab, text=_dyn.T("tabs.research_gaps"))
        sub.add(self.research_pi_approx_tab, text=_dyn.T("tabs.research_pi_approx"))
        self._build_research_squares_tab()
        self._build_research_polynomials_tab()

        self.research_goldbach_tab_widget = ResearchGoldbachTab(
            self._scroll_body("research_goldbach_tab"), get_portal_folder=lambda: _dyn.PORTAL_FOLDER,
            status_var=self.status, translator=_dyn.TRANSLATOR,
            update_nav_controls=update_nav_controls,
            eval_quick_number=_eval_quick_number, page_size=_const.PAGE_SIZE,
            totals_progress=self.totals_progress,
            offer_generate_missing_range=self._goldbach_offer_generate_missing_range)
        self.research_goldbach_tab_widget.pack(fill="both", expand=True)

        self._build_research_gaps_tab()
        self._build_research_pi_approx_tab()

    def _build_research_squares_tab(self):
        """Square-interval explorer (Legendre/Oppermann/Brocard presets + custom
        boundary formula), via primeatlas/research/research_squares_tab.py's
        ResearchSquaresTab, with a data-source toggle (on-disk-archive bridge,
        primeatlas/research/research_squares.py) and CSV export -- see that module's own
        docstring. Same dependency-injection/local-import convention as
        ResearchGoldbachTab above."""
        from primeatlas.research.research_squares_tab import ResearchSquaresTab

        self.research_squares_tab_widget = ResearchSquaresTab(
            self._scroll_body("research_squares_tab"), translator=_dyn.TRANSLATOR,
            totals_progress=self.totals_progress,
            eval_quick_number=_eval_quick_number,
            get_portal_folder=lambda: _dyn.PORTAL_FOLDER, status_var=self.status)
        self.research_squares_tab_widget.pack(fill="both", expand=True)

    def _build_research_polynomials_tab(self):
        """Prime-generating polynomial explorer (Landau n^2+1, Euler n^2+n+41,
        custom formula), via primeatlas/research/research_polynomials_tab.py's
        ResearchPolynomialsTab -- same shape as _build_research_squares_tab()
        above (data-source toggle + CSV export from day one, see that
        module's own docstring), just with one f(n) formula per row instead
        of an a(n)/b(n) covering interval."""
        from primeatlas.research.research_polynomials_tab import ResearchPolynomialsTab

        self.research_polynomials_tab_widget = ResearchPolynomialsTab(
            self._scroll_body("research_polynomials_tab"), translator=_dyn.TRANSLATOR,
            totals_progress=self.totals_progress,
            eval_quick_number=_eval_quick_number,
            get_portal_folder=lambda: _dyn.PORTAL_FOLDER, status_var=self.status)
        self.research_polynomials_tab_widget.pack(fill="both", expand=True)

    def _goldbach_offer_generate_missing_range(self, op, payload):
        """One-line delegate to GenerationOfferCoordinator -- see
        _offer_generate_missing_prime_window()'s own docstring and
        primeatlas/generation/generation_offer_coordinator.py's module docstring. Still the
        ONE piece of the Goldbach sub-tab's own logic injected from outside
        primeatlas/research/research_goldbach_tab.py's ResearchGoldbachTab --
        ResearchGoldbachTab receives this exact bound method as its own
        `offer_generate_missing_range(op, payload)` callable (see that class's own
        docstring) and has no idea (nor needs to) that the actual logic lives in a
        coordinator class rather than directly on PortalBrowserApp."""
        return self._generation_offer_coord.offer_generate_missing_range(op, payload)

    def _build_research_gaps_tab(self):
        """Prime gap explorer (raw gaps + a selectable Andrica/Firoozbakht/Cramer
        overlay), via primeatlas/research/research_gaps_tab.py's ResearchGapsTab -- same
        shape as _build_research_squares_tab()/_build_research_polynomials_tab()
        above (data-source toggle + CSV export from day one), just with n
        indexing prime POSITION (p_n, p_(n+1) pairs) instead of a plain integer
        range, and no user-typed formula (the overlay is one of a fixed set, see
        gaps_window.py's own module docstring)."""
        from primeatlas.research.research_gaps_tab import ResearchGapsTab

        self.research_gaps_tab_widget = ResearchGapsTab(
            self._scroll_body("research_gaps_tab"), translator=_dyn.TRANSLATOR,
            totals_progress=self.totals_progress,
            eval_quick_number=_eval_quick_number,
            get_portal_folder=lambda: _dyn.PORTAL_FOLDER, status_var=self.status)
        self.research_gaps_tab_widget.pack(fill="both", expand=True)

    def _build_research_pi_approx_tab(self):
        """pi(x) approximation accuracy explorer (li(x), R(x) against the real
        count), via primeatlas/research/research_pi_approx_tab.py's ResearchPiApproxTab --
        same shape as _build_research_squares_tab()/_build_research_polynomials_
        tab()/_build_research_gaps_tab() above (data-source toggle + CSV export
        from day one), just checkpointed over [x_from, x_to] by `step` instead of
        a plain n_from/n_to loop, and with no conjecture verdict at all -- this is
        a pure measurement/accuracy comparison, see pi_approx_window.py's own
        module docstring."""
        from primeatlas.research.research_pi_approx_tab import ResearchPiApproxTab

        self.research_pi_approx_tab_widget = ResearchPiApproxTab(
            self._scroll_body("research_pi_approx_tab"), translator=_dyn.TRANSLATOR,
            totals_progress=self.totals_progress,
            eval_quick_number=_eval_quick_number,
            get_portal_folder=lambda: _dyn.PORTAL_FOLDER, status_var=self.status)
        self.research_pi_approx_tab_widget.pack(fill="both", expand=True)
