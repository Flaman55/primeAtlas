"""
quick_gen_plan.py -- QuickGenPlan, which turns the Quick generation panel's fields into
one launch: _quick_gen_plan_literal_range() maps a literal number range onto floor
windows, _on_quick_generate_clicked() validates the selected mode's fields and calls the
matching launcher in quick_gen_runs.py.

A GenerationTab mixin: it uses the widgets, Variables and runner state that GenerationTab
and its other mixins set up, so it is never instantiated on its own.
"""
from tkinter import messagebox

from ..core.storage import digit_count_floor, LOW_FLOOR_CUTOFF
from .quick_number import _eval_quick_number
from .window_planning import (QUICK_GEN_MAX_WINDOW_WIDTH, count_existing_windows,
                              find_continuation_target_idx, find_highest_populated_floor,
                              _round_range_to_window, _floor_window_count, PRIMESIEVE_MAX_STOP,
                              CUDASIEVE_MIN_PRINTABLE_TOP, CUDASIEVE_MAX_STOP)


class QuickGenPlan:
    def _quick_gen_plan_literal_range(self, start, end, max_window_count=None):
        """Shared by Range mode and Floor mode WITH a starting point set (see
        _on_quick_generate_clicked): given a literal [start, end) target, rounds it
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

        LAUNCH START: "target_idx_start" in the launch-case dict is max(the request's
        OWN literal target_idx, existing_count). Never less than the literal request:
        a starting point deep into an otherwise-empty floor must not turn into
        backfilling everything from index 0 (which misrepresents the request and, for
        a big enough gap, makes prime_sieve_v4_1.py build a target_idx list too large
        for memory). Never less than existing_count either: filling from at/near the
        front of a partially generated floor starts at existing_count.
        window_count_per_run is sized to this SAME start, so it only covers what is
        still missing from [target_idx_start, target_idx_end). Callers should launch
        via a target_idx_start-CAPABLE engine (see _launch_direct_window_range()), not
        orchestrator_loop_v2.py's continuation-only wrapper, which cannot start past
        wherever storage currently ends.

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
        existing_count = find_continuation_target_idx(
            self._get_portal_folder(), floor_lo, QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine())
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
                self._get_portal_folder(), floor_value, QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine())
            if floor_value < LOW_FLOOR_CUTOFF:
                # A floor below the cutoff (see LOW_FLOOR_CUTOFF) is ALWAYS at most
                # one window wide, never continuable past target_idx=0 -- treated like
                # a normal floor, a blank-starting-point click would append another
                # QUICK_GEN_MAX_WINDOW_WIDTH-sized window (e.g. "..._off_10M.bin") onto
                # a floor whose numeric domain is only thousands/millions wide,
                # mislabeling a HIGHER floor's numbers as this one's. existing_count >= 1
                # means the single low-floor window is already there (written by
                # main_batch_scanner's low-floor branch, possibly while cascading up from
                # a lower floor's request -- see that function's docstring).
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
            # crosses into the NEXT floor's numeric range (see _floor_window_count).
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
                floor_value = find_highest_populated_floor(self._get_portal_folder(), engine=self._selected_engine())
                if floor_value is None:
                    messagebox.showerror(
                        self.T("quick.dialog_title"), self.T("quick.error_explore_floor_required"))
                    return
            iterations = _eval_quick_number(self.quick_iterations_var.get()) or 1
            width_mult = _eval_quick_number(self.quick_explore_width_var.get()) or 1
            window_count_per_run = width_mult
            existing_count = find_continuation_target_idx(
                self._get_portal_folder(), floor_value, QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine())
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
                    # own iterations/width there, instead of reporting "already in
                    # storage" and stopping (e.g. Floor=6 picked by the Auto button).
                    # The Floor field
                    # itself is updated to show "7" too, so what's displayed matches
                    # what actually ran, and a follow-up click (blank or typed) starts
                    # from the right place.
                    floor_value = LOW_FLOOR_CUTOFF
                    self.quick_explore_floor_var.set(str(floor_value))
                    existing_count = find_continuation_target_idx(
                        self._get_portal_folder(), floor_value, QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine())
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
            # only resolves the 0-6 -> 7 jump once. Without this loop, a typed (or
            # Auto-detected) floor >= 7 that is already complete would fall straight
            # through to _apply_loop_params_and_run below with no completion check
            # (unlike Floor mode's remaining<=0 guard), writing more windows into a
            # complete floor's folder -- data that numerically belongs to the NEXT floor.
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
                    self._get_portal_folder(), floor_value, QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine())
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
        elif mode == "hybrid":
            main_cap = _eval_quick_number(self.quick_hybrid_main_cap_var.get())
            filter_prime_count = _eval_quick_number(self.quick_hybrid_filter_prime_count_var.get())
            try:
                start, end = self._hybrid_selected_range()
            except (ValueError, TypeError):
                messagebox.showerror(self.T("quick.hybrid_error_title"),
                                      self.T("quick.hybrid_error_invalid_target"))
                return
            self._prepare_hybrid(start, end, main_cap, filter_prime_count)
        elif mode == "pseudosquares":
            self._on_quick_generate_pseudosquares()  # quick_gen_pseudosquares.py
        elif mode == "primesieve":
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
                        self._get_portal_folder(), floor_value, QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine())
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
                    self._get_portal_folder(), floor_lo, QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine())
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
        else:
            # mode == "cudasieve": GPU counterpart to primesieve mode -- IDENTICAL From
            # + Width planning logic (see the "primesieve" branch's own comment just
            # above), with two engine-specific differences: the uint64 ceiling check
            # uses CUDASIEVE_MAX_STOP (CUDASieve's own --help text documents examples up
            # to 2**64, the same domain as libprimesieve's), and there's an ADDITIONAL
            # floor -- CUDASieve's own CLI documents that printing individual primes is
            # ignored below 2**40 (CUDASIEVE_MIN_PRINTABLE_TOP); prime_sieve_cudasieve.py's
            # own generate_primes_in_range() rejects anything below that with a
            # RuntimeError, so it's checked HERE too, before paying a WSL round-trip for
            # a request already known to fail. Unlike primesieve mode, there's no
            # low-floor (0-6) special case: LOW_FLOOR_CUTOFF's floors are always far
            # below CUDASIEVE_MIN_PRINTABLE_TOP anyway, so that branch could never
            # legitimately fire for this engine -- the general below-min check just past
            # `end` below catches it instead, with a clear message rather than a silent
            # floor jump.
            raw_from = self.quick_cudasieve_from_var.get().strip()
            start = _eval_quick_number(raw_from)
            width_mult = _eval_quick_number(self.quick_cudasieve_width_var.get()) or 1
            if not raw_from or start is None:
                raw_floor = self.quick_cudasieve_floor_var.get().strip()
                floor_value = _eval_quick_number(raw_floor)
                if not raw_floor or floor_value is None or floor_value < 0:
                    messagebox.showerror(
                        self.T("quick.dialog_title"), self.T("quick.error_primesieve_from_required"))
                    return
                start = 10 ** floor_value
                if floor_value >= LOW_FLOOR_CUTOFF:
                    existing_count = find_continuation_target_idx(
                        self._get_portal_folder(), floor_value, QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine())
                    start = 10 ** floor_value + existing_count * QUICK_GEN_MAX_WINDOW_WIDTH
                self.quick_cudasieve_from_var.set(str(start))
            if start < 0:
                messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_range_negative"))
                return

            end = start + width_mult * QUICK_GEN_MAX_WINDOW_WIDTH
            if (end - 1) < CUDASIEVE_MIN_PRINTABLE_TOP:
                messagebox.showerror(self.T("quick.dialog_title"), self.T(
                    "quick.error_cudasieve_below_min",
                    min_printable=f"{CUDASIEVE_MIN_PRINTABLE_TOP:,}"))
                return
            if start > CUDASIEVE_MAX_STOP:
                messagebox.showerror(self.T("quick.dialog_title"), self.T(
                    "quick.error_cudasieve_beyond_ceiling",
                    max_stop=f"{CUDASIEVE_MAX_STOP:,}"))
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
            ceiling_truncated = (plan["rounded_end"] - 1) > CUDASIEVE_MAX_STOP
            self.quick_status_var.set(self.T(
                "quick.summary_range", start=f"{start:,}", end=f"{end:,}",
                rounded_start=f"{plan['rounded_start']:,}",
                rounded_end=f"{plan['rounded_end']:,}", floor=plan["floor"],
                existing_count=plan["real_existing_count"],
                added_count=plan["window_count_per_run"])
                + (self.T("quick.note_truncated_floor_boundary",
                      boundary=f"{plan['rounded_end']:,}")
                   if plan.get("truncated") else "")
                + (self.T("quick.note_cudasieve_ceiling",
                      max_stop=f"{CUDASIEVE_MAX_STOP:,}")
                   if ceiling_truncated else ""))
            self._apply_cudasieve_params_and_run(
                plan["floor"], plan["target_idx_start"], plan["window_count_per_run"])
