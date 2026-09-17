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


def main():
    _test_first_claim_wins()
    _test_second_claimant_blocked_while_first_holds_it()
    _test_same_owner_reclaiming_is_idempotent()
    _test_release_frees_the_bar_for_anyone()
    _test_release_by_non_owner_is_a_safe_noop()
    _test_release_on_a_never_claimed_bar_is_a_safe_noop()
    _test_symmetric_handoff_matches_the_reported_priority_model()

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
