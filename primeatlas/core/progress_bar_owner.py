"""
progress_bar_owner.py -- arbitrates writes to the one shared totals_progress bar
across every tab/coordinator that drives it: BaseTab's own busy-spinner helper (used
by PrimalityTab, PrimesieveCalcTab, ConstellationsRecordsTab, and every Research
sub-tab), TotalsSearchCoordinator (floor-totals scan and the Prime numbers/
Constellations search boxes), GenerationTab (every run engine), and
ResearchGoldbachTab's own worker-progress callback.

The bug this fixes: with no coordination between these independent writers, whichever
one's next Tk poll tick happened to call .configure() LAST silently overwrote
whatever any other writer had just shown -- e.g. a constellation search's own bar
could sit frozen near-empty (or full, from a leftover previous state) even while its
own status TEXT correctly reported it 99%+ done, because a floor-totals scan or a
search-box lookup had claimed the widget in the meantime.

First writer to claim() an owner token wins and keeps exclusive write access until
that SAME owner calls release() -- every other owner's claim() calls return False
meanwhile, so the caller should skip its own write for that tick; its own state
tracking still runs normally in the background, it just doesn't get painted onto the
widget. Once released, the bar is up for grabs again -- whichever owner's own next
regular poll tick calls claim() first reclaims it and repaints with ITS current
state, since every writer here already polls itself on a short Tk after() timer
(~100-150ms) regardless of who currently owns the widget. No explicit hand-off
notification between owners is needed because of that.

`owner` is any hashable, stable-identity token -- in practice always the calling tab/
coordinator instance itself (`self`), since Python object identity already gives each
one a natural, unique token with no extra bookkeeping.
"""

_OWNER_ATTR = "_pa_progress_owner"


def claim_progress_bar(widget, owner):
    """True if `owner` may write to `widget` right now -- either nobody currently
    owns it, or `owner` already does -- and, as a side effect, marks `owner` as the
    current holder in the former case. False means some OTHER owner currently holds
    it; the caller should skip its own write this tick rather than call .configure()."""
    current = getattr(widget, _OWNER_ATTR, None)
    if current is None or current is owner:
        setattr(widget, _OWNER_ATTR, owner)
        return True
    return False


def owns_progress_bar(widget, owner):
    """True if `owner` currently holds the claim on `widget`. Use this (never
    claim_progress_bar, which would happily grab a FREE bar) before a "run just
    finished, reset to my own final state" write that should only happen if this
    owner is the one who's actually been painting it."""
    return getattr(widget, _OWNER_ATTR, None) is owner


def release_progress_bar(widget, owner):
    """Releases `owner`'s claim on `widget`, if it currently holds one -- a safe
    no-op (never raises, never clears someone ELSE's claim) if it doesn't, so callers
    can call this unconditionally on every "finished" path without checking first."""
    if getattr(widget, _OWNER_ATTR, None) is owner:
        setattr(widget, _OWNER_ATTR, None)
