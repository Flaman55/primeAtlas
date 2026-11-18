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

Every check() states the specific expected vs. actual value, to catch failures and
show their actual cause, not just red/green.

The three methods under test, plus the Quick-gen panel's own StringVar/BooleanVar state,
live on GenerationTab (primeatlas/generation/generation_tab.py) rather than on the app class
directly -- this suite drives them via app.generation_tab_widget.X instead of app.X
(see that module's own docstring for the extraction design).

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
    """source_primes/ is sharded into shard_NNNNN subfolders (see window_sharding.py) --
    placed via window_sharding.shard_dir() with the real target_idx as
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


def _touch_kind(portal, floor, target_idx, kind, window_m=10_000_000):
    """A window of the D or P store (storage_kinds.window_path(), sharded like _touch_window)."""
    import storage_kinds
    offset = target_idx * window_m
    label = "0" if offset == 0 else f"{offset // 1_000_000}M"
    path = storage_kinds.window_path(portal, floor, offset, window_m, label, kind)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()


def _plan_idx(plan):
    return plan.get("target_idx_start"), plan.get("window_count_per_run")


def _check_literal_range_gaps(app_dynamic, gen, portal, recorder, W):
    """A literal range (Range mode, Floor mode with a starting point, the search offer) asks
    about its own windows only: windows above it on the floor say nothing about its gaps."""
    T = app_dynamic.T
    base = 10 ** 13
    for idx in (0, 1, 3, 9):  # gaps 2 and 4..8, highest window 9
        _touch_window(portal, 13, idx)

    plan = gen._quick_gen_plan_literal_range(base, base + 5 * W)
    check(not plan.get("already") and _plan_idx(plan) == (2, 3),
          f"[0,5) under the highest window with gaps 2 and 4 launches 2..4, not 'already' "
          f"(got {plan!r})")
    plan = gen._quick_gen_plan_literal_range(base, base + 2 * W)
    check(plan.get("already") is True and plan.get("stored_count") == 2,
          f"[0,2) fully stored reports 'already' with the range's own count 2, not the "
          f"floor's 4 (got {plan!r})")
    plan = gen._quick_gen_plan_literal_range(base + 4 * W, base + 9 * W)
    check(_plan_idx(plan) == (4, 5) and plan.get("stored_count") == 0,
          f"[4,9) empty under window 9 launches 4..8 with 0 stored (got {plan!r})")
    plan = gen._quick_gen_plan_literal_range(base + 2 * W, base + 3 * W)
    check(_plan_idx(plan) == (2, 1),
          f"one missing window [2,3) under the highest launches exactly it (got {plan!r})")
    plan = gen._quick_gen_plan_literal_range(base + 3 * W, base + 4 * W)
    check(plan.get("already") is True and plan.get("stored_count") == 1,
          f"one stored window [3,4) reports 'already', 1 window (got {plan!r})")

    for idx in (1, 2, 7):  # gap at the front of the range, a window above it
        _touch_window(portal, 14, idx)
    plan = gen._quick_gen_plan_literal_range(10 ** 14, 10 ** 14 + 3 * W)
    check(_plan_idx(plan) == (0, 1) and plan.get("stored_count") == 2,
          f"front gap: [0,3) with 1,2 stored launches window 0 only (got {plan!r})")
    for idx in (0, 1, 5):  # gap at the back of the range
        _touch_window(portal, 15, idx)
    plan = gen._quick_gen_plan_literal_range(10 ** 15, 10 ** 15 + 3 * W)
    check(_plan_idx(plan) == (2, 1),
          f"back gap: [0,3) with 0,1 stored launches window 2 only (got {plan!r})")
    for idx in (0, 2, 4, 8):  # stored windows inside the missing run are rewritten
        _touch_window(portal, 16, idx)
    plan = gen._quick_gen_plan_literal_range(10 ** 16, 10 ** 16 + 5 * W)
    check(_plan_idx(plan) == (1, 3) and plan.get("stored_count") == 3,
          f"[0,5) with 0,2,4 stored launches first..last missing = 1..3 (got {plan!r})")

    # Floor mode with a starting point: status texts and a second click after the run.
    gen.quick_mode_var.set("floor")
    gen.quick_floor_var.set("13")
    gen.quick_floor_width_var.set("5")
    gen.quick_floor_start_var.set(str(base))
    recorder.calls.clear()
    gen._on_quick_generate_clicked()
    check([c[2:] for c in recorder.calls] == [(2, 3)],
          f"Floor mode start {base:,} width 5 launches windows 2..4 (got {recorder.calls!r})")
    expected = T("quick.summary_range", start=f"{base:,}", end=f"{base + 5 * W:,}",
                 rounded_start=f"{base:,}", rounded_end=f"{base + 5 * W:,}", floor=13,
                 existing_count=3, range_count=5, added_count=3)
    check(gen.quick_status_var.get() == expected,
          f"summary counts the range: 3 of 5 windows stored, 3 launched "
          f"(got {gen.quick_status_var.get()!r})")
    for idx in (2, 4):  # the launched run wrote its windows
        _touch_window(portal, 13, idx)
    recorder.calls.clear()
    gen._on_quick_generate_clicked()
    expected = T("quick.status_already_in_storage", rounded_start=f"{base:,}",
                 rounded_end=f"{base + 5 * W:,}", existing_count=5)
    check(recorder.calls == [] and gen.quick_status_var.get() == expected,
          f"the second click after the run reports 'already', 5 windows "
          f"(got {recorder.calls!r}, {gen.quick_status_var.get()!r})")

    gen.quick_mode_var.set("range")
    gen.quick_from_var.set(str(10 ** 14))
    gen.quick_to_var.set(str(10 ** 14 + 3 * W))
    recorder.calls.clear()
    gen._on_quick_generate_clicked()
    check([c[2:] for c in recorder.calls] == [(0, 1)],
          f"Range mode [0,3) on floor 14 under window 7 fills window 0 (got {recorder.calls!r})")
    gen.quick_floor_start_var.set("")
    gen.quick_mode_var.set("floor")


def _check_engine_store_counts(app_dynamic, gen, portal, W):
    """Counts and the 'already' decision read the store the selected engine writes into."""
    import storage_kinds
    for idx in range(5):
        _touch_kind(portal, 25, idx, storage_kinds.KIND_D)
    for idx in (0, 1):
        _touch_kind(portal, 25, idx, storage_kinds.KIND_P)
    base = 10 ** 25
    engines = gen._engine_fields
    previous = engines.engine_var.get()
    engines.engine_var.set(storage_kinds.ENGINE_PT1)
    plan = gen._quick_gen_plan_literal_range(base, base + 2 * W)
    check(plan.get("already") is True and plan.get("stored_count") == 2,
          f"pt1 on floor 25: P windows 0,1 cover [0,2), 2 stored (got {plan!r})")
    plan = gen._quick_gen_plan_literal_range(base, base + 4 * W)
    check(_plan_idx(plan) == (2, 2) and plan.get("stored_count") == 2,
          f"pt1 on floor 25: [0,4) launches P windows 2,3; the D windows do not count "
          f"(got {plan!r})")
    check(gen._engine_window_count(25) == 2,
          f"pt1 floor-25 count is its P store's 2 windows, not D's 5 "
          f"(got {gen._engine_window_count(25)!r})")
    engines.engine_var.set(previous)
    plan = gen._quick_gen_plan_literal_range(base, base + 4 * W)
    check(plan.get("already") is True and plan.get("stored_count") == 4,
          f"a sieve engine on floor 25 sees the D store: [0,4) stored (got {plan!r})")
    check(gen._engine_window_count(25) == 5,
          f"sieve floor-25 count is the D store's 5 windows, not P's (got "
          f"{gen._engine_window_count(25)!r})")

    # floor 24 holds both: pt1 counts D below MR_DET_BOUND plus P from it on.
    below = (storage_kinds.MR_DET_BOUND - 10 ** 24) // W - 2
    for idx in (below, below + 1):
        _touch_kind(portal, 24, idx, storage_kinds.KIND_D)
    _touch_kind(portal, 24, below + 3, storage_kinds.KIND_P)
    engines.engine_var.set(storage_kinds.ENGINE_PT1)
    lo = 10 ** 24 + below * W
    plan = gen._quick_gen_plan_literal_range(lo, lo + 4 * W)
    check(_plan_idx(plan) == (below + 2, 1) and plan.get("stored_count") == 3,
          f"pt1 on floor 24: D below the bound and P above count, the window on the bound "
          f"is launched (got {plan!r})")
    engines.engine_var.set(previous)

    # The blank-start Floor summary counts the engine's store too.
    gen.quick_mode_var.set("floor")
    gen.quick_floor_start_var.set("")  # clearing the starting point clears Floor too
    gen.quick_floor_var.set("25")
    gen.quick_floor_width_var.set("1")
    gen.quick_floor_fill_gaps_var.set(False)
    engines.engine_var.set(storage_kinds.ENGINE_PT1)
    loop_calls = []
    gen._apply_loop_params_and_run = lambda *a: loop_calls.append(a)
    gen._on_quick_generate_clicked()
    expected = app_dynamic.T(
        "quick.summary_floor", floor=25, width_mult=1, width_total=f"{W:,}",
        start=app_dynamic.T("quick.start_continue_last"), existing_count=2, added_count=1)
    check(gen.quick_status_var.get() == expected,
          f"pt1 Floor summary shows the P store's 2 windows (got {gen.quick_status_var.get()!r})")
    engines.engine_var.set(previous)


def _check_fill_gaps_reaches_every_gap(app_dynamic, gen, portal, recorder, W):
    """'Fill gaps first' on: repeated clicks fill every gap of the floor in ascending order,
    then continue past the highest window; no gap is ever skipped."""
    import storage_kinds
    loop_calls = []
    gen._apply_loop_params_and_run = lambda *a: loop_calls.append(a)
    gen.quick_mode_var.set("floor")
    gen.quick_floor_start_var.set("")
    gen.quick_floor_fill_gaps_var.set(True)

    for idx in (2, 5, 6):  # gaps 0,1 at the front and 3,4 in the middle
        _touch_window(portal, 17, idx)
    gen.quick_floor_var.set("17")
    gen.quick_floor_width_var.set("1")
    launched = []
    for _click in range(6):
        recorder.calls.clear()
        loop_calls.clear()
        gen._on_quick_generate_clicked()
        if recorder.calls:
            idx = recorder.calls[0][2]
            launched.append(idx)
            _touch_window(portal, 17, idx)
        elif loop_calls:
            launched.append("continue")
            break
    check(launched == [0, 1, 3, 4, "continue"],
          f"width 1: clicks fill gaps 0,1,3,4 in order, then continue past window 6 "
          f"(got {launched!r})")

    for idx in (0, 2, 7):  # width wider than the gap reaches the next gap
        _touch_window(portal, 18, idx)
    gen.quick_floor_var.set("18")
    gen.quick_floor_width_var.set("4")
    recorder.calls.clear()
    gen._on_quick_generate_clicked()
    check([c[2:] for c in recorder.calls] == [(1, 4)],
          f"width 4 from gap 1 covers 1..4 (window 2 rewritten) (got {recorder.calls!r})")

    # floor 7 holds windows 0..8: its top window is stored, window 4 is not.
    for idx in (0, 1, 2, 3, 5, 6, 7, 8):
        _touch_window(portal, 7, idx)
    gen.quick_floor_var.set("7")
    gen.quick_floor_width_var.set("1")
    recorder.calls.clear()
    gen._on_quick_generate_clicked()
    check([c[1:] for c in recorder.calls] == [(7, 4, 1)],
          f"a floor whose top window is stored fills its gap 4, never 'floor full' "
          f"(got {recorder.calls!r}, {gen.quick_status_var.get()!r})")
    gen.quick_floor_fill_gaps_var.set(False)
    recorder.calls.clear()
    gen._on_quick_generate_clicked()
    expected = app_dynamic.T("quick.status_floor_full_gaps", floor=7, existing_count=8,
                             floor_window_count=9)
    check(recorder.calls == [] and gen.quick_status_var.get() == expected,
          f"fill gaps off: a full-to-the-top floor with a gap says so and points to the "
          f"option (got {gen.quick_status_var.get()!r})")

    # pt1 fills the gaps of its own store: P windows 0,2 on floor 26, D windows 0..3.
    for idx in range(4):
        _touch_kind(portal, 26, idx, storage_kinds.KIND_D)
    for idx in (0, 2):
        _touch_kind(portal, 26, idx, storage_kinds.KIND_P)
    engines = gen._engine_fields
    previous = engines.engine_var.get()
    engines.engine_var.set(storage_kinds.ENGINE_PT1)
    gen.quick_floor_fill_gaps_var.set(True)
    gen.quick_floor_var.set("26")
    recorder.calls.clear()
    gen._on_quick_generate_clicked()
    check([c[1:] for c in recorder.calls] == [(26, 1, 1)],
          f"pt1 fills P gap 1 although D window 1 exists (got {recorder.calls!r})")
    engines.engine_var.set(previous)

    # Exploration fills a gap on the floor it starts from and on every floor it rolls through.
    gen.quick_mode_var.set("explore")
    gen.quick_explore_floor_var.set("7")
    gen.quick_iterations_var.set("1")
    gen.quick_explore_width_var.set("1")
    _touch_window(portal, 7, 4)
    for idx in [i for i in range(90) if i != 30]:  # floor 8 full to the top, gap 30
        _touch_window(portal, 8, idx)
    recorder.calls.clear()
    gen._on_quick_generate_clicked()
    check([c[1:] for c in recorder.calls] == [(8, 30, 1)],
          f"Exploration rolls past full floor 7 and fills floor 8's gap 30 "
          f"(got {recorder.calls!r})")
    gen.quick_mode_var.set("floor")
    gen.quick_floor_fill_gaps_var.set(False)


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
    import prime_atlas_v2
    from primeatlas.app import app_dynamic
    from primeatlas.generation import window_planning
    from primeatlas.generation.window_planning import _floor_window_count

    W = 10_000_000
    portal = tempfile.mkdtemp(prefix="primeatlas_gen_launch_test_")
    try:
        sys.argv = ["prime_atlas_v2.py"]
        from app_sandbox import isolate_app
        isolate_app(portal)
        app_cls = prime_atlas_v2._build_gui()
        app = app_cls()
        app.update()
        gen = app.generation_tab_widget

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
        gen.quick_hybrid_target_var.set("n")
        gen.quick_hybrid_value_var.set("12000500")
        gen.quick_hybrid_main_cap_var.set("997")
        gen.quick_hybrid_filter_prime_count_var.set("11")
        gen._on_quick_generate_clicked()
        # Preflight now runs in the background and increases the filter when needed.
        import time
        from prime_sieve.hybrid_policy import parameters
        deadline = time.monotonic() + 10
        while not hybrid_calls and time.monotonic() < deadline:
            app.update()
            time.sleep(0.01)
        fitted = parameters(997, 11, 20_000_000)
        check(hybrid_calls == [(10_000_000, 20_000_000, fitted["main"], fitted["count"])],
              f"hybrid Quick mode waits for preflight and launches the fitted range (got {hybrid_calls!r})")
        check(gen.quick_hybrid_filter_prime_count_var.get() == str(fitted["count"]),
              "automatically fitted filter is visible before launch")
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
        # Floor boundary: a request whose END crosses into the NEXT floor's numbers
        # must be clamped, never write the next floor's numbers into this floor's
        # folder. Floor 7 = [10**7, 10**8), its last window is target_idx 8
        # (90,000,000-100,000,000); ask for a range that reaches deep into floor 8's
        # numbers instead.
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
              f"(PRIMESIEVE_MAX_STOP={window_planning.PRIMESIEVE_MAX_STOP}) must fall back "
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
        check(gen.quick_status_var.get() == app_dynamic.T("quick.status_range_fully_covered"),
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

        # A dialog would block the clicks below: record it instead, none is expected.
        from tkinter import messagebox
        dialogs = []
        for name in ("showerror", "showinfo", "showwarning", "askyesno", "askokcancel"):
            setattr(messagebox, name, lambda *a, _name=name, **k: dialogs.append((_name, a)))
        _check_literal_range_gaps(app_dynamic, gen, portal, recorder, W)
        _check_engine_store_counts(app_dynamic, gen, portal, W)
        _check_fill_gaps_reaches_every_gap(app_dynamic, gen, portal, recorder, W)
        check(dialogs == [], f"no Quick-gen click above opens a dialog (got {dialogs!r})")

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
