"""
generation_offer_coordinator.py -- GenerationOfferCoordinator, the three
"offer to generate this missing fragment, then let the caller re-check" bridge
methods that used to live directly on PortalBrowserApp itself in prime_atlas_v1.py:
_offer_generate_missing_prime_window, _offer_generate_missing_constellation, and
_goldbach_offer_generate_missing_range.

Extracted on the refactor-phase3 branch (2026-08-27), continuing the same "God
object" reduction TotalsSearchCoordinator started on refactor-phase2 (task #410,
2026-08-26) and PrimesTreeCoordinator/ConstellationsTreeCoordinator continued
immediately before this (same branch) -- see either module's own docstring and
README.md's "GUI module conventions" -> "Known gaps" section.

Unlike the two tree coordinators, this class needs only ONE piece of app state at
call time -- self.generation_tab_widget (GenerationTab, primeatlas/generation_tab.py)
-- reached via a lazy get_generation_tab_widget() callable rather than a direct
reference, since all three of these methods are only ever CALLED well after every
tab (including Generation) already exists (in response to a search job finding a
gap, or a Wizualizacja/decompose job hitting one) -- unlike PrimesTreeCoordinator/
ConstellationsTreeCoordinator, which reach into their own tab widgets from an
async scan callback that could, in principle, still be in flight from the loading
screen's own startup kickoff. Being lazy also means this class can be constructed
at ANY point in PortalBrowserApp.__init__, not just after Generation tab exists.

What stays on PortalBrowserApp instead of moving here: _select_constellations_hits_
view/_jump_records_detail_to_hits/_on_const_search_result are genuine multi-tab
coordination glue that reaches into self.main_notebook/self.constellations_sub_
notebook/self.constellations_hits_tab_widget/self.constellations_calc_tab_widget --
none of which belongs to the Generation-offer mechanism this class owns, and none
of which any one tab (or this coordinator) has (or should have) direct knowledge
of. This mirrors TotalsSearchCoordinator's own on_const_search_result seam:
_on_const_search_result calls into THIS class's own offer_generate_missing_prime_
window/offer_generate_missing_constellation methods directly (same as it always
called the inline PortalBrowserApp methods), it just doesn't own the offering
logic itself.
"""
from tkinter import messagebox


class GenerationOfferCoordinator:
    def __init__(self, get_generation_tab_widget, status_var, translator,
                 quick_gen_max_window_width, primesieve_max_stop):
        """
        get_generation_tab_widget: lazy callable returning the live GenerationTab --
        see this module's own docstring for why a getter is used here instead of a
        direct reference (unlike PrimesTreeCoordinator/ConstellationsTreeCoordinator's
        own tab-widget constructor arguments).

        status_var/translator: same dependency-injection pattern as every other
        extracted tab/coordinator -- see primeatlas/primes_tab.py's own docstring.

        quick_gen_max_window_width/primesieve_max_stop: primeatlas.generation's own
        QUICK_GEN_MAX_WINDOW_WIDTH/PRIMESIEVE_MAX_STOP constants, passed through
        rather than imported directly here -- keeps this module's only import a
        plain stdlib one (tkinter.messagebox), matching totals_search_coordinator.py's
        own precedent for a coordinator class that needs message dialogs.
        """
        self._get_generation_tab_widget = get_generation_tab_widget
        self.status = status_var
        self.T = translator.t
        self._quick_gen_max_window_width = quick_gen_max_window_width
        self._primesieve_max_stop = primesieve_max_stop

    def offer_generate_missing_prime_window(self, kind, base_exponent, number):
        """Called from _on_prime_search_result()/_on_const_search_result() the moment
        find_prime_in_floor() comes back empty -- which, on its own, is ambiguous:
        either `number` really is composite, OR the window that would COVER it was
        simply never generated (the floor folder exists -- that's checked earlier, in
        _search_prime()/_search_constellation() -- but this specific fragment inside
        it doesn't). _quick_gen_plan_literal_range(number, number + 1) is the exact
        same "is this literal point already on disk" check Range/Floor mode already
        use (see that method's own docstring) -- reused here unchanged rather than
        re-deriving the on-disk-coverage logic a second time.

        Returns one of three strings, so the caller can pick the right final message
        instead of a single generic "not found" for every case:
          "launched"  -- a generation run was actually started; the caller should show
                          NOTHING yet -- _on_loop_finished() re-runs the search once the
                          run completes and THAT result decides the final message.
          "composite" -- plan says "already": the window covering `number` DOES exist
                          on disk, find_prime_in_floor() already searched it and came up
                          empty, so this isn't a data gap at all -- `number` is
                          CONFIRMED composite. The caller should say so plainly instead
                          of the generic "not found in storage" wording, which exists
                          specifically for the ambiguous case this ISN'T.
          "skipped"   -- still ambiguous: either a generation run is already in flight
                          (an error dialog was already shown here, via the same
                          T("quick.error_already_running") message the Quick-gen panel
                          itself uses for the identical situation) or the user declined
                          the confirmation prompt. The caller should fall back to the
                          generic "not found in storage" wording -- true either way,
                          since the fragment genuinely isn't on disk.

        LAUNCH ENGINE: deliberately _apply_primesieve_params_and_run(), NOT
        _apply_loop_params_and_run() (v4's own batch engine) -- window_count_per_run
        from _quick_gen_plan_literal_range() is measured relative to
        find_continuation_target_idx()'s CONTINUATION point (existing_count), which is
        exactly right for Range/Floor mode (a person deliberately filling a range they
        want whole), but wrong here: a number searched deep into an otherwise-empty
        floor would silently turn into a request to backfill EVERY window from index 0
        up to it first, because orchestrator_loop_v2.py/v4's engine has no notion of
        "start at an arbitrary target_idx" -- it only ever continues from wherever a
        floor's storage currently ends (see build_loop_argv()'s own CLI, which has no
        target_idx_start position at all). One real run hit exactly this: floor 11,
        nothing on disk yet, searched a number landing at target_idx ~30000 -> a
        30,001-window batch instead of the single window actually needed.
        build_primesieve_argv()'s script (prime_sieve_primesieve.py) takes
        target_idx_start explicitly and has no continuation requirement -- it writes
        just the ONE window asked for, gaps before it and all, which is exactly what a
        single-number check needs (see that function's own docstring).

        CEILING FALLBACK: primesieve mode can't reach every floor -- libprimesieve's
        own uint64 domain tops out at PRIMESIEVE_MAX_STOP (2**64-1 =~ 1.8e19), while a
        search can land on any floor at all (a floor-30 constellation search real-world
        hit this: 10^30 is about eleven orders of magnitude past that ceiling, so
        primesieve mode silently truncated the run to nothing rather than writing the
        window). Once `plan['rounded_start']` is past that ceiling, primesieve mode
        cannot write ANY part of the requested window, so this falls back to
        orchestrator_v3.py run directly (see build_orchestrator_direct_argv()'s own
        docstring for why that engine -- not its loop wrapper -- is the one capable of
        an arbitrary single-window write at any magnitude)."""
        gen = self._get_generation_tab_widget()
        plan = gen._quick_gen_plan_literal_range(number, number + 1)
        if plan.get("error"):
            return "skipped"
        if plan.get("already"):
            return "composite"
        if gen._loop_runner is not None and gen._loop_runner.is_running():
            messagebox.showinfo(self.T("quick.dialog_title"), self.T("quick.error_already_running"))
            return "skipped"
        if not messagebox.askyesno(
                self.T("common.dialog_search_title"),
                self.T("search.offer_generate_prime_window", number=f"{number:,}",
                        base_exponent=base_exponent,
                        rounded_start=f"{plan['rounded_start']:,}",
                        rounded_end=f"{plan['rounded_end']:,}")):
            return "skipped"
        gen._pending_search_after_prime_gen = {
            "kind": kind, "base_exponent": base_exponent, "number": number}
        self.status.set(self.T("search.status_generating_prime_window", number=f"{number:,}"))
        target_idx = (plan["rounded_start"] - 10 ** plan["floor"]) // self._quick_gen_max_window_width
        if plan["rounded_start"] > self._primesieve_max_stop:
            gen._apply_orchestrator_direct_params_and_run(plan["floor"], target_idx, 1)
        else:
            gen._apply_primesieve_params_and_run(plan["floor"], target_idx, 1)
        return "launched"

    def offer_generate_missing_constellation(self, base_exponent, number):
        """Two callers: _on_const_search_result(), when `number` IS a confirmed prime
        (its window exists and find_prime_in_floor() found it) but
        find_constellation_participation() came back with zero matches -- ambiguous
        on its own: either this number genuinely isn't the base/offset-member of any
        tracked pattern at this floor, OR constellation_finder_v1.py has simply never
        been run for floor 10p{base_exponent} at all, so there's nothing recorded to
        match against either way. That caller checks list_constellation_hits()
        returning an empty list (no hit FILES at all for this floor, for any pattern
        in the catalog) first, to distinguish the second case from genuine
        non-participation, before calling this.

        The second caller, ConstellationsCalcTab.search_selected() (Kalkulator
        konstelacji), checks something more specific instead: whether the ONE pattern it's asking
        about has a hit file yet, regardless of whether other patterns already do --
        list_constellation_hits()'s "nothing at all" check would stay silent in
        that case even though this exact pattern was never confirmed either way
        (see that method's own docstring for why the coarser check isn't enough
        there). Either way, once this actually launches, process_floor() itself is
        what decides whether there's genuinely new work to do (it only re-scans
        windows past its own per-floor checkpoint -- a floor already fully
        checkpointed under the current catalog just reports "nothing new" and
        reconfirms the same non-participation result, harmless either way).
        search.offer_generate_constellation's own wording is deliberately scenario-
        agnostic ("no hits recorded", not "never ran") so it reads correctly from
        both callers.

        Same True/False launched-or-not contract this file uses elsewhere for a single
        generation offer (simpler than offer_generate_missing_prime_window()'s 3-way
        "launched"/"composite"/"skipped" string, since there's no equivalent of
        "composite" here -- an empty hit-file list is ALWAYS ambiguous, never a
        confirmed answer, so there's nothing finer to distinguish), but
        drives constellation_finder_v1.py's own runner/queue (self._const_runner) via
        _on_run_constellation()'s exact launch path instead of the prime-window one --
        see _on_constellation_finished() for the completion/re-search side."""
        gen = self._get_generation_tab_widget()
        if gen._const_runner is not None and gen._const_runner.is_running():
            messagebox.showinfo(self.T("quick.dialog_title"), self.T("quick.error_already_running"))
            return False
        if not messagebox.askyesno(
                self.T("common.dialog_search_title"),
                self.T("search.offer_generate_constellation", number=f"{number:,}",
                        base_exponent=base_exponent)):
            return False
        gen._pending_search_after_const_gen = {
            "kind": "const", "base_exponent": base_exponent, "number": number}
        self.status.set(self.T("search.status_generating_constellation", base_exponent=base_exponent))
        gen._const_base_exponent_var.set(str(base_exponent))
        gen._on_run_constellation()
        return True

    def offer_generate_missing_range(self, op, payload):
        """Offers to generate the primes storage a Wizualizacja/decompose job
        just found missing (MissingStorageRangeError, translated into this dict
        by the worker loop's own except MissingStorageRangeError blocks --
        see ResearchGoldbachTab._goldbach_job's docstring). Mirrors
        offer_generate_missing_prime_window()'s askyesno pattern, but launches
        through _quick_gen_plan_literal_range()/_launch_direct_window_range() --
        the SAME path Quick-gen's own Range mode button uses -- instead of always
        forcing the primesieve engine directly the way that helper does: a Goldbach
        gap can span many windows (the whole floor up to needed_upto), not just the one
        window a single prime search needs, so the continuation-based
        orchestrator engine (fills from wherever the floor's storage already
        ends, up to the requested count) is the right fit here, not
        primesieve's "write exactly this one window" contract.

        Injected into ResearchGoldbachTab as the single
        `offer_generate_missing_range(op, payload)` callable (see that class's own
        docstring) -- ResearchGoldbachTab itself doesn't need to know this now lives
        in its own coordinator class rather than directly on PortalBrowserApp,
        `prime_atlas_v1.py`'s own `_goldbach_offer_generate_missing_range` delegate
        still passes this same bound method through unchanged.

        Records `op` ("viz" or "decompose") into gen._pending_goldbach_retry_op
        once a run is actually launched, so _on_loop_finished knows WHICH job to
        re-queue once generation completes -- the two ops read their target n from
        different places (see that method's own docstring), so blindly always
        retrying "viz" would silently drop a decompose request that hit this same
        offer. read_is_prime_from_storage only ever reports the FIRST short floor it
        hits while walking 0,1,2,... in order, so a range spanning multiple short
        floors may still come back short again after one generation run -- re-queuing
        just repeats this same offer for the next gap rather than trying to solve
        every gap in one shot."""
        gen = self._get_generation_tab_widget()
        floor = payload["floor"]
        needed_upto = payload["needed_upto"]
        if gen._loop_runner is not None and gen._loop_runner.is_running():
            messagebox.showinfo(self.T("quick.dialog_title"), self.T("quick.error_already_running"))
            return
        plan = gen._quick_gen_plan_literal_range(10 ** floor, needed_upto + 1)
        if plan.get("error"):
            messagebox.showerror(*plan["error"])
            return
        if plan.get("already"):
            # Shouldn't normally happen (read_is_prime_from_storage's own check
            # just said this floor was short), but if a race/edge case lands
            # here anyway, fall back to the plain error rather than launching a
            # no-op run.
            messagebox.showerror(self.T("research_goldbach.error_dialog_title"), payload["message"])
            return
        if not messagebox.askyesno(
                self.T("common.dialog_search_title"),
                self.T("research_goldbach.offer_generate_missing_range",
                        floor=floor, rounded_start=f"{plan['rounded_start']:,}",
                        rounded_end=f"{plan['rounded_end']:,}")):
            return
        gen._pending_goldbach_retry_op = op
        self.status.set(self.T("research_goldbach.status_generating_range", floor=floor))
        gen._launch_direct_window_range(
            plan["floor"], plan["target_idx_start"], plan["window_count_per_run"])
