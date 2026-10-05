"""
test_storage_fill.py -- spec tests for filling an empty storage from a literal [from, to]
range across floors (the visualization's "storage is empty -- generate?" offer):

  A. plan_storage_fill(start, end): the [start, end) request as a list of
     (floor, target_idx_start, window_count) launches, in ascending order:
       - anything below 10**LOW_FLOOR_CUTOFF is one launch (floor 0, window 0, 1 window)
         -- the engines split that one window into floors 0..6 themselves;
       - from floor 7 on, one launch per floor touched, covering [max(start, 10**f),
         min(end, 10**(f+1))) rounded out to whole windows, never past the floor;
       - a floor straddling the primesieve uint64 ceiling is split at the last window
         that fits under it, so primesieve does everything it can;
       - an empty or inverted request plans nothing.
  B. parse_generate_range(raw_from, raw_to): "to" is required; an empty "from" means 2;
     both accept the app's number forms (10**7, 1e7); from <= to; to >= 2. Returns
     (start, end_inclusive) or an error key.
  C. GenerationTab storage-fill queue: start_storage_fill launches the first planned
     step; each finished run (_on_loop_finished) launches the next; a step already
     covered on disk is skipped without waiting; a failed launch or a non-zero exit
     stops the queue and reports failure; the last step reports success; a second
     start while a run is in flight is refused.

Usage:
    python unitTests/test_storage_fill.py
"""
import os
import sys
import types

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "constellation"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


W = 10_000_000


def section_a_plan():
    print("\n--- A: plan_storage_fill ---")
    from primeatlas.generation.generation import plan_storage_fill, PRIMESIEVE_MAX_STOP
    check(plan_storage_fill(2, 1001) == [(0, 0, 1)], "2..1000 is the single low-floor launch")
    check(plan_storage_fill(2, 10**7 + 1) == [(0, 0, 1), (7, 0, 1)],
          f"2..10**7 adds floor 7's first window (got {plan_storage_fill(2, 10**7 + 1)})")
    check(plan_storage_fill(2, 10**8 + 1) == [(0, 0, 1), (7, 0, 9), (8, 0, 1)],
          f"2..10**8: low block, all 9 windows of floor 7, floor 8's first (got {plan_storage_fill(2, 10**8 + 1)})")
    got = plan_storage_fill(35 * 10**6, 52 * 10**6)
    check(got == [(7, 2, 3)], f"35e6..52e6 rounds out to windows 2..4 of floor 7 (got {got})")
    got = plan_storage_fill(10**9 + 5, 10**9 + 6)
    check(got == [(9, 0, 1)], f"a single number deep in floor 9 is one window (got {got})")
    check(plan_storage_fill(5, 5) == [] and plan_storage_fill(9, 3) == [], "empty/inverted requests plan nothing")
    check(plan_storage_fill(0, 10) == [(0, 0, 1)], "a start below 1 still plans the low block")

    base = 10**19
    split = (PRIMESIEVE_MAX_STOP + 1 - base) // W
    got = plan_storage_fill(base, base + (split + 3) * W)
    check(got == [(19, 0, split), (19, split, 3)],
          f"floor 19 splits at the last window under the uint64 ceiling (got {got[:2]})")
    got = plan_storage_fill(base + (split + 1) * W, base + (split + 2) * W)
    check(got == [(19, split + 1, 1)], f"a request wholly above the ceiling is not split (got {got})")
    for launches in (plan_storage_fill(2, 10**12), plan_storage_fill(123456789, 98765432109)):
        ok = all(c > 0 and i >= 0 and (f < 7 or 10**f + (i + c) * W <= 10**(f + 1)) for f, i, c in launches)
        check(ok, "no launch is empty or crosses its floor's upper edge")
        floors = [f for f, _, _ in launches]
        check(floors == sorted(floors), "launches are in ascending floor order")
    big = plan_storage_fill(2, 10**25 + 1)
    check(big[-1] == (25, 0, 1) and len(big) == 1 + (25 - 7 + 1) + 1,
          f"a 26-digit upper end plans one launch per floor plus the uint64 split (got {len(big)})")


def section_b_parse():
    print("\n--- B: parse_generate_range ---")
    from primeatlas.visualization.shared.viz_tab_base import parse_generate_range
    check(parse_generate_range("", "1000") == (2, 1000), "empty 'from' means 2")
    check(parse_generate_range("  ", "10**7") == (2, 10**7), "'to' accepts 10**7")
    check(parse_generate_range("100", "1e6") == (100, 10**6), "both fields parse")
    check(parse_generate_range("5", "5") == (5, 5), "from == to is allowed")
    for raw_from, raw_to, key in (("", "", "error_generate_to_required"),
                                  ("", "abc", "error_generate_to_required"),
                                  ("x", "100", "error_generate_from_invalid"),
                                  ("200", "100", "error_generate_order"),
                                  ("", "1", "error_generate_to_required"),
                                  ("-5", "100", "error_generate_from_invalid")):
        got = parse_generate_range(raw_from, raw_to)
        check(got == key, f"parse_generate_range({raw_from!r}, {raw_to!r}) -> {key} (got {got!r})")


class _FakeRunner:
    def __init__(self):
        self.running = True

    def is_running(self):
        return self.running


def _fake_tab(results):
    """A stand-in for GenerationTab carrying only what the queue methods touch.
    `results` lists what each _launch_direct_window_range call reports."""
    from primeatlas.generation.generation_tab import GenerationTab
    tab = types.SimpleNamespace()
    tab.calls = []
    tab._loop_runner = None
    tab._pending_storage_fill = None
    pending = list(results)

    def launch(floor, idx, count):
        tab.calls.append((floor, idx, count))
        result = pending.pop(0)
        if result == "launched":
            tab._loop_runner = _FakeRunner()
        return result

    tab._launch_direct_window_range = launch
    tab._other_engine_is_running = lambda name: False
    for name in ("start_storage_fill", "_advance_storage_fill", "_finish_storage_fill",
                 "_on_storage_fill_run_finished"):
        setattr(tab, name, types.MethodType(getattr(GenerationTab, name), tab))
    return tab


def section_c_queue():
    print("\n--- C: GenerationTab storage-fill queue ---")
    done = []
    launches = [(0, 0, 1), (7, 0, 9), (8, 0, 1)]
    tab = _fake_tab(["launched", "covered", "launched"])
    check(tab.start_storage_fill(launches, done.append) is True, "start_storage_fill accepts the plan")
    check(tab.calls == [(0, 0, 1)] and not done, "the first step launches, nothing reported yet")
    tab._loop_runner.running = False
    tab._on_storage_fill_run_finished(0)
    check(tab.calls == [(0, 0, 1), (7, 0, 9), (8, 0, 1)] and not done,
          "a finished run launches the next step; a covered step is skipped at once")
    tab._loop_runner.running = False
    tab._on_storage_fill_run_finished(0)
    check(done == [True] and tab._pending_storage_fill is None, "the last finished step reports success")

    done = []
    tab = _fake_tab(["launched", "launched"])
    tab.start_storage_fill(launches, done.append)
    tab._loop_runner.running = False
    tab._on_storage_fill_run_finished(1)
    check(done == [False] and tab.calls == [(0, 0, 1)] and tab._pending_storage_fill is None,
          "a non-zero exit (failure or Stop) ends the queue and reports failure")

    done = []
    tab = _fake_tab(["failed"])
    tab.start_storage_fill(launches, done.append)
    check(done == [False] and tab._pending_storage_fill is None, "a failed launch ends the queue")

    done = []
    tab = _fake_tab(["covered", "covered", "covered"])
    tab.start_storage_fill(launches, done.append)
    check(done == [True], "a plan already fully on disk reports success at once")

    done = []
    tab = _fake_tab([])
    tab._loop_runner = _FakeRunner()
    check(tab.start_storage_fill(launches, done.append) is False and not tab.calls and not done,
          "a second start while a run is in flight is refused")

    tab = _fake_tab([])
    tab._on_storage_fill_run_finished(0)
    check(tab.calls == [], "a run finishing with no fill pending does nothing")


if __name__ == "__main__":
    for section in (section_a_plan, section_b_parse, section_c_queue):
        try:
            section()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(False, f"{section.__name__} raised {type(e).__name__}: {e}")
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
