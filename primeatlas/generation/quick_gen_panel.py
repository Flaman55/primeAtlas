"""
quick_gen_panel.py -- QuickGenPanel, the Quick generation panel of the Generation tab: its
shared Variables, the per-mode frames (Floor, Range, Exploration, Hybrid, primesieve,
cudasieve), the width/iteration validators and caps, and the Auto buttons that fill a
field from the RAM/CPU probe or the storage contents.

A GenerationTab mixin: it uses the widgets, Variables and runner state that GenerationTab
and its other mixins set up, so it is never instantiated on its own.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from ..core.info_tip import InfoTip
from ..core.storage import digit_count_floor, LOW_FLOOR_CUTOFF
from ..core.ui_state import remember
from . import engine_options
from .quick_number import _eval_quick_number
from .window_planning import (QUICK_GEN_MAX_WINDOW_WIDTH, count_existing_windows,
                              find_continuation_target_idx, find_highest_populated_floor,
                              PRIMESIEVE_MAX_WIDTH_MULT, CUDASIEVE_MIN_PRINTABLE_TOP,
                              CUDASIEVE_MAX_WIDTH_MULT, QUICK_FLOOR_MAX, UINT64_FLOOR_MAX)
from .wsl_resources import (estimate_wsl_available_ram_bytes, estimate_wsl_available_cpu_count,
                            recommended_worker_count)


def _floor_spinbox(parent, var, width, to=QUICK_FLOOR_MAX):
    """A Floor field: the arrows and the mouse wheel step the floor through [0, to]; any
    text can still be typed (Quick-gen evaluates expressions such as 10**3)."""
    return ttk.Spinbox(parent, from_=0, to=to, increment=1, textvariable=var, width=width)


# Every Quick-gen input variable ui_state remembers (see _remember_quick_fields).
_REMEMBERED_QUICK_VARS = (
    "quick_mode_var", "quick_floor_var", "quick_floor_width_var", "quick_floor_fill_gaps_var",
    "quick_from_var", "quick_to_var",
    "quick_explore_floor_var", "quick_iterations_var", "quick_explore_width_var",
    "quick_hybrid_floor_var", "quick_hybrid_iterations_var", "quick_hybrid_width_var",
    "quick_hybrid_filter_prime_count_var", "quick_hybrid_from_var", "quick_hybrid_to_var",
    "quick_hybrid_main_cap_var", "quick_hybrid_value_var", "quick_hybrid_target_floor_var",
    "quick_primesieve_floor_var", "quick_primesieve_from_var", "quick_primesieve_width_var",
    "quick_primesieve_native_var", "quick_primesieve_native_mode_var",
    "quick_cudasieve_floor_var", "quick_cudasieve_from_var", "quick_cudasieve_width_var",
    "quick_pseudosquares_floor_var", "quick_pseudosquares_from_var",
    "quick_pseudosquares_width_var", "quick_pseudosquares_mode_var",
    "quick_pseudosquares_threads_var",
)


class QuickGenPanel:
    def _init_quick_generation_state(self):
        """Creates every Quick-gen StringVar/BooleanVar exactly once, shared by every
        panel instance _build_quick_generation_panel() builds (the embedded one plus
        any detached copy, see that method's note below) -- sharing the same Variable
        objects, rather than one set per instance, is what keeps two simultaneously-
        visible panels showing identical values without any manual syncing: typing in
        either copy's Entry widget updates both immediately."""
        self.quick_mode_var = tk.StringVar(value="floor")
        # write_files of every mode's run; the Benchmark checkbox shows it inverted
        # (checked = measure only, nothing written into the storage).
        self._loop_write_files_var = tk.BooleanVar(
            value=bool(self._generation_settings["loop"].get("write_files", True)))
        self._benchmark_checkbuttons = []  # every panel copy's Benchmark checkbox
        self.quick_floor_var = tk.StringVar(value="")
        self.quick_floor_width_var = tk.StringVar(value="1")
        self._quick_width_spinboxes = []  # Floor/Exploration Width, every panel copy
        self.quick_floor_start_var = tk.StringVar(value="")
        self.quick_floor_start_var.trace_add("write", self._on_quick_floor_start_changed)
        # Shared by TWO modes' own continuation paths: Floor mode's own BLANK-
        # starting-point path (a typed starting point already means "start exactly
        # there", see _quick_gen_plan_literal_range's own docstring, unaffected by
        # this toggle either way) and Exploration mode's own Floor field (blank OR
        # typed -- both of Exploration's own starting points can land on a floor
        # with a gap, see _try_fill_quick_gen_gap()'s own docstring, matching Floor
        # mode's own behavior exactly). Default False
        # (continue past the highest existing file) rather than True, so enabling
        # gap-filling is an explicit,
        # conscious choice rather than a surprising default for a person who has
        # never left a gap and doesn't need to think about this at all.
        self.quick_floor_fill_gaps_var = tk.BooleanVar(value=False)
        self.quick_from_var = tk.StringVar(value="")
        self.quick_to_var = tk.StringVar(value="")
        self.quick_explore_floor_var = tk.StringVar(value="")
        self.quick_iterations_var = tk.StringVar(value="1")
        self.quick_explore_width_var = tk.StringVar(value="1")
        # Hybrid intentionally owns its state instead of borrowing Exploration's
        # variables.  Its stage size is a filter-prime prefix (k_adv), not a count of
        # fixed 10M windows, so sharing the Width field would falsely imply the same
        # numerical contract and would make a later mode switch overwrite input.
        self.quick_hybrid_floor_var = tk.StringVar(value="")
        self.quick_hybrid_iterations_var = tk.StringVar(value="1")
        self.quick_hybrid_width_var = tk.StringVar(value="1")
        self.quick_hybrid_filter_prime_count_var = tk.StringVar(value="10000")
        self.quick_hybrid_from_var = tk.StringVar(value="")
        self.quick_hybrid_to_var = tk.StringVar(value="")
        self.quick_hybrid_main_cap_var = tk.StringVar(value="100")
        self.quick_hybrid_range_var = tk.StringVar(value=self.T("quick.hybrid_range_calculating"))
        # The ordinary intent is to extend a selected floor.  A concrete n is
        # available for research, but must never silently turn a typed floor
        # into the unrelated global window containing zero.
        self.quick_hybrid_target_var = tk.StringVar(value=self.T("quick.hybrid_target_continue_floor"))
        self.quick_hybrid_value_var = tk.StringVar(value="")
        self.quick_hybrid_target_floor_var = tk.StringVar(value="")
        self._hybrid_target_groups = []
        for var in (self.quick_hybrid_main_cap_var, self.quick_hybrid_filter_prime_count_var,
                    self.quick_hybrid_target_var, self.quick_hybrid_value_var,
                    self.quick_hybrid_target_floor_var):
            var.trace_add("write", self._schedule_hybrid_preview)
        self.quick_hybrid_target_var.trace_add("write", self._sync_hybrid_target_fields)
        # primesieve mode: its OWN Floor/From/Width variables rather than reusing
        # quick_from_var/quick_to_var -- see _build_quick_mode_primesieve's docstring:
        # this mode's Auto button fills From with the floor's storage continuation
        # point (not a RAM-based width), and it has Width instead of a literal To
        # field, so sharing Range mode's variables would let a value typed in one
        # mode's fields mispopulate the other's on a mode switch.
        self.quick_primesieve_floor_var = tk.StringVar(value="")
        self.quick_primesieve_from_var = tk.StringVar(value="")
        self.quick_primesieve_width_var = tk.StringVar(value="1")
        # Native: run the primesieve program itself ("print" text output or "count" of
        # pi(x)) instead of the wrapper that converts its result into Atlas windows.
        self.quick_primesieve_native_var = tk.BooleanVar(value=False)
        self.quick_primesieve_native_mode_var = tk.StringVar(value="print")
        # cudasieve mode (optional GPU engine):
        # own Floor/From/Width variables, same reasoning as primesieve mode's own three
        # just above (see _build_quick_mode_primesieve's docstring) -- kept entirely
        # separate so the two GPU-vs-CPU "fast single-shot" modes never cross-populate
        # each other's fields on a mode switch.
        self.quick_cudasieve_floor_var = tk.StringVar(value="")
        self.quick_cudasieve_from_var = tk.StringVar(value="")
        self.quick_cudasieve_width_var = tk.StringVar(value="1")
        self._init_pseudosquares_state()  # quick_gen_pseudosquares.py
        self.quick_hint_var = tk.StringVar(value="")
        self.quick_status_var = tk.StringVar(value="")
        self._quick_panels = []
        self._remember_quick_fields()

    def _remember_quick_fields(self):
        """Restores and keeps saving every Quick-gen input (ui_state.remember) except the
        Floor mode's starting point: a run consumes it, and a remembered one would aim the
        next run at numbers already generated. The Floor field it fills is restored on its
        own. Called before any panel is built, so the panels show the restored values."""
        for name in _REMEMBERED_QUICK_VARS:
            remember(f"quick.{name[len('quick_'):-len('_var')]}", getattr(self, name))
        remember("quick.hybrid_target", self.quick_hybrid_target_var, choices={
            "n": "n",
            "continue_floor": self.T("quick.hybrid_target_continue_floor"),
            "fill_gap": self.T("quick.hybrid_target_fill_gap"),
            "exact_window": self.T("quick.hybrid_target_exact_window")})

    def _build_quick_generation_panel(self, parent):
        """Higher-level "just tell me the floor / range" panel above the raw
        orchestrator_loop_v2.py parameter form -- those low-level
        fields (window_count_per_run, workers, batches_per_worker...) are too
        low-level for the app/user. This panel lets the person say WHAT they want --
        a floor, or a numeric range in Python-expression-friendly notation (e.g.
        10**5) -- and translates it into the low-level fields below: window width
        capped at QUICK_GEN_MAX_WINDOW_WIDTH (10,000,000), window count derived from
        the target range so the total comes out right, "exploration" mode appending
        further chunks to a floor's existing data.

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
        ttk.Label(parent, text=self.T("quick.intro"), style="Hint.TLabel",
                  wraplength=900, justify="left").pack(
            anchor="w", padx=8, pady=(6, 4))

        mode_row = ttk.Frame(parent)
        mode_row.pack(fill="x", padx=8, pady=(0, 2))
        quick_modes = [
            ("floor", self.T("quick.mode_floor")),
            ("range", self.T("quick.mode_range")),
            ("explore", self.T("quick.mode_explore")),
            ("hybrid", self.T("quick.mode_hybrid")),
            ("primesieve", self.T("quick.mode_primesieve")),
            ("cudasieve", self.T("quick.mode_cudasieve")),
            ("pseudosquares", self.T("quick.mode_pseudosquares")),
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
        self._build_quick_mode_hybrid(fields_container, mode_frames)
        self._build_quick_mode_primesieve(fields_container, mode_frames)
        self._build_quick_mode_cudasieve(fields_container, mode_frames)
        self._build_quick_mode_pseudosquares(fields_container, mode_frames)

        ttk.Label(parent, textvariable=self.quick_hint_var, style="Hint.TLabel",
                  wraplength=900, justify="left").pack(anchor="w", padx=8, pady=(0, 4))

        btn_row = ttk.Frame(parent)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        # Generate is the primary Start/Stop control (the raw
        # Run/Stop pair moved inside the collapsible advanced block, see
        # _build_loop_section()) -- see
        # _on_quick_generate_or_stop_clicked/_on_run_loop/_on_loop_finished for the
        # three places that flip its label between quick.generate_button and
        # common.stop (looping over self._quick_panels so every copy flips together).
        generate_btn = ttk.Button(
            btn_row, text=self.T("quick.generate_button"),
            command=self._on_quick_generate_or_stop_clicked)
        generate_btn.pack(side="left")
        self._build_time_simulation_button(btn_row)
        benchmark_cb = ttk.Checkbutton(btn_row, text=self.T("gen.check_benchmark"),
                                       variable=self._loop_write_files_var,
                                       onvalue=False, offvalue=True)
        benchmark_cb.pack(side="left", padx=(12, 0))
        InfoTip(btn_row, lambda: self.T("gen.info_benchmark")).label.pack(
            side="left", padx=(4, 0))
        self._benchmark_checkbuttons.append(benchmark_cb)
        self._sync_benchmark_lock()
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

        Returns the Floor spinbox so the caller can track it per-panel-instance
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
        floor_entry = _floor_spinbox(frame, self.quick_floor_var, 10)
        floor_entry.pack(side="left", padx=(6, 20))
        ttk.Label(frame, text=self.T("quick.field_width")).pack(side="left")
        width_vcmd = (self.register(self._validate_quick_width_spinbox), "%P")
        width_spinbox = ttk.Spinbox(
            frame, from_=1, to=self._quick_width_cap(), textvariable=self.quick_floor_width_var,
            width=6, validate="key", validatecommand=width_vcmd)
        width_spinbox.pack(side="left", padx=(6, 4))
        self._quick_width_spinboxes.append(width_spinbox)
        ttk.Button(frame, text=self.T("quick.auto_button"),
                   command=lambda: self._on_quick_auto_width_clicked(
                       self.quick_floor_width_var,
                       self._quick_floor_of(self.quick_floor_var))).pack(side="left", padx=(0, 20))
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
        in [1, _quick_width_cap()] -- UI-level input restriction only; this is not where
        the actual 1 unit = 10,000,000 translation happens."""
        if proposed == "":
            return True
        return proposed.isdigit() and 1 <= int(proposed) <= self._quick_width_cap()

    def _selected_engine(self):
        """Engine selected in the pipeline form (the default engine's while the form is
        not built yet): continuation, first-gap, trim and highest-floor planning read the
        store that engine writes into (storage_kinds.engine_target_idxs())."""
        fields = getattr(self, "_engine_fields", None)
        return fields.engine() if fields is not None else engine_options.DEFAULT_ENGINE

    def _quick_width_cap(self):
        """Per-run window ceiling of the engine selected in the pipeline form (the
        default engine's while the form is not built yet)."""
        fields = getattr(self, "_engine_fields", None)
        engine = fields.engine() if fields is not None else engine_options.DEFAULT_ENGINE
        return engine_options.max_windows_per_run(engine)

    def _sync_quick_width_caps(self):
        cap = self._quick_width_cap()
        alive = []
        for spinbox in self._quick_width_spinboxes:
            try:
                spinbox.configure(to=cap)
            except tk.TclError:  # a closed detached panel's copy
                continue
            alive.append(spinbox)
        self._quick_width_spinboxes = alive

    @staticmethod
    def _quick_floor_of(var, is_number=False):
        """Floor typed in a Quick-gen field (or the floor of a number typed there when
        is_number), None when blank or unparseable."""
        value = _eval_quick_number(var.get())
        if value is None or value < (1 if is_number else 0):
            return None
        return len(str(value)) - 1 if is_number else value

    def _validate_primesieve_width_spinbox(self, proposed):
        """validatecommand for primesieve mode's OWN Width spinbox -- same shape as
        _validate_quick_width_spinbox, but bounded to PRIMESIEVE_MAX_WIDTH_MULT instead
        of 1000 (see that constant's own docstring for why this mode's Width field has
        no RAM-driven reason to stay small)."""
        if proposed == "":
            return True
        return proposed.isdigit() and 1 <= int(proposed) <= PRIMESIEVE_MAX_WIDTH_MULT

    def _validate_cudasieve_width_spinbox(self, proposed):
        """validatecommand for cudasieve mode's OWN Width spinbox -- same shape as
        _validate_primesieve_width_spinbox, bounded to CUDASIEVE_MAX_WIDTH_MULT (same
        uint64_t domain as libprimesieve's own PRIMESIEVE_MAX_STOP -- see that constant's
        own docstring in window_planning.py)."""
        if proposed == "":
            return True
        return proposed.isdigit() and 1 <= int(proposed) <= CUDASIEVE_MAX_WIDTH_MULT

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
                   command=lambda: self._on_quick_auto_width_clicked(
                       None, self._quick_floor_of(self.quick_from_var, is_number=True))).pack(
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
        user-controllable here as it is there.

        Second row: the SAME "fill gaps first" checkbox/variable Floor mode's own
        blank-starting-point path uses (quick_floor_fill_gaps_var, matching Floor
        mode's behavior exactly). Relevant to BOTH of this mode's own starting points --
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
        _floor_spinbox(frame, self.quick_explore_floor_var, 10).pack(
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
        width_spinbox = ttk.Spinbox(
            frame, from_=1, to=self._quick_width_cap(), textvariable=self.quick_explore_width_var,
            width=6, validate="key", validatecommand=width_vcmd)
        width_spinbox.pack(side="left", padx=(6, 4))
        self._quick_width_spinboxes.append(width_spinbox)
        ttk.Button(frame, text=self.T("quick.auto_button"),
                   command=lambda: self._on_quick_auto_width_clicked(
                       self.quick_explore_width_var,
                       self._quick_floor_of(self.quick_explore_floor_var))).pack(side="left")
        gap_row = ttk.Frame(outer)
        gap_row.grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Checkbutton(gap_row, text=self.T("quick.field_fill_gaps_first"),
                         variable=self.quick_floor_fill_gaps_var).pack(side="left")
        mode_frames["explore"] = outer

    def _build_quick_mode_hybrid(self, container, mode_frames):
        """Build the visible contract for the hybrid-extension engine.

        The continuation choice intentionally mirrors Exploration: blank Floor means
        the deepest populated floor, while the Auto button makes that choice visible.
        Unlike Exploration, a hybrid stage has no fixed-width field.  Its reach comes
        from the explicit filter-prime count ``k_adv`` and must be computed by the
        hybrid planner after it has validated the current archive boundary.

        No "fill gaps first" checkbox: hybrid correctness requires a contiguous
        trusted MAIN base, so the hybrid planner rejects a gapped base rather than
        this panel defining a different continuation policy.
        """
        wrapper = ttk.Frame(container)
        wrapper.grid(row=0, column=0, sticky="w")
        frame = ttk.Frame(wrapper)
        frame.pack(anchor="w")
        ttk.Label(frame, text=self.T("quick.hybrid_field_target")).pack(side="left")
        ttk.Combobox(frame, state="readonly", width=15, textvariable=self.quick_hybrid_target_var,
                     values=("n", self.T("quick.hybrid_target_continue_floor"),
                             self.T("quick.hybrid_target_fill_gap"),
                             self.T("quick.hybrid_target_exact_window"))).pack(side="left", padx=(6, 12))
        value_group = ttk.Frame(frame)
        ttk.Label(value_group, text=self.T("quick.hybrid_field_n_or_index")).pack(side="left")
        ttk.Entry(value_group, textvariable=self.quick_hybrid_value_var, width=20).pack(side="left", padx=(6, 12))
        floor_group = ttk.Frame(frame)
        ttk.Label(floor_group, text=self.T("quick.field_floor")).pack(side="left")
        _floor_spinbox(floor_group, self.quick_hybrid_target_floor_var, 7).pack(side="left", padx=(6, 12))
        ttk.Label(frame, text="MAIN <=").pack(side="left")
        ttk.Entry(frame, textvariable=self.quick_hybrid_main_cap_var, width=8).pack(side="left", padx=(6, 12))
        ttk.Label(frame, text=self.T("quick.field_filter_prime_count")).pack(side="left")
        filter_vcmd = (self.register(self._validate_hybrid_filter_prime_count_spinbox), "%P")
        ttk.Spinbox(frame, from_=1, to=1_000_000,
                    textvariable=self.quick_hybrid_filter_prime_count_var,
                    width=9, validate="key", validatecommand=filter_vcmd).pack(
            side="left", padx=(6, 0))
        ttk.Label(wrapper, textvariable=self.quick_hybrid_range_var, wraplength=950).pack(fill="x")
        self._schedule_hybrid_preview()
        self._hybrid_target_groups.append((value_group, floor_group))
        self._sync_hybrid_target_fields()
        mode_frames["hybrid"] = wrapper

    def _sync_hybrid_target_fields(self, *_args):
        """Show only inputs meaningful for the selected one-window intent."""
        target = self.quick_hybrid_target_var.get()
        show_value = target in ("n", self.T("quick.hybrid_target_exact_window"))
        show_floor = target in (self.T("quick.hybrid_target_continue_floor"),
                                 self.T("quick.hybrid_target_fill_gap"),
                                 self.T("quick.hybrid_target_exact_window"))
        for value_group, floor_group in self._hybrid_target_groups:
            if show_value:
                value_group.pack(side="left")
            else:
                value_group.pack_forget()
            if show_floor:
                floor_group.pack(side="left")
            else:
                floor_group.pack_forget()

    def _build_quick_mode_primesieve(self, container, mode_frames):
        """Floor + From + Width, not a From/To pair.
        From is a literal absolute starting point (like Floor mode's own
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
        _floor_spinbox(row1, self.quick_primesieve_floor_var, 10, to=UINT64_FLOOR_MAX).pack(
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
        row2 = ttk.Frame(frame)
        row2.pack(anchor="w", pady=(4, 0))
        ttk.Checkbutton(row2, text=self.T("quick.field_primesieve_native"),
                        variable=self.quick_primesieve_native_var).pack(side="left")
        InfoTip(row2, lambda: self.T("quick.info_primesieve_native"
                                     if self.quick_primesieve_native_var.get()
                                     else "quick.info_primesieve_wrapper")).label.pack(
            side="left", padx=(4, 12))
        modes = {"print": self.T("quick.primesieve_mode_print"),
                 "count": self.T("quick.primesieve_mode_count")}
        shown = tk.StringVar(value=modes.get(self.quick_primesieve_native_mode_var.get(),
                                             modes["print"]))
        combo = ttk.Combobox(row2, textvariable=shown, values=list(modes.values()),
                             state="disabled", width=36)
        combo.pack(side="left")
        # One combo per built panel (the embedded one and a detached copy).
        self.quick_primesieve_native_mode_combo = combo
        self._primesieve_native_combos = getattr(self, "_primesieve_native_combos", []) + [combo]
        shown.trace_add("write", lambda *_: self.quick_primesieve_native_mode_var.set(
            next(k for k, v in modes.items() if v == shown.get())))
        for var in (self.quick_primesieve_native_var, self.quick_mode_var):
            var.trace_add("write", lambda *_: self._sync_primesieve_native_controls())
        ttk.Label(frame, text=self.T("quick.attribution_primesieve"), style="Hint.TLabel",
                  font=("TkDefaultFont", 8), wraplength=860, justify="left").pack(
            anchor="w", pady=(4, 0))
        mode_frames["primesieve"] = frame
        self._sync_primesieve_native_controls()

    def _sync_primesieve_native_controls(self):
        """print/count usable only with Native on; the Benchmark lock follows."""
        native_var = getattr(self, "quick_primesieve_native_var", None)
        if native_var is None:
            return
        native = native_var.get()
        for combo in getattr(self, "_primesieve_native_combos", ()):
            if combo.winfo_exists():
                combo.configure(state="readonly" if native else "disabled")
        self._sync_benchmark_lock()

    def _sync_benchmark_lock(self):
        """While a native program's mode is selected (native primesieve, Pseudosquares; count
        and print) Benchmark is disabled and shows checked: a native run measures the program
        in its own format, so it is always a benchmark. The checkbox then shows a fixed
        Variable instead of the shared write_files one, so the user's setting for the Atlas
        modes stays as it was and shows again in them."""
        mode = self.quick_mode_var.get()
        native_var = getattr(self, "quick_primesieve_native_var", None)
        locked = (mode == "pseudosquares"
                  or mode == "primesieve" and native_var is not None and native_var.get())
        if not hasattr(self, "_benchmark_shown_checked_var"):
            # onvalue=False: the box is checked while this Variable is False.
            self._benchmark_shown_checked_var = tk.BooleanVar(value=False)
        variable = self._benchmark_shown_checked_var if locked else self._loop_write_files_var
        for benchmark_cb in getattr(self, "_benchmark_checkbuttons", ()):
            if benchmark_cb.winfo_exists():
                benchmark_cb.configure(variable=variable,
                                       state="disabled" if locked else "normal")

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
            self._get_portal_folder(), floor_value, QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine())
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

    def _build_quick_mode_cudasieve(self, container, mode_frames):
        """GPU counterpart to _build_quick_mode_primesieve -- IDENTICAL Floor + From +
        Width layout and reasoning (see that method's own docstring for the full
        rationale), just launching prime_sieve_cudasieve.py instead of
        prime_sieve_primesieve.py. Requires the third-party CUDASieve CLI to already be
        built via Settings > Updates -- if it isn't, this mode still shows up (no
        WSL round-trip is paid just to build the Quick-gen panel), but the run itself
        fails with prime_sieve_cudasieve.py's own clear "not found, install it first"
        error rather than a mysterious hang.

        The attribution label is ALWAYS visible while this mode is selected, same
        reasoning as primesieve mode's own -- this calls a separate, GPLv3-licensed,
        third-party GPU executable as its own OS process, never linked into this
        project (see prime_sieve_cudasieve.py's module header, "PROCESS BOUNDARY, NOT
        LINKING")."""
        frame = ttk.Frame(container)
        frame.grid(row=0, column=0, sticky="w")
        row1 = ttk.Frame(frame)
        row1.pack(anchor="w")
        ttk.Label(row1, text=self.T("quick.field_floor")).pack(side="left")
        _floor_spinbox(row1, self.quick_cudasieve_floor_var, 10, to=UINT64_FLOOR_MAX).pack(
            side="left", padx=(6, 20))
        ttk.Label(row1, text=self.T("quick.field_from")).pack(side="left")
        ttk.Entry(row1, textvariable=self.quick_cudasieve_from_var, width=24).pack(
            side="left", padx=(6, 4))
        ttk.Button(row1, text=self.T("quick.auto_button"),
                   command=self._on_cudasieve_auto_from_clicked).pack(
            side="left", padx=(0, 20))
        ttk.Label(row1, text=self.T("quick.field_width")).pack(side="left")
        width_vcmd = (self.register(self._validate_cudasieve_width_spinbox), "%P")
        ttk.Spinbox(row1, from_=1, to=CUDASIEVE_MAX_WIDTH_MULT,
                    textvariable=self.quick_cudasieve_width_var,
                    width=14, validate="key", validatecommand=width_vcmd).pack(
            side="left", padx=(6, 0))
        ttk.Label(frame, text=self.T("quick.attribution_cudasieve"), style="Hint.TLabel",
                  font=("TkDefaultFont", 8), wraplength=860, justify="left").pack(
            anchor="w", pady=(4, 0))
        mode_frames["cudasieve"] = frame

    def _on_cudasieve_auto_from_clicked(self):
        """cudasieve mode's OWN Auto button -- same continuation-lookup logic as
        _on_primesieve_auto_from_clicked (this just reads whatever is already on disk,
        which doesn't care which engine wrote it), PLUS one addition: CUDASieve's own
        CLI documents that printing individual primes is ignored below 2**40
        (CUDASIEVE_MIN_PRINTABLE_TOP) -- a continuation point below that is clamped UP
        to it instead of silently handing back a value this mode can never actually
        use (prime_sieve_cudasieve.py would just reject it with a RuntimeError anyway;
        better to say so here, before a WSL round-trip)."""
        raw_floor = self.quick_cudasieve_floor_var.get().strip()
        floor_value = _eval_quick_number(raw_floor)
        if not raw_floor or floor_value is None or floor_value < 0:
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_floor_required"))
            return
        existing_count = find_continuation_target_idx(
            self._get_portal_folder(), floor_value, QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine())
        if floor_value < LOW_FLOOR_CUTOFF:
            continuation_point = 10 ** floor_value
        else:
            continuation_point = (
                10 ** floor_value + existing_count * QUICK_GEN_MAX_WINDOW_WIDTH)
        if continuation_point < CUDASIEVE_MIN_PRINTABLE_TOP:
            self.quick_cudasieve_from_var.set(str(CUDASIEVE_MIN_PRINTABLE_TOP))
            messagebox.showinfo(self.T("quick.dialog_title"), self.T(
                "quick.cudasieve_auto_from_clamped", floor=floor_value,
                min_printable=f"{CUDASIEVE_MIN_PRINTABLE_TOP:,}"))
            return
        self.quick_cudasieve_from_var.set(str(continuation_point))
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
        deepest floor" is easy to miss, and an explicit "0" is a legitimate floor
        request, not the same as blank (see this mode's docstring). A labeled button
        matches every other Quick-gen mode's Auto convention.

        Unlike _on_quick_auto_width_clicked (shared, RAM-based, targets a Width field)
        and _on_primesieve_auto_from_clicked (fills a From field given an ALREADY-KNOWN
        Floor), this button determines the Floor itself from scratch by scanning the
        whole database -- there is no floor to read from the UI first."""
        highest = find_highest_populated_floor(self._get_portal_folder(), engine=self._selected_engine())
        if highest is None:
            messagebox.showinfo(
                self.T("quick.dialog_title"), self.T("quick.explore_auto_floor_empty"))
            return
        self.quick_explore_floor_var.set(str(highest))

    def _on_hybrid_auto_floor_clicked(self):
        """Hybrid counterpart of Exploration's explicit highest-floor picker.

        It deliberately does not share the Exploration StringVar: the two modes must
        retain independently typed values when the user compares them side by side.
        """
        highest = find_highest_populated_floor(self._get_portal_folder(), engine=self._selected_engine())
        if highest is None:
            messagebox.showinfo(
                self.T("quick.dialog_title"), self.T("quick.explore_auto_floor_empty"))
            return
        self.quick_hybrid_floor_var.set(str(highest))

    def _validate_quick_iterations_spinbox(self, proposed):
        """validatecommand for the Number of iterations spinbox -- same shape as
        _validate_quick_width_spinbox, bounded to [1, 100] (100 x 10 bln = 1 trillion
        upper bound)."""
        if proposed == "":
            return True
        return proposed.isdigit() and 1 <= int(proposed) <= 100

    def _validate_hybrid_filter_prime_count_spinbox(self, proposed):
        """Accept a visible positive ``k_adv`` value without letting an accidental
        multi-billion entry freeze a future planner before it can present a clear
        validation message.  One million is a UI safety bound, not a mathematical
        limitation of the engine; later phases may make it configurable if benchmarks
        justify that."""
        if proposed == "":
            return True
        return proposed.isdigit() and 1 <= int(proposed) <= 1_000_000

    def _on_quick_auto_width_clicked(self, width_var, base_exponent=None):
        """Auto button handler, shared by every mode's button (see
        _build_quick_mode_floor/_build_quick_mode_explore/_build_quick_mode_range).
        Queries available RAM INSIDE WSL (estimate_wsl_available_ram_bytes -- the
        sieve itself runs there, not in this native Windows process) and turns it
        into a recommended window count (engine_options.recommend -- see that
        function's docstring for exactly what it is and isn't accounting for).

        width_var is the Width spinbox's StringVar to fill in directly (Floor/
        Exploration modes); pass None for Range mode, which has no window-count
        field to fill -- there the recommendation is only reported via the dialog,
        for the person to factor into their own From/To choice.

        The recommendation follows the engine selected in the pipeline form
        (engine_options.recommend()): v5 and v6 scale the window count with base_exponent
        (None = unknown floor, sized like a shallow one) and, when RAM is short, lowers
        the bucket-memory field to what fits."""
        choice, bad_key = self._engine_fields.choice()
        if choice is None:
            messagebox.showerror(self.T("quick.dialog_title"),
                                 self.T("gen.error_field_int", field=bad_key))
            return
        available = estimate_wsl_available_ram_bytes()
        if available is None:
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_ram_probe_failed"))
            return
        budget = engine_options.recommend(available, choice, base_exponent,
                                          QUICK_GEN_MAX_WINDOW_WIDTH)
        recommended = budget.windows
        numbers_total = recommended * QUICK_GEN_MAX_WINDOW_WIDTH
        if width_var is not None:
            width_var.set(str(recommended))
        if choice.engine in engine_options.PT1_ENGINES:
            messagebox.showinfo(self.T("quick.dialog_title"), self.T(
                "quick.auto_result_pt1", recommended=f"{recommended:,}",
                numbers_total=f"{numbers_total:,}"))
            return
        bucket_key = engine_options.bucket_knob(choice.engine)
        if bucket_key is None:
            messagebox.showinfo(self.T("quick.dialog_title"), self.T(
                "quick.auto_ram_result", available_gb=f"{available / 1e9:.1f}",
                budget_pct=choice.knobs[engine_options.RAM_BUDGET_KNOB],
                recommended=f"{recommended:,}", numbers_total=f"{numbers_total:,}"))
            return
        if budget.bucket_mb != choice.knobs[bucket_key]:
            self._engine_fields.set_bucket_mb(budget.bucket_mb, choice.engine)
        messagebox.showinfo(self.T("quick.dialog_title"), self.T(
            "quick.auto_ram_result_v5", available_gb=f"{available / 1e9:.1f}",
            budget_pct=choice.knobs[engine_options.RAM_BUDGET_KNOB],
            engine=engine_options.ENGINE_VERSIONS[choice.engine],
            floor="?" if base_exponent is None else base_exponent,
            recommended=f"{recommended:,}", numbers_total=f"{numbers_total:,}",
            bucket_mb=f"{budget.bucket_mb:,}"))

    def _on_workers_auto_clicked(self):
        """Auto button handler for the "workers" field in the loop pipeline's
        advanced form (see _build_loop_section's own comment above the button)
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
            "hybrid": self.T("quick.hint_hybrid"),
            "primesieve": self.T("quick.hint_primesieve"),
            "cudasieve": self.T("quick.hint_cudasieve"),
            "pseudosquares": self.T("quick.hint_pseudosquares"),
        }
        self.quick_hint_var.set(hints.get(self.quick_mode_var.get(), ""))
        self._rebind_time_simulation()

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
