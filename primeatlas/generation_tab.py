"""
generation_tab.py -- GenerationTab, the tkinter widgets for the Generation tab: the
Quick-gen panel (Floor/Range/Exploration/primesieve modes), the low-level
orchestrator_loop_v2.py pipeline form (Section A), the constellation_finder_v1.py search
form (Section B), and the k-tuple sieve form (Section C) -- plus every launch/poll/finish
handler behind their Run/Stop buttons and the shared bottom progress bar.

Extracted from prime_atlas_v1.py during the refactor branch's Faza 3 (tab-by-tab
backend/UI split, 2026-08-23), alongside the tab's own pure-logic split
(see generation.py's own docstring). This is the largest of the five tab extractions
(~2571 lines) and the one with the most cross-tab coupling -- three separate pieces of
this tab's own state are shared with code OUTSIDE it:

  - status_var/totals_progress: the SAME StringVar/Progressbar every other tab's
    background worker also writes to (one shared status bar, not one per tab) -- same
    injection pattern as every other extracted tab, see primeatlas/primes_tab.py's own
    docstring.
  - reload_primes_tree/reload_constellations_tree: app-level methods that rebuild the
    OTHER two tabs' trees -- called from _on_loop_finished()/_on_constellation_finished()
    once a generation run completes, so newly-written windows/hits show up there without
    a manual Refresh click.
  - research_goldbach_tab_widget: _on_loop_finished() calls back into its retry_viz()/
    retry_decompose() methods once a Goldbach-triggered "generate the missing range" run
    finishes (see research_goldbach_tab.py's own docstring for the other half of this
    pair) -- safe to inject directly (not via a generic callback) since the Research tab
    is built BEFORE the Generation tab (see prime_atlas_v1.py's __init__ tab-build order),
    so this widget already exists by the time GenerationTab's constructor runs.

The REVERSE direction -- app-level code (search-miss handlers in the Prime numbers/
Constellations tabs, and the Goldbach tab's own missing-range offer) reaching INTO this
tab to launch a generation run -- stays app-level by necessity (search misses/Goldbach
gaps aren't this tab's own concern) and reaches through the constructed
GenerationTab instance directly (self.generation_tab_widget.X in prime_atlas_v1.py) for:
_quick_gen_plan_literal_range, _launch_direct_window_range,
_apply_primesieve_params_and_run, _apply_orchestrator_direct_params_and_run,
_on_run_constellation, _loop_runner, _const_runner, _const_base_exponent_var, and the
three pending-retry slots (_pending_search_after_prime_gen, _pending_search_after_const_
gen, _pending_goldbach_retry_op) -- see prime_atlas_v1.py's own
_offer_generate_missing_prime_window/_offer_generate_missing_constellation/
_goldbach_offer_generate_missing_range docstrings for the full reasoning on why those
three specific methods stay at the app level rather than moving here.
"""
import datetime
import queue

import tkinter as tk
from tkinter import ttk, messagebox

import pattern_catalog_v1

from .generation_console import GenerationConsole
from .storage import digit_count_floor, LOW_FLOOR_CUTOFF
from .generation import (
    QUICK_GEN_MAX_WINDOW_WIDTH, count_existing_windows, find_continuation_target_idx,
    find_first_gap_target_idx, _trim_existing_from_target_idx_range,
    find_highest_populated_floor, _eval_quick_number, _round_range_to_window,
    _floor_window_count, _KTUPLE_STRATEGY_KEYS, load_generation_settings,
    save_generation_settings, recommended_digit_sweep_n_locations, PRIMESIEVE_MAX_STOP,
    PRIMESIEVE_MAX_WIDTH_MULT, build_loop_argv, build_primesieve_argv,
    build_orchestrator_direct_argv, build_constellation_finder_argv,
    build_ktuple_sieve_argv, generation_log_paths, build_wsl_logged_command,
    estimate_wsl_available_ram_bytes, recommended_max_windows,
    estimate_wsl_available_cpu_count, recommended_worker_count, WslLoggedRunner,
    _LOOP_SESSION_DONE_RE, _LOOP_SESSION_START_RE, _LOOP_ITERATION_START_RE,
    _GEN_SIEVE_DONE_RE, _GEN_CONST_DONE_RE, _GEN_SIEVE_PROGRESS_RE,
    _GEN_CONST_PROGRESS_RE, _GEN_PREP_DONE_RE,
)


class GenerationTab(ttk.Frame):
    def __init__(self, parent, get_portal_folder, status_var, translator,
                 totals_progress, reload_primes_tree, reload_constellations_tree,
                 research_goldbach_tab_widget):
        """
        get_portal_folder/status_var/translator/totals_progress: same dependency-
        injection pattern as every other extracted tab -- see primeatlas/primes_tab.py's
        own docstring.

        reload_primes_tree/reload_constellations_tree/research_goldbach_tab_widget: see
        this module's own docstring for why these three specific cross-tab references
        are injected directly rather than via single-purpose callbacks -- unlike the
        Goldbach tab's offer_generate_missing_range (a single, well-defined action),
        these three are called from several different places inside this tab's own
        completion handlers.
        """
        super().__init__(parent)
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self.T = translator
        self.totals_progress = totals_progress
        self.reload_primes_tree = reload_primes_tree
        self.reload_constellations_tree = reload_constellations_tree
        self.research_goldbach_tab_widget = research_goldbach_tab_widget

        # "Generate missing fragment, then re-search" state -- set by prime_atlas_v1.py's
        # own _offer_generate_missing_prime_window()/_offer_generate_missing_constellation()
        # (reaching in as self.generation_tab_widget._pending_search_after_prime_gen, etc.)
        # right before launching a generation run in response to a search miss, and
        # consumed (cleared + the original search re-run) by _on_loop_finished()/
        # _on_constellation_finished() below once that SPECIFIC run's exit sentinel
        # arrives. See prime_atlas_v1.py's own _offer_generate_missing_prime_window
        # docstring for the full two-slot reasoning (a "const" search miss can set the
        # prime-window slot first, then the constellation slot on a later re-search).
        self._pending_search_after_prime_gen = None
        self._pending_search_after_const_gen = None

        # Same idea, one more slot: a Wizualizacja/decompose job that hit
        # MissingStorageRangeError and whose "generate this range?" offer was accepted --
        # see prime_atlas_v1.py's own _goldbach_offer_generate_missing_range docstring.
        # Records WHICH op to retry ("viz" or "decompose", None = nothing pending).
        self._pending_goldbach_retry_op = None

        # Whole-pipeline step count for the shared bottom progress bar -- see
        # _update_shared_progress_from_generation_chunk()'s own docstring below. None
        # between runs / before the first batch-progress line of a run has arrived.
        self._gen_step_total = None
        # Multi-iteration Exploration-mode loop state, same lazy None-between-runs
        # lifecycle as _gen_step_total above.
        self._gen_loop_run_count = None
        self._gen_loop_iteration = None

        self._build_generation_tab()

    def _build_scrollable_container(self, parent):
        """Wraps `parent` in a vertically-scrollable canvas+frame and returns the
        inner ttk.Frame -- pack the tab's REAL content into that returned frame
        instead of into `parent` directly; everything else (canvas, scrollbar,
        width sync, mousewheel binding) is handled here. Added 2026-08-19 because
        the Generation tab's three sections (A: pipeline, B: constellation search,
        C: k-tuple search -- each with its own Advanced-fields block and its own
        GenerationConsole terminal) together need more vertical space than the
        1050x680 main window has, and a plain pack()/Panedwindow layout has no way
        to reach whatever falls below the visible area -- Section C being added
        last effectively pushed A/B's terminals and advanced fields (write_files,
        compute_sieving_primes_count, etc.) out of reach even though nothing was
        actually removed. This is a pure ADDITIVE wrapper (same rule as
        digit_sweep/pass_counter above: extend, don't replace) -- it changes
        nothing about what's inside, only how it's reached once it doesn't fit.

        Standard canvas-scrollregion idiom: an inner frame is placed on a canvas
        via create_window; the inner frame's own <Configure> (fires whenever its
        packed children change its natural size) updates the canvas' scrollregion
        to match, and the canvas' own <Configure> (fires on window resize) keeps
        the inner frame exactly as WIDE as the visible canvas so fill="x" widgets
        inside it still span the full width like they did before this wrapper
        existed, instead of collapsing to their minimum content width. Mousewheel
        scrolling is bound only while the pointer is actually over this canvas
        (bound on <Enter>, unbound on <Leave>) so it doesn't steal wheel events
        from Treeviews or other scrollable widgets on other tabs. <MouseWheel>
        covers Windows/Mac; <Button-4>/<Button-5> cover X11 (Linux) which reports
        the wheel as button clicks instead of a delta."""
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, highlightthickness=0)
        # ROOT CAUSE (found 2026-08-23 via live debug logging on the cudasieve
        # branch's forked copy of this exact idiom, prime_atlas_v2.py): Tk's
        # Canvas defaults to yscrollincrement=0, which makes any "scroll N units"
        # call (mousewheel, scrollbar arrows) jump by ~10% of the canvas's
        # CURRENT VIEWPORT height -- not a small fixed pixel step. When the real
        # content is SHORTER than the viewport (nothing to scroll to at all), Tk
        # does not clamp that oversized jump back to 0; the view is left
        # negative, which visually shows as blank canvas ABOVE the content that
        # grows with every further wheel tick (confirmed live: canvas.yview()
        # kept reporting (0.0, 1.0) -- Tk itself thought nothing had scrolled --
        # while the content's on-screen position kept sliding down). A small
        # fixed increment alone doesn't fully fix this, so scrolling is also
        # hard-disabled below whenever content already fits the viewport (see
        # _content_fits()).
        canvas.configure(yscrollincrement=20)

        # `scroll_state["user_scrolled"]` starts False and flips to True the first
        # time the person actually drags the scrollbar or spins the wheel (see the
        # three handlers below). Until that happens, `_sync_scrollregion()` keeps
        # re-pinning the view to the top -- see that function's own comment for why
        # this is needed, not just the scrollregion-size fix below it.
        scroll_state = {"user_scrolled": False}

        def _content_fits():
            # Nothing to scroll to -- content already fits inside the visible
            # canvas. winfo_height() is 0/1 before the widget is first mapped,
            # so treat that as "doesn't fit yet" rather than "fits".
            canvas_h = canvas.winfo_height()
            return canvas_h > 1 and inner.winfo_reqheight() <= canvas_h

        def _on_scrollbar(*args):
            if _content_fits():
                return
            scroll_state["user_scrolled"] = True
            canvas.yview(*args)

        vsb = ttk.Scrollbar(outer, orient="vertical", command=_on_scrollbar)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        inner = ttk.Frame(canvas)
        inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        # NOTE (2026-08-23 fix): scrollregion is set from inner.winfo_reqwidth()/
        # reqheight() -- NOT canvas.bbox("all"). bbox("all") is the bounding box of
        # everything ever drawn on the canvas and can end up taller than the frame's
        # actual current content (e.g. right after a mode switch collapses a section
        # via grid_remove(), or during the width-driven reflow below, before layout
        # has fully settled) -- Tk then happily lets yview scroll into that stale
        # leftover space, which is exactly the "top isn't pinned, you can scroll to
        # blank space" bug Artur reported. Querying the frame's own requested size
        # directly is always in sync with what's actually packed inside it right now,
        # so the scrollregion can never exceed real content.
        #
        # That alone wasn't enough: this tab's content keeps changing height AFTER
        # it first draws (Quick-gen mode switches via grid()/grid_remove(), Advanced
        # sections collapsing) and Tk does not guarantee the view stays pinned to
        # the top pixel across a scrollregion resize -- it can drift, leaving a
        # blank gap above the real content with the scrollbar thumb sitting
        # somewhere in the middle even though nothing was ever manually scrolled.
        # So: as long as the person hasn't manually scrolled yet -- OR content
        # fits and there's nothing to scroll to regardless -- force the view
        # back to the top on every resync.
        def _sync_scrollregion():
            canvas.configure(scrollregion=(0, 0, inner.winfo_reqwidth(), inner.winfo_reqheight()))
            # STRETCH FIX (2026-08-23): a canvas window item's height is never
            # auto-stretched to fill leftover viewport space -- by default it's
            # always exactly inner's natural winfo_reqheight(), even though
            # inner.pack(fill="both", expand=True) suggests otherwise. That was
            # invisible on tabs whose content is a flat stack of widgets, but on
            # the Generation tab, `inner` (generation_body) holds a
            # ttk.Panedwindow packed with fill="both", expand=True -- the paned
            # window can only hand its panes MORE than their minimum size if it
            # is itself GIVEN more than its minimum size, which never happened,
            # so a bigger-than-content main window just left blank canvas below
            # the last pane instead of growing the three sections proportionally
            # (per their existing weight=1 shares -- see Artur's report). When
            # content fits the viewport, explicitly stretch the window item to
            # the full viewport height so expand=True children actually receive
            # that extra space; otherwise set it back to the natural height
            # explicitly (needed for scrolling -- see _content_fits()). NOTE:
            # height="" (Tk's documented way to say "go back to the window's
            # own requested size") throws TclError: bad screen distance "" on
            # this Tk/Python combination -- passing the natural height itself
            # is equivalent and doesn't hit that.
            canvas_h = canvas.winfo_height()
            natural_h = inner.winfo_reqheight()
            if canvas_h > 1 and natural_h <= canvas_h:
                canvas.itemconfigure(inner_window, height=canvas_h)
            elif natural_h > 0:
                canvas.itemconfigure(inner_window, height=natural_h)
            if not scroll_state["user_scrolled"] or _content_fits():
                canvas.yview_moveto(0.0)

        def _on_inner_configure(_event):
            _sync_scrollregion()
        inner.bind("<Configure>", _on_inner_configure)

        def _on_canvas_configure(event):
            canvas.itemconfigure(inner_window, width=event.width)
            # Changing the inner frame's width can immediately change its required
            # height (wraplength'd Labels reflow) -- resync right away instead of
            # waiting on inner's own <Configure> so a window resize can't leave a
            # stale, too-tall scrollregion behind for even one frame.
            canvas.after_idle(_sync_scrollregion)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            if _content_fits():
                return
            scroll_state["user_scrolled"] = True
            canvas.yview_scroll(int(-3 * (event.delta / 120)), "units")

        def _on_button4(_event):
            if _content_fits():
                return
            scroll_state["user_scrolled"] = True
            canvas.yview_scroll(-3, "units")

        def _on_button5(_event):
            if _content_fits():
                return
            scroll_state["user_scrolled"] = True
            canvas.yview_scroll(3, "units")

        def _bind_mousewheel(_event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            canvas.bind_all("<Button-4>", _on_button4)
            canvas.bind_all("<Button-5>", _on_button5)

        def _unbind_mousewheel(_event):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", _bind_mousewheel)
        canvas.bind("<Leave>", _unbind_mousewheel)

        return inner

    def _build_generation_tab(self):
        """Two independent sections ("Separate calls and parameterization"):
        orchestrator_loop_v2.py's full generation pipeline on
        top, constellation_finder_v1.py's k-tuple search below -- each with its own
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
        generation_body = self._build_scrollable_container(self)

        self._init_quick_generation_state()
        quick_outer = ttk.Labelframe(generation_body, text=self.T("quick.section_title"))
        quick_outer.pack(fill="x", padx=6, pady=(6, 0))
        self._build_quick_generation_panel(quick_outer)

        paned = ttk.Panedwindow(generation_body, orient="vertical")
        paned.pack(fill="both", expand=True, padx=6, pady=6)

        # --- Section A: orchestrator_loop_v2.py (generation pipeline) ------------
        loop_outer = ttk.Labelframe(
            paned, text=self.T("gen.section_loop"))
        paned.add(loop_outer, weight=1)

        # These are advanced settings, so base_exponent/run_count/
        # n_instances/window_count_per_run/workers/batches_per_worker/window_m (plus
        # the two checkboxes) collapse behind a toggle button, collapsed by default.
        #
        # loop_btn_row (Run/Stop/status) is hidden along with them: the raw
        # Run button only makes sense once you can actually SEE what it'll run
        # with, so loop_btn_row now lives INSIDE the same collapsible block as the
        # fields, not next to it -- one toggle hides/shows both together. The normal
        # way to run is now the Quick-gen "Generate" button above
        # (_on_quick_generate_or_stop_clicked), which doubles as Stop while a run is
        # in flight (see _on_run_loop/_on_loop_finished).
        loop_advanced_row = ttk.Frame(loop_outer)
        loop_advanced_row.pack(fill="x", padx=8, pady=(6, 0))
        self._loop_advanced_visible = False
        self.loop_advanced_toggle_btn = ttk.Button(
            loop_advanced_row, text=self.T("gen.advanced_show"),
            command=self._on_toggle_loop_advanced)
        self.loop_advanced_toggle_btn.pack(side="left")

        loop_advanced_content = ttk.Frame(loop_outer)
        self._loop_advanced_content = loop_advanced_content
        # NOT packed here -- starts collapsed, see _on_toggle_loop_advanced(). Packed
        # (when shown) with before=self.loop_console.toggle_row so it always lands
        # right below the toggle button, above the console's own toggle row.

        loop_form = ttk.Frame(loop_advanced_content)
        loop_form.pack(fill="x")

        self._loop_vars = {}
        loop_settings = self._generation_settings["loop"]

        def add_loop_field(row, col, key, label, width=10):
            ttk.Label(loop_form, text=label).grid(
                row=row, column=col * 2, sticky="w", padx=(0, 4), pady=2)
            var = tk.StringVar(value=str(loop_settings.get(key, "")))
            ttk.Entry(loop_form, textvariable=var, width=width).grid(
                row=row, column=col * 2 + 1, sticky="w", padx=(0, 20), pady=2)
            self._loop_vars[key] = var

        add_loop_field(0, 0, "base_exponent", self.T("gen.field_base_exponent"))
        add_loop_field(0, 1, "run_count", self.T("gen.field_run_count"))
        add_loop_field(1, 0, "n_instances", self.T("gen.field_n_instances"))
        add_loop_field(1, 1, "window_count_per_run", self.T("gen.field_window_count"))
        add_loop_field(2, 0, "workers", self.T("gen.field_workers"))
        # Auto button for "workers", same idea as Quick generation's own RAM-based
        # Auto button for window count (_on_quick_auto_width_clicked) -- probes
        # WSL's available CPU count and fills the field with it (see
        # _on_workers_auto_clicked's own docstring). Occupies the grid slot
        # batches_per_worker used to sit in (raw column 2); batches_per_worker
        # itself moves one field-slot to the right (col=2 -> raw columns 4/5) to
        # make room, rather than crowding a fourth thing onto this row.
        ttk.Button(loop_form, text=self.T("quick.auto_button"), width=6,
                   command=self._on_workers_auto_clicked).grid(
            row=2, column=2, sticky="w", padx=(0, 8), pady=2)
        add_loop_field(2, 2, "batches_per_worker", self.T("gen.field_batches"))
        # window_m: was hardcoded to 10,000,000 in three separate scanner/orchestrator
        # files -- now a real CLI-overridable parameter, threaded all the way down to
        # prime_sieve_v3.py (see build_loop_argv()'s docstring for the full chain and
        # the "only safe to change for a floor with no existing data" caveat).
        add_loop_field(3, 0, "window_m", self.T("gen.field_window_m"), width=14)

        self._loop_write_files_var = tk.BooleanVar(
            value=bool(loop_settings.get("write_files", True)))
        ttk.Checkbutton(loop_form, text=self.T("gen.check_write_files"),
                         variable=self._loop_write_files_var).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._loop_count_sieving_var = tk.BooleanVar(
            value=bool(loop_settings.get("compute_sieving_primes_count", False)))
        ttk.Checkbutton(
            loop_form, text=self.T("gen.check_count_sieving"),
            variable=self._loop_count_sieving_var).grid(
            row=4, column=2, columnspan=2, sticky="w", pady=(6, 0))

        loop_btn_row = ttk.Frame(loop_advanced_content)
        loop_btn_row.pack(fill="x", pady=(6, 0))
        self.loop_run_btn = ttk.Button(loop_btn_row, text=self.T("common.run"), command=self._on_run_loop)
        self.loop_run_btn.pack(side="left")
        self.loop_stop_btn = ttk.Button(
            loop_btn_row, text=self.T("common.stop"), command=self._on_stop_loop, state="disabled")
        self.loop_stop_btn.pack(side="left", padx=(6, 0))
        self.loop_status_label = tk.StringVar(value=self.T("common.ready"))
        ttk.Label(loop_btn_row, textvariable=self.loop_status_label).pack(
            side="left", padx=(12, 0))

        # Each terminal pane (loop and constellation) has its own collapse toggle,
        # collapsed whenever its script isn't running: own toggle, collapsed on every
        # app start (no persisted state), auto-expanded by _show_loop_terminal() the
        # moment a run actually starts (_on_run_loop), and deliberately left alone
        # (never auto-collapsed) once it finishes -- see _on_loop_finished. Toggle/
        # clear/open-in-new-window live together in GenerationConsole (primeatlas/
        # generation_console.py), reused identically by this section and the
        # constellation-finder section below. The detached window additionally gets
        # its own copy of the Quick-gen panel (see _build_detached_quick_panel), bound
        # to the SAME shared StringVars as the embedded one, so both always show the
        # same values and a run started from either place behaves identically.
        self.loop_console = GenerationConsole(
            loop_outer, self.T, height=20,
            extra_controls_builder=self._build_detached_quick_panel,
            on_change=self._refresh_generation_pane_minsize)
        self.loop_output = self.loop_console.text

        self._loop_runner = None
        self._loop_output_queue = queue.Queue()

        # --- Section B: constellation_finder_v1.py (k-tuple search) --------------
        const_outer = ttk.Labelframe(
            paned, text=self.T("gen.section_const"))
        paned.add(const_outer, weight=1)

        const_form = ttk.Frame(const_outer)
        const_form.pack(fill="x", padx=8, pady=6)
        const_settings = self._generation_settings["constellation"]
        ttk.Label(const_form, text=self.T("gen.const_field_base_exponent")).pack(
            side="left")
        self._const_base_exponent_var = tk.StringVar(
            value=str(const_settings.get("base_exponent", "")))
        ttk.Entry(const_form, textvariable=self._const_base_exponent_var, width=10).pack(
            side="left", padx=(6, 0))

        const_btn_row = ttk.Frame(const_outer)
        const_btn_row.pack(fill="x", padx=8, pady=(0, 4))
        self.const_run_btn = ttk.Button(
            const_btn_row, text=self.T("common.run"), command=self._on_run_constellation)
        self.const_run_btn.pack(side="left")
        self.const_stop_btn = ttk.Button(
            const_btn_row, text=self.T("common.stop"), command=self._on_stop_constellation,
            state="disabled")
        self.const_stop_btn.pack(side="left", padx=(6, 0))
        self.const_status_label = tk.StringVar(value=self.T("common.ready"))
        ttk.Label(const_btn_row, textvariable=self.const_status_label).pack(
            side="left", padx=(12, 0))

        # Collapsible terminal, same as the pipeline section's loop_console above --
        # see GenerationConsole's docstring for the full rationale. No extra_controls_
        # builder here -- the constellation-finder section has no Quick-gen-style panel
        # to duplicate, only its own raw Run/Stop pair above.
        self.const_console = GenerationConsole(
            const_outer, self.T, height=20,
            on_change=self._refresh_generation_pane_minsize)
        self.const_output = self.const_console.text

        self._const_runner = None
        self._const_output_queue = queue.Queue()

        # --- Section C: ktuple_sieve_v1.py (targeted k-tuple candidate sieve) -----
        # Complementary to Section B: that one pattern-matches against windows
        # already fully sieved by prime_sieve; this one hunts a single, sparse
        # pattern (e.g. k=15) directly, via a residue wheel + trial division +
        # Miller-Rabin, across scattered window locations -- see ktuple_sieve_v1.py's
        # own module docstring for why that's a fundamentally different (and, for a
        # sparse-enough pattern, far cheaper) approach than fully sieving a wide
        # enough span for Section B to find the same thing.
        ktuple_outer = ttk.Labelframe(paned, text=self.T("gen.section_ktuple"))
        paned.add(ktuple_outer, weight=1)

        ktuple_settings = self._generation_settings["ktuple"]

        ktuple_pattern_row = ttk.Frame(ktuple_outer)
        ktuple_pattern_row.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Label(ktuple_pattern_row, text=self.T("gen.ktuple_field_k")).pack(side="left")
        self._ktuple_k_values = pattern_catalog_v1.all_k()
        self.ktuple_k_combo = ttk.Combobox(
            ktuple_pattern_row, state="readonly", width=6,
            values=[str(k) for k in self._ktuple_k_values])
        self.ktuple_k_combo.pack(side="left", padx=(6, 16))
        self.ktuple_k_combo.bind("<<ComboboxSelected>>", self._on_ktuple_k_changed)

        ttk.Label(ktuple_pattern_row, text=self.T("gen.ktuple_field_variant")).pack(side="left")
        self._ktuple_variants = []
        self.ktuple_variant_combo = ttk.Combobox(ktuple_pattern_row, state="readonly", width=10)
        self.ktuple_variant_combo.pack(side="left", padx=(6, 0))
        self.ktuple_variant_combo.bind(
            "<<ComboboxSelected>>", self._on_ktuple_variant_changed)

        self.ktuple_pattern_info_var = tk.StringVar(value="")
        ttk.Label(ktuple_outer, textvariable=self.ktuple_pattern_info_var,
                  wraplength=760, justify="left", foreground="#555").pack(
            anchor="w", padx=8, pady=(0, 4))

        ktuple_form = ttk.Frame(ktuple_outer)
        ktuple_form.pack(fill="x", padx=8, pady=(0, 4))

        self._ktuple_vars = {}

        def add_ktuple_field(row, col, key, label, width=10):
            ttk.Label(ktuple_form, text=label).grid(
                row=row, column=col * 2, sticky="w", padx=(0, 4), pady=2)
            var = tk.StringVar(value=str(ktuple_settings.get(key, "")))
            ttk.Entry(ktuple_form, textvariable=var, width=width).grid(
                row=row, column=col * 2 + 1, sticky="w", padx=(0, 20), pady=2)
            self._ktuple_vars[key] = var

        add_ktuple_field(0, 0, "base_exponent", self.T("gen.ktuple_field_base_exponent"))
        add_ktuple_field(0, 1, "n_locations", self.T("gen.ktuple_field_n_locations"))
        # Auto button: recommended_digit_sweep_n_locations()'s own suggestion --
        # see _on_ktuple_n_locations_auto_clicked()'s docstring for why this
        # exists (a shared n_locations field left digit_sweep's per-branch depth
        # much thinner than Artur had pictured). Occupies the free grid slot right
        # after n_locations's own entry (columns 2/3), same "Auto button right
        # next to the field it fills" placement as the loop pipeline's own
        # workers Auto button above.
        ttk.Button(ktuple_form, text=self.T("quick.auto_button"), width=6,
                   command=self._on_ktuple_n_locations_auto_clicked).grid(
            row=0, column=4, sticky="w", padx=(0, 8), pady=2)
        add_ktuple_field(1, 0, "window_m", self.T("gen.ktuple_field_window_m"), width=14)

        ttk.Label(ktuple_form, text=self.T("gen.ktuple_field_strategy")).grid(
            row=1, column=2, sticky="w", padx=(0, 4), pady=2)
        self.ktuple_strategy_combo = ttk.Combobox(
            ktuple_form, state="readonly", width=16,
            values=[self.T("gen.ktuple_strategy_even"), self.T("gen.ktuple_strategy_concentrated"),
                    self.T("gen.ktuple_strategy_manual_list"), self.T("gen.ktuple_strategy_manual_step"),
                    self.T("gen.ktuple_strategy_digit_sweep")])
        self.ktuple_strategy_combo.grid(row=1, column=3, sticky="w", padx=(0, 20), pady=2)
        _saved_strategy = ktuple_settings.get("strategy", "concentrated")
        self.ktuple_strategy_combo.current(
            _KTUPLE_STRATEGY_KEYS.index(_saved_strategy)
            if _saved_strategy in _KTUPLE_STRATEGY_KEYS else 1)

        # "step": optional override for even/concentrated (both auto-compute their
        # own step otherwise -- see ktuple_sieve_v1.step_for_even()/
        # step_for_concentrated()), REQUIRED for manual_step. Visible in the
        # primary form (not tucked behind Advanced) since it's central to how
        # every non-manual_list strategy now behaves -- see the checkpoint/step
        # design added 2026-08-19 at Artur's request, after his first real run
        # showed every Run re-scanning the same locations with nothing persisted
        # in between.
        add_ktuple_field(2, 0, "step", self.T("gen.ktuple_field_step"), width=14)

        ktuple_advanced_row = ttk.Frame(ktuple_outer)
        ktuple_advanced_row.pack(fill="x", padx=8)
        self._ktuple_advanced_visible = False
        self.ktuple_advanced_toggle_btn = ttk.Button(
            ktuple_advanced_row, text=self.T("gen.advanced_show"),
            command=self._on_toggle_ktuple_advanced)
        self.ktuple_advanced_toggle_btn.pack(side="left")

        ktuple_advanced_content = ttk.Frame(ktuple_outer)
        self._ktuple_advanced_content = ktuple_advanced_content
        # NOT packed here -- starts collapsed, see _on_toggle_ktuple_advanced().

        ktuple_advanced_form = ttk.Frame(ktuple_advanced_content)
        ktuple_advanced_form.pack(fill="x")

        def add_ktuple_advanced_field(row, col, key, label, width=10):
            ttk.Label(ktuple_advanced_form, text=label).grid(
                row=row, column=col * 2, sticky="w", padx=(0, 4), pady=2)
            var = tk.StringVar(value=str(ktuple_settings.get(key, "")))
            ttk.Entry(ktuple_advanced_form, textvariable=var, width=width).grid(
                row=row, column=col * 2 + 1, sticky="w", padx=(0, 20), pady=2)
            self._ktuple_vars[key] = var

        add_ktuple_advanced_field(
            0, 0, "fragment_width", self.T("gen.ktuple_field_fragment_width"), width=18)
        add_ktuple_advanced_field(
            0, 1, "fragment_start", self.T("gen.ktuple_field_fragment_start"), width=18)
        add_ktuple_advanced_field(1, 0, "deep_prime_limit", self.T("gen.ktuple_field_deep_prime_limit"))
        add_ktuple_advanced_field(1, 1, "mr_rounds", self.T("gen.ktuple_field_mr_rounds"))
        # pass_counter: strategy=digit_sweep only -- the starting pass number (only
        # used the first time, before any checkpoint exists -- default 0 matches
        # Artur's own worked example verbatim). Each pass sweeps the whole floor
        # once more with every drilled position committing to a DIFFERENT digit
        # than the pass before (a different rate per position, so the explored path
        # looks scrambled/varied rather than a single repeated digit -- see
        # ktuple_sieve_v1.py's digit_sweep_locations() PATH VARIETY note). Kept in
        # Advanced alongside the other rarely-touched fields since the default
        # already matches his intent.
        add_ktuple_advanced_field(2, 0, "pass_counter", self.T("gen.ktuple_field_pass_counter"))
        ttk.Label(ktuple_advanced_form, text=self.T("gen.ktuple_field_manual_offsets")).grid(
            row=3, column=0, sticky="w", padx=(0, 4), pady=2)
        _manual_offsets_var = tk.StringVar(value=str(ktuple_settings.get("manual_offsets", "")))
        ttk.Entry(ktuple_advanced_form, textvariable=_manual_offsets_var, width=50).grid(
            row=3, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=2)
        self._ktuple_vars["manual_offsets"] = _manual_offsets_var

        ktuple_btn_row = ttk.Frame(ktuple_outer)
        ktuple_btn_row.pack(fill="x", padx=8, pady=(4, 4))
        self.ktuple_run_btn = ttk.Button(
            ktuple_btn_row, text=self.T("common.run"),
            command=lambda: self._launch_ktuple(auto=False))
        self.ktuple_run_btn.pack(side="left")
        # "Auto": same launch path as Run, only auto=True differs -- keeps looping
        # batch after batch (checkpointing after each, see ktuple_sieve_v1.
        # run_ktuple_job()'s own docstring) inside the SAME WSL process until a
        # confirmed hit, Stop, or the floor is exhausted, rather than requiring a
        # fresh Run click per batch.
        self.ktuple_auto_btn = ttk.Button(
            ktuple_btn_row, text=self.T("gen.ktuple_auto_button"),
            command=lambda: self._launch_ktuple(auto=True))
        self.ktuple_auto_btn.pack(side="left", padx=(6, 0))
        self.ktuple_stop_btn = ttk.Button(
            ktuple_btn_row, text=self.T("common.stop"), command=self._on_stop_ktuple,
            state="disabled")
        self.ktuple_stop_btn.pack(side="left", padx=(6, 0))
        self.ktuple_status_label = tk.StringVar(value=self.T("common.ready"))
        ttk.Label(ktuple_btn_row, textvariable=self.ktuple_status_label).pack(
            side="left", padx=(12, 0))

        # Reset-checkpoint: a plain checkbox rather than its own button/action --
        # checked, it adds --reset-checkpoint to whichever of Run/Auto is clicked
        # next (see _launch_ktuple), so resetting never needs its own separate WSL
        # round trip just to delete one small text file. Left checked afterward
        # (not auto-unchecked) -- deliberately, so a person who wants to restart a
        # SEQUENCE of runs from scratch doesn't have to re-check it before every
        # click.
        self._ktuple_reset_checkpoint_var = tk.BooleanVar(
            value=bool(ktuple_settings.get("reset_checkpoint", False)))
        ttk.Checkbutton(
            ktuple_outer, text=self.T("gen.ktuple_check_reset_checkpoint"),
            variable=self._ktuple_reset_checkpoint_var).pack(anchor="w", padx=8, pady=(0, 4))

        self.ktuple_console = GenerationConsole(
            ktuple_outer, self.T, height=20,
            on_change=self._refresh_generation_pane_minsize)
        self.ktuple_output = self.ktuple_console.text

        self._ktuple_runner = None
        self._ktuple_output_queue = queue.Queue()

        # ROOT CAUSE (found 2026-08-23, after a first attempt to give each
        # section its OWN scrollbar was correctly rejected by Artur -- one
        # scrollable page for the whole tab is the right mental model, not
        # nested independent ones): a ttk.Panedwindow does NOT report its own
        # required height as the sum of what its panes actually need. Left
        # alone, it reports something close to just the sash furniture, and
        # happily compresses a pane below what its packed children require --
        # which is exactly how Section C's fields below the pattern/Auto row
        # were getting silently clipped with nothing to scroll to: the tab's
        # OUTER scrollable container (_build_scrollable_container) sizes its
        # scrollregion from `inner.winfo_reqheight()`, and since `paned` sits
        # inside `inner`, an under-reporting Panedwindow meant Tk genuinely
        # believed the whole tab already fit, no matter how tall the three
        # sections' real content was.
        #
        # ttk.Panedwindow's `add`/`pane` only expose `-weight` (used to share
        # out any SURPLUS space) -- unlike the plain tk.PanedWindow used
        # elsewhere in this file, there is no per-pane `-minsize` option at
        # all (confirmed the hard way: TclError: unknown option "-minsize").
        # So instead of a per-pane floor, `paned` itself is given an explicit
        # -height equal to the sum of its three panes' real natural heights --
        # that becomes its reqheight, which is what the outer container needs
        # to build a tall-enough scrollregion, so the ONE main scrollbar can
        # scroll past Quick-gen + Section A + Section B all the way down to
        # the full, uncropped bottom of Section C. `paned.pack(fill="both",
        # expand=True)` still lets it grow taller than this whenever the
        # window actually has the extra room (that's the separate canvas-
        # stretch fix in _build_scrollable_container) -- this height is only
        # ever a floor, never a cap.
        # Saved so later, post-construction content growth (expanding a section's
        # Advanced block, showing its console -- see _refresh_generation_pane_
        # minsize() below) can re-measure and re-apply this the same way,
        # instead of only ever getting it right at initial build time.
        self._generation_paned = paned
        self._loop_section_outer = loop_outer
        self._const_section_outer = const_outer
        self._ktuple_section_outer = ktuple_outer

        # FIFTH PASS (2026-08-23) -- root cause finally found: calling this
        # synchronously here, still inside __init__/_build_generation_tab(),
        # runs BEFORE the Atlas window has ever been mapped/shown on screen.
        # At that point ttk.Panedwindow's ACTUAL on-screen size is still
        # whatever tiny placeholder Tk assigns an unmapped widget -- nowhere
        # near the real height _refresh_generation_pane_minsize() just
        # configured. sashpos() silently CLAMPS the position it's given to
        # what's valid for the widget's CURRENT actual size, so sash1 (and
        # therefore Section C's real height) was being clamped down to that
        # placeholder every single time, no matter how much padding got
        # added to the target -- explaining exactly why bigger padding
        # never changed anything visible. Deferring the first call via
        # after() until the window has actually been mapped (with a second,
        # later call as a safety net for a slow first paint) lets sashpos()
        # clamp against the REAL final size instead.
        self.after(300, self._refresh_generation_pane_minsize)
        self.after(1200, self._refresh_generation_pane_minsize)

        if self._ktuple_k_values:
            _saved_k = ktuple_settings.get("k", "")
            try:
                _saved_k_int = int(_saved_k) if _saved_k else None
            except ValueError:
                _saved_k_int = None
            self.ktuple_k_combo.current(
                self._ktuple_k_values.index(_saved_k_int)
                if _saved_k_int in self._ktuple_k_values else 0)
            self._on_ktuple_k_changed(restore_variant_id=ktuple_settings.get("variant_id"))

        self.after(150, self._poll_loop_output)
        self.after(150, self._poll_constellation_output)
        self.after(150, self._poll_ktuple_output)

    def _refresh_generation_pane_minsize(self):
        """Re-measures all three Generation-tab sections' natural required
        heights, re-applies their sum as the Panedwindow's own explicit
        -height (see _build_generation_tab()'s comment on the initial call to
        this, right after building all three sections, for the full root-
        cause: ttk.Panedwindow has no per-pane -minsize option at all, so the
        widget's OWN -height is the only lever that makes it report a tall
        enough reqheight for the tab's one main scrollbar to reach), and THEN
        explicitly places both sashes at each section's own cumulative
        natural height. That last step matters even once -height is exactly
        right: with no explicit sash positions, ttk.Panedwindow's own initial
        placement doesn't necessarily match each pane's individual natural
        need (weight=1 on all three only governs how any SURPLUS beyond the
        sum is shared, not how the total itself is split) -- so Section B
        (fewer fields) could end up with slightly more than it needs while
        Section C (more fields + the console) still came up short and
        clipped, even though the grand total was already correct. Pinning
        both sashes removes that guesswork entirely.
        Called once right after building all three sections, and again after
        anything that can grow one afterwards (expanding its Advanced block,
        showing its console -- see call sites below) -- recomputing across
        all three every time, not just the one that grew, since both -height
        and the sash positions are properties of the whole Panedwindow.

        PER-PANE PADDING (found 2026-08-23, third pass): sash thickness and
        the Panedwindow's own border/relief both eat a few pixels that never
        show up in any pane's winfo_reqheight() -- and not symmetrically
        (edge panes only border ONE sash and the widget's own outer edge;
        the middle pane borders sashes on both sides; the bottom pane also
        meets the widget's bottom border). Rather than chase the exact
        pixel accounting for each of those separately (fixing one edge at a
        time only moved the shortfall to a different pane -- first Section B
        came up short, then, after padding the sashes, Section C did), every
        pane now simply gets its OWN flat safety margin added directly to
        its measured height, regardless of position. A few pixels of extra
        blank space at the bottom of a section is a much smaller problem
        than clipped content -- see Artur's explicit ask to prioritize
        "wszystkie się mieszczą w pełni" (all of them fit in full).

        FOURTH PASS (2026-08-23): +15px per pane still left Section C (the
        LAST one) clipped by roughly one button row, even though the exact
        same padding was already enough for A and B. Section C is the only
        one that also touches the Panedwindow's own OUTER bottom edge/
        border, on top of bordering a sash on its top side -- that outer
        border isn't included in any pane's winfo_reqheight() and isn't
        fixed by moving sashes at all, so it was never going to be covered
        by a flat, position-independent pad. Rather than keep chasing the
        exact pixel cost of that border, `_LAST_PANE_EXTRA_PAD` gives the
        last pane a generously larger buffer than the other two -- cheap
        insurance against clipping, at the cost of a bit more blank space
        specifically under Section C.

        SIXTH PASS (2026-08-23): opening a section's console (each is ~500px
        tall once shown -- previously invisible in every screenshot because
        an unmapped/unpacked Text widget contributes nothing to its parent's
        winfo_reqheight() at all) showed the SAME stale-clamp bug the fifth
        pass fixed for the very first, startup-time call, except now it can
        happen on every later call too: `paned.configure(height=...)` only
        changes the widget's OWN reqsize immediately -- the ACTUAL on-screen
        size of `paned` only catches up once that change has propagated all
        the way up through `inner`'s pack manager and back down through the
        outer scrollable canvas's own <Configure> handling
        (_build_scrollable_container), which is a multi-widget chain that a
        single update_idletasks() call does not reliably flush in one pass.
        sashpos() clamps to whatever `paned`'s actual size still is AT THE
        MOMENT it's called -- so a sash set right after just one
        update_idletasks() can still get clamped back to the pre-resize
        size, discarding a newly-opened, much taller console into whatever
        sliver of space happened to be left over. Pumping update_idletasks()
        several times in a row (each call lets Tk process one more layer of
        newly-queued geometry work before the next) reliably drains that
        whole chain before sashpos() ever runs."""
        def _settle():
            for _ in range(4):
                self.update_idletasks()
        _settle()
        _PANE_PAD = 25
        _LAST_PANE_EXTRA_PAD = 25
        h0 = self._loop_section_outer.winfo_reqheight() + _PANE_PAD
        h1 = self._const_section_outer.winfo_reqheight() + _PANE_PAD
        h2 = (self._ktuple_section_outer.winfo_reqheight()
              + _PANE_PAD + _LAST_PANE_EXTRA_PAD)
        self._generation_paned.configure(height=h0 + h1 + h2)
        _settle()
        self._generation_paned.sashpos(0, h0)
        self._generation_paned.sashpos(1, h0 + h1)
        _settle()

    def _on_toggle_loop_advanced(self):
        """Shows/hides loop_advanced_content -- the fields AND the raw Run/
        Stop/status row together (see _build_generation_tab()'s comment on
        Section A) -- packed with before=self.loop_console.toggle_row so it always
        lands back in the same slot (between the toggle button and the console's own
        toggle row) regardless of how many times it's been forgotten/re-shown."""
        if self._loop_advanced_visible:
            self._loop_advanced_content.pack_forget()
            self._loop_advanced_visible = False
            self.loop_advanced_toggle_btn.configure(text=self.T("gen.advanced_show"))
        else:
            self._loop_advanced_content.pack(
                fill="x", padx=8, pady=(0, 4), before=self.loop_console.toggle_row)
            self._loop_advanced_visible = True
            self.loop_advanced_toggle_btn.configure(text=self.T("gen.advanced_hide"))
            self._refresh_generation_pane_minsize()

    def _show_loop_terminal(self):
        """Force-expands the pipeline console if it's currently collapsed -- called
        from _on_run_loop() the moment a run actually starts. No-op if already visible
        (e.g. the user had opened it manually)."""
        self.loop_console.show()
        self._refresh_generation_pane_minsize()

    def _show_const_terminal(self):
        self.const_console.show()
        self._refresh_generation_pane_minsize()

    def _new_run_separator(self):
        """Appended (not clear()'d -- see _on_run_loop/_on_run_constellation) at the
        start of every run, so several runs' output can stay stacked in the console
        for comparison instead of being wiped on every click. The Clear button (see
        GenerationConsole) is the only thing that actually empties the console now."""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        return "\n" + "=" * 70 + f"\n{self.T('gen.new_run_marker', time=ts)}\n" + "=" * 70 + "\n"

    # --- Quick generation panel (higher-level, sits above the raw pipeline form) ---

    def _init_quick_generation_state(self):
        """Creates every Quick-gen StringVar/BooleanVar exactly once, shared by every
        panel instance _build_quick_generation_panel() builds (the embedded one plus
        any detached copy, see that method's note below) -- sharing the same Variable
        objects, rather than one set per instance, is what keeps two simultaneously-
        visible panels showing identical values without any manual syncing: typing in
        either copy's Entry widget updates both immediately."""
        self.quick_mode_var = tk.StringVar(value="floor")
        self.quick_floor_var = tk.StringVar(value="")
        self.quick_floor_width_var = tk.StringVar(value="1")
        self.quick_floor_start_var = tk.StringVar(value="")
        self.quick_floor_start_var.trace_add("write", self._on_quick_floor_start_changed)
        # Shared by TWO modes' own continuation paths: Floor mode's own BLANK-
        # starting-point path (a typed starting point already means "start exactly
        # there", see _quick_gen_plan_literal_range's own docstring, unaffected by
        # this toggle either way) and Exploration mode's own Floor field (blank OR
        # typed -- both of Exploration's own starting points can land on a floor
        # with a gap, see _try_fill_quick_gen_gap()'s own docstring, added there
        # 2026-08-18 at Artur's request to match Floor mode exactly). Default False
        # (continue past the highest existing file, today's historical behavior,
        # unchanged) rather than True, so enabling gap-filling is an explicit,
        # conscious choice rather than a surprising default for a person who has
        # never left a gap and doesn't need to think about this at all. Not
        # persisted across restarts, same as every other Quick-gen field (Width,
        # punkt startowy) -- see _apply_loop_params_and_run's own docstring for why
        # only the low-level orchestrator form persists.
        self.quick_floor_fill_gaps_var = tk.BooleanVar(value=False)
        self.quick_from_var = tk.StringVar(value="")
        self.quick_to_var = tk.StringVar(value="")
        self.quick_explore_floor_var = tk.StringVar(value="")
        self.quick_iterations_var = tk.StringVar(value="1")
        self.quick_explore_width_var = tk.StringVar(value="1")
        # primesieve mode: deliberately its OWN Floor/From/Width variables rather than
        # reusing quick_from_var/quick_to_var (an earlier version of this mode did) --
        # see _build_quick_mode_primesieve's docstring for why: this mode's own Auto
        # button now has a completely different meaning (fills From with this floor's
        # storage continuation point, not a RAM-based width suggestion), and Width
        # replaces the old literal To field entirely, so sharing Range mode's variables
        # would mean a value typed in one mode's fields could silently mispopulate the
        # other's on a mode switch.
        self.quick_primesieve_floor_var = tk.StringVar(value="")
        self.quick_primesieve_from_var = tk.StringVar(value="")
        self.quick_primesieve_width_var = tk.StringVar(value="1")
        self.quick_hint_var = tk.StringVar(value="")
        self.quick_status_var = tk.StringVar(value="")
        self._quick_panels = []

    def _build_quick_generation_panel(self, parent):
        """Higher-level "just tell me the floor / range" panel above the raw
        orchestrator_loop_v2.py parameter form -- those low-level
        fields (window_count_per_run, workers, batches_per_worker...) are too
        low-level for the app/user. This
        panel lets the person say WHAT they want -- a floor, or a numeric range in
        Python-expression-friendly notation (e.g. 10**5) -- in one of three ways, and a
        LATER step will translate that into the low-level fields below automatically:
        window width capped at QUICK_GEN_MAX_WINDOW_WIDTH (10,000,000), window count
        derived from the target range so the total comes out right, "exploration" mode
        appending N further 10-billion-wide chunks to a floor's existing data.

        An earlier "range -- width" mode (floor + a single width
        field) was dropped -- with no explicit start, it behaved identically to
        "floor only" (both just continue/create that floor), so it was a redundant
        duplicate rather than a genuinely different way of specifying the target.

        Callable more than once -- the detached generation window (see
        _build_detached_quick_panel) gets its own full copy of this panel, built by
        calling this same method again with a different parent. Every widget it
        creates is bound to the shared StringVars from _init_quick_generation_state()
        (called once, before the first call to this method), so typing in either copy
        updates both immediately; the one thing NOT shared is the widgets themselves,
        which is why mode-switching (_on_quick_mode_changed), the Floor field's
        readonly toggle (_on_quick_floor_start_changed), and the Generate/Stop label
        flip (_on_run_loop/_on_loop_finished) all loop over self._quick_panels instead
        of touching one fixed widget reference."""
        ttk.Label(parent, text=self.T("quick.intro"), foreground="#555555",
                  wraplength=900, justify="left").pack(
            anchor="w", padx=8, pady=(6, 4))

        mode_row = ttk.Frame(parent)
        mode_row.pack(fill="x", padx=8, pady=(0, 2))
        quick_modes = [
            ("floor", self.T("quick.mode_floor")),
            ("range", self.T("quick.mode_range")),
            ("explore", self.T("quick.mode_explore")),
            ("primesieve", self.T("quick.mode_primesieve")),
        ]
        for value, label in quick_modes:
            ttk.Radiobutton(mode_row, text=label, value=value, variable=self.quick_mode_var,
                             command=self._on_quick_mode_changed).pack(side="left", padx=(0, 16))

        # All three mode sub-frames share the same grid cell (row 0, col 0) and are
        # switched with .tkraise() -- keeps whichever fields aren't relevant to the
        # current mode out of the way instead of disabling-in-place, and avoids
        # reflowing the rest of the panel's layout when the mode changes.
        fields_container = ttk.Frame(parent)
        fields_container.pack(fill="x", padx=8, pady=(2, 4))
        mode_frames = {}
        floor_entry = self._build_quick_mode_floor(fields_container, mode_frames)
        self._build_quick_mode_range(fields_container, mode_frames)
        self._build_quick_mode_explore(fields_container, mode_frames)
        self._build_quick_mode_primesieve(fields_container, mode_frames)

        ttk.Label(parent, textvariable=self.quick_hint_var, foreground="#555555",
                  wraplength=900, justify="left").pack(anchor="w", padx=8, pady=(0, 4))

        btn_row = ttk.Frame(parent)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        # Generate is the primary Start/Stop control (the raw
        # Run/Stop pair moved inside the collapsible advanced block, see
        # _build_generation_tab()'s Section A) -- see
        # _on_quick_generate_or_stop_clicked/_on_run_loop/_on_loop_finished for the
        # three places that flip its label between quick.generate_button and
        # common.stop (looping over self._quick_panels so every copy flips together).
        generate_btn = ttk.Button(
            btn_row, text=self.T("quick.generate_button"),
            command=self._on_quick_generate_or_stop_clicked)
        generate_btn.pack(side="left")
        ttk.Label(btn_row, textvariable=self.quick_status_var).pack(side="left", padx=(12, 0))

        panel = {"mode_frames": mode_frames, "floor_entry": floor_entry,
                 "generate_btn": generate_btn}
        self._quick_panels.append(panel)
        self._sync_quick_panel(panel)  # show the right sub-frame + state for this copy
        return panel

    def _build_quick_mode_floor(self, container, mode_frames):
        """The on-disk window format stays EXACTLY as it is -- always round the
        requested amount UP to a whole number of QUICK_GEN_MAX_WINDOW_WIDTH
        (10,000,000) windows, since rounding up costs almost no extra time and keeps
        file management predictable. So Width here is a MULTIPLIER of that window
        size, not a raw integer -- entering 1 means one 10-million window, 1000 means
        1000 of them (10 billion, the max, an explicit input cap). A ttk.Spinbox (not a
        plain Entry) makes that bounded-multiplier nature visible at a glance and a
        validatecommand blocks keystrokes that would push it out of [1, 1000].

        Starting point is optional and drives which of its TWO roles the Floor field
        plays: blank start -> Floor is a normal, manually-typed field, and generation
        continues from that floor's last existing file; a start value -> Floor
        becomes a READ-ONLY, auto-computed display of digit_count_floor(start) (also
        solves "it's not easy to count how many zeros are in a big number" -- counting
        zeros in a huge number by eye is exactly what this now does for you). See
        _on_quick_floor_start_changed, wired via a trace on quick_floor_start_var
        (added once, in _init_quick_generation_state).

        Returns the Floor Entry widget so the caller can track it per-panel-instance
        (see _on_quick_floor_start_changed).

        Second row: a "fill gaps first" checkbox, relevant ONLY to the blank-starting-
        point path (a typed starting point already means "start exactly there" --
        see _quick_gen_plan_literal_range's own docstring, unaffected by this toggle)
        -- see quick_floor_fill_gaps_var's own comment in _init_quick_generation_state
        for why this defaults off. Deliberately not disabled/greyed out when a
        starting point IS typed -- it's simply ignored by that path, no need for the
        extra state-tracking a live enable/disable would cost."""
        # Outer wraps BOTH rows (field row + gap-toggle row) so mode_frames tracks
        # a single widget for the whole "floor" mode UI -- _sync_quick_panel only
        # grid()/grid_remove()s whatever is registered in mode_frames, so if the
        # toggle row were a sibling of outer in container (its own row=1) instead of
        # nested inside outer, it would never be hidden when switching to another
        # Quick-gen mode. Nesting it here is what keeps the two rows shown/hidden
        # together.
        outer = ttk.Frame(container)
        outer.grid(row=0, column=0, sticky="w")
        frame = ttk.Frame(outer)
        frame.grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text=self.T("quick.field_floor")).pack(side="left")
        floor_entry = ttk.Entry(frame, textvariable=self.quick_floor_var, width=10)
        floor_entry.pack(side="left", padx=(6, 20))
        ttk.Label(frame, text=self.T("quick.field_width")).pack(side="left")
        width_vcmd = (self.register(self._validate_quick_width_spinbox), "%P")
        ttk.Spinbox(frame, from_=1, to=1000, textvariable=self.quick_floor_width_var,
                    width=6, validate="key", validatecommand=width_vcmd).pack(
            side="left", padx=(6, 4))
        ttk.Button(frame, text=self.T("quick.auto_button"),
                   command=lambda: self._on_quick_auto_width_clicked(
                       self.quick_floor_width_var)).pack(side="left", padx=(0, 20))
        ttk.Label(frame, text=self.T("quick.field_start")).pack(side="left")
        ttk.Entry(frame, textvariable=self.quick_floor_start_var, width=20).pack(
            side="left", padx=(6, 0))
        gap_row = ttk.Frame(outer)
        gap_row.grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Checkbutton(gap_row, text=self.T("quick.field_fill_gaps_first"),
                         variable=self.quick_floor_fill_gaps_var).pack(side="left")
        mode_frames["floor"] = outer
        return floor_entry

    def _validate_quick_width_spinbox(self, proposed):
        """validatecommand for the Width spinbox -- allows an empty field WHILE
        editing (so the user can select-all-and-retype), otherwise only digit strings
        in [1, 1000] -- UI-level input restriction only; this is not where the actual
        1 unit = 10,000,000 translation happens (that's the logic step, not yet
        written)."""
        if proposed == "":
            return True
        return proposed.isdigit() and 1 <= int(proposed) <= 1000

    def _validate_primesieve_width_spinbox(self, proposed):
        """validatecommand for primesieve mode's OWN Width spinbox -- same shape as
        _validate_quick_width_spinbox, but bounded to PRIMESIEVE_MAX_WIDTH_MULT instead
        of 1000 (see that constant's own docstring for why this mode's Width field has
        no RAM-driven reason to stay small)."""
        if proposed == "":
            return True
        return proposed.isdigit() and 1 <= int(proposed) <= PRIMESIEVE_MAX_WIDTH_MULT

    def _on_quick_floor_start_changed(self, *_args):
        """Gives the Floor field its two roles (see _build_quick_mode_floor's
        docstring): a parseable starting point value makes it a read-only,
        auto-computed "which floor is this number in" display; clearing/blanking it
        (or typing something unparseable) hands control back to the person, since an
        empty starting point means "continue this floor" and the app has no other way
        to know WHICH floor that is."""
        value = _eval_quick_number(self.quick_floor_start_var.get())
        new_floor_value = "" if value is None else str(digit_count_floor(value))
        new_state = "normal" if value is None else "readonly"
        self.quick_floor_var.set(new_floor_value)
        for panel in self._quick_panels:
            panel["floor_entry"].configure(state=new_state)

    def _build_quick_mode_range(self, container, mode_frames):
        frame = ttk.Frame(container)
        frame.grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text=self.T("quick.field_from")).pack(side="left")
        ttk.Entry(frame, textvariable=self.quick_from_var, width=20).pack(
            side="left", padx=(6, 20))
        ttk.Label(frame, text=self.T("quick.field_to")).pack(side="left")
        ttk.Entry(frame, textvariable=self.quick_to_var, width=20).pack(
            side="left", padx=(6, 20))
        # Range mode has no window-COUNT field to fill in (From/To are literal
        # numbers, not a window multiplier) -- Auto here reports the recommendation
        # via a dialog instead (width_var=None, see _on_quick_auto_width_clicked),
        # for the person to factor into their own From/To choice.
        ttk.Button(frame, text=self.T("quick.auto_button"),
                   command=lambda: self._on_quick_auto_width_clicked(None)).pack(
            side="left")
        mode_frames["range"] = frame

    def _build_quick_mode_explore(self, container, mode_frames):
        """Exploration maps directly onto orchestrator_loop_v2's own
        run_count/WINDOW_COUNT_PER_RUN loop -- this mode ONLY continues on an EXISTING
        floor, never creates a new one. Floor can be left blank: the dispatch handler
        (_on_quick_generate_clicked) then auto-detects the highest 10p{N} folder that
        actually has data (find_highest_populated_floor()) and continues THAT, re-
        detected fresh on every click rather than sticky in the entry field -- so
        repeatedly pressing Generate with nothing typed keeps extending whatever is
        genuinely the deepest generated data right now. Typing a floor explicitly still
        works, to explore a specific one instead -- including a LOW floor (0-6), which
        legitimately reports "already in storage" once its own small, fixed domain is
        fully covered (see the low-floor guard in _on_quick_generate_clicked) rather
        than being treated as some kind of "auto" sentinel value; 0 is a real floor,
          not a placeholder for blank.

        The Floor field's own "Auto" button (_on_explore_auto_floor_clicked, separate
        from the Width field's own Auto button further right in this same row) fills
        it with that SAME auto-detected highest-populated-floor value explicitly --
        leaving the field blank and clicking Generate directly already does the
        identical thing, but typing/deleting text to reach an empty field is a much
        less discoverable way to trigger it than a labeled button, especially compared
        to every other Quick-gen mode's own Auto button doing something visibly similar
        for their own fields.

        One iteration covers Width x QUICK_GEN_MAX_WINDOW_WIDTH numbers -- same Width
        spinbox/meaning as "Floor only"'s (reuses _validate_quick_width_spinbox,
        [1, 1000]), so the per-iteration memory footprint is exactly as
        user-controllable here as it is there, instead of being pinned to a fixed
        1000-window (10 billion) iteration size regardless of how much RAM the machine
        running the WSL sieve actually has.

        Second row: the SAME "fill gaps first" checkbox/variable Floor mode's own
        blank-starting-point path uses (quick_floor_fill_gaps_var -- added here
        2026-08-18, at Artur's request, to match Floor mode's behavior exactly: "tak
        jak tylko piętro"). Relevant to BOTH of this mode's own starting points --
        blank Floor (auto-detects the highest populated floor) and a typed Floor --
        since either one can land on a floor that has a gap (see
        _try_fill_quick_gen_gap()'s own docstring for why a floor Exploration hasn't
        personally visited yet can still have one, e.g. from a search or Goldbach
        direct-range write)."""
        outer = ttk.Frame(container)
        outer.grid(row=0, column=0, sticky="w")
        frame = ttk.Frame(outer)
        frame.grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text=self.T("quick.field_floor")).pack(side="left")
        ttk.Entry(frame, textvariable=self.quick_explore_floor_var, width=10).pack(
            side="left", padx=(6, 4))
        ttk.Button(frame, text=self.T("quick.explore_auto_floor_button"),
                   command=self._on_explore_auto_floor_clicked).pack(
            side="left", padx=(0, 20))
        ttk.Label(frame, text=self.T("quick.field_iterations")).pack(side="left")
        iterations_vcmd = (self.register(self._validate_quick_iterations_spinbox), "%P")
        ttk.Spinbox(frame, from_=1, to=100, textvariable=self.quick_iterations_var,
                    width=6, validate="key", validatecommand=iterations_vcmd).pack(
            side="left", padx=(6, 20))
        ttk.Label(frame, text=self.T("quick.field_width")).pack(side="left")
        width_vcmd = (self.register(self._validate_quick_width_spinbox), "%P")
        ttk.Spinbox(frame, from_=1, to=1000, textvariable=self.quick_explore_width_var,
                    width=6, validate="key", validatecommand=width_vcmd).pack(
            side="left", padx=(6, 4))
        ttk.Button(frame, text=self.T("quick.auto_button"),
                   command=lambda: self._on_quick_auto_width_clicked(
                       self.quick_explore_width_var)).pack(side="left")
        gap_row = ttk.Frame(outer)
        gap_row.grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Checkbutton(gap_row, text=self.T("quick.field_fill_gaps_first"),
                         variable=self.quick_floor_fill_gaps_var).pack(side="left")
        mode_frames["explore"] = outer

    def _build_quick_mode_primesieve(self, container, mode_frames):
        """Floor + From + Width -- NOT the From/To pair the first version of this mode
        used. From is a literal absolute starting point (like Floor mode's own
        "Starting point" field), and Width is a multiplier of QUICK_GEN_MAX_WINDOW_WIDTH
        (same [1, 1000] spinbox convention as Floor/Exploration mode's Width) that
        replaces having to type a second huge literal number for the end of the range --
        picking a floor deep in the uint64 range and navigating to an arbitrary point
          within it is exactly what this mode is FOR, and typing two 19+ digit numbers by
        hand for every request was real friction that Floor/To-based Range mode doesn't
        have (a floor's own start already anchors one end there).

        Floor is INDEPENDENT of From -- not derived from it the way Floor mode's own
        Floor field is derived from its Starting point (see _on_quick_floor_start_changed)
        -- because this mode's Auto button needs a floor to look up BEFORE a From value
        necessarily exists yet: click Auto with just a Floor typed in, and it fills From
        with wherever that floor's storage currently ends (see
        _on_primesieve_auto_from_clicked), which is the actual point of this layout --
        orienting yourself on a floor that can hold hundreds of billions of windows
        without having to compute a resume point by hand. Generation itself derives its
        real target floor from From alone (via _quick_gen_plan_literal_range ->
        digit_count_floor), same as Floor mode's own starting-point flow -- the Floor
        field here is a lookup convenience for Auto, not fed back into the request.

        The attribution label is ALWAYS visible while this mode is selected, not just
        mentioned in a hint or code comment -- this mode calls directly into a
        third-party library (libprimesieve, by Kim Walisch) with no engine of ours in
        between, and that should be visible to whoever clicks Generate, not just to
        whoever reads the source."""
        frame = ttk.Frame(container)
        frame.grid(row=0, column=0, sticky="w")
        row1 = ttk.Frame(frame)
        row1.pack(anchor="w")
        ttk.Label(row1, text=self.T("quick.field_floor")).pack(side="left")
        ttk.Entry(row1, textvariable=self.quick_primesieve_floor_var, width=10).pack(
            side="left", padx=(6, 20))
        ttk.Label(row1, text=self.T("quick.field_from")).pack(side="left")
        ttk.Entry(row1, textvariable=self.quick_primesieve_from_var, width=24).pack(
            side="left", padx=(6, 4))
        ttk.Button(row1, text=self.T("quick.auto_button"),
                   command=self._on_primesieve_auto_from_clicked).pack(
            side="left", padx=(0, 20))
        ttk.Label(row1, text=self.T("quick.field_width")).pack(side="left")
        width_vcmd = (self.register(self._validate_primesieve_width_spinbox), "%P")
        ttk.Spinbox(row1, from_=1, to=PRIMESIEVE_MAX_WIDTH_MULT,
                    textvariable=self.quick_primesieve_width_var,
                    width=14, validate="key", validatecommand=width_vcmd).pack(
            side="left", padx=(6, 0))
        ttk.Label(frame, text=self.T("quick.attribution_primesieve"), foreground="#777777",
                  font=("TkDefaultFont", 8), wraplength=860, justify="left").pack(
            anchor="w", pady=(4, 0))
        mode_frames["primesieve"] = frame

    def _on_primesieve_auto_from_clicked(self):
        """primesieve mode's OWN Auto button -- unlike every other mode's Auto (RAM-
        based window-count suggestion, see _on_quick_auto_width_clicked), this one fills
        the From field with wherever the given Floor's storage currently ends (0 if
        nothing is there yet), computed the exact same way find_continuation_target_idx
        already does for every other mode's own continuation logic. This is the whole
        point of splitting Floor out from From (see _build_quick_mode_primesieve's
        docstring): a floor this deep can hold hundreds of billions of windows, so
          "where does my data actually stop on floor N" is not something to work out by
        hand."""
        raw_floor = self.quick_primesieve_floor_var.get().strip()
        floor_value = _eval_quick_number(raw_floor)
        if not raw_floor or floor_value is None or floor_value < 0:
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_floor_required"))
            return
        existing_count = find_continuation_target_idx(
            self._get_portal_folder(), floor_value, QUICK_GEN_MAX_WINDOW_WIDTH)
        if floor_value < LOW_FLOOR_CUTOFF:
            # A low floor is AT MOST one combined window wide, ever (see
            # LOW_FLOOR_CUTOFF) -- existing_count>=1 means it (and every other floor
            # 0-6) is already fully generated, not "add one more window" the way the
            # formula below would wrongly compute (10**floor + 10M lands in the NEXT
            # floor's own territory, not a meaningful continuation point here).
            continuation_point = 10 ** floor_value
            self.quick_primesieve_from_var.set(str(continuation_point))
            if existing_count >= 1:
                messagebox.showinfo(self.T("quick.dialog_title"), self.T(
                    "quick.primesieve_auto_from_low_floor_done", floor=floor_value))
            else:
                messagebox.showinfo(self.T("quick.dialog_title"), self.T(
                    "quick.primesieve_auto_from_low_floor_result", floor=floor_value))
            return
        continuation_point = 10 ** floor_value + existing_count * QUICK_GEN_MAX_WINDOW_WIDTH
        self.quick_primesieve_from_var.set(str(continuation_point))
        # existing_count above is a CONTINUATION POSITION (see
        # find_continuation_target_idx()'s own docstring), not necessarily the real
        # file count once a floor has interior gaps -- the message shows the real
        # count instead (see count_existing_windows()'s own docstring for why).
        real_window_count = count_existing_windows(self._get_portal_folder(), floor_value)
        messagebox.showinfo(self.T("quick.dialog_title"), self.T(
            "quick.primesieve_auto_from_result", floor=floor_value,
            existing_count=real_window_count, continuation_point=f"{continuation_point:,}"))

    def _on_explore_auto_floor_clicked(self):
        """Exploration mode's OWN Floor-Auto button -- fills quick_explore_floor_var
        with find_highest_populated_floor()'s result, the SAME value leaving Floor
        blank and clicking Generate directly already resolves to (see
        _on_quick_generate_clicked's "explore" branch). This button exists purely for
        discoverability: an empty text field as the trigger for "auto-continue the
        deepest floor" turned out to be easy to miss in practice (a person testing this
        mode typed an explicit "0" rather than clearing the field, which is a
        perfectly legitimate floor to request -- see this mode's own docstring for why
        that's NOT the same thing as leaving it blank) -- a labeled button matches
        every other Quick-gen mode's own Auto convention instead of relying on an
        invisible one.

        Unlike _on_quick_auto_width_clicked (shared, RAM-based, targets a Width field)
        and _on_primesieve_auto_from_clicked (fills a From field given an ALREADY-KNOWN
        Floor), this button determines the Floor itself from scratch by scanning the
        whole database -- there is no floor to read from the UI first."""
        highest = find_highest_populated_floor(self._get_portal_folder())
        if highest is None:
            messagebox.showinfo(
                self.T("quick.dialog_title"), self.T("quick.explore_auto_floor_empty"))
            return
        self.quick_explore_floor_var.set(str(highest))

    def _validate_quick_iterations_spinbox(self, proposed):
        """validatecommand for the Number of iterations spinbox -- same shape as
        _validate_quick_width_spinbox, bounded to [1, 100] (100 x 10 bln = 1 trillion
        upper bound)."""
        if proposed == "":
            return True
        return proposed.isdigit() and 1 <= int(proposed) <= 100

    def _on_quick_auto_width_clicked(self, width_var):
        """Auto button handler, shared by every mode's button (see
        _build_quick_mode_floor/_build_quick_mode_explore/_build_quick_mode_range).
        Queries available RAM INSIDE WSL (estimate_wsl_available_ram_bytes -- the
        sieve itself runs there, not in this native Windows process) and turns it
        into a recommended window count (recommended_max_windows -- see that
        function's docstring for exactly what it is and isn't accounting for).

        width_var is the Width spinbox's StringVar to fill in directly (Floor/
        Exploration modes); pass None for Range mode, which has no window-count
        field to fill -- there the recommendation is only reported via the dialog,
        for the person to factor into their own From/To choice."""
        available = estimate_wsl_available_ram_bytes()
        if available is None:
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_ram_probe_failed"))
            return
        recommended = recommended_max_windows(available)
        numbers_total = recommended * QUICK_GEN_MAX_WINDOW_WIDTH
        if width_var is not None:
            width_var.set(str(recommended))
        messagebox.showinfo(self.T("quick.dialog_title"), self.T(
            "quick.auto_ram_result", available_gb=f"{available / 1e9:.1f}",
            recommended=f"{recommended:,}", numbers_total=f"{numbers_total:,}"))

    def _on_workers_auto_clicked(self):
        """Auto button handler for the "workers" field in the loop pipeline's
        advanced form (see _build_generation_tab's own comment above the button)
        -- the CPU-count counterpart to _on_quick_auto_width_clicked's RAM-based
        window-count suggestion above. Queries the CPU count INSIDE WSL
        (estimate_wsl_available_cpu_count -- the sieve's worker processes run
        there, not in this native Windows process) and fills the "workers" field
        with the recommendation (recommended_worker_count -- simply the detected
        count itself, since requesting more workers than available CPUs adds
        scheduling overhead without adding real parallelism).

        This only ever SUGGESTS a value into the field -- like every other field
        in this advanced form, "workers" stays a plain, freely-editable Entry
        afterward (the person can still type anything from 1 up to, or beyond,
        the detected count; nothing here enforces a hard ceiling on typing, same
        as window_count_per_run's own field right above it)."""
        available = estimate_wsl_available_cpu_count()
        if available is None:
            messagebox.showerror(self.T("quick.dialog_title"), self.T("gen.error_cpu_probe_failed"))
            return
        recommended = recommended_worker_count(available)
        self._loop_vars["workers"].set(str(recommended))
        messagebox.showinfo(self.T("quick.dialog_title"), self.T(
            "gen.auto_cpu_result", available=available, recommended=recommended))

    def _sync_quick_panel(self, panel):
        """tkraise() only reorders stacking within the shared grid cell -- it does
        NOT clip a sibling frame's own size. Since the "floor" sub-frame
        (Floor+Width+Starting point) is wider than "range" (From+To), raising
        "range" on top would still leave "floor"'s trailing Starting point label/
        entry visible past range's right edge. grid_remove()/grid() actually pulls
        the inactive frames out of the layout instead of just moving them behind.

        Operates on a single panel's mode_frames -- called for every entry in
        self._quick_panels so the embedded panel and any open detached copy switch
        mode together (they share quick_mode_var, but each has its OWN frame
        widgets, so each needs this applied individually)."""
        mode = self.quick_mode_var.get()
        for name, frame in panel["mode_frames"].items():
            if name == mode:
                frame.grid(row=0, column=0, sticky="w")
            else:
                frame.grid_remove()

    def _on_quick_mode_changed(self):
        for panel in self._quick_panels:
            self._sync_quick_panel(panel)
        hints = {
            "floor": self.T("quick.hint_floor"),
            "range": self.T("quick.hint_range"),
            "explore": self.T("quick.hint_explore"),
            "primesieve": self.T("quick.hint_primesieve"),
        }
        self.quick_hint_var.set(hints.get(self.quick_mode_var.get(), ""))

    def _build_detached_quick_panel(self, parent):
        """extra_controls_builder callback for self.loop_console (see
        GenerationConsole.open_detached) -- builds a second, independent copy of the
        Quick-gen panel inside the detached console window, so a run can be started
        from there without switching back to the main window. Wrapped in its own
        Labelframe to visually separate it from the mirrored console output below.

        Returns a cleanup closure that GenerationConsole invokes when the detached
        window closes, removing this copy from self._quick_panels so later
        mode/state-sync loops don't touch destroyed widgets."""
        outer = ttk.Labelframe(parent, text=self.T("quick.section_title"))
        outer.pack(fill="x", padx=8, pady=(8, 0))
        panel = self._build_quick_generation_panel(outer)

        def _cleanup():
            if panel in self._quick_panels:
                self._quick_panels.remove(panel)

        return _cleanup

    def _on_quick_generate_or_stop_clicked(self):
        """Dual-function dispatch for the Quick-gen 'Generate' button: while a
        pipeline run is in flight, this button IS the stop control
        (its label already reads Stop -- see _on_run_loop); otherwise it's the
        normal generate path. Checked the same way _on_quick_generate_clicked already
        guards against double-launch (self._loop_runner.is_running())."""
        if self._loop_runner is not None and self._loop_runner.is_running():
            self._on_stop_loop()
        else:
            self._on_quick_generate_clicked()

    def _apply_loop_params_and_run(self, base_exponent, run_count, window_count_per_run):
        """Writes the computed low-level parameters into the EXISTING orchestrator_
        loop_v2 form fields (self._loop_vars) and fires the same launch path the
        low-level "Run" button uses (_on_run_loop) -- reuses its validation,
        settings-persistence, WslLoggedRunner wiring and live-output panel verbatim
        instead of duplicating any of it (the log pane right below this panel is
        where the real output shows up). n_instances/write_files/
        compute_sieving_primes_count/workers/batches_per_worker/window_m are left
        exactly as they already are in the low-level form -- the app translates the
        quick-gen inputs into width/window-count in the form below, but quick-gen
        only ever decides base_exponent/run_count/window_count_per_run, nothing
        else."""
        self._loop_vars["base_exponent"].set(str(base_exponent))
        self._loop_vars["run_count"].set(str(run_count))
        self._loop_vars["window_count_per_run"].set(str(window_count_per_run))
        self._on_run_loop()

    def _apply_primesieve_params_and_run(self, base_exponent, target_idx_start,
                                          window_count_per_run):
        """Quick-gen 'primesieve' mode's counterpart to _apply_loop_params_and_run() --
        this engine has no low-level form of its own (see prime_sieve_primesieve.py's
        simpler CLI, module header), so there are no self._loop_vars-equivalent fields
        to round-trip through first; the three values already fully determine the WSL
        command (see build_primesieve_argv/_on_run_primesieve). write_files is still
        read from the SAME checkbox the low-level orchestrator form uses
        (self._loop_write_files_var) -- one general "write files vs. count-only
        diagnostic" concept shared across every engine this app can launch, not
        something specific to orchestrator_loop_v2.py."""
        self._on_run_primesieve(base_exponent, target_idx_start, window_count_per_run)

    def _on_run_primesieve(self, base_exponent, target_idx_start, window_count_per_run):
        """Launch path for prime_sieve_primesieve.py -- deliberately reuses the SAME
        self._loop_runner/self._loop_output_queue/self.loop_console/self.loop_run_btn/
        self.loop_stop_btn/self.loop_status_label/_poll_loop_output/_on_loop_finished
        plumbing _on_run_loop() uses, rather than a separate runner+console+queue
        triple: only one Generation run can be in flight at a time regardless of which
        engine it uses (_on_quick_generate_or_stop_clicked already guards on
        self._loop_runner.is_running() for exactly this reason), and the live-output
        console/Stop control/tree-refresh-on-finish behavior are all engine-agnostic --
        duplicating that machinery for one more script would only add a second place
        every future change to it has to be made twice."""
        if self._loop_runner is not None and self._loop_runner.is_running():
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_already_running"))
            return
        write_files = self._loop_write_files_var.get()
        try:
            argv = build_primesieve_argv(
                base_exponent, target_idx_start, window_count_per_run,
                QUICK_GEN_MAX_WINDOW_WIDTH, write_files)
            log_path, exit_path, _run_id = generation_log_paths(self._get_portal_folder(), "primesieve")
            cmd = build_wsl_logged_command(argv, log_path, exit_path, self._get_portal_folder())

            self.loop_console.append(self._new_run_separator())
            self._loop_output_queue = queue.Queue()
            self._loop_runner = WslLoggedRunner(
                cmd, log_path, exit_path, self._loop_output_queue,
                kill_pattern="prime_sieve_primesieve.py")
            self._loop_runner.start()
        except Exception as e:  # noqa: BLE001 -- see _on_run_loop's own comment on
            # why this is caught and surfaced instead of silently swallowed.
            self._loop_runner = None
            messagebox.showerror(self.T("gen.dialog_title"), self.T(
                "gen.error_launch_failed", error=str(e)))
            return
        self.loop_run_btn.configure(state="disabled")
        self.loop_stop_btn.configure(state="normal")
        self.loop_status_label.set(self.T("common.running"))
        for panel in self._quick_panels:
            panel["generate_btn"].configure(text=self.T("common.stop"))
        self._show_loop_terminal()

    def _apply_orchestrator_direct_params_and_run(self, base_exponent, target_idx_start,
                                                    window_count_per_run):
        """Fallback counterpart to _apply_primesieve_params_and_run() for
        _offer_generate_missing_prime_window(), used only when the requested window
        falls beyond libprimesieve's own uint64 ceiling (PRIMESIEVE_MAX_STOP) -- see
        build_orchestrator_direct_argv()'s own docstring for why orchestrator_v3.py
        itself (not its loop wrapper) is the right engine there. Reads
        write_files/compute_sieving_primes_count from the same low-level form fields
        primesieve mode and the main 'Uruchom' button already use
        (self._loop_write_files_var/self._loop_count_sieving_var), and
        workers/batches_per_worker from self._loop_vars with a safe fallback of 1 each
        if that form hasn't been touched/validated yet -- unlike _on_run_loop()'s own
        validation, this call site must never block a search-triggered generation on
        an unrelated low-level field being blank or malformed."""
        self._on_run_orchestrator_direct(base_exponent, target_idx_start, window_count_per_run)

    def _on_run_orchestrator_direct(self, base_exponent, target_idx_start, window_count_per_run):
        """Launch path for orchestrator_v3.py run DIRECTLY (see
        build_orchestrator_direct_argv()) -- reuses the exact same
        self._loop_runner/self._loop_output_queue/self.loop_console/... plumbing
        _on_run_loop()/_on_run_primesieve() both already use, for the same
        one-runner-at-a-time reasoning _on_run_primesieve()'s own docstring gives."""
        if self._loop_runner is not None and self._loop_runner.is_running():
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_already_running"))
            return
        write_files = self._loop_write_files_var.get()
        compute_sieving = self._loop_count_sieving_var.get()

        def _positive_int_or(key, default):
            raw = self._loop_vars[key].get().strip()
            return int(raw) if raw.isdigit() and int(raw) > 0 else default

        workers = _positive_int_or("workers", 1)
        batches_per_worker = _positive_int_or("batches_per_worker", 1)
        try:
            argv = build_orchestrator_direct_argv(
                base_exponent, target_idx_start, window_count_per_run,
                QUICK_GEN_MAX_WINDOW_WIDTH, write_files, compute_sieving,
                workers, batches_per_worker)
            log_path, exit_path, _run_id = generation_log_paths(self._get_portal_folder(), "orchdirect")
            cmd = build_wsl_logged_command(argv, log_path, exit_path, self._get_portal_folder())

            self.loop_console.append(self._new_run_separator())
            self._loop_output_queue = queue.Queue()
            self._loop_runner = WslLoggedRunner(
                cmd, log_path, exit_path, self._loop_output_queue,
                kill_pattern="orchestrator_v3.py")
            self._loop_runner.start()
        except Exception as e:  # noqa: BLE001 -- see _on_run_loop's own comment on
            # why this is caught and surfaced instead of silently swallowed.
            self._loop_runner = None
            messagebox.showerror(self.T("gen.dialog_title"), self.T(
                "gen.error_launch_failed", error=str(e)))
            return
        self.loop_run_btn.configure(state="disabled")
        self.loop_stop_btn.configure(state="normal")
        self.loop_status_label.set(self.T("common.running"))
        for panel in self._quick_panels:
            panel["generate_btn"].configure(text=self.T("common.stop"))
        self._show_loop_terminal()

    def _try_fill_quick_gen_gap(self, floor_value, existing_count, width_mult):
        """Shared "fill gaps first" check for Floor mode's blank-starting-point path
        AND Exploration mode (see quick_floor_fill_gaps_var's own comment in
        _init_quick_generation_state -- the SAME toggle/variable drives both; added to
        Exploration 2026-08-18, at Artur's request, to match Floor mode's own
        behavior exactly ("tak jak tylko piętro")). Only changes anything when
        floor_value genuinely HAS a gap: find_first_gap_target_idx() returns the exact
        same value as existing_count (find_continuation_target_idx()) otherwise, so
        the "no gap" case returns False and callers fall straight through to their own
        normal continue-from-highest logic, unchanged. Returns True (and has ALREADY
        launched something + set quick_status_var) if a gap was found and filled;
        False otherwise -- callers should `return` immediately on True, exactly like
        any other terminal branch in _on_quick_generate_clicked.

        Deliberately launches at most width_mult windows into the gap -- ONE
        iteration's worth, never more, even from Exploration mode's own multi-
        iteration call site (which has no equivalent single-shot cap otherwise).
        Exploration's normal (non-gap) launches go through orchestrator_loop_v2.py
        specifically so each subprocess's own batch gets a bounded window_count_per_run
        -- orchestrator_v3.py's own batch_size is simply set equal to whatever
        window_count it receives (see that file's main(), batch_size = window_count),
        with NO internal chunking of its own. Collapsing gap-filling into one direct
        _launch_direct_window_range() call sized at iterations*width_mult instead of
        just width_mult would silently hand a single subprocess a batch far larger
        than Exploration's own Iterations field was ever meant to allow through in one
        step, reintroducing exactly the per-batch RAM risk multi-iteration launches
        exist to avoid (see [[feedback_ram_budget_round_down]]-style reasoning: prefer
        under-filling a wide gap over one oversized launch). A gap wider than
        width_mult is filled incrementally instead -- click by click, or automatically
        over repeated blank-Floor auto-detect passes -- using the same
        quick.note_gap_partial the caller already surfaces for this."""
        if not self.quick_floor_fill_gaps_var.get():
            return False
        gap_target_idx = find_first_gap_target_idx(
            self._get_portal_folder(), floor_value, QUICK_GEN_MAX_WINDOW_WIDTH)
        if gap_target_idx >= existing_count:
            return False
        floor_window_count = _floor_window_count(floor_value)
        gap_remaining = floor_window_count - gap_target_idx
        capped_width = min(width_mult, gap_remaining)
        reaches_existing = gap_target_idx + capped_width >= existing_count
        gap_start = 10 ** floor_value + gap_target_idx * QUICK_GEN_MAX_WINDOW_WIDTH
        self.quick_status_var.set(self.T(
            "quick.summary_floor_fill_gap", floor=floor_value,
            width_mult=capped_width,
            width_total=f"{capped_width * QUICK_GEN_MAX_WINDOW_WIDTH:,}",
            gap_start=f"{gap_start:,}",
            existing_count=count_existing_windows(self._get_portal_folder(), floor_value),
            added_count=capped_width)
            + (self.T("quick.note_gap_partial") if not reaches_existing else ""))
        # _launch_direct_window_range() (not _apply_loop_params_and_run()) since this
        # is a literal target_idx -- it also trims any edge overlap with what's
        # already on disk, though none is expected here since gap_target_idx is by
        # definition the first MISSING window.
        self._launch_direct_window_range(floor_value, gap_target_idx, capped_width)
        return True

    def _launch_direct_window_range(self, floor, target_idx_start, window_count):
        """Shared dispatch for every caller that already knows its own literal
        [target_idx_start, target_idx_start + window_count) target (Range mode, Floor
        mode with a starting point, Goldbach's 'generate missing range' offer -- see
        _quick_gen_plan_literal_range()'s own docstring for how that target_idx_start
        is computed) -- writes starting EXACTLY there, never backfilling anything
        before it, unlike orchestrator_loop_v2.py's own continuation-only wrapper
        (build_loop_argv()), which has no notion of an arbitrary start position at
        all. Picks whichever engine can actually reach that magnitude: primesieve
        mode if the whole requested range still fits under libprimesieve's own uint64
        ceiling (PRIMESIEVE_MAX_STOP), else orchestrator_v3.py launched directly (see
        build_orchestrator_direct_argv()'s own docstring) -- the exact same
        ceiling-aware choice _offer_generate_missing_prime_window() already makes for
        the search flow's own missing-fragment offer.

        Trims against what's ALREADY on disk first (see
        _trim_existing_from_target_idx_range()'s own docstring) -- every engine this
        app can launch overwrites unconditionally with no existence check of its own,
        so this is the one place that avoids redundantly re-sieving/rewriting windows
        the caller's own request happens to overlap."""
        trimmed_start, trimmed_count = _trim_existing_from_target_idx_range(
            self._get_portal_folder(), floor, target_idx_start, window_count, QUICK_GEN_MAX_WINDOW_WIDTH)
        if trimmed_count <= 0:
            self.quick_status_var.set(self.T("quick.status_range_fully_covered"))
            return
        range_end_abs = 10 ** floor + (trimmed_start + trimmed_count) * QUICK_GEN_MAX_WINDOW_WIDTH
        if range_end_abs - 1 > PRIMESIEVE_MAX_STOP:
            self._apply_orchestrator_direct_params_and_run(floor, trimmed_start, trimmed_count)
        else:
            self._apply_primesieve_params_and_run(floor, trimmed_start, trimmed_count)

    def _quick_gen_plan_literal_range(self, start, end, max_window_count=None):
        """Shared by Range mode and Floor mode WITH a starting point set (see
        _on_quick_generate_clicked): given a literal [start, end) target, rounds it
        out to whole QUICK_GEN_MAX_WINDOW_WIDTH windows, CLAMPS it to the starting
        floor's own boundary if it would otherwise cross into the next floor (see the
        "truncated" note below), rejects it if it can't be grid-aligned even after
        rounding/clamping (only affects very low floors), and checks it against
        find_continuation_target_idx -- i.e. against what's ACTUALLY on disk --
        instead of just handing window_count_per_run to orchestrator_loop_v2's own
        continuation-only engine and hoping it lines up with what was asked for. That
        mismatch used to be a real bug for Floor mode: a starting point picked WHICH
        floor to generate (via digit_count_floor) but was otherwise silently ignored
        -- generation always just continued from wherever that floor's storage
        already ended, even if the requested range was already fully covered. This
        makes both modes report "already in storage" instead of launching a
        redundant run in that case, and generate only the missing gap otherwise --
        never anything outside/before what was asked for, consistent with this
        project's established "always round up, never trim" philosophy (see
        _round_range_to_window) -- EXCEPT at the far end, where "never trim" would
        mean silently spilling numbers from the NEXT floor into this one's folder
        (see the floor-7-with-130M-numbers bug this was written to fix). The floor
        boundary is the one edge this function always trims TO rather than rounds
        past.

        CLAMPING NOTE: a requested end past the starting floor's own boundary
        (10**(floor_lo+1)) gets silently pulled back to that boundary -- e.g. asking
        for floor 7 with a width that would reach into floor 8's numbers instead
        stops at floor 7's last window, and whatever was asked for beyond that is
        simply dropped, never generated under this call. This mirrors exactly what a
        low floor's own single-window cap already does (see LOW_FLOOR_CUTOFF) --
        every floor, low or high, now has a firm upper edge this function will not
        cross. Deliberately GUI-side, not backend: main_batch_scanner itself has no
        opinion on where a floor ends for base_power >= LOW_FLOOR_CUTOFF (it just
        writes whatever combined range it's given under the requested folder), so the
        caller choosing window_count_per_run is what has to stay inside the lines.
        Exploration mode is NOT routed through this function and is NOT capped this
        way on purpose -- marching across floor boundaries and picking up wherever
        the next floor needs filling is that mode's whole point, not a bug to guard
        against (see _on_quick_generate_clicked's explore branch).

        Returns a dict:
          {"error": (title, message)}                          -- invalid request,
                                                                    show it and stop
          {"already": True, "rounded_start", "rounded_end",
           "existing_count", "truncated"}                       -- fully covered
                                                                    already
          {"floor", "existing_count", "window_count_per_run",
           "rounded_start", "rounded_end", "truncated"}          -- what to launch
        "truncated" is True whenever the requested end got clamped back to the
        floor's own boundary -- callers should mention that in their status message
        so a shortened run isn't mistaken for the full request having been honored.

        LAUNCH START (added 2026-08-18, at Artur's request): "target_idx_start" in
        the launch-case dict is max(the request's OWN literal target_idx, existing_
        count) -- never less than the literal request (so a starting point picked
        deep into an otherwise-empty floor no longer silently balloons into
        backfilling everything from index 0 up to it, which used to both misrepresent
        what was asked for AND crash prime_sieve_v4_1.py outright for a big enough gap
        -- MemoryError building a target_idx Python list hundreds of quadrillions of
        entries long, a real run on floor 25 hit exactly this), and never less than
        existing_count either (so the ordinary case -- filling from at/near the front
        of an already-partially-generated floor -- is untouched: this reduces to
        exactly today's existing_count-based start when the request doesn't reach
        past it). window_count_per_run is sized to this SAME start, so it only ever
        covers what's actually still missing from [target_idx_start, target_idx_end)
        -- never more. Callers should launch via a target_idx_start-CAPABLE engine
        (see _launch_direct_window_range()), not orchestrator_loop_v2.py's own
        continuation-only wrapper, which has no way to honor a start past wherever
        storage currently ends.

        max_window_count (added 2026-08-18, at Artur's request, after a real floor-25
        run logged "target_idx X..X+1000 (1001 windows)" for a Width=1000 request):
        _round_range_to_window() rounds the START down AND the END up to the nearest
        window boundary -- deliberate for Range mode's own from/to contract ("never
        fall short of what was literally asked for", see that function's docstring),
        but wrong for a caller like Floor mode's Starting-point path, where Width is
        an explicit WINDOW-COUNT BUDGET, not a literal end number: whenever the typed
        starting point isn't itself a multiple of QUICK_GEN_MAX_WINDOW_WIDTH (the
        common case for a search-driven starting point), rounding BOTH ends outward
        silently adds exactly one extra window beyond the requested count -- a
        correctness bug on its own (the launched run no longer matches what the
        summary message told the person it would do), and specifically the wrong
        direction for a RAM-budgeted launch, where the safer failure mode is covering
        slightly less than asked (at most one window's width short at the tail) rather
        than more. Callers that pass a window-count budget here (Floor mode's
        Starting-point path; NOT Range mode, which has no count concept, only the
        literal from/to numbers themselves) should pass their own width_mult as
        max_window_count -- this clamps target_idx_end (and, consequently,
        window_count_per_run) to never exceed literal_target_idx_start +
        max_window_count, on top of whatever the floor-boundary clamp above already
        did (whichever constraint is tighter wins; if the floor boundary already cut
        target_idx_end down at or below the budget, this is a no-op). Sets
        "width_capped" in the returned dict so callers can surface a distinct note --
        deliberately NOT folded into "truncated" (that flag/note is specifically about
        the floor-boundary reason and would misdescribe this one)."""
        rounded_start, rounded_end = _round_range_to_window(start, end)
        floor_lo = digit_count_floor(rounded_start)
        floor_boundary = 10 ** (floor_lo + 1)
        truncated = rounded_end > floor_boundary
        if truncated:
            rounded_end = floor_boundary
        base = 10 ** floor_lo
        if ((rounded_start - base) % QUICK_GEN_MAX_WINDOW_WIDTH
                or (rounded_end - base) % QUICK_GEN_MAX_WINDOW_WIDTH):
            return {"error": (self.T("quick.dialog_title"), self.T("quick.error_range_misaligned"))}
        literal_target_idx_start = (rounded_start - base) // QUICK_GEN_MAX_WINDOW_WIDTH
        target_idx_end = (rounded_end - base) // QUICK_GEN_MAX_WINDOW_WIDTH
        width_capped = False
        if max_window_count is not None:
            budget_target_idx_end = literal_target_idx_start + max_window_count
            if budget_target_idx_end < target_idx_end:
                target_idx_end = budget_target_idx_end
                rounded_end = base + target_idx_end * QUICK_GEN_MAX_WINDOW_WIDTH
                width_capped = True
        existing_count = find_continuation_target_idx(
            self._get_portal_folder(), floor_lo, QUICK_GEN_MAX_WINDOW_WIDTH)
        # existing_count above is a CONTINUATION POSITION, not necessarily the real
        # file count on a floor with interior gaps -- real_existing_count is for
        # DISPLAY only (see count_existing_windows()'s own docstring); every caller's
        # own arithmetic must keep using existing_count/target_idx_start.
        real_existing_count = count_existing_windows(self._get_portal_folder(), floor_lo)
        if target_idx_end <= existing_count:
            return {"already": True, "rounded_start": rounded_start,
                    "rounded_end": rounded_end, "existing_count": existing_count,
                    "real_existing_count": real_existing_count,
                    "truncated": truncated, "width_capped": width_capped}
        launch_target_idx_start = max(literal_target_idx_start, existing_count)
        return {"floor": floor_lo, "existing_count": existing_count,
                 "real_existing_count": real_existing_count,
                 "target_idx_start": launch_target_idx_start,
                 "window_count_per_run": target_idx_end - launch_target_idx_start,
                 "rounded_start": rounded_start, "rounded_end": rounded_end,
                 "truncated": truncated, "width_capped": width_capped}

    def _on_quick_generate_clicked(self):
        """Real launch path: computes base_exponent/run_count/
        window_count_per_run for whichever mode is selected and hands them to
        _apply_loop_params_and_run().

        Floor only: blank starting point is pure "add N more windows to this
        floor" (orchestrator_loop_v2's own continuation-only behavior -- always
        either right after the highest existing window, or target_idx=0 if nothing
        exists yet). A starting point given, though, now means a literal target --
        handled by _quick_gen_plan_literal_range exactly like Range mode, so it can
        report "already in storage" instead of silently generating past what was
        actually asked for.

        Range -- from/to and Exploration (via its own Width field, same meaning as
        Floor only's) both go through _quick_gen_plan_literal_range /
        find_continuation_target_idx too -- see that method's docstring."""
        if self._loop_runner is not None and self._loop_runner.is_running():
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_already_running"))
            return
        mode = self.quick_mode_var.get()
        if mode == "floor":
            raw_floor = self.quick_floor_var.get().strip()
            floor_value = _eval_quick_number(raw_floor)
            if floor_value is None or floor_value < 0:
                messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_floor_required"))
                return
            width_mult = _eval_quick_number(self.quick_floor_width_var.get()) or 1
            width_total = width_mult * QUICK_GEN_MAX_WINDOW_WIDTH
            raw_start = self.quick_floor_start_var.get().strip()
            start_value = _eval_quick_number(raw_start)
            if start_value is not None:
                # max_window_count=width_mult -- Width here is an explicit window-COUNT
                # budget (unlike Range mode's raw from/to, which has no count concept
                # and is left uncapped, see _quick_gen_plan_literal_range's own
                # docstring) -- without this, a starting point that isn't itself a
                # multiple of QUICK_GEN_MAX_WINDOW_WIDTH (the common case for a
                # search-driven starting point) silently launches ONE MORE window than
                # Width says, exactly the "1001 windows for a Width=1000 request" bug a
                # real floor-25 run hit.
                plan = self._quick_gen_plan_literal_range(
                    start_value, start_value + width_total, max_window_count=width_mult)
                if plan.get("error"):
                    messagebox.showerror(*plan["error"])
                    return
                if plan.get("already"):
                    self.quick_status_var.set(self.T(
                        "quick.status_already_in_storage",
                        rounded_start=f"{plan['rounded_start']:,}",
                        rounded_end=f"{plan['rounded_end']:,}",
                        existing_count=plan["real_existing_count"]))
                    return
                self.quick_status_var.set(self.T(
                    "quick.summary_range", start=f"{start_value:,}",
                    end=f"{start_value + width_total:,}",
                    rounded_start=f"{plan['rounded_start']:,}",
                    rounded_end=f"{plan['rounded_end']:,}", floor=plan["floor"],
                    existing_count=plan["real_existing_count"],
                    added_count=plan["window_count_per_run"])
                    + (self.T("quick.note_truncated_floor_boundary",
                          boundary=f"{plan['rounded_end']:,}")
                       if plan.get("truncated") else "")
                    + (self.T("quick.note_width_capped_alignment")
                       if plan.get("width_capped") else ""))
                self._launch_direct_window_range(
                    plan["floor"], plan["target_idx_start"], plan["window_count_per_run"])
                return
            existing_count = find_continuation_target_idx(
                self._get_portal_folder(), floor_value, QUICK_GEN_MAX_WINDOW_WIDTH)
            if floor_value < LOW_FLOOR_CUTOFF:
                # A floor below the cutoff (see LOW_FLOOR_CUTOFF's own docstring) is
                # ALWAYS exactly one window wide at most, never continuable past
                # target_idx=0 -- treating it like a normal floor here used to let a
                # blank-starting-point click keep appending another
                # QUICK_GEN_MAX_WINDOW_WIDTH-sized window (e.g. "..._off_10M.bin")
                # onto a floor whose real numeric domain is only a few thousand/million
                # numbers wide, silently mislabeling a chunk of a HIGHER floor's numbers
                # as belonging to this one. existing_count >= 1 means the single
                # low-floor window is already there (written by main_batch_scanner's
                # low-floor branch, possibly while cascading up from a lower floor's own
                # request -- see that function's docstring) -- nothing left to do.
                if existing_count >= 1:
                    rounded_start = 10 ** floor_value
                    rounded_end = rounded_start + QUICK_GEN_MAX_WINDOW_WIDTH
                    self.quick_status_var.set(self.T(
                        "quick.status_already_in_storage",
                        rounded_start=f"{rounded_start:,}", rounded_end=f"{rounded_end:,}",
                        existing_count=existing_count))
                    return
                self.quick_status_var.set(self.T(
                    "quick.summary_floor", floor=floor_value, width_mult=1,
                    width_total=f"{QUICK_GEN_MAX_WINDOW_WIDTH:,}",
                    start=self.T("quick.start_continue_last"),
                    existing_count=0, added_count=1))
                self._apply_loop_params_and_run(floor_value, 1, 1)
                return
            # Floor >= LOW_FLOOR_CUTOFF: cap window_count_per_run so target_idx never
            # crosses into the NEXT floor's own numeric range -- see
            # _floor_window_count's docstring for the bug this closes (floor 7 ending
            # up with 130-million-range numbers filed under its folder because nothing
            # here checked where floor 7 actually ends).
            floor_window_count = _floor_window_count(floor_value)
            if self._try_fill_quick_gen_gap(floor_value, existing_count, width_mult):
                return
            remaining = floor_window_count - existing_count
            if remaining <= 0:
                self.quick_status_var.set(self.T(
                    "quick.status_floor_full", floor=floor_value,
                    existing_count=count_existing_windows(self._get_portal_folder(), floor_value),
                    floor_window_count=floor_window_count))
                return
            capped_width = min(width_mult, remaining)
            self.quick_status_var.set(self.T(
                "quick.summary_floor", floor=floor_value, width_mult=capped_width,
                width_total=f"{capped_width * QUICK_GEN_MAX_WINDOW_WIDTH:,}",
                start=self.T("quick.start_continue_last"),
                existing_count=count_existing_windows(self._get_portal_folder(), floor_value),
                added_count=capped_width)
                + (self.T("quick.note_truncated_floor_boundary",
                      boundary=f"{10 ** (floor_value + 1):,}")
                   if capped_width < width_mult else ""))
            self._apply_loop_params_and_run(floor_value, 1, capped_width)
        elif mode == "range":
            raw_from = self.quick_from_var.get().strip()
            raw_to = self.quick_to_var.get().strip()
            start = _eval_quick_number(raw_from)
            end = _eval_quick_number(raw_to)
            if not raw_from or not raw_to or start is None or end is None:
                messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_range_required"))
                return
            if start < 0:
                messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_range_negative"))
                return
            if start >= end:
                messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_range_order"))
                return
            plan = self._quick_gen_plan_literal_range(start, end)
            if plan.get("error"):
                messagebox.showerror(*plan["error"])
                return
            if plan.get("already"):
                self.quick_status_var.set(self.T(
                    "quick.status_already_in_storage",
                    rounded_start=f"{plan['rounded_start']:,}",
                    rounded_end=f"{plan['rounded_end']:,}",
                    existing_count=plan["real_existing_count"]))
                return
            self.quick_status_var.set(self.T(
                "quick.summary_range", start=f"{start:,}", end=f"{end:,}",
                rounded_start=f"{plan['rounded_start']:,}",
                rounded_end=f"{plan['rounded_end']:,}", floor=plan["floor"],
                existing_count=plan["real_existing_count"],
                added_count=plan["window_count_per_run"])
                + (self.T("quick.note_truncated_floor_boundary",
                      boundary=f"{plan['rounded_end']:,}")
                   if plan.get("truncated") else ""))
            self._launch_direct_window_range(
                plan["floor"], plan["target_idx_start"], plan["window_count_per_run"])
        elif mode == "explore":
            raw_floor = self.quick_explore_floor_var.get().strip()
            if raw_floor:
                floor_value = _eval_quick_number(raw_floor)
                if floor_value is None or floor_value < 0:
                    messagebox.showerror(
                        self.T("quick.dialog_title"), self.T("quick.error_explore_floor_required"))
                    return
            else:
                # Blank Floor = continue from wherever the deepest generated data in
                # the WHOLE database currently sits (the highest 10p{N} folder with any
                # files), re-detected fresh on every click rather than sticky in the
                # entry field -- so repeatedly pressing Generate with nothing typed
                # always keeps extending whatever floor is genuinely deepest right now,
                # even if something else (another Quick-gen run, a restore) advanced
                # the database in the meantime. See find_highest_populated_floor()'s own
                # docstring. Falls through to the same "type one yourself" error as
                # before when literally nothing has been generated anywhere yet -- there
                # is no floor to continue from in that case.
                floor_value = find_highest_populated_floor(self._get_portal_folder())
                if floor_value is None:
                    messagebox.showerror(
                        self.T("quick.dialog_title"), self.T("quick.error_explore_floor_required"))
                    return
            iterations = _eval_quick_number(self.quick_iterations_var.get()) or 1
            width_mult = _eval_quick_number(self.quick_explore_width_var.get()) or 1
            window_count_per_run = width_mult
            existing_count = find_continuation_target_idx(
                self._get_portal_folder(), floor_value, QUICK_GEN_MAX_WINDOW_WIDTH)
            if floor_value < LOW_FLOOR_CUTOFF:
                # Same low-floor guard as blank-starting-point Floor mode above (see
                # that branch's comment for the full rationale) -- Exploration is meant
                # for deep/high floors, but nothing stops someone from picking a low one
                # here too, and it would hit the exact same "keeps appending
                # QUICK_GEN_MAX_WINDOW_WIDTH-sized chunks past a floor's real, much
                # smaller domain" bug otherwise.
                if existing_count >= 1:
                    # Floors 0-6 are ALREADY fully done -- the one-shot low-floor batch
                    # already ran, whether just now (this click) or in the past --
                    # there is nothing left to explore down here, EVER (LOW_FLOOR_CUTOFF
                    # is a fixed, permanently-capped range, not a moving target). Roll
                    # forward to floor 7 -- the first floor Exploration's real
                    # target_idx-based, uncapped continuation actually applies to -- and
                    # fall through to the SAME launch logic below using the request's
                    # own iterations/width there, instead of just reporting "already in
                    # storage" and stopping dead. Reported via screenshot: Floor=6
                    # (already complete, picked by the Auto button) kept reporting
                    # nothing to do instead of continuing into floor 7+. The Floor field
                    # itself is updated to show "7" too, so what's displayed matches
                    # what actually ran, and a follow-up click (blank or typed) starts
                    # from the right place.
                    floor_value = LOW_FLOOR_CUTOFF
                    self.quick_explore_floor_var.set(str(floor_value))
                    existing_count = find_continuation_target_idx(
                        self._get_portal_folder(), floor_value, QUICK_GEN_MAX_WINDOW_WIDTH)
                else:
                    self.quick_status_var.set(self.T(
                        "quick.summary_explore", floor=floor_value, iterations=1,
                        width_mult=1, iterations_total=f"{QUICK_GEN_MAX_WINDOW_WIDTH:,}",
                        existing_count=0, added_count=1))
                    self._apply_loop_params_and_run(floor_value, 1, 1)
                    return
            # Floor >= LOW_FLOOR_CUTOFF (arrived here directly, or just rolled forward
            # from a completed low-floor batch above): roll forward through however
            # many CONSECUTIVE floors are already full -- the low-floor block above
            # only ever resolves the 0-6 -> 7 jump once, so without this loop, typing
            # (or Auto-detecting) any floor >= 7 that happens to already be complete
            # hit the exact bug reported: Exploration fell straight through to
            # _apply_loop_params_and_run below with no completion check at all (unlike
            # Floor mode's remaining<=0 guard a few branches up), so it kept writing
            # more windows into an ALREADY-COMPLETE floor's folder -- silently filing
            # data that numerically belongs to the NEXT floor under this one's name.
            # Bounded at 1000 advances purely as a runaway-loop guard; floor capacity
            # grows fast enough (see _floor_window_count) that a real run should never
            # get remotely close to that.
            # "Fill gaps first" check BEFORE the roll-forward loop below -- checked
            # again inside the loop too, for every floor it advances THROUGH: a floor
            # Exploration has never personally visited can still have a gap (e.g. a
            # search or Goldbach "generate missing range" offer wrote directly into
            # it), and the roll-forward loop's own "remaining<=0" fullness check
            # only looks at the highest existing file, not interior gaps -- so
            # without this, such a floor would be silently skipped past as "already
            # full" instead of having its gap filled first. See
            # _try_fill_quick_gen_gap()'s own docstring.
            if self._try_fill_quick_gen_gap(floor_value, existing_count, width_mult):
                return
            floor_window_count = _floor_window_count(floor_value)
            remaining = floor_window_count - existing_count
            advances = 0
            while remaining <= 0 and advances < 1000:
                floor_value += 1
                self.quick_explore_floor_var.set(str(floor_value))
                existing_count = find_continuation_target_idx(
                    self._get_portal_folder(), floor_value, QUICK_GEN_MAX_WINDOW_WIDTH)
                if self._try_fill_quick_gen_gap(floor_value, existing_count, width_mult):
                    return
                floor_window_count = _floor_window_count(floor_value)
                remaining = floor_window_count - existing_count
                advances += 1
            if remaining <= 0:
                self.quick_status_var.set(self.T(
                    "quick.status_floor_full", floor=floor_value,
                    existing_count=count_existing_windows(self._get_portal_folder(), floor_value),
                    floor_window_count=floor_window_count))
                return
            # Same reasoning as Floor mode's capped_width just above: base_exponent is
            # FIXED for an entire orchestrator run (see _apply_loop_params_and_run's own
            # docstring), so a single launch can never itself cross from this floor into
            # the next one -- cap the requested iterations*window_count_per_run down to
            # whatever this floor actually has left, rather than letting it overshoot.
            requested_total = iterations * window_count_per_run
            truncated = requested_total > remaining
            if truncated:
                if window_count_per_run <= remaining:
                    iterations = max(1, remaining // window_count_per_run)
                else:
                    window_count_per_run = remaining
                    iterations = 1
            iteration_width = window_count_per_run * QUICK_GEN_MAX_WINDOW_WIDTH
            iterations_total = iterations * iteration_width
            self.quick_status_var.set(self.T(
                "quick.summary_explore", floor=floor_value, iterations=iterations,
                width_mult=window_count_per_run, iterations_total=f"{iterations_total:,}",
                existing_count=count_existing_windows(self._get_portal_folder(), floor_value),
                added_count=iterations * window_count_per_run)
                + (self.T("quick.note_truncated_floor_boundary",
                      boundary=f"{10 ** (floor_value + 1):,}")
                   if truncated else ""))
            self._apply_loop_params_and_run(floor_value, iterations, window_count_per_run)
        else:
            # mode == "primesieve": From + Width (NOT From/To -- see
            # _build_quick_mode_primesieve's docstring for why) determine the literal
            # [start, end) target the exact same way Floor mode's own "Starting point"
            # flow does (start_value, start_value + width_total) -- fed into the SAME
            # _quick_gen_plan_literal_range() Range mode uses, PLUS a check against
            # libprimesieve's own uint64 ceiling (PRIMESIEVE_MAX_STOP) -- see that
            # constant's docstring and prime_sieve_primesieve.py's
            # generate_floor_windows() for where the actual clamp happens (backend-side,
            # reading the live library value, not this duplicated GUI-side one). Launches
            # via _apply_primesieve_params_and_run (prime_sieve_primesieve.py) instead of
            # _apply_loop_params_and_run (orchestrator_loop_v2.py).
            raw_from = self.quick_primesieve_from_var.get().strip()
            start = _eval_quick_number(raw_from)
            width_mult = _eval_quick_number(self.quick_primesieve_width_var.get()) or 1
            if not raw_from or start is None:
                # Blank From with a Floor typed in is NOT an error -- it means the same
                # thing blank Floor mode's own Starting point does: continue
                # automatically from wherever this floor's storage currently ends (0,
                # i.e. the floor's own start, if nothing is there yet). Clicking Auto
                # first is a convenience to SEE that number before committing, not a
                # required step -- Generate alone should already do the right thing on
                # an empty floor, the same way every other mode's blank-continuation
                # flow does.
                raw_floor = self.quick_primesieve_floor_var.get().strip()
                floor_value = _eval_quick_number(raw_floor)
                if not raw_floor or floor_value is None or floor_value < 0:
                    messagebox.showerror(
                        self.T("quick.dialog_title"), self.T("quick.error_primesieve_from_required"))
                    return
                start = 10 ** floor_value
                if floor_value >= LOW_FLOOR_CUTOFF:
                    existing_count = find_continuation_target_idx(
                        self._get_portal_folder(), floor_value, QUICK_GEN_MAX_WINDOW_WIDTH)
                    start = 10 ** floor_value + existing_count * QUICK_GEN_MAX_WINDOW_WIDTH
                self.quick_primesieve_from_var.set(str(start))
            if start < 0:
                messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_range_negative"))
                return

            # A low floor (see LOW_FLOOR_CUTOFF) is at most ONE combined window wide,
            # ever -- Width is meaningless for it (mirrors Floor mode's own blank-
            # starting-point low-floor branch, which ignores its Width field the same
            # way). Whatever floor `start` actually falls in decides this, not the
            # separate Floor field (which is only a lookup convenience for Auto) --
            # same reasoning Floor mode's own starting-point flow already uses
            # (digit_count_floor(start), not a separately-typed field).
            floor_lo = digit_count_floor(start)
            if floor_lo < LOW_FLOOR_CUTOFF:
                existing_count = find_continuation_target_idx(
                    self._get_portal_folder(), floor_lo, QUICK_GEN_MAX_WINDOW_WIDTH)
                if existing_count >= 1:
                    rounded_start = 10 ** floor_lo
                    rounded_end = rounded_start + QUICK_GEN_MAX_WINDOW_WIDTH
                    self.quick_status_var.set(self.T(
                        "quick.status_already_in_storage",
                        rounded_start=f"{rounded_start:,}", rounded_end=f"{rounded_end:,}",
                        existing_count=existing_count))
                    return
                self.quick_status_var.set(self.T(
                    "quick.summary_floor", floor=floor_lo, width_mult=1,
                    width_total=f"{QUICK_GEN_MAX_WINDOW_WIDTH:,}",
                    start=self.T("quick.start_continue_last"),
                    existing_count=0, added_count=1))
                self._apply_primesieve_params_and_run(floor_lo, 0, 1)
                return

            end = start + width_mult * QUICK_GEN_MAX_WINDOW_WIDTH
            if start > PRIMESIEVE_MAX_STOP:
                messagebox.showerror(self.T("quick.dialog_title"), self.T(
                    "quick.error_primesieve_beyond_ceiling",
                    max_stop=f"{PRIMESIEVE_MAX_STOP:,}"))
                return
            plan = self._quick_gen_plan_literal_range(start, end)
            if plan.get("error"):
                messagebox.showerror(*plan["error"])
                return
            if plan.get("already"):
                self.quick_status_var.set(self.T(
                    "quick.status_already_in_storage",
                    rounded_start=f"{plan['rounded_start']:,}",
                    rounded_end=f"{plan['rounded_end']:,}",
                    existing_count=plan["real_existing_count"]))
                return
            ceiling_truncated = (plan["rounded_end"] - 1) > PRIMESIEVE_MAX_STOP
            self.quick_status_var.set(self.T(
                "quick.summary_range", start=f"{start:,}", end=f"{end:,}",
                rounded_start=f"{plan['rounded_start']:,}",
                rounded_end=f"{plan['rounded_end']:,}", floor=plan["floor"],
                existing_count=plan["real_existing_count"],
                added_count=plan["window_count_per_run"])
                + (self.T("quick.note_truncated_floor_boundary",
                      boundary=f"{plan['rounded_end']:,}")
                   if plan.get("truncated") else "")
                + (self.T("quick.note_primesieve_ceiling",
                      max_stop=f"{PRIMESIEVE_MAX_STOP:,}")
                   if ceiling_truncated else ""))
            self._apply_primesieve_params_and_run(
                plan["floor"], plan["target_idx_start"], plan["window_count_per_run"])

    def _collect_loop_settings_from_form(self):
        """Reads + validates every orchestrator_loop_v2 form field. Returns a dict of
        parsed values on success, or None (after a messagebox explaining which field
        is wrong) if anything fails validation -- mirrors the existing "Szukaj"
        fields' isdigit()-based validation pattern elsewhere in this file."""
        # base_exponent (the floor) is the ONE field here allowed to be 0 -- floor 0
        # is [10^0, 10^1) = [1, 10), a legitimate floor (holds 2, 3, 5, 7 among
        # others), not a placeholder/unset value. Every other field genuinely needs
        # to be strictly positive (0 windows/workers/batches/runs/instances doesn't
        # mean anything) -- this used to lump base_exponent in with those and reject
        # it right alongside them, silently making floor 0 impossible to generate.
        zero_allowed_fields = {"base_exponent"}
        int_fields = ("base_exponent", "run_count", "n_instances", "window_count_per_run",
                      "workers", "batches_per_worker", "window_m")
        parsed = {}
        for key in int_fields:
            raw = self._loop_vars[key].get().strip()
            minimum = 0 if key in zero_allowed_fields else 1
            if not raw.isdigit() or int(raw) < minimum:
                messagebox.showerror(
                    self.T("gen.dialog_title"), self.T("gen.error_field_int", field=key))
                return None
            parsed[key] = int(raw)
        parsed["write_files"] = self._loop_write_files_var.get()
        parsed["compute_sieving_primes_count"] = self._loop_count_sieving_var.get()
        return parsed

    def _on_run_loop(self):
        if self._loop_runner is not None and self._loop_runner.is_running():
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_already_running"))
            return
        parsed = self._collect_loop_settings_from_form()
        if parsed is None:
            return

        try:
            self._generation_settings["loop"] = {
                "base_exponent": str(parsed["base_exponent"]),
                "run_count": str(parsed["run_count"]),
                "n_instances": str(parsed["n_instances"]),
                "write_files": parsed["write_files"],
                "compute_sieving_primes_count": parsed["compute_sieving_primes_count"],
                "window_count_per_run": str(parsed["window_count_per_run"]),
                "workers": str(parsed["workers"]),
                "batches_per_worker": str(parsed["batches_per_worker"]),
                "window_m": str(parsed["window_m"]),
            }
            save_generation_settings(self._get_portal_folder(), self._generation_settings)

            argv = build_loop_argv(
                parsed["base_exponent"], parsed["run_count"], parsed["n_instances"],
                parsed["write_files"], parsed["compute_sieving_primes_count"],
                parsed["window_count_per_run"], parsed["workers"], parsed["batches_per_worker"],
                parsed["window_m"])
            log_path, exit_path, _run_id = generation_log_paths(self._get_portal_folder(), "loop")
            cmd = build_wsl_logged_command(argv, log_path, exit_path, self._get_portal_folder())

            self.loop_console.append(self._new_run_separator())
            self._loop_output_queue = queue.Queue()
            self._loop_runner = WslLoggedRunner(
                cmd, log_path, exit_path, self._loop_output_queue,
                kill_pattern="orchestrator_loop_v2.py")
            self._loop_runner.start()
        except Exception as e:  # noqa: BLE001 -- a launch failure here used to be
            # silently swallowed by Tk's default callback exception handling (printed
            # to a console window the user usually can't see, GUI otherwise looked
            # unchanged -- "plan computed, nothing launches, no error" -- reported by
            # Artur 2026-08-24). Surface it instead of guessing at the cause blind.
            self._loop_runner = None
            messagebox.showerror(self.T("gen.dialog_title"), self.T(
                "gen.error_launch_failed", error=str(e)))
            return
        self.loop_run_btn.configure(state="disabled")
        self.loop_stop_btn.configure(state="normal")
        self.loop_status_label.set(self.T("common.running"))
        # Generate doubles as Stop while this runs (see
        # _on_quick_generate_or_stop_clicked), and the terminal auto-expands the
        # moment a run actually starts -- reset back to normal in
        # _on_loop_finished() once it exits. Looped over every currently-open
        # Quick-gen panel instance (embedded + detached copy, if any).
        for panel in self._quick_panels:
            panel["generate_btn"].configure(text=self.T("common.stop"))
        self._show_loop_terminal()

    def _on_stop_loop(self):
        if self._loop_runner is not None:
            self._loop_runner.stop()
            self.loop_status_label.set(self.T("common.stopping"))

    def _on_loop_finished(self):
        """_drain_output_queue's on_exit callback for the loop queue -- resets every
        open Quick-gen panel's 'Generate' button back from its temporary 'Stop'
        label now that nothing is running. Deliberately does NOT touch the console's
        collapse state -- it stays expanded so the final log is still visible after
        the run finishes.

        Also re-runs reload_primes_tree() -- the SAME rebuild the manual Refresh
        button on the Prime numbers tab triggers -- so newly written/regenerated
        windows show up there without the person having to notice the run finished
        and go click Refresh themselves. Previously nothing here touched that tree at
        all, so a completed generation (including a low-floor completion/regeneration
        -- see LOW_FLOOR_CUTOFF) stayed invisible until a manual refresh; this closes
        that gap the same way _set_portal_folder already does after a storage-path
        change."""
        for panel in self._quick_panels:
            panel["generate_btn"].configure(text=self.T("quick.generate_button"))
        self.reload_primes_tree()

        # A search-triggered "generate the missing window" run (see
        # _offer_generate_missing_prime_window()) just finished -- re-run the SAME
        # search now that the fragment should be on disk. Runs regardless of the
        # exit code: a failed/stopped run just means the re-search comes back empty
        # again, same as any other genuinely-not-found case, rather than needing a
        # separate error path here.
        if self._pending_search_after_prime_gen is not None:
            pending = self._pending_search_after_prime_gen
            self._pending_search_after_prime_gen = None
            self._start_search_job(pending["kind"], pending["base_exponent"], pending["number"])

        # Mirrors the block above, for a Wizualizacja/decompose "generate the
        # missing range" offer instead of a prime/constellation search miss
        # (see _goldbach_offer_generate_missing_range) -- re-queues whichever
        # of the two ops actually reported the gap, now that generation should
        # have filled it. "viz" re-reads n/row-page/od-do fresh from the still-
        # open Toplevel's own entries (_goldbach_queue_viz); "decompose" reuses
        # self._goldbach_decompose_current_n/current_pmax/page, already set by
        # the original _on_goldbach_viz_decompose click and left untouched by
        # the failed attempt (see _goldbach_queue_decompose_page's docstring).
        # Runs regardless of exit code, same reasoning as the prime-window
        # block: a failed/stopped run just means the retry reports the same
        # gap again.
        if self._pending_goldbach_retry_op is not None:
            retry_op = self._pending_goldbach_retry_op
            self._pending_goldbach_retry_op = None
            if retry_op == "viz":
                self.research_goldbach_tab_widget.retry_viz()
            elif retry_op == "decompose":
                self.research_goldbach_tab_widget.retry_decompose()

    def _poll_loop_output(self):
        self._drain_output_queue(self._loop_output_queue, self.loop_console,
                                  self.loop_run_btn, self.loop_stop_btn, self.loop_status_label,
                                  on_exit=self._on_loop_finished)
        self.after(150, self._poll_loop_output)

    def _on_run_constellation(self):
        if self._const_runner is not None and self._const_runner.is_running():
            return
        base_exponent = self._const_base_exponent_var.get().strip()
        if base_exponent and not base_exponent.isdigit():
            messagebox.showerror(
                self.T("gen.dialog_title"), self.T("gen.error_base_exponent_int"))
            return

        self._generation_settings["constellation"] = {"base_exponent": base_exponent}
        save_generation_settings(self._get_portal_folder(), self._generation_settings)

        argv = build_constellation_finder_argv(base_exponent if base_exponent else None)
        log_path, exit_path, _run_id = generation_log_paths(self._get_portal_folder(), "constellation")
        cmd = build_wsl_logged_command(argv, log_path, exit_path, self._get_portal_folder())

        self.const_console.append(self._new_run_separator())
        self._const_output_queue = queue.Queue()
        self._const_runner = WslLoggedRunner(
            cmd, log_path, exit_path, self._const_output_queue,
            kill_pattern="constellation_finder_v1.py")
        self._const_runner.start()
        self.const_run_btn.configure(state="disabled")
        self.const_stop_btn.configure(state="normal")
        self.const_status_label.set(self.T("common.running"))
        self._show_const_terminal()

    def _on_stop_constellation(self):
        if self._const_runner is not None:
            self._const_runner.stop()
            self.const_status_label.set(self.T("common.stopping"))

    def _on_constellation_finished(self):
        """_drain_output_queue's on_exit callback for the constellation queue --
        mirrors _on_loop_finished's reload_primes_tree() call, but for the
        Constellations tab: re-runs reload_constellations_tree() so newly found hits
        show up there the moment a run finishes, without a manual Refresh click.
        constellation_finder_v1.py has no dual-purpose button label to reset (unlike
        the Quick-gen 'Generate'/'Stop' one _on_loop_finished handles), so this is
        otherwise a much shorter version of that method."""
        self.reload_constellations_tree()

        # Mirrors _on_loop_finished()'s pending-search re-run, for a search-triggered
        # "run constellation_finder for this floor" instead (see
        # _offer_generate_missing_constellation()) -- see that method's own docstring
        # for why this is a SEPARATE slot from the prime-window one.
        if self._pending_search_after_const_gen is not None:
            pending = self._pending_search_after_const_gen
            self._pending_search_after_const_gen = None
            self._start_search_job(pending["kind"], pending["base_exponent"], pending["number"])

    def _poll_constellation_output(self):
        self._drain_output_queue(self._const_output_queue, self.const_console,
                                  self.const_run_btn, self.const_stop_btn,
                                  self.const_status_label,
                                  on_exit=self._on_constellation_finished)
        self.after(150, self._poll_constellation_output)

    def _on_ktuple_k_changed(self, _event=None, restore_variant_id=None):
        """Repopulates the variant combo for whichever k is now selected -- same
        two-combo cascade as the Kalkulator konstelacji tab's own
        _on_const_calc_k_changed(). `restore_variant_id`, given only on initial
        build (see _build_generation_tab()'s own call), re-selects a persisted
        variant instead of always defaulting to index 0, so the form reopens showing
        whatever pattern was last used here."""
        k_str = self.ktuple_k_combo.get()
        if not k_str:
            return
        self._ktuple_variants = pattern_catalog_v1.patterns_for_k(int(k_str))
        self.ktuple_variant_combo.configure(
            values=[self.T("const_calc.variant_label", id=w["id"])
                    for w in self._ktuple_variants])
        if self._ktuple_variants:
            idx = 0
            if restore_variant_id not in (None, ""):
                for i, w in enumerate(self._ktuple_variants):
                    if str(w["id"]) == str(restore_variant_id):
                        idx = i
                        break
            self.ktuple_variant_combo.current(idx)
        else:
            self.ktuple_variant_combo.set("")
        self._on_ktuple_variant_changed()

    def _on_ktuple_variant_changed(self, _event=None):
        idx = self.ktuple_variant_combo.current()
        if idx < 0 or idx >= len(self._ktuple_variants):
            self.ktuple_pattern_info_var.set("")
            return
        w = self._ktuple_variants[idx]
        offsets_str = ", ".join(str(o) for o in w["offsets"])
        if w["record_digits"] is not None:
            self.ktuple_pattern_info_var.set(self.T(
                "const_calc.pattern_info", offsets=offsets_str,
                record_digits=w["record_digits"], discoverer=w["discoverer"],
                date=w["date"]))
        else:
            self.ktuple_pattern_info_var.set(
                self.T("const_calc.pattern_info_untracked", offsets=offsets_str))

    def _on_ktuple_n_locations_auto_clicked(self):
        """Auto button for the shared "n_locations" field -- primarily meant for
        strategy=digit_sweep (see recommended_digit_sweep_n_locations()'s own
        docstring for why it exists: the field is shared across all five
        strategies, so a single static default couldn't fit digit_sweep's
        per-branch-depth needs without either being far too small for it or far
        too large for the other four). Reads base_exponent/window_m straight from
        their own fields (both already on screen, no WSL round-trip needed --
        unlike _on_workers_auto_clicked's CPU probe, this is pure arithmetic), and
        fills n_locations with the recommendation. Like every other Auto button in
        this app, only ever SUGGESTS a value -- the field stays freely editable
        afterward."""
        base_exponent_str = self._ktuple_vars["base_exponent"].get().strip()
        window_m_str = self._ktuple_vars["window_m"].get().strip()
        if not base_exponent_str.isdigit() or not window_m_str.isdigit():
            messagebox.showerror(self.T("gen.dialog_title"), self.T("gen.error_base_exponent_int"))
            return
        base_exponent = int(base_exponent_str)
        window_m = int(window_m_str)
        recommended = recommended_digit_sweep_n_locations(base_exponent, window_m)
        self._ktuple_vars["n_locations"].set(str(recommended))
        numbers_total = recommended * window_m
        messagebox.showinfo(self.T("quick.dialog_title"), self.T(
            "gen.ktuple_auto_n_locations_result",
            recommended=f"{recommended:,}", numbers_total=f"{numbers_total:,}"))

    def _on_toggle_ktuple_advanced(self):
        """Same show/hide-together idiom as _on_toggle_loop_advanced() -- see that
        method's own docstring."""
        if self._ktuple_advanced_visible:
            self._ktuple_advanced_content.pack_forget()
            self._ktuple_advanced_visible = False
            self.ktuple_advanced_toggle_btn.configure(text=self.T("gen.advanced_show"))
        else:
            self._ktuple_advanced_content.pack(
                fill="x", padx=8, pady=(0, 4), before=self.ktuple_console.toggle_row)
            self._ktuple_advanced_visible = True
            self.ktuple_advanced_toggle_btn.configure(text=self.T("gen.advanced_hide"))
            self._refresh_generation_pane_minsize()

    def _show_ktuple_terminal(self):
        self.ktuple_console.show()
        self._refresh_generation_pane_minsize()

    def _launch_ktuple(self, auto):
        """Shared by both the Run button (auto=False -- one batch, checkpointed,
        per click) and the Auto button (auto=True -- ktuple_sieve_v1.py itself
        keeps looping batch after batch inside this one WSL process until a
        confirmed hit, Stop, or the floor is exhausted -- see
        ktuple_sieve_v1.run_ktuple_job()'s own docstring). Everything below the
        auto-specific argv flag is identical between the two."""
        if self._ktuple_runner is not None and self._ktuple_runner.is_running():
            return
        base_exponent = self._ktuple_vars["base_exponent"].get().strip()
        if not base_exponent.isdigit():
            messagebox.showerror(self.T("gen.dialog_title"), self.T("gen.error_base_exponent_int"))
            return

        k_idx = self.ktuple_k_combo.current()
        variant_idx = self.ktuple_variant_combo.current()
        if k_idx < 0 or variant_idx < 0 or variant_idx >= len(self._ktuple_variants):
            messagebox.showerror(self.T("gen.dialog_title"), self.T("gen.ktuple_error_no_pattern"))
            return
        pattern = self._ktuple_variants[variant_idx]

        n_locations = self._ktuple_vars["n_locations"].get().strip()
        window_m = self._ktuple_vars["window_m"].get().strip()
        step = self._ktuple_vars["step"].get().strip()
        fragment_width = self._ktuple_vars["fragment_width"].get().strip()
        fragment_start = self._ktuple_vars["fragment_start"].get().strip() or "0"
        deep_prime_limit = self._ktuple_vars["deep_prime_limit"].get().strip() or "2000"
        mr_rounds = self._ktuple_vars["mr_rounds"].get().strip() or "40"
        manual_offsets_str = self._ktuple_vars["manual_offsets"].get().strip()
        pass_counter = self._ktuple_vars["pass_counter"].get().strip() or "0"

        numeric_ok = (
            n_locations.isdigit() and window_m.isdigit() and fragment_start.isdigit()
            and deep_prime_limit.isdigit() and mr_rounds.isdigit() and pass_counter.isdigit()
            and (not fragment_width or fragment_width.isdigit())
            and (not step or step.isdigit()))
        if not numeric_ok:
            messagebox.showerror(self.T("gen.dialog_title"), self.T("gen.ktuple_error_numeric_fields"))
            return

        strategy_idx = self.ktuple_strategy_combo.current()
        strategy = (_KTUPLE_STRATEGY_KEYS[strategy_idx]
                    if 0 <= strategy_idx < len(_KTUPLE_STRATEGY_KEYS) else "concentrated")

        manual_offsets = None
        if strategy == "manual_list":
            try:
                manual_offsets = [int(tok) for tok in manual_offsets_str.replace(",", " ").split()]
            except ValueError:
                manual_offsets = []
            if not manual_offsets:
                messagebox.showerror(self.T("gen.dialog_title"), self.T("gen.ktuple_error_manual_offsets"))
                return
        elif strategy == "manual_step" and not step:
            messagebox.showerror(self.T("gen.dialog_title"), self.T("gen.ktuple_error_manual_step_needs_step"))
            return

        reset_checkpoint = self._ktuple_reset_checkpoint_var.get()

        self._generation_settings["ktuple"] = {
            "base_exponent": base_exponent, "k": str(pattern["k"]),
            "variant_id": str(pattern["id"]), "n_locations": n_locations,
            "window_m": window_m, "strategy": strategy, "step": step,
            "fragment_width": fragment_width, "fragment_start": fragment_start,
            "manual_offsets": manual_offsets_str, "deep_prime_limit": deep_prime_limit,
            "mr_rounds": mr_rounds, "reset_checkpoint": reset_checkpoint,
            "pass_counter": pass_counter,
        }
        save_generation_settings(self._get_portal_folder(), self._generation_settings)

        argv = build_ktuple_sieve_argv(
            base_exponent, pattern["k"], pattern["id"],
            n_locations=int(n_locations), window_m=int(window_m), strategy=strategy,
            step=int(step) if step else None,
            fragment_width=int(fragment_width) if fragment_width else None,
            fragment_start=int(fragment_start) if strategy != "manual_list" else None,
            manual_offsets=manual_offsets, deep_prime_limit=int(deep_prime_limit),
            mr_rounds=int(mr_rounds), auto=auto, reset_checkpoint=reset_checkpoint,
            pass_counter=int(pass_counter) if strategy == "digit_sweep" else None)
        log_path, exit_path, _run_id = generation_log_paths(self._get_portal_folder(), "ktuple")
        cmd = build_wsl_logged_command(argv, log_path, exit_path, self._get_portal_folder())

        self.ktuple_console.append(self._new_run_separator())
        self._ktuple_output_queue = queue.Queue()
        self._ktuple_runner = WslLoggedRunner(
            cmd, log_path, exit_path, self._ktuple_output_queue,
            kill_pattern="ktuple_sieve_v1.py")
        self._ktuple_runner.start()
        self.ktuple_run_btn.configure(state="disabled")
        self.ktuple_auto_btn.configure(state="disabled")
        self.ktuple_stop_btn.configure(state="normal")
        self.ktuple_status_label.set(self.T("common.running"))
        self._show_ktuple_terminal()

    def _on_stop_ktuple(self):
        if self._ktuple_runner is not None:
            self._ktuple_runner.stop()
            self.ktuple_status_label.set(self.T("common.stopping"))

    def _on_ktuple_finished(self):
        """Mirrors _on_constellation_finished() -- confirmed hits land in the same
        per-(k,variant) hit files Section B writes to, so the Constellations tab
        needs the same post-run refresh. Also re-enables ktuple_auto_btn --
        _drain_output_queue() only knows about the plain run_btn/stop_btn pair
        shared with every other section, not this section's own extra Auto
        button, so that one is reset here instead."""
        self.reload_constellations_tree()
        self.ktuple_auto_btn.configure(state="normal")

    def _poll_ktuple_output(self):
        self._drain_output_queue(self._ktuple_output_queue, self.ktuple_console,
                                  self.ktuple_run_btn, self.ktuple_stop_btn,
                                  self.ktuple_status_label,
                                  on_exit=self._on_ktuple_finished)
        self.after(150, self._poll_ktuple_output)

    def _drain_output_queue(self, q, console, run_btn, stop_btn, status_var, on_exit=None):
        """Shared by both Generation sections: drains whatever output
        a WslLoggedRunner has pushed onto `q` since the last poll into
        `console` (a GenerationConsole -- autoscrolling to the bottom is handled by
        its own append()), and on that runner's
        ("__exit__", returncode) sentinel, re-enables Run / disables Stop and
        reports the exit code. Same 150ms self.after() polling cadence as the floor-
        totals worker (_poll_totals_results) -- this method itself does NOT
        reschedule; each caller (_poll_loop_output / _poll_constellation_output) owns
        its own self.after() chain so the two sections' polling stays independent.

        An optional on_exit() callback fires right after the exit-sentinel
        handling above -- currently only _poll_loop_output uses it (to reset the
        Quick-gen 'Generate' button's temporary 'Stop' label, see
        _on_loop_finished); _poll_constellation_output has no equivalent dual-purpose
        button so it leaves this at its default of None.

        Every plain-text chunk is ALSO fed to _update_shared_progress_from_generation_
        chunk() -- see that method's own docstring -- so the shared bottom bar reflects
        live generation/constellation-search progress, on top of the raw text staying
        visible in `console` exactly as before."""
        try:
            while True:
                item = q.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__exit__":
                    returncode = item[1]
                    run_btn.configure(state="normal")
                    stop_btn.configure(state="disabled")
                    if returncode is None:
                        status_var.set(self.T("common.error_starting_process"))
                    elif returncode == 0:
                        status_var.set(self.T("common.finished_ok"))
                    else:
                        status_var.set(self.T("common.finished_code", code=returncode))
                    if on_exit is not None:
                        on_exit()
                    continue
                console.append(item)
                self._update_shared_progress_from_generation_chunk(item)
        except queue.Empty:
            pass

    def _update_shared_progress_from_generation_chunk(self, chunk):
        """Reflects a generation run's live console output onto the shared bottom status
        bar -- the SAME self.status/self.totals_progress the floor-totals scan and the
        Primes/Constellations search box already use -- covering the WHOLE pipeline as
        one sequence of steps, not just the batch-sieve phase. Scans `chunk` (a raw text
        blob straight from WslLoggedRunner's log-tailing -- may hold zero, one, or
        several lines, and may occasionally split one line across two chunks; a missed
        match here just means the bar catches up on the next chunk a moment later,
        harmless for a live display) for whichever of the five line shapes documented on
        _GEN_PREP_DONE_RE/_GEN_SIEVE_PROGRESS_RE/_GEN_SIEVE_DONE_RE/_GEN_CONST_PROGRESS_RE/
        _GEN_CONST_DONE_RE's own module-level comment is present, checked in the order a
        real run actually prints them (prep -> batches -> done; the constellation path has
        no separate prep step of its own, just per-file progress -> done).

        Sieve-pipeline step model (self._gen_step_total, reset to None between runs):
        step 0 is the pi(L_final) prep phase (which can itself run into minutes at
        extreme depth -- see prime_sieve_v4_1.py's own SKIPPED-mode comment -- and used
        to leave the bar sitting completely empty for all of it), steps 1..n_batches are
        each individual sieve batch. The real n_batches isn't known until the FIRST
        batch-progress line arrives, so between the prep line and that first batch line
        the bar shows a provisional 1-of-2 (half full) rather than 0-of-unknown -- it
        gets corrected to the real proportion the moment the first batch line defines the
        actual total, which in practice is only a few seconds later. The run-finished
        line ("[*] TOTAL PRIMES FOUND...") snaps the bar to fully complete regardless of
        exactly how many steps were tracked, then clears _gen_step_total so the NEXT
        run starts from the same 'unknown total yet' state rather than inheriting this
        run's batch count.

        No explicit arbitration against search/totals for ownership of the shared bar:
        each of the three writes self.status on its own independent schedule, so
        whichever last had something to say is simply what's showing. In practice
        generation dominates while it's actually running, since these lines repeat every
        couple of seconds -- far more often than search's one-shot "searching..."
        message or the totals scan's own periodic updates -- without needing a priority
        flag to enforce that.

        Multi-iteration Exploration-mode loop (self._gen_loop_run_count/_gen_loop_
        iteration, both None outside a loop run): orchestrator_loop_v2.py launches
        run_count separate orchestrator_v3.py subprocesses back to back, one per
        iteration, and each one prints its OWN independent prep/batch-progress/done
        lines as if it were a lone single-window-range run. Without loop-awareness the
        bar would snap to "done" after iteration 1 of N (see _LOOP_SESSION_START_RE's
        own module-level comment). While _gen_loop_run_count is set, the per-iteration
        step count from the sieve-pipeline model above is treated as one slice of a
        wider run_count-slice bar: overall maximum = run_count * that iteration's own
        step_total, overall value = completed-iterations-worth of steps + the current
        iteration's own progress into its slice. Only _LOOP_SESSION_DONE_RE -- the
        line orchestrator_loop_v2.py itself prints once ALL iterations are over --
        snaps the bar to full and clears _gen_loop_run_count/_gen_loop_iteration back
        to None; the per-iteration "[*] TOTAL PRIMES FOUND..." line just marks that
        iteration's slice as complete and keeps waiting."""
        if _LOOP_SESSION_DONE_RE.search(chunk):
            total = self._gen_step_total or 1
            self.totals_progress.stop()
            self.totals_progress.configure(mode="determinate", maximum=total, value=total)
            self.status.set(self.T("gen.status_progress_done"))
            self._gen_step_total = None
            self._gen_loop_run_count = None
            self._gen_loop_iteration = None
            return

        loop_start_match = _LOOP_SESSION_START_RE.search(chunk)
        if loop_start_match:
            self._gen_loop_run_count = int(loop_start_match.group(1))
            self._gen_loop_iteration = 1

        iter_start_matches = _LOOP_ITERATION_START_RE.findall(chunk)
        if iter_start_matches:
            iteration_str, _run_count_str = iter_start_matches[-1]
            self._gen_loop_iteration = int(iteration_str)
            self._gen_step_total = None  # fresh subprocess -- real total not known
                                          # until its own first batch-progress line

        if _GEN_SIEVE_DONE_RE.search(chunk) or _GEN_CONST_DONE_RE.search(chunk):
            if self._gen_loop_run_count is not None:
                # One iteration of a multi-iteration run just finished -- NOT the whole
                # session. Only _LOOP_SESSION_DONE_RE (checked above) snaps the bar to
                # full/clears loop state; here just mark this iteration's own slice as
                # complete and keep the loop state alive for the next iteration.
                run_count = self._gen_loop_run_count
                iteration = self._gen_loop_iteration or 1
                step_total = self._gen_step_total or 1
                self.totals_progress.stop()
                self.totals_progress.configure(
                    mode="determinate", maximum=run_count * step_total,
                    value=min(iteration, run_count) * step_total)
                self.status.set(self.T("gen.status_progress_loop_iteration_done",
                                   iteration=iteration, run_count=run_count))
                return
            total = self._gen_step_total or 1
            self.totals_progress.stop()
            self.totals_progress.configure(mode="determinate", maximum=total, value=total)
            self.status.set(self.T("gen.status_progress_done"))
            self._gen_step_total = None
            return

        sieve_matches = _GEN_SIEVE_PROGRESS_RE.findall(chunk)
        if sieve_matches:
            percent_str, done_str, total_str = sieve_matches[-1]
            done, n_batches = int(done_str), int(total_str)
            self._gen_step_total = n_batches + 1  # +1 for the prep step already done
            self.totals_progress.stop()
            if self._gen_loop_run_count is not None:
                run_count = self._gen_loop_run_count
                iteration = self._gen_loop_iteration or 1
                self.totals_progress.configure(
                    mode="determinate", maximum=run_count * self._gen_step_total,
                    value=(iteration - 1) * self._gen_step_total + (done + 1))
                self.status.set(self.T("gen.status_progress_loop_sieve", iteration=iteration,
                                   run_count=run_count, percent=percent_str,
                                   done=done, total=n_batches))
            else:
                self.totals_progress.configure(mode="determinate",
                                                maximum=self._gen_step_total, value=done + 1)
                self.status.set(self.T("gen.status_progress_sieve", percent=percent_str,
                                   done=done, total=n_batches))
            return

        const_matches = _GEN_CONST_PROGRESS_RE.findall(chunk)
        if const_matches:
            done_str, total_str = const_matches[-1]
            done, total = int(done_str), int(total_str)
            self._gen_step_total = total
            self.totals_progress.stop()
            self.totals_progress.configure(mode="determinate", maximum=max(1, total), value=done)
            self.status.set(self.T("gen.status_progress_const", done=done, total=total))
            return

        if _GEN_PREP_DONE_RE.search(chunk):
            self._gen_step_total = None  # real total not known until the first
                                          # batch-progress line -- see docstring above
            self.totals_progress.stop()
            if self._gen_loop_run_count is not None:
                run_count = self._gen_loop_run_count
                iteration = self._gen_loop_iteration or 1
                self.totals_progress.configure(
                    mode="determinate", maximum=run_count * 2, value=(iteration - 1) * 2 + 1)
                self.status.set(self.T("gen.status_progress_loop_prep", iteration=iteration,
                                   run_count=run_count))
            else:
                self.totals_progress.configure(mode="determinate", maximum=2, value=1)
                self.status.set(self.T("gen.status_progress_prep"))

    # --- Tab 5: Settings -----------------------------------------------------

