"""
app_window.py -- PortalBrowserApp, the main window: loading screen, the main notebook
with one tab per section, the shared background coordinators (floor totals and
search, both tree scans, "generate the missing fragment") and the startup sequence.
Each section's tab-building methods live in its own mixin (primes_section.py,
constellations_section.py, research_section.py, visualization_section.py,
single_tabs_section.py, settings_wiring.py); colors and font scale in app_theme.py.

Imported only from prime_atlas_v2._build_gui(), so importing prime_atlas_v2 itself
needs no tkinter.
"""
import tkinter as tk
from tkinter import ttk

from primeatlas.app import app_const as _const
from primeatlas.app import app_dynamic as _dyn
from primeatlas import prune_empty_floor_dirs
from primeatlas.app.app_theme import ThemeMixin
from primeatlas.app.constellations_section import ConstellationsSectionMixin
from primeatlas.app.primes_section import PrimesSectionMixin
from primeatlas.app.research_section import ResearchSectionMixin
from primeatlas.app.settings_wiring import SettingsWiringMixin
from primeatlas.app.single_tabs_section import SingleTabsSectionMixin
from primeatlas.app.visualization_section import VisualizationSectionMixin
from primeatlas.constellations.constellations_tree_coordinator import ConstellationsTreeCoordinator
from primeatlas.core.app_icon import apply_tk_icon
from primeatlas.core.totals_search_coordinator import TotalsSearchCoordinator
from primeatlas.core.version import version_label
from primeatlas.generation import close_guard
from primeatlas.generation.generation_offer_coordinator import GenerationOfferCoordinator
from primeatlas.generation.window_planning import QUICK_GEN_MAX_WINDOW_WIDTH, PRIMESIEVE_MAX_STOP
from primeatlas.primes.primes_tree_coordinator import PrimesTreeCoordinator
from primeatlas.settings.settings_tab import SettingsTab


class PortalBrowserApp(ThemeMixin, PrimesSectionMixin, ConstellationsSectionMixin,
                       ResearchSectionMixin, VisualizationSectionMixin,
                       SingleTabsSectionMixin, SettingsWiringMixin, tk.Tk):
    def __init__(self):
        super().__init__()
        apply_tk_icon(self)
        self._apply_font_scale(_dyn.APP_SETTINGS.font_scale)
        self._apply_theme(_dyn.APP_SETTINGS.theme)
        # Release, merges since it and the checked-out commit, see version.py.
        self.title(f"{_dyn.T('app.title')} {version_label(_dyn.REPO_DIR)}")
        self.geometry("1050x680")

        # status_frame/notebook are BUILT here but deliberately left UNPACKED until
        # _finish_loading_screen() reveals them -- see the loading_frame block just
        # below for why: packing the notebook immediately and running the six
        # _build_*_section/_build_*_tab calls plus the three post-build
        # reload_*_tree()/reload_benchmark_log() calls synchronously against an
        # already-visible (but empty/half-built) window makes every one of those
        # steps look like a freeze rather than a load. ttk widgets can be
        # constructed and have children added while unpacked -- only the geometry
        # manager step (.pack itself) is deferred.
        #
        # status_frame is packed BEFORE the notebook, not after, once both are
        # revealed. tkinter's pack() geometry manager carves up the toplevel's cavity
        # in the ORDER widgets are packed, not by `side` -- a widget packed with
        # fill=both, expand=True (the notebook) claims however much of the cavity is
        # available AT THE TIME it's packed, so if it goes first, anything packed
        # afterward (status_frame -- the bottom status bar showing the grand total
        # prime count/generation time plus the totals-scan progress bar) only gets
        # whatever sliver is left once tab content exceeds the window's height. This
        # is a classic Tk pitfall: dock-to-edge widgets like a status bar must be
        # packed before the fill=both,expand=True central widget, not after -- it
        # only becomes visible once a tab's content grows tall enough to exceed the
        # default 1050x680 window size. Packing status_frame FIRST guarantees its own
        # natural height is always reserved; the notebook (still fill=both,
        # expand=True) then fills whatever remains, exactly as intended.
        status_frame = ttk.Frame(self)
        self._status_frame = status_frame  # stashed so _finish_loading_screen can pack it
        self.status = tk.StringVar(value=_dyn.T("app.status_portal_initial", folder=_dyn.PORTAL_FOLDER))
        ttk.Label(status_frame, textvariable=self.status, anchor="w",
                  style="Status.TLabel").pack(fill="x", side="top")
        # Visible progress bar for the floor-totals background scan -- the status TEXT
        # alone, updating only once per finished floor, makes it look like nothing is
        # happening for the first ~78s on a big floor; a bar that fills in as floors
        # complete, plus a "start" message the instant a floor's scan actually begins
        # (not just when it finishes), makes the in-progress state visibly obvious.
        # Always packed (not shown/hidden dynamically)
        # so its position never jumps around -- sits at 0/0 (empty) until the first batch
        # starts, see TotalsSearchCoordinator.compute_all_floor_totals()/
        # _on_floor_total_start() (primeatlas/core/totals_search_coordinator.py).
        self.totals_progress = ttk.Progressbar(status_frame, orient="horizontal",
                                                 mode="determinate", maximum=1, value=0)
        self.totals_progress.pack(fill="x", side="top")

        notebook = ttk.Notebook(self)

        # Loading screen -- covers both the six tab-build calls and the async tree
        # scans below. Packed and painted (self.update()) BEFORE any tab is built,
        # so the window shows something immediately instead of sitting blank while
        # ttk.Notebook/Treeview widgets for six tabs are constructed.
        loading_frame = ttk.Frame(self)
        loading_frame.pack(fill="both", expand=True)
        loading_center = ttk.Frame(loading_frame)
        loading_center.place(relx=0.5, rely=0.5, anchor="center")
        ttk.Label(loading_center, text=_dyn.T("app.title"),
                  font=("TkDefaultFont", 16, "bold")).pack(pady=(0, 12))
        self._loading_caption = tk.StringVar(value=_dyn.T("app.loading_starting"))
        ttk.Label(loading_center, textvariable=self._loading_caption).pack(pady=(0, 8))
        self._loading_bar = ttk.Progressbar(loading_center, orient="horizontal",
                                             mode="indeterminate", length=280)
        self._loading_bar.pack()
        self._loading_bar.start(12)
        self._loading_frame = loading_frame
        self.update()

        # Saved so other tabs/sub-tab modules can programmatically switch the main
        # notebook (e.g. jumping to the Constellations tab, see
        # _select_constellations_hits_view() below).
        self.main_notebook = notebook

        self.primes_tab = ttk.Frame(notebook)
        self.constellations_tab = ttk.Frame(notebook)
        self.research_tab = ttk.Frame(notebook)
        self.generation_tab = ttk.Frame(notebook)
        self.visualization_tab = ttk.Frame(notebook)
        self.benchmark_tab = ttk.Frame(notebook)
        self.settings_tab_container = ttk.Frame(notebook)
        self.about_tab = ttk.Frame(notebook)
        notebook.add(self.primes_tab, text=_dyn.T("tabs.primes"))
        notebook.add(self.constellations_tab, text=_dyn.T("tabs.constellations"))
        notebook.add(self.research_tab, text=_dyn.T("tabs.research"))
        notebook.add(self.generation_tab, text=_dyn.T("tabs.generation"))
        notebook.add(self.visualization_tab, text=_dyn.T("tabs.visualization"))
        notebook.add(self.benchmark_tab, text=_dyn.T("tabs.benchmark"))
        notebook.add(self.settings_tab_container, text=_dyn.T("tabs.settings"))
        notebook.add(self.about_tab, text=_dyn.T("tabs.about"))
        # Sub-tab frame attribute name -> its ScrollablePage, see _scroll_body().
        self.scroll_pages = {}

        loading_steps = (
            (_dyn.T("tabs.primes"), self._build_primes_section),
            (_dyn.T("tabs.constellations"), self._build_constellations_section),
            (_dyn.T("tabs.research"), self._build_research_section),
            (_dyn.T("tabs.generation"), self._build_generation_tab),
            (_dyn.T("tabs.visualization"), self._build_visualization_section),
            (_dyn.T("tabs.benchmark"), self._build_benchmark_tab),
            (_dyn.T("tabs.settings"), lambda: self._build_settings_tab(SettingsTab)),
            (_dyn.T("tabs.about"), self._build_about_tab),
        )
        for step_name, step_fn in loading_steps:
            self._loading_caption.set(_dyn.T("app.status_loading_step", step=step_name))
            self.update()
            step_fn()

        # Floor-totals + prime/constellation search: two PersistentWorkers, wrapped
        # by TotalsSearchCoordinator (primeatlas/core/totals_search_coordinator.py; see
        # that module's own docstring and README.md's "Known gaps" for the design
        # rationale). Constructed here, AFTER every tab widget above already exists,
        # because it reaches directly into
        # primes_tab_widget/constellations_hits_tab_widget (same construction-
        # order requirement the original inline code already had). on_const_
        # search_result stays a method on THIS class (self._on_const_search_result
        # below) rather than moving into the coordinator -- it's genuine three-tab
        # coordination (Constellations-hits AND Constellations-calc), not part of
        # the two-worker mechanism itself.
        self._totals_search = TotalsSearchCoordinator(
            self, get_portal_folder=lambda: _dyn.PORTAL_FOLDER, status_var=self.status,
            totals_progress=self.totals_progress, translator=_dyn.TRANSLATOR,
            primes_tab_widget=self.primes_tab_widget,
            constellations_hits_tab_widget=self.constellations_hits_tab_widget,
            on_const_search_result=self._on_const_search_result)

        # Primes-tree/Constellations-tree background scan+reload live in their own
        # primeatlas/primes/primes_tree_coordinator.py and
        # primeatlas/constellations/constellations_tree_coordinator.py (see either module's own
        # docstring). Constructed here for the same construction-order reason as
        # TotalsSearchCoordinator: _on_scan_done reaches directly into
        # primes_tab_widget/constellations_hits_tab_widget, both of which already
        # exist by this point. reload_primes_tree()/reload_constellations_tree()
        # below stay as one-line delegating METHODS on this class (not instance
        # attributes reassigned here), so every caller that holds a
        # self.reload_primes_tree/self.reload_constellations_tree reference
        # (PrimesTab, ConstellationsHitsTab, GenerationTab, _set_portal_folder,
        # the startup kickoff further down) resolves it late, at call time.
        self._primes_tree_coord = PrimesTreeCoordinator(
            self, get_portal_folder=lambda: _dyn.PORTAL_FOLDER, status_var=self.status,
            translator=_dyn.TRANSLATOR, primes_tab_widget=self.primes_tab_widget,
            totals_search=self._totals_search,
            prune_empty_floor_dirs=prune_empty_floor_dirs,
            on_startup_scan_done=self._on_tree_startup_scan_done)
        self._constellations_tree_coord = ConstellationsTreeCoordinator(
            self, get_portal_folder=lambda: _dyn.PORTAL_FOLDER, status_var=self.status,
            translator=_dyn.TRANSLATOR,
            constellations_hits_tab_widget=self.constellations_hits_tab_widget,
            prune_empty_floor_dirs=prune_empty_floor_dirs,
            on_startup_scan_done=self._on_tree_startup_scan_done)

        # The three "offer to generate this missing fragment" bridge methods
        # (_offer_generate_missing_prime_window/_offer_generate_missing_constellation/
        # _goldbach_offer_generate_missing_range) live in
        # primeatlas/generation/generation_offer_coordinator.py (see that module's own
        # docstring). Uses a LAZY get_generation_tab_widget callable (unlike the two
        # tree coordinators' direct tab-widget references above) since
        # generation_tab_widget doesn't exist yet at this point in __init__ (the
        # Generation tab is built AFTER this point in loading_steps) -- every one of
        # these three methods is only ever called well after full construction
        # anyway, so this can safely be built here alongside the other coordinators.
        self._generation_offer_coord = GenerationOfferCoordinator(
            get_generation_tab_widget=lambda: self.generation_tab_widget,
            status_var=self.status, translator=_dyn.TRANSLATOR,
            quick_gen_max_window_width=QUICK_GEN_MAX_WINDOW_WIDTH,
            primesieve_max_stop=PRIMESIEVE_MAX_STOP)

        # The primesieve calculator worker (Prime numbers -> primesieve sub-tab)
        # and primality-testing worker (Prime numbers -> Primality tests
        # sub-tab) live entirely inside their own PrimesieveCalcTab/PrimalityTab
        # classes -- each is confirmed exclusive to its own one sub-tab, unlike the
        # shared search/totals workers above, which stay here -- see
        # primeatlas/primality/primesieve_calc_tab.py and primeatlas/primality/primality_tab.py's own
        # docstrings.

        # The Goldbach structural-window worker (Research -> Goldbach sub-tab), its
        # Visualize/decompose Toplevel state, and all their pagination fields
        # live entirely inside ResearchGoldbachTab -- it's confirmed exclusive to
        # that one sub-tab, unlike the shared search/totals workers below, which
        # stay here -- see primeatlas/research/research_goldbach_tab.py's own docstring.

        # The constellation-records-table scan worker (Constellations -> Records
        # table sub-tab) lives entirely inside ConstellationsRecordsTab -- it's
        # confirmed exclusive to that one sub-tab, unlike the shared search/totals
        # workers below, which stay here -- see
        # primeatlas/constellations/constellations_records_tab.py's own docstring.

        # "Generate missing fragment, then re-search" state (_pending_search_after_
        # prime_gen/_pending_search_after_const_gen/_pending_goldbach_retry_op) and
        # the shared-progress-bar step counters (_gen_step_total/_gen_loop_run_count/
        # _gen_loop_iteration) live in GenerationTab's own __init__ -- they're
        # exclusively read/written by Generation-tab methods (see
        # primeatlas/generation/generation_tab.py's own docstring). App-level code that sets the
        # first three from OUTSIDE the tab (_offer_generate_missing_prime_window/
        # _offer_generate_missing_constellation/_goldbach_offer_generate_missing_range,
        # all below) reaches in via self.generation_tab_widget.X instead.

        # reload_benchmark_log() stays synchronous here -- it's one small CSV read,
        # not a per-floor disk scan (see reload_primes_tree()'s own docstring for the
        # cost distinction) -- so it's cheap enough to keep on the GUI thread even
        # during the loading screen.
        self.benchmark_tab_widget.reload_benchmark_log()
        # reload_primes_tree()/reload_constellations_tree() are BOTH asynchronous
        # (see their own docstrings) -- each dispatches its disk scan onto
        # background.run_in_background() and returns immediately. _loading_startup_
        # pending tracks which of the two startup scans are still outstanding;
        # _on_primes_tree_scan_done/_on_hits_tree_scan_done each discard their own
        # name from this set and call _finish_loading_screen() once it's empty, which
        # is what actually reveals status_frame/notebook. Every LATER call to either
        # reload function (Refresh button, storage-path change, etc.) finds this
        # attribute already None (see _finish_loading_screen) and skips the check.
        self._loading_startup_pending = {"primes", "constellations"}
        self._loading_caption.set(_dyn.T("app.status_loading_data"))
        self.update()
        self.reload_primes_tree()  # this ALSO kicks off the floor-totals scan for every
                                    # floor -- see reload_primes_tree()'s docstring
        self.reload_constellations_tree()

        # Closing while a Generation-tab job runs asks first, and a generation run the
        # previous session never saw finish is settled now (CLOSE_GUARD_PLAN.md).
        self.protocol("WM_DELETE_WINDOW", lambda: close_guard.request_close(
            self, self.generation_tab_widget, _dyn.T))
        self.generation_tab_widget.recover_previous_run(on_done=self.reload_primes_tree)

        # App self-update auto-check -- deferred several seconds past
        # startup (not run inline here) so a `git fetch` against GitHub -- a real
        # network round-trip that can be slow or simply hang on a bad connection --
        # never delays the loading screen or the two tree scans just kicked off
        # above. Reuses SettingsTab's own _check_for_app_update() (built for the
        # manual 'Check now' button) rather than duplicating its network-thread/
        # dialog/download logic here -- single code path, so the Settings tab's
        # status label reflects this automatic check too, not just manual ones.
        # Only actually runs if AppSettings.auto_update_check is on (default True;
        # see that property's own docstring) -- settings_tab is already fully built
        # by this point (every loading_steps entry above has run).
        if _dyn.APP_SETTINGS.auto_update_check:
            self.after(_const.APP_UPDATE_STARTUP_CHECK_DELAY_MS,
                       self.settings_tab._check_for_app_update)

    def _finish_loading_screen(self):
        """Reveals the real UI (status_frame + notebook) and tears down the loading
        overlay -- called once from _on_tree_startup_scan_done, once whichever of the
        two startup scans finishes LAST (see _loading_startup_pending's own comment in
        __init__). Safe to call at most once per app lifetime: _on_tree_startup_scan_done
        nulls out _loading_startup_pending before calling this, and every other
        reload_*_tree() call site checks that attribute is still a non-empty set before
        ever touching this method."""
        self._loading_bar.stop()
        self._loading_frame.destroy()
        self._status_frame.pack(fill="x", side="bottom")
        self.main_notebook.pack(fill="both", expand=True)

    def _on_tree_startup_scan_done(self, name):
        """Shared completion seam for BOTH PrimesTreeCoordinator and
        ConstellationsTreeCoordinator's own on_startup_scan_done callback (see either
        module's own docstring) -- genuinely shared state (one _loading_startup_pending
        set, one _finish_loading_screen call) that neither coordinator should own or
        reach into on the other's behalf, so it stays here rather than moving into
        either extracted class. `name` is "primes" or "constellations"."""
        pending = getattr(self, "_loading_startup_pending", None)
        if pending:
            pending.discard(name)
            if not pending:
                self._finish_loading_screen()

    # Floor-total background worker, prime/constellation search worker: live in
    # primeatlas/core/totals_search_coordinator.py's TotalsSearchCoordinator -- see that
    # module's own docstring and __init__ above (self._totals_search).

    def _scroll_body(self, name):
        """Wraps the page frame `self.<name>` in a ScrollablePage (scrollbar and
        ScrollPad only while its content does not fit) and returns the frame the
        page's tab widget is built into."""
        from primeatlas.core.widgets import ScrollablePage
        page = ScrollablePage(getattr(self, name), pad_text=_dyn.T("common.scroll_pad"))
        self.scroll_pages[name] = page
        return page.body
