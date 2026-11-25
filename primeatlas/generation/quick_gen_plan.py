"""
quick_gen_plan.py -- QuickGenPlan, which turns the Quick generation panel's fields into
one launch: _quick_gen_plan_literal_range() maps a literal number range onto floor
windows, _on_quick_generate_clicked() hands the click to the selected mode's planner
(_plan_quick_<mode>), which validates that mode's fields and calls the matching launcher in
quick_gen_runs.py.

A GenerationTab mixin: it uses the widgets, Variables and runner state that GenerationTab
and its other mixins set up, so it is never instantiated on its own.
"""
from tkinter import messagebox

from ..core import number_field, number_format
from ..core.storage import digit_count_floor, LOW_FLOOR_CUTOFF
from . import native_plan
from .quick_number import _eval_quick_number
from .window_planning import (QUICK_GEN_MAX_WINDOW_WIDTH, find_continuation_target_idx,
                              find_highest_populated_floor, missing_span, stored_target_idxs,
                              _round_range_to_window, _floor_window_count, PRIMESIEVE_MAX_STOP,
                              CUDASIEVE_MIN_PRINTABLE_TOP, CUDASIEVE_MAX_STOP)


class QuickGenPlan:
    def _on_quick_generate_primesieve_native(self):
        """primesieve mode with Native on: the program writes nothing into the storage, so the
        run is planned like Pseudosquares' (native_plan.plan, primesieve's stop) and never
        compared with the windows already stored; a blank From starts at the Floor's start
        and stays blank."""
        raw_from = self.quick_primesieve_from_var.get().strip()
        start = _eval_quick_number(raw_from) if raw_from else None
        if raw_from and start is None:
            start = 0  # not a number: refused as below 1
        raw_floor = self.quick_primesieve_floor_var.get().strip()
        floor = _eval_quick_number(raw_floor) if raw_floor else None
        width = _eval_quick_number(self.quick_primesieve_width_var.get())
        result = native_plan.plan(start, floor, width, QUICK_GEN_MAX_WINDOW_WIDTH,
                                  PRIMESIEVE_MAX_STOP)
        if "error" in result:
            key = ("quick.error_primesieve_beyond_ceiling" if result["error"] == "beyond_ceiling"
                   else f"quick.error_native_{result['error']}")
            messagebox.showerror(self.T("quick.dialog_title"),
                                 self.T(key, max_stop=number_format.whole(PRIMESIEVE_MAX_STOP)))
            return
        self.quick_status_var.set(self.T(
            "quick.summary_primesieve_native", mode=self.quick_primesieve_native_mode_var.get(),
            floor=result["floor"], lo=number_format.whole(result['lo']),
            hi=number_format.whole(result['hi']),
            count=result["count"])
            + (self.T("quick.note_primesieve_native_clamped") if result["clamped"] else ""))
        self._apply_primesieve_params_and_run(
            result["floor"], result["target_idx_start"], result["count"])

    def _quick_gen_plan_literal_range(self, start, end, max_window_count=None):
        """Shared by Range mode and Floor mode WITH a starting point set (see
        _plan_quick_floor): given a literal [start, end) target, rounds it
        out to whole QUICK_GEN_MAX_WINDOW_WIDTH windows, CLAMPS it to the starting
        floor's own boundary if it would otherwise cross into the next floor (see the
        "truncated" note below), rejects it if it can't be grid-aligned even after
        rounding/clamping (only affects very low floors), and checks it against
        find_continuation_target_idx -- i.e. against what's ACTUALLY on disk --
        instead of just handing window_count_per_run to orchestrator_loop_v2's own
        continuation-only engine. Without this, a starting point would only pick WHICH
        floor to generate (via digit_count_floor) and generation would continue from
        wherever that floor's storage ends, even when the requested range is already
        covered. Both modes report "already in storage" in that case and otherwise
        generate only the missing gap -- never anything outside/before what was asked
        for, consistent with "always round up, never trim" (see
        _round_range_to_window) -- EXCEPT at the far end, where "never trim" would
        spill numbers from the NEXT floor into this one's folder. The floor
        boundary is the one edge this function always trims TO rather than rounds
        past.

        CLAMPING NOTE: a requested end past the starting floor's own boundary
        (10**(floor_lo+1)) gets silently pulled back to that boundary -- e.g. asking
        for floor 7 with a width that would reach into floor 8's numbers instead
        stops at floor 7's last window, and whatever was asked for beyond that is
        simply dropped, never generated under this call. This mirrors exactly what a
        low floor's own single-window cap already does (see LOW_FLOOR_CUTOFF) --
        every floor, low or high, has a firm upper edge this function will not
        cross. Deliberately GUI-side, not backend: main_batch_scanner itself has no
        opinion on where a floor ends for base_power >= LOW_FLOOR_CUTOFF (it just
        writes whatever combined range it's given under the requested folder), so the
        caller choosing window_count_per_run is what has to stay inside the lines.
        Exploration mode is NOT routed through this function and is NOT capped this
        way on purpose -- marching across floor boundaries and picking up wherever
        the next floor needs filling is that mode's whole point, not a bug to guard
        against (see _plan_quick_explore).

        Returns a dict:
          {"error": (title, message)}                          -- invalid request,
                                                                    show it and stop
          {"already": True, "rounded_start", "rounded_end",
           "stored_count", "range_count", "truncated"}          -- fully covered
                                                                    already
          {"floor", "target_idx_start", "window_count_per_run",
           "stored_count", "range_count", "rounded_start",
           "rounded_end", "truncated"}                          -- what to launch
        "truncated" is True whenever the requested end got clamped back to the
        floor's own boundary -- callers should mention that in their status message
        so a shortened run isn't mistaken for the full request having been honored.

        STORED WINDOWS: only the requested windows [literal target_idx, target_idx_end)
        of the store the selected engine writes into (storage_kinds.engine_target_idxs())
        decide: windows elsewhere on the floor, above or below the range, say nothing
        about its gaps. "stored_count" of the "range_count" requested windows are on
        disk. The launch runs from the first missing window to one past the last missing
        one, never before the literal start (a starting point deep into an otherwise-
        empty floor must not turn into backfilling from index 0, which for a big enough
        gap makes prime_sieve_v4_1.py build a target_idx list too large for memory);
        stored windows between two gaps are rewritten with identical content (one launch
        per request). Callers launch via a target_idx_start-CAPABLE engine (see
        _launch_direct_window_range()), not orchestrator_loop_v2.py's continuation-only
        wrapper, which cannot start past wherever storage currently ends.

        max_window_count: _round_range_to_window() rounds the START down AND the END
        up to the nearest window boundary -- right for Range mode's from/to contract
        ("never fall short of what was literally asked for", see that function's
        docstring), but wrong where Width is an explicit WINDOW-COUNT BUDGET (Floor
        mode's Starting-point path): whenever the typed starting point isn't a
        multiple of QUICK_GEN_MAX_WINDOW_WIDTH (the common case for a search-driven
        starting point), rounding BOTH ends outward adds one window beyond the
        requested count (e.g. 1001 windows for Width=1000). The launched run would
        not match the summary message, and for a RAM-budgeted launch the safer
        failure mode is covering slightly less than asked (at most one window's width
        short at the tail) rather than more. Callers that pass a window-count budget
        here (Floor mode's
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
        stored = stored_target_idxs(self._get_portal_folder(), floor_lo,
                                    literal_target_idx_start, target_idx_end,
                                    QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine())
        span = missing_span(stored, literal_target_idx_start, target_idx_end)
        counts = {"stored_count": len(stored),
                  "range_count": target_idx_end - literal_target_idx_start}
        if span is None:
            return {"already": True, "rounded_start": rounded_start,
                    "rounded_end": rounded_end, "truncated": truncated,
                    "width_capped": width_capped, **counts}
        return {"floor": floor_lo, "target_idx_start": span[0],
                "window_count_per_run": span[1] - span[0],
                "rounded_start": rounded_start, "rounded_end": rounded_end,
                "truncated": truncated, "width_capped": width_capped, **counts}

    def _report_floor_full(self, floor, floor_window_count):
        """Status for a floor whose last window is stored: complete, or with gaps below it
        that only "fill gaps first" reaches (the continuation starts past the last window)."""
        stored = self._engine_window_count(floor)
        key = "quick.status_floor_full" if stored >= floor_window_count else "quick.status_floor_full_gaps"
        self.quick_status_var.set(self.T(key, floor=floor, existing_count=stored,
                                         floor_window_count=floor_window_count))

    _QUICK_MODE_NUMBER_VARS = {
        "floor": ("quick_floor_var", "quick_floor_width_var", "quick_floor_start_var"),
        "range": ("quick_from_var", "quick_to_var"),
        "explore": ("quick_explore_floor_var", "quick_iterations_var",
                    "quick_explore_width_var"),
        "hybrid": ("quick_hybrid_value_var", "quick_hybrid_target_floor_var",
                   "quick_hybrid_main_cap_var", "quick_hybrid_filter_prime_count_var"),
        "pseudosquares": ("quick_pseudosquares_floor_var", "quick_pseudosquares_from_var",
                          "quick_pseudosquares_width_var", "quick_pseudosquares_threads_var"),
        "primesieve": ("quick_primesieve_floor_var", "quick_primesieve_from_var",
                       "quick_primesieve_width_var"),
        "cudasieve": ("quick_cudasieve_floor_var", "quick_cudasieve_from_var",
                      "quick_cudasieve_width_var"),
    }

    def _quick_mode_number_vars(self, mode):
        """The number fields' variables a Quick-gen run of `mode` reads: a red one blocks
        the run (instead of a blank or default value), a red field of another mode does not."""
        return [getattr(self, name) for name in self._QUICK_MODE_NUMBER_VARS.get(mode, ())
                if getattr(self, name, None) is not None]

    def _on_quick_generate_clicked(self):
        """Generate button: refuses while a run is going or while a number field of the
        selected mode is red, then hands the click to that mode's planner."""
        if self._loop_runner is not None and self._loop_runner.is_running():
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_already_running"))
            return
        mode = self.quick_mode_var.get()
        if number_field.refuse_problem(self._quick_mode_number_vars(mode), self.T,
                                       self.T("quick.dialog_title")):
            return
        match mode:
            case "floor":
                self._plan_quick_floor()
            case "range":
                self._plan_quick_range()
            case "explore":
                self._plan_quick_explore()
            case "hybrid":
                self._plan_quick_hybrid()
            case "pseudosquares":
                self._on_quick_generate_pseudosquares()  # quick_gen_pseudosquares.py
            case "primesieve" if self.quick_primesieve_native_var.get():
                self._on_quick_generate_primesieve_native()
            case "primesieve":
                self._plan_quick_primesieve()
            case "cudasieve":
                self._plan_quick_cudasieve()
            case _:
                pass  # a mode the panel does not offer (e.g. a stale saved value) launches nothing

    def _report_already_in_storage(self, rounded_start, rounded_end, existing_count):
        self.quick_status_var.set(self.T(
            "quick.status_already_in_storage",
            rounded_start=number_format.whole(rounded_start),
            rounded_end=number_format.whole(rounded_end),
            existing_count=existing_count))

    def _launch_literal_plan(self, start, end, launch, max_window_count=None, ceiling=None,
                             ceiling_note_key=None):
        """Plans the literal [start, end) target (_quick_gen_plan_literal_range), reports
        it and calls launch(floor, target_idx_start, window_count) for the missing windows.
        `ceiling` is the engine's last reachable number: a plan ending past it gets
        `ceiling_note_key`'s note, the engine clamps the run itself."""
        plan = self._quick_gen_plan_literal_range(start, end, max_window_count=max_window_count)
        if plan.get("error"):
            messagebox.showerror(*plan["error"])
            return
        if plan.get("already"):
            self._report_already_in_storage(plan["rounded_start"], plan["rounded_end"],
                                            plan["stored_count"])
            return
        ceiling_note = ""
        if ceiling is not None and (plan["rounded_end"] - 1) > ceiling:
            ceiling_note = self.T(ceiling_note_key, max_stop=number_format.whole(ceiling))
        self.quick_status_var.set(self.T(
            "quick.summary_range", start=number_format.whole(start),
            end=number_format.whole(end),
            rounded_start=number_format.whole(plan['rounded_start']),
            rounded_end=number_format.whole(plan['rounded_end']), floor=plan["floor"],
            existing_count=plan["stored_count"], range_count=plan["range_count"],
            added_count=plan["window_count_per_run"])
            + (self.T("quick.note_truncated_floor_boundary",
                      boundary=number_format.whole(plan['rounded_end']))
               if plan.get("truncated") else "")
            + (self.T("quick.note_width_capped_alignment")
               if plan.get("width_capped") else "")
            + ceiling_note)
        launch(plan["floor"], plan["target_idx_start"], plan["window_count_per_run"])

    def _run_low_floor_once(self, floor, existing_count, launch):
        """A floor below LOW_FLOOR_CUTOFF is one window at most: with that window stored the
        click reports it, otherwise launch() writes it. Width does not apply, so a second
        click never appends a QUICK_GEN_MAX_WINDOW_WIDTH window holding a higher floor's
        numbers."""
        if existing_count >= 1:
            rounded_start = 10 ** floor
            self._report_already_in_storage(rounded_start, rounded_start + QUICK_GEN_MAX_WINDOW_WIDTH,
                                            existing_count)
            return
        self.quick_status_var.set(self.T(
            "quick.summary_floor", floor=floor, width_mult=1,
            width_total=number_format.whole(QUICK_GEN_MAX_WINDOW_WIDTH),
            start=self.T("quick.start_continue_last"),
            existing_count=0, added_count=1))
        launch()

    def _continuation_count(self, floor):
        """Stored windows of `floor` up to the first one a continuation writes."""
        return find_continuation_target_idx(self._get_portal_folder(), floor,
                                            QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine())

    def _plan_quick_floor(self):
        """Floor mode. A Starting point is a literal target of Width windows; a blank one
        continues the floor from its last stored window (or its first gap with "fill gaps
        first"), capped at the floor's own last window."""
        floor_value = _eval_quick_number(self.quick_floor_var.get().strip())
        if floor_value is None or floor_value < 0:
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_floor_required"))
            return
        width_mult = _eval_quick_number(self.quick_floor_width_var.get()) or 1
        start_value = _eval_quick_number(self.quick_floor_start_var.get().strip())
        if start_value is not None:
            # Width is a window-count budget here: max_window_count keeps a start off the
            # window grid from adding one window past it.
            self._launch_literal_plan(start_value, start_value + width_mult * QUICK_GEN_MAX_WINDOW_WIDTH,
                                      self._launch_direct_window_range, max_window_count=width_mult)
            return
        existing_count = self._continuation_count(floor_value)
        if floor_value < LOW_FLOOR_CUTOFF:
            self._run_low_floor_once(floor_value, existing_count,
                                     lambda: self._apply_loop_params_and_run(floor_value, 1, 1))
            return
        floor_window_count = _floor_window_count(floor_value)
        if self._try_fill_quick_gen_gap(floor_value, existing_count, width_mult):
            return
        remaining = floor_window_count - existing_count
        if remaining <= 0:
            self._report_floor_full(floor_value, floor_window_count)
            return
        # One run stays inside the floor: its windows past the floor's end would hold the
        # next floor's numbers.
        capped_width = min(width_mult, remaining)
        self.quick_status_var.set(self.T(
            "quick.summary_floor", floor=floor_value, width_mult=capped_width,
            width_total=number_format.whole(capped_width * QUICK_GEN_MAX_WINDOW_WIDTH),
            start=self.T("quick.start_continue_last"),
            existing_count=self._engine_window_count(floor_value),
            added_count=capped_width)
            + (self.T("quick.note_truncated_floor_boundary",
                      boundary=number_format.whole(10 ** (floor_value + 1)))
               if capped_width < width_mult else ""))
        self._apply_loop_params_and_run(floor_value, 1, capped_width)

    def _plan_quick_range(self):
        """Range mode: the literal [From, To) target, both fields required."""
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
        self._launch_literal_plan(start, end, self._launch_direct_window_range)

    def _explore_start_floor(self):
        """The typed Floor, or with Floor blank the deepest floor with any stored window,
        looked up on every click; None (after an error) when neither gives a floor."""
        raw_floor = self.quick_explore_floor_var.get().strip()
        if raw_floor:
            floor_value = _eval_quick_number(raw_floor)
            if floor_value is not None and floor_value >= 0:
                return floor_value
        else:
            floor_value = find_highest_populated_floor(self._get_portal_folder(),
                                                       engine=self._selected_engine())
            if floor_value is not None:
                return floor_value
        messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_explore_floor_required"))
        return None

    def _plan_quick_explore(self):
        """Exploration mode: Iterations runs of Width windows each, continuing the start
        floor; a full floor rolls the Floor field forward to the next one with room, so
        exploration crosses floor boundaries that the other modes stop at."""
        floor_value = self._explore_start_floor()
        if floor_value is None:
            return
        iterations = _eval_quick_number(self.quick_iterations_var.get()) or 1
        width_mult = _eval_quick_number(self.quick_explore_width_var.get()) or 1
        window_count_per_run = width_mult
        existing_count = self._continuation_count(floor_value)
        if floor_value < LOW_FLOOR_CUTOFF:
            if existing_count >= 1:
                # The low floors are written in one batch, so a stored low floor means
                # all of them are: exploration moves on to LOW_FLOOR_CUTOFF, the first
                # floor that continues window by window.
                floor_value = LOW_FLOOR_CUTOFF
                self.quick_explore_floor_var.set(str(floor_value))
                existing_count = self._continuation_count(floor_value)
            else:
                self.quick_status_var.set(self.T(
                    "quick.summary_explore", floor=floor_value, iterations=1,
                    width_mult=1,
                    iterations_total=number_format.whole(QUICK_GEN_MAX_WINDOW_WIDTH),
                    existing_count=0, added_count=1))
                self._apply_loop_params_and_run(floor_value, 1, 1)
                return
        # "Fill gaps first" is checked on the start floor and on every full floor passed:
        # a floor's fullness only looks at its last window, not at gaps below it.
        if self._try_fill_quick_gen_gap(floor_value, existing_count, width_mult):
            return
        floor_window_count = _floor_window_count(floor_value)
        remaining = floor_window_count - existing_count
        advances = 0
        while remaining <= 0 and advances < 1000:  # 1000: runaway guard only
            floor_value += 1
            self.quick_explore_floor_var.set(str(floor_value))
            existing_count = self._continuation_count(floor_value)
            if self._try_fill_quick_gen_gap(floor_value, existing_count, width_mult):
                return
            floor_window_count = _floor_window_count(floor_value)
            remaining = floor_window_count - existing_count
            advances += 1
        if remaining <= 0:
            self._report_floor_full(floor_value, floor_window_count)
            return
        # base_exponent is fixed for a whole orchestrator run, so one launch stays inside
        # the floor: Iterations x Width is cut down to the windows the floor has left.
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
            width_mult=window_count_per_run,
            iterations_total=number_format.whole(iterations_total),
            existing_count=self._engine_window_count(floor_value),
            added_count=iterations * window_count_per_run)
            + (self.T("quick.note_truncated_floor_boundary",
                      boundary=number_format.whole(10 ** (floor_value + 1)))
               if truncated else ""))
        self._apply_loop_params_and_run(floor_value, iterations, window_count_per_run)

    def _plan_quick_hybrid(self):
        """Hybrid mode: the selected target range goes to the hybrid preflight."""
        main_cap = _eval_quick_number(self.quick_hybrid_main_cap_var.get())
        filter_prime_count = _eval_quick_number(self.quick_hybrid_filter_prime_count_var.get())
        try:
            start, end = self._hybrid_selected_range()
        except (ValueError, TypeError):
            messagebox.showerror(self.T("quick.hybrid_error_title"),
                                 self.T("quick.hybrid_error_invalid_target"))
            return
        self._prepare_hybrid(start, end, main_cap, filter_prime_count)

    def _sieve_start(self, from_var, floor_var):
        """From of primesieve and cudasieve mode. A blank or unreadable From continues the
        Floor's storage (the floor's start when nothing is stored) and is written into the
        field; None (after an error) when neither field gives a start of at least 0."""
        raw_from = from_var.get().strip()
        start = _eval_quick_number(raw_from)
        if not raw_from or start is None:
            raw_floor = floor_var.get().strip()
            floor_value = _eval_quick_number(raw_floor)
            if not raw_floor or floor_value is None or floor_value < 0:
                messagebox.showerror(
                    self.T("quick.dialog_title"), self.T("quick.error_primesieve_from_required"))
                return None
            start = 10 ** floor_value
            if floor_value >= LOW_FLOOR_CUTOFF:
                start += self._continuation_count(floor_value) * QUICK_GEN_MAX_WINDOW_WIDTH
            from_var.set(str(start))
        if start < 0:
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_range_negative"))
            return None
        return start

    def _plan_quick_primesieve(self):
        """primesieve mode, Native off: the literal [From, From + Width windows) target,
        launched through prime_sieve_primesieve.py. The floor From falls in decides, not
        the Floor field (only a lookup for a blank From); a low floor is its one window."""
        start = self._sieve_start(self.quick_primesieve_from_var, self.quick_primesieve_floor_var)
        if start is None:
            return
        width_mult = _eval_quick_number(self.quick_primesieve_width_var.get()) or 1
        floor_lo = digit_count_floor(start)
        if floor_lo < LOW_FLOOR_CUTOFF:
            self._run_low_floor_once(floor_lo, self._continuation_count(floor_lo),
                                     lambda: self._apply_primesieve_params_and_run(floor_lo, 0, 1))
            return
        if start > PRIMESIEVE_MAX_STOP:
            messagebox.showerror(self.T("quick.dialog_title"), self.T(
                "quick.error_primesieve_beyond_ceiling",
                max_stop=number_format.whole(PRIMESIEVE_MAX_STOP)))
            return
        self._launch_literal_plan(start, start + width_mult * QUICK_GEN_MAX_WINDOW_WIDTH,
                                  self._apply_primesieve_params_and_run,
                                  ceiling=PRIMESIEVE_MAX_STOP,
                                  ceiling_note_key="quick.note_primesieve_ceiling")

    def _plan_quick_cudasieve(self):
        """cudasieve mode: planned like primesieve mode, launched through
        prime_sieve_cudasieve.py. CUDASieve prints no primes below
        CUDASIEVE_MIN_PRINTABLE_TOP, so a target ending below it is refused before the WSL
        round-trip; that also covers the low floors, which need no branch of their own."""
        start = self._sieve_start(self.quick_cudasieve_from_var, self.quick_cudasieve_floor_var)
        if start is None:
            return
        width_mult = _eval_quick_number(self.quick_cudasieve_width_var.get()) or 1
        end = start + width_mult * QUICK_GEN_MAX_WINDOW_WIDTH
        if (end - 1) < CUDASIEVE_MIN_PRINTABLE_TOP:
            messagebox.showerror(self.T("quick.dialog_title"), self.T(
                "quick.error_cudasieve_below_min",
                min_printable=number_format.whole(CUDASIEVE_MIN_PRINTABLE_TOP)))
            return
        if start > CUDASIEVE_MAX_STOP:
            messagebox.showerror(self.T("quick.dialog_title"), self.T(
                "quick.error_cudasieve_beyond_ceiling",
                max_stop=number_format.whole(CUDASIEVE_MAX_STOP)))
            return
        self._launch_literal_plan(start, end, self._apply_cudasieve_params_and_run,
                                  ceiling=CUDASIEVE_MAX_STOP,
                                  ceiling_note_key="quick.note_cudasieve_ceiling")
