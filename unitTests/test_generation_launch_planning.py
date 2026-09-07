"""
test_generation_launch_planning.py -- drives the REAL app-level planning methods used by
the Generation tab's Quick-generation panel (_quick_gen_plan_literal_range,
_launch_direct_window_range, _try_fill_quick_gen_gap) exactly the way clicking Generate
does, but with the actual subprocess launch stubbed out (_apply_primesieve_params_and_run
/_apply_orchestrator_direct_params_and_run replaced with recorders) -- these three
functions decide WHAT to generate and WHERE to write it; nothing downstream of that
decision can be exercised in this sandbox (no libprimesieve.so.12, no WSL -- see
test_generation_window_arithmetic.py's own module docstring), but everything upstream of
it -- the exact layer responsible for every historical Generation bug on record -- can be,
and is, exercised for real here: real temp portal folder, real seeded window files, real
method calls, only the final "start a subprocess" step swapped for a recorder.

Companion to test_generation_window_arithmetic.py, which covers the lower-level pure
functions (_round_range_to_window, _floor_window_count, _trim_existing_from_target_idx_
range, etc.) these three methods are built out of; this file covers the methods
themselves, including the three documented historical incidents each was written to fix
(see each test section's own comment for which incident it targets) and the
engine-selection logic in _launch_direct_window_range (primesieve vs. orchestrator-direct,
by PRIMESIEVE_MAX_STOP).

Every check() states the specific expected vs. actual value, per Artur's explicit request
that this suite "wyłapały i wyświetliły co faktycznie powoduje błąd" -- catch failures AND
show their actual cause, not just red/green.

Updated during the Generation-tab extraction itself (Faza 3, 2026-08-23): all three
methods under test, plus the Quick-gen panel's own StringVar/BooleanVar state, moved from
PortalBrowserApp into GenerationTab (primeatlas/generation_tab.py) -- this suite now
drives them via app.generation_tab_widget.X instead of app.X directly (see that module's
own docstring for the full extraction design).

Usage (Windows, real display):
    python unitTests\\test_generation_launch_planning.py

Usage (this sandbox, headless):
    PYTHONPATH="/tmp/tkextract/extracted/usr/lib/python3.10:/tmp/tkextract/extracted/usr/lib/python3.10/lib-dynload:$PYTHONPATH" \\
    LD_LIBRARY_PATH="/tmp/tkextract/extracted/usr/lib/x86_64-linux-gnu:/tmp/tkextract/extracted/usr/lib:$LD_LIBRARY_PATH" \\
    xvfb-run -a python3 unitTests/test_generation_launch_planning.py
"""
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _touch_window(portal, floor, target_idx, window_m=10_000_000):
    """source_primes/ is sharded into shard_NNNNN subfolders (see window_sharding.py,
    task #405) -- placed via window_sharding.shard_dir() with the real target_idx as
    window_index (target_idx IS the window's 0-based generation-order index, matching
    every real writer's own offset // window_m math), so the sharded layout this test
    produces matches what a real engine run would have produced."""
    import window_sharding
    offset = target_idx * window_m
    source_dir = os.path.join(portal, f"10p{floor}", "source_primes")
    shard_dir = window_sharding.shard_dir(source_dir, target_idx)
    os.makedirs(shard_dir, exist_ok=True)
    suffix = f"{offset // 1_000_000}M" if offset and offset % 1_000_000 == 0 else str(offset)
    name = f"PRIME_WINDOW_10p{floor}_off_{suffix}.bin"
    open(os.path.join(shard_dir, name), "wb").close()


def _patch_app_settings(app_settings):
    app_settings.save = lambda: None


class _LaunchRecorder:
    """Stands in for _apply_primesieve_params_and_run/_apply_orchestrator_direct_params_
    and_run -- records exactly what _launch_direct_window_range decided to launch instead
    of actually starting a WslLoggedRunner subprocess (which needs a real WSL/engine this
    sandbox doesn't have -- see this file's own module docstring)."""

    def __init__(self):
        self.calls = []  # list of (engine_name, base_exponent, target_idx_start, window_count_per_run)

    def primesieve(self, base_exponent, target_idx_start, window_count_per_run):
        self.calls.append(("primesieve", base_exponent, target_idx_start, window_count_per_run))

    def orchestrator_direct(self, base_exponent, target_idx_start, window_count_per_run):
        self.calls.append(("orchestrator_direct", base_exponent, target_idx_start, window_count_per_run))


def main():
    import prime_atlas_v1
    from primeatlas.generation import _floor_window_count

    W = 10_000_000
    portal = tempfile.mkdtemp(prefix="primeatlas_gen_launch_test_")
    try:
        sys.argv = ["prime_atlas_v1.py"]
        app_cls = prime_atlas_v1._build_gui()
        app = app_cls()
        app.update()
        gen = app.generation_tab_widget

        settings_tab = app.settings_tab
        _patch_app_settings(settings_tab.app_settings)
        settings_tab.app_settings.set_storage_path(portal)
        settings_tab.wsl["set_portal_folder"](portal)
        app.update()

        recorder = _LaunchRecorder()
        gen._apply_primesieve_params_and_run = recorder.primesieve
        gen._apply_orchestrator_direct_params_and_run = recorder.orchestrator_direct
        hybrid_calls = []
        gen._on_run_hybrid_narrow = lambda start, end, main_cap, filter_prime_count: hybrid_calls.append(
            (start, end, main_cap, filter_prime_count))

        # Hybrid Quick mode must launch its own fixed contract, never translate
        # k_adv into the classical loop's width/window settings.
        gen.quick_mode_var.set("hybrid")
        gen.quick_hybrid_from_var.set("12000000")
        gen.quick_hybrid_to_var.set("12000500")
        gen.quick_hybrid_main_cap_var.set("997")
        gen.quick_hybrid_filter_prime_count_var.set("11")
        gen._on_quick_generate_clicked()
        check(hybrid_calls == [(12_000_000, 12_000_500, 997, 11)],
              f"hybrid Quick mode delegates one literal narrow range plus explicit MAIN/filter bounds "
              f"contract to the hybrid runner (got {hybrid_calls!r})")
        gen.quick_mode_var.set("floor")

        # =====================================================================
        # BUG #1 -- MemoryError on floor 25: a starting point picked deep into an
        # otherwise-empty floor used to backfill target_idx from 0, building a Python
        # list with hundreds of quadrillions of entries. Floor 9 (base 10**9, holding
        # windows 0..899 -- see _floor_window_count(9)) is empty here; requesting a
        # literal starting point at window 500 must launch starting AT window 500, never
        # at 0. (NOTE: 10**9 + 500*W, not 10**8 + 500*W -- window index 500 does not fit
        # inside floor 8's own 90-window range at all, so a naive 10**8-based offset would
        # silently land the request in floor 9's numbers anyway via digit_count_floor;
        # anchoring explicitly on floor 9's own base keeps this test's arithmetic honest.)
        # =====================================================================
        plan = gen._quick_gen_plan_literal_range(
            10 ** 9 + 500 * W, 10 ** 9 + 501 * W, max_window_count=1)
        check("floor" in plan,
              f"floor-9 window-500 request (on an EMPTY floor) plans a launch, not "
              f"'already covered' (got keys {sorted(plan.keys())})")
        check(plan.get("target_idx_start") == 500,
              f"launch target_idx_start must be the LITERAL requested position (500), "
              f"never 0 -- backfilling from 0 here is exactly the floor-25 MemoryError "
              f"regression (got {plan.get('target_idx_start')!r})")
        check(plan.get("window_count_per_run") == 1,
              f"window_count_per_run must cover ONLY the single requested window, not "
              f"501 windows of backfill (got {plan.get('window_count_per_run')!r})")

        # =====================================================================
        # BUG #2 -- floor-7-with-130M-numbers: a request whose END crosses into the
        # NEXT floor's numbers used to be honored past the boundary, silently writing
        # the next floor's numbers into this floor's folder. Floor 7 = [10**7, 10**8),
        # its last window is target_idx 8 (90,000,000-100,000,000); ask for a range
        # that reaches deep into floor 8's numbers instead.
        # =====================================================================
        plan2 = gen._quick_gen_plan_literal_range(
            10 ** 7 + 8 * W, 10 ** 8 + 5 * W)  # requested end reaches into floor 8
        check(plan2.get("truncated") is True,
              f"a request crossing floor 7's own boundary (10**8) must be reported as "
              f"truncated (got truncated={plan2.get('truncated')!r})")
        check(plan2.get("rounded_end") == 10 ** 8,
              f"the launch must be clamped to EXACTLY floor 7's boundary (100,000,000), "
              f"never spill into floor 8's numbers under floor 7's folder "
              f"(got rounded_end={plan2.get('rounded_end')!r})")
        check(plan2.get("floor") == 7,
              f"the clamped plan still targets floor 7 (got {plan2.get('floor')!r})")

        # =====================================================================
        # BUG #3 -- "1001 windows for a Width=1000 request" off-by-one: Floor mode's
        # Starting-point path treats its Width field as a WINDOW-COUNT BUDGET, not a
        # literal end -- rounding BOTH ends outward (the Range-mode behavior) silently
        # adds one extra window whenever the starting point isn't itself window-aligned.
        # Floor 8, starting point NOT aligned to a 10,000,000 boundary, budget=5 windows.
        # =====================================================================
        misaligned_start = 10 ** 8 + 3 * W + 12345  # not a multiple of W
        budget = 5
        naive_end = misaligned_start + budget * W
        # Without the max_window_count cap: reproduces the historical off-by-one.
        plan3_uncapped = gen._quick_gen_plan_literal_range(misaligned_start, naive_end)
        check(plan3_uncapped.get("window_count_per_run") == budget + 1,
              f"DOCUMENTING the historical bug: omitting max_window_count on a "
              f"non-aligned starting point rounds both ends outward and silently adds "
              f"one extra window beyond the {budget}-window budget "
              f"(got window_count_per_run={plan3_uncapped.get('window_count_per_run')!r}, "
              f"historically this was {budget + 1} where {budget} was asked for)")
        # With the cap (what Floor-mode's real caller actually passes): must NOT overshoot.
        plan3_capped = gen._quick_gen_plan_literal_range(
            misaligned_start, naive_end, max_window_count=budget)
        check(plan3_capped.get("window_count_per_run") == budget,
              f"passing max_window_count={budget} (as the real Floor-mode Starting-point "
              f"caller does) must cap window_count_per_run at exactly the requested "
              f"budget, never {budget + 1} "
              f"(got {plan3_capped.get('window_count_per_run')!r})")
        check(plan3_capped.get("width_capped") is True,
              f"the plan must flag width_capped=True so the caller can tell the user the "
              f"run was capped, distinct from the floor-boundary 'truncated' flag "
              f"(got width_capped={plan3_capped.get('width_capped')!r})")

        # =====================================================================
        # "already in storage" case: the whole requested range is already on disk ->
        # must report already=True and launch NOTHING (no recorder call at all from a
        # direct _quick_gen_plan_literal_range call -- that method only ever returns a
        # plan dict, launching is _launch_direct_window_range's job; this just confirms
        # the plan dict itself is the "nothing to do" shape).
        # =====================================================================
        for idx in range(3):
            _touch_window(portal, 9, idx)
        plan4 = gen._quick_gen_plan_literal_range(10 ** 9, 10 ** 9 + 2 * W)
        check(plan4.get("already") is True,
              f"a range fully covered by existing floor-9 windows reports already=True "
              f"(got {plan4!r})")

        # =====================================================================
        # Low-floor misalignment: floor 3 (base=1000, NOT a multiple of the 10,000,000
        # window) fed through the literal-range path (meant for floors >= LOW_FLOOR_
        # CUTOFF) must be rejected with an explicit error, never silently mis-plan a
        # launch on a floor this function's own alignment arithmetic doesn't fit.
        # =====================================================================
        plan5 = gen._quick_gen_plan_literal_range(500, 5000)
        check("error" in plan5,
              f"a low-floor (floor 3) literal-range request is rejected with an explicit "
              f"error rather than silently mis-planning a launch (got {plan5!r})")

        # =====================================================================
        # _launch_direct_window_range: engine selection (primesieve vs.
        # orchestrator-direct) by PRIMESIEVE_MAX_STOP, and edge-trimming against disk.
        # =====================================================================
        recorder.calls.clear()
        gen._launch_direct_window_range(10, 0, 2)  # small floor, well under uint64 ceiling
        check(len(recorder.calls) == 1 and recorder.calls[0][0] == "primesieve",
              f"a small-floor request (well under PRIMESIEVE_MAX_STOP) launches via the "
              f"primesieve engine (got calls={recorder.calls!r})")
        check(recorder.calls[0][1:] == (10, 0, 2),
              f"the primesieve call's own (floor, target_idx_start, window_count) must "
              f"match the request exactly when nothing is already on disk "
              f"(got {recorder.calls[0][1:]!r}, expected (10, 0, 2))")

        recorder.calls.clear()
        gen._launch_direct_window_range(25, 0, 2)  # floor 25 end is far past 2**64-1
        check(len(recorder.calls) == 1 and recorder.calls[0][0] == "orchestrator_direct",
              f"a floor whose requested range exceeds libprimesieve's own uint64 ceiling "
              f"(PRIMESIEVE_MAX_STOP={prime_atlas_v1.PRIMESIEVE_MAX_STOP}) must fall back "
              f"to orchestrator_v3.py launched directly, not primesieve "
              f"(got calls={recorder.calls!r})")

        # Edge-trimming: the recorder above never actually writes anything to disk (it
        # replaces the real launch, per this file's own module docstring), so seed floor
        # 10's windows 0,1 directly to set up a real "already partially on disk" scenario
        # -- requesting [0,3) must trim the already-existing front edge and only launch
        # what's missing.
        _touch_window(portal, 10, 0)
        _touch_window(portal, 10, 1)
        recorder.calls.clear()
        gen._launch_direct_window_range(10, 0, 3)
        check(len(recorder.calls) == 1 and recorder.calls[0][2:] == (2, 1),
              f"requesting [0,3) on floor 10 (which already has windows 0,1 on disk) "
              f"must trim to launching only the missing window 2 (target_idx_start=2, "
              f"window_count=1) (got {recorder.calls[0] if recorder.calls else None!r})")

        # Fully-covered request: no launch call at all, status message set instead. Seed
        # window 2 directly (simulating that the trimmed launch above actually completed,
        # since the recorder itself never writes a file) so the SAME [0,3) request is now
        # genuinely fully covered.
        _touch_window(portal, 10, 2)
        recorder.calls.clear()
        gen._launch_direct_window_range(10, 0, 3)
        check(len(recorder.calls) == 0,
              f"a request fully covered by existing windows must launch NOTHING "
              f"(got calls={recorder.calls!r})")
        check(gen.quick_status_var.get() == prime_atlas_v1.T("quick.status_range_fully_covered"),
              "a fully-covered request sets the 'fully covered' status message")

        # =====================================================================
        # _try_fill_quick_gen_gap: gap-filling toggle + capped width + status message.
        # =====================================================================
        _touch_window(portal, 12, 0)
        _touch_window(portal, 12, 1)
        _touch_window(portal, 12, 4)  # gap at target_idx 2,3; existing_count(continuation)=5

        gen.quick_floor_fill_gaps_var.set(False)
        recorder.calls.clear()
        result_off = gen._try_fill_quick_gen_gap(12, 5, width_mult=10)
        check(result_off is False,
              "with the 'fill gaps first' toggle OFF, _try_fill_quick_gen_gap is a no-op "
              f"(got return value {result_off!r})")
        check(len(recorder.calls) == 0,
              f"toggle OFF must launch nothing at all (got calls={recorder.calls!r})")

        gen.quick_floor_fill_gaps_var.set(True)
        recorder.calls.clear()
        result_on = gen._try_fill_quick_gen_gap(12, 5, width_mult=10)
        check(result_on is True,
              f"with the toggle ON and a real gap present (window 2 missing), "
              f"_try_fill_quick_gen_gap returns True (got {result_on!r})")
        check(len(recorder.calls) == 1 and recorder.calls[0][2:] == (2, 10),
              f"the gap fill must start exactly at the first missing window (target_idx="
              f"2) and launch capped_width=min(width_mult=10, floor_window_count(12)-2="
              f"{_floor_window_count(12) - 2}) = 10 (width_mult is what "
              f"actually binds here, floor 12's own structural cap is nowhere close) -- "
              f"one iteration's worth only, never more, per _try_fill_quick_gen_gap's own "
              f"docstring (got {recorder.calls[0] if recorder.calls else None!r})")

        app.destroy()

        if failures:
            print(f"\n{len(failures)} FAILURE(S)")
            return 1
        print("\nALL CHECKS PASSED")
        return 0
    finally:
        shutil.rmtree(portal, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
