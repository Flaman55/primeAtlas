"""
test_progress_bar_owner.py -- unit tests for primeatlas/core/progress_bar_owner.py,
the arbitration helper that stops the many independent tabs/coordinators sharing one
totals_progress bar from silently overwriting each other's display (see that module's
own docstring for the bug this fixes).

Pure logic, no tkinter -- claim_progress_bar()/owns_progress_bar()/release_progress_
bar() only ever read/write a plain attribute on whatever object they're given, so a
bare `object()` stands in for the real ttk.Progressbar widget.

Usage:
    python unitTests\\test_progress_bar_owner.py
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
# primeatlas/__init__.py transitively imports .settings.manifest, which does a bare
# `import window_sharding` -- see storage.py's own module docstring for why
# prime_sieve_v1.py/window_sharding.py live outside this package as separate
# top-level modules -- so prime_sieve must be on sys.path before the primeatlas.*
# import below, same as unitTests/test_storage.py's own setup.
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.core.progress_bar_owner import (  # noqa: E402
    claim_progress_bar, owns_progress_bar, release_progress_bar,
    pump_indeterminate, stop_indeterminate_pump,
)

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


class _FakeWidget:
    """Stands in for the real ttk.Progressbar -- claim_progress_bar() et al. only
    ever getattr/setattr a plain marker attribute, and a bare `object()` instance
    (unlike a real Tk widget) has no __dict__ to hold one."""


def _fresh_widget():
    return _FakeWidget()


def _test_first_claim_wins():
    widget = _fresh_widget()
    owner_a, owner_b = object(), object()
    check(claim_progress_bar(widget, owner_a) is True,
          "a free bar's first claimant succeeds")
    check(owns_progress_bar(widget, owner_a) is True,
          "the successful claimant now owns the bar")
    check(owns_progress_bar(widget, owner_b) is False,
          "a different, non-owning object does not own the bar")


def _test_second_claimant_blocked_while_first_holds_it():
    widget = _fresh_widget()
    owner_a, owner_b = object(), object()
    claim_progress_bar(widget, owner_a)
    check(claim_progress_bar(widget, owner_b) is False,
          "a second owner's claim fails while the first still holds it")
    check(owns_progress_bar(widget, owner_a) is True,
          "the original owner still owns the bar after the blocked claim attempt")


def _test_same_owner_reclaiming_is_idempotent():
    widget = _fresh_widget()
    owner = object()
    claim_progress_bar(widget, owner)
    check(claim_progress_bar(widget, owner) is True,
          "the SAME owner claiming again (e.g. its own next poll tick) still succeeds")


def _test_release_frees_the_bar_for_anyone():
    widget = _fresh_widget()
    owner_a, owner_b = object(), object()
    claim_progress_bar(widget, owner_a)
    release_progress_bar(widget, owner_a)
    check(owns_progress_bar(widget, owner_a) is False,
          "releasing owner no longer owns the bar")
    check(claim_progress_bar(widget, owner_b) is True,
          "a different owner can claim the bar once it's released")


def _test_release_by_non_owner_is_a_safe_noop():
    widget = _fresh_widget()
    owner_a, owner_b = object(), object()
    claim_progress_bar(widget, owner_a)
    release_progress_bar(widget, owner_b)  # owner_b never held it
    check(owns_progress_bar(widget, owner_a) is True,
          "a non-owner's release() call does not clear someone ELSE's claim")


def _test_release_on_a_never_claimed_bar_is_a_safe_noop():
    widget = _fresh_widget()
    owner = object()
    release_progress_bar(widget, owner)  # must not raise
    check(owns_progress_bar(widget, owner) is False,
          "releasing a claim that was never held leaves the bar unowned, no crash")


def _test_symmetric_handoff_matches_the_reported_priority_model():
    """Mirrors the exact scenario reported live: a floor-totals scan starts first, a
    Generation run starts while it's still going (must be silently blocked, not
    overwrite the scan's own display), and once the scan finishes and releases, the
    still-running Generation run's own next write reclaims the bar and paints ITS
    current state -- "whichever started first owns it until IT finishes, then the
    other one (if still running) takes over" in both directions, not just one."""
    widget = _fresh_widget()
    totals_scan, generation_run = object(), object()

    check(claim_progress_bar(widget, totals_scan) is True,
          "totals scan starts first and claims the bar")
    check(claim_progress_bar(widget, generation_run) is False,
          "generation run starting afterward is blocked while the scan still owns it")

    release_progress_bar(widget, totals_scan)
    check(claim_progress_bar(widget, generation_run) is True,
          "generation run's own next write reclaims the bar the instant the scan releases it")

    # And the reverse order/direction -- generation starts first this time.
    widget2 = _fresh_widget()
    check(claim_progress_bar(widget2, generation_run) is True,
          "generation run starts first this time and claims the bar")
    check(claim_progress_bar(widget2, totals_scan) is False,
          "a totals scan starting afterward is blocked while generation still owns it")
    release_progress_bar(widget2, generation_run)
    check(claim_progress_bar(widget2, totals_scan) is True,
          "totals scan's own next write reclaims the bar the instant generation releases it")


class _FakeAnimatedWidget:
    """Stands in for ttk.Progressbar for pump_indeterminate()/stop_indeterminate_
    pump() -- records .configure()/.step() calls and implements a minimal,
    synchronous .after()/.after_cancel() so the pump's own scheduling guarantee (at
    most one job alive at a time) can be tested deterministically, without a real Tk
    event loop."""

    def __init__(self):
        self.configure_calls = []
        self.step_calls = 0
        self._next_job_id = 0
        self.scheduled = {}  # job_id -> (interval_ms, callback)
        self.cancelled = []

    def configure(self, **kwargs):
        self.configure_calls.append(kwargs)

    def step(self):
        self.step_calls += 1

    def after(self, ms, callback):
        self._next_job_id += 1
        job_id = self._next_job_id
        self.scheduled[job_id] = (ms, callback)
        return job_id

    def after_cancel(self, job_id):
        self.cancelled.append(job_id)
        self.scheduled.pop(job_id, None)

    def fire_latest(self):
        """Simulates the most recently scheduled job's timer firing -- calls its
        callback directly (a real Tk event loop would do this on its own)."""
        if not self.scheduled:
            return
        job_id = max(self.scheduled)
        _ms, callback = self.scheduled.pop(job_id)
        callback()


def _test_pump_indeterminate_sets_mode_and_schedules_exactly_one_job():
    widget = _FakeAnimatedWidget()
    pump_indeterminate(widget, 120)
    check(widget.configure_calls[-1] == {"mode": "indeterminate"},
          f"pump_indeterminate() sets indeterminate mode (got {widget.configure_calls})")
    check(widget.step_calls == 1, "the first .step() fires immediately, not just on the first tick")
    check(len(widget.scheduled) == 1,
          f"exactly one job is scheduled after starting the pump (got {len(widget.scheduled)})")


def _test_pump_indeterminate_ticks_keep_a_single_job_alive():
    widget = _FakeAnimatedWidget()
    pump_indeterminate(widget, 120)
    for _ in range(5):
        widget.fire_latest()
    check(widget.step_calls == 6, f".step() fires once per tick, 1 initial + 5 fired (got {widget.step_calls})")
    check(len(widget.scheduled) == 1,
          f"still exactly one job alive after several ticks, not an accumulating pile (got {len(widget.scheduled)})")


def _test_pump_indeterminate_called_again_cancels_the_prior_loop():
    """This is the actual bug fix: plain Progressbar.start()/.stop(), called from the
    ~10 independent sites that share this widget across a long session, could leave
    more than one of Tcl's own internal timers alive on the same widget at once --
    looking exactly like the reported symptom (thumb snapping between the two
    extremes instead of gliding). pump_indeterminate() guarantees a SECOND call
    always cancels the first loop's still-pending job before scheduling its own."""
    widget = _FakeAnimatedWidget()
    pump_indeterminate(widget, 120)
    first_job_id = next(iter(widget.scheduled))
    pump_indeterminate(widget, 120)
    check(first_job_id in widget.cancelled,
          f"a second pump_indeterminate() call cancels the FIRST loop's pending job "
          f"(got cancelled={widget.cancelled})")
    check(len(widget.scheduled) == 1,
          f"still exactly one job alive, never two overlapping loops (got {len(widget.scheduled)})")


def _test_stop_indeterminate_pump_cancels_and_is_idempotent():
    widget = _FakeAnimatedWidget()
    pump_indeterminate(widget, 120)
    job_id = next(iter(widget.scheduled))
    stop_indeterminate_pump(widget)
    check(job_id in widget.cancelled, "stop_indeterminate_pump() cancels the pending job")
    check(len(widget.scheduled) == 0, "no job left scheduled after stopping")
    widget.fire_latest()  # nothing scheduled -- must be a safe no-op
    check(widget.step_calls == 1, "no further .step() calls happen once stopped")
    stop_indeterminate_pump(widget)  # calling again with nothing running must not raise
    check(True, "calling stop_indeterminate_pump() again when nothing is running does not raise")


def main():
    _test_first_claim_wins()
    _test_second_claimant_blocked_while_first_holds_it()
    _test_same_owner_reclaiming_is_idempotent()
    _test_release_frees_the_bar_for_anyone()
    _test_release_by_non_owner_is_a_safe_noop()
    _test_release_on_a_never_claimed_bar_is_a_safe_noop()
    _test_symmetric_handoff_matches_the_reported_priority_model()
    _test_pump_indeterminate_sets_mode_and_schedules_exactly_one_job()
    _test_pump_indeterminate_ticks_keep_a_single_job_alive()
    _test_pump_indeterminate_called_again_cancels_the_prior_loop()
    _test_stop_indeterminate_pump_cancels_and_is_idempotent()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
