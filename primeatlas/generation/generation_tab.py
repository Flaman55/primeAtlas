"""
generation_tab.py -- GenerationTab, the Generation tab: the Quick generation panel, the
orchestrator_loop_v2.py pipeline form (Section A), the constellation_finder_v2_2.py search
form (Section B) and the k-tuple sieve form (Section C), each with its Run/Stop buttons
and console, plus the shared bottom progress bar.

This module builds the tab and owns the state every part shares; the parts live in mixins:
quick_gen_panel.py (panel widgets), quick_gen_runs.py (per-engine launchers),
quick_gen_plan.py (fields -> launch), loop_section.py, constellation_section.py and
ktuple_section.py (Sections A-C), run_progress.py (output draining and the progress bar),
hybrid_controls.py and run_guard_controls.py. Three pieces of the tab's state are shared
with code outside it:

  - status_var/totals_progress: the SAME StringVar/Progressbar every other tab's
    background worker also writes to (one shared status bar, not one per tab) -- same
    injection pattern as every other extracted tab, see primeatlas/primes/primes_tab.py's own
    docstring.
  - reload_primes_tree/reload_constellations_tree: app-level methods that rebuild the
    OTHER two tabs' trees -- called from _on_loop_finished()/_on_constellation_finished()
    once a generation run completes, so newly-written windows/hits show up there without
    a manual Refresh click.
  - research_goldbach_tab_widget: _on_loop_finished() calls back into its retry_viz()/
    retry_decompose() methods once a Goldbach-triggered "generate the missing range" run
    finishes (see research_goldbach_tab.py's own docstring for the other half of this
    pair) -- safe to inject directly (not via a generic callback) since the Research tab
    is built BEFORE the Generation tab (see prime_atlas_v2.py's __init__ tab-build order),
    so this widget already exists by the time GenerationTab's constructor runs.

The REVERSE direction -- app-level code (search-miss handlers in the Prime numbers/
Constellations tabs, and the Goldbach tab's own missing-range offer) reaching INTO this
tab to launch a generation run -- stays app-level by necessity (search misses/Goldbach
gaps aren't this tab's own concern) and reaches through the constructed
GenerationTab instance directly (self.generation_tab_widget.X in prime_atlas_v2.py) for:
_quick_gen_plan_literal_range, _launch_direct_window_range,
_apply_primesieve_params_and_run, _apply_orchestrator_direct_params_and_run,
_on_run_constellation, _loop_runner, _const_runner, _const_base_exponent_var, and the
three pending-retry slots (_pending_search_after_prime_gen, _pending_search_after_const_
gen, _pending_goldbach_retry_op) -- see prime_atlas_v2.py's own
_offer_generate_missing_prime_window/_offer_generate_missing_constellation/
_goldbach_offer_generate_missing_range docstrings for the full reasoning on why those
three specific methods stay at the app level rather than moving here.
"""
import datetime

from tkinter import ttk

from ..core.base_tab import BaseTab
from ..core.widgets import ScrollablePage
from .hybrid_controls import HybridControls
from .run_guard_controls import RunGuardControls
from .quick_gen_panel import QuickGenPanel
from .quick_gen_runs import QuickGenRuns
from .quick_gen_plan import QuickGenPlan
from .loop_section import LoopSection
from .constellation_section import ConstellationSection
from .ktuple_section import KtupleSection
from .run_progress import GenerationRunProgress
from .generation_settings import load_generation_settings
from .logged_runners import WslLoggedRunner


class GenerationTab(QuickGenPanel, QuickGenRuns, QuickGenPlan, LoopSection,
                    ConstellationSection, KtupleSection, GenerationRunProgress,
                    HybridControls, RunGuardControls, BaseTab):
    def __init__(self, parent, get_portal_folder, status_var, translator,
                 totals_progress, reload_primes_tree, reload_constellations_tree,
                 research_goldbach_tab_widget):
        """
        get_portal_folder/status_var/translator/totals_progress: same dependency-
        injection pattern as every other extracted tab -- see primeatlas/primes/primes_tab.py's
        own docstring.

        reload_primes_tree/reload_constellations_tree/research_goldbach_tab_widget: see
        this module's own docstring for why these three specific cross-tab references
        are injected directly rather than via single-purpose callbacks -- unlike the
        Goldbach tab's offer_generate_missing_range (a single, well-defined action),
        these three are called from several different places inside this tab's own
        completion handlers.
        """
        super().__init__(parent, translator)
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self.totals_progress = totals_progress
        self.reload_primes_tree = reload_primes_tree
        self.reload_constellations_tree = reload_constellations_tree
        self.research_goldbach_tab_widget = research_goldbach_tab_widget

        # "Generate missing fragment, then re-search" state -- set by prime_atlas_v2.py's
        # own _offer_generate_missing_prime_window()/_offer_generate_missing_constellation()
        # (reaching in as self.generation_tab_widget._pending_search_after_prime_gen, etc.)
        # right before launching a generation run in response to a search miss, and
        # consumed (cleared + the original search re-run) by _on_loop_finished()/
        # _on_constellation_finished() below once that SPECIFIC run's exit sentinel
        # arrives. See prime_atlas_v2.py's own _offer_generate_missing_prime_window
        # docstring for the full two-slot reasoning (a "const" search miss can set the
        # prime-window slot first, then the constellation slot on a later re-search).
        self._pending_search_after_prime_gen = None
        self._pending_search_after_const_gen = None

        # Same idea, one more slot: a Visualize/decompose job that hit
        # MissingStorageRangeError and whose "generate this range?" offer was accepted --
        # see prime_atlas_v2.py's own _goldbach_offer_generate_missing_range docstring.
        # Records WHICH op to retry ("viz" or "decompose", None = nothing pending).
        self._pending_goldbach_retry_op = None
        # A multi-step "fill this range into storage" plan (see start_storage_fill):
        # None, or {"launches": remaining steps, "on_finished": callback}.
        self._pending_storage_fill = None

        # Whole-pipeline step count for the shared bottom progress bar -- see
        # _update_shared_progress_from_generation_chunk()'s own docstring below. None
        # between runs / before the first batch-progress line of a run has arrived.
        self._gen_step_total = None
        # Multi-iteration Exploration-mode loop state, same lazy None-between-runs
        # lifecycle as _gen_step_total above.
        self._gen_loop_run_count = None
        self._gen_loop_iteration = None
        # Whether the CURRENTLY RUNNING engine actually prints anything
        # _update_shared_progress_from_generation_chunk() can parse mid-run -- see
        # that method's own _set_gen_progress_bar() helper for the full rationale
        # (primesieve/cudasieve mode's own stdout has nothing granular to show, so the
        # bar was jumping straight from empty to "100% done" with nothing meaningful in
        # between -- worse than just leaving it alone). Defaults True (the old
        # batched engine's behavior, which DOES print granular progress); each
        # _on_run_*() launcher below sets this to match its own engine right before
        # starting.
        self._gen_progress_bar_active = True

        self._build_generation_tab()

    def _build_scrollable_container(self, parent):
        """Wraps `parent` in a ScrollablePage and returns `(body, register_exclude)`: the
        frame the tab's content is packed into, and the call that keeps the wheel over a
        nested self-scrolling widget (a console) from scrolling the page. The three
        sections (pipeline, constellation search, k-tuple search), each with its Advanced
        fields and its own GenerationConsole, can be taller than the window."""
        self._scroll_page = ScrollablePage(parent, pad_text=self.T("common.scroll_pad"))
        self._scroll_pad = self._scroll_page.pad
        return self._scroll_page.body, self._scroll_page.register_exclude

    def _build_generation_tab(self):
        """Two independent sections ("Separate calls and parameterization"):
        orchestrator_loop_v2.py's full generation pipeline on
        top, constellation_finder_v2_2.py's k-tuple search below -- each with its own
        form (every CLI parameter those scripts expose, including the ones that used
        to require editing source files -- see orchestrator_v3.py's/orchestrator_
        loop_v2.py's workers/batches_per_worker/window_count_per_run CLI-exposure
        changes), its own Run/Stop pair, and its own live output pane. Form
        values are loaded from .portal_generation_settings.json once here and
        persisted again every time Run is pressed (see _on_run_loop/
        _on_run_constellation) -- so the next app start reopens with
        whatever was last used, no re-typing needed."""
        self._generation_settings = load_generation_settings(self._get_portal_folder())

        # Scrollable wrapper (see _build_scrollable_container's own docstring) --
        # everything below packs into `generation_body`, not into
        # self.generation_tab directly, so the tab as a whole gains a vertical
        # scrollbar/mousewheel once Sections A+B+C together exceed the window's
        # visible height, instead of silently cutting off whatever doesn't fit.
        generation_body, self._register_scroll_exclude = self._build_scrollable_container(self)

        self._init_quick_generation_state()
        quick_outer = ttk.Labelframe(generation_body, text=self.T("quick.section_title"))
        quick_outer.pack(fill="x", padx=6, pady=(6, 0))
        self._build_quick_generation_panel(quick_outer)

        # Sections stack at their natural height; each console's own HeightGrip sets
        # how tall its output is.
        sections = ttk.Frame(generation_body)
        sections.pack(fill="both", expand=True, padx=6, pady=6)
        self._build_loop_section(sections)
        self._build_constellation_section(sections)
        self._build_ktuple_section(sections)

        self.after(150, self._poll_loop_output)
        self.after(150, self._poll_constellation_output)
        self.after(150, self._poll_ktuple_output)

    def _new_run_separator(self):
        """Appended (not clear()'d -- see _on_run_loop/_on_run_constellation) at the
        start of every run, so several runs' output can stay stacked in the console
        for comparison instead of being wiped on every click. The Clear button (see
        GenerationConsole) is the only thing that actually empties the console now."""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        return "\n" + "=" * 70 + f"\n{self.T('gen.new_run_marker', time=ts)}\n" + "=" * 70 + "\n"

    def _new_wsl_runner(self, *args, **kwargs):
        """A WslLoggedRunner for every section, looked up at call time so tests can
        swap this module's WslLoggedRunner."""
        return WslLoggedRunner(*args, **kwargs)
