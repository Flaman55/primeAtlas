"""The Quick-gen Generate click dispatches to one planner method per mode, and the code the
modes share has one copy in primeatlas/generation/quick_gen_plan.py.

Checks: _on_quick_generate_clicked holds only the running and red-field guards and the mode
dispatch; every mode has its own planner method; the "already in storage" report, the range
summary, the blank-From lookup and the low-floor summary each appear once in the module; a
click runs exactly the selected mode's planner once (primesieve with Native on runs the
native planner), a running loop or a red field of the mode runs none, and a mode the panel
does not offer runs none and shows no dialog. No display needed:
    python unitTests/test_quick_gen_plan_split.py
"""
import inspect
from pathlib import Path
import sys
import tkinter.messagebox

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.core import number_field  # noqa: E402
from primeatlas.generation import quick_gen_plan  # noqa: E402
from primeatlas.generation.quick_gen_plan import QuickGenPlan  # noqa: E402

failures = []

# Planner per mode; primesieve with Native on has its own.
PLANNERS = {
    "floor": "_plan_quick_floor",
    "range": "_plan_quick_range",
    "explore": "_plan_quick_explore",
    "hybrid": "_plan_quick_hybrid",
    "pseudosquares": "_on_quick_generate_pseudosquares",
    "primesieve": "_plan_quick_primesieve",
    "primesieve_native": "_on_quick_generate_primesieve_native",
    "cudasieve": "_plan_quick_cudasieve",
}
# The click handler: docstring, two guards, the match. A per-mode body does not fit.
MAX_CLICK_LINES = 40
# Text that one shared helper owns: each key appears once in the module.
SINGLE_COPY_KEYS = ("quick.status_already_in_storage", "quick.summary_range",
                    "quick.error_primesieve_from_required")
# quick.summary_floor: once in the low-floor helper, once in Floor mode's continuation.
SUMMARY_FLOOR_COPIES = 2


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_structure():
    missing = [name for name in PLANNERS.values() if not callable(getattr(QuickGenPlan, name, None))
               and name != "_on_quick_generate_pseudosquares"]
    check(not missing, f"QuickGenPlan has a planner per mode (missing: {missing})")
    click_lines = len(inspect.getsource(QuickGenPlan._on_quick_generate_clicked).splitlines())
    check(click_lines <= MAX_CLICK_LINES,
          f"_on_quick_generate_clicked is guards + dispatch, at most {MAX_CLICK_LINES} lines "
          f"(got {click_lines})")
    source = inspect.getsource(quick_gen_plan)
    for key in SINGLE_COPY_KEYS:
        count = source.count(f'"{key}"')
        check(count == 1, f"{key} appears once in quick_gen_plan.py (got {count})")
    count = source.count('"quick.summary_floor"')
    check(count == SUMMARY_FLOOR_COPIES,
          f"the low-floor summary has one copy: quick.summary_floor appears "
          f"{SUMMARY_FLOOR_COPIES} times (got {count})")


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class _Runner:
    def __init__(self, running):
        self.running = running

    def is_running(self):
        return self.running


class _FakeTab(QuickGenPlan):
    """QuickGenPlan with every planner replaced by a recorder."""

    def __init__(self, mode, native=False, running=False):
        self.quick_mode_var = _Var(mode)
        self.quick_primesieve_native_var = _Var(native)
        self._loop_runner = _Runner(running) if running is not None else None
        self.calls = []
        for name in PLANNERS.values():
            setattr(self, name, lambda name=name: self.calls.append(name))

    def T(self, key, **kwargs):
        return key


def _click(tab, red_field=False):
    """Runs one click; returns (planners called, dialogs shown, exception or None)."""
    dialogs = []
    real = (tkinter.messagebox.showerror, number_field.refuse_problem)
    tkinter.messagebox.showerror = lambda *a, **k: dialogs.append(a)
    number_field.refuse_problem = lambda variables, T, title: red_field
    try:
        tab._on_quick_generate_clicked()
        error = None
    except Exception as exc:  # the old inline branches reach attributes the fake lacks
        error = exc
    finally:
        tkinter.messagebox.showerror, number_field.refuse_problem = real
    return tab.calls, dialogs, error


def _test_dispatch():
    for mode in ("floor", "range", "explore", "hybrid", "pseudosquares", "primesieve",
                 "cudasieve"):
        calls, dialogs, error = _click(_FakeTab(mode, running=None))
        check(error is None and calls == [PLANNERS[mode]] and not dialogs,
              f"mode {mode!r} runs only {PLANNERS[mode]}, once (got {calls}, {dialogs}, {error!r})")
    calls, dialogs, error = _click(_FakeTab("primesieve", native=True, running=False))
    check(error is None and calls == [PLANNERS["primesieve_native"]] and not dialogs,
          f"primesieve with Native on runs only the native planner (got {calls}, {error!r})")
    calls, dialogs, error = _click(_FakeTab("cudasieve", native=True, running=False))
    check(error is None and calls == [PLANNERS["cudasieve"]],
          f"Native on does not reroute another mode (got {calls}, {error!r})")


def _test_guards():
    calls, dialogs, error = _click(_FakeTab("floor", running=True))
    check(error is None and not calls and [d[1] for d in dialogs] == ["quick.error_already_running"],
          f"a running loop runs no planner and shows the 'already running' error "
          f"(got {calls}, {dialogs}, {error!r})")
    calls, dialogs, error = _click(_FakeTab("range", running=False), red_field=True)
    check(error is None and not calls,
          f"a red field of the mode runs no planner (got {calls}, {error!r})")
    calls, dialogs, error = _click(_FakeTab("no-such-mode", running=False))
    check(error is None and not calls and not dialogs,
          f"a mode the panel does not offer runs no planner and shows nothing "
          f"(got {calls}, {dialogs}, {error!r})")


def main():
    _test_structure()
    _test_dispatch()
    _test_guards()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
