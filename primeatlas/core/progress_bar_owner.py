"""
progress_bar_owner.py -- arbitrates writes to the one shared totals_progress bar
across every tab/coordinator that drives it: BaseTab's own busy-spinner helper (used
by PrimalityTab, PrimesieveCalcTab, ConstellationsRecordsTab, and every Research
sub-tab), TotalsSearchCoordinator (floor-totals scan and the Prime numbers/
Constellations search boxes), GenerationTab (every run engine), and
ResearchGoldbachTab's own worker-progress callback.

Without coordination between these independent writers, whichever one's next Tk poll
tick calls .configure() LAST overwrites whatever another writer just showed -- e.g. a
constellation search's bar frozen near-empty while its status TEXT reports 99%+ done,
because a floor-totals scan or a search-box lookup claimed the widget meanwhile.

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


_PUMP_JOB_ATTR = "_pa_progress_pump_job"


def pump_indeterminate(widget, interval_ms):
    """Drives `widget`'s indeterminate-mode thumb via our OWN repeated .step() calls
    on a single self-owned .after() loop, instead of Progressbar.start()'s own
    internal Tcl-level repeating timer.

    Why: this widget is `totals_progress`, reused by roughly a dozen independent call
    sites (search, every BaseTab subclass's busy spinner, generation, the
    records-table export, the Goldbach worker -- see this module's docstring), each
    calling .stop()/.start() on the SAME long-lived widget many times over a session.
    With ttk's own timer the thumb snaps between the two extreme ends instead of
    gliding, independent of the .start(ms) interval -- the known ttk::progressbar
    footgun where .stop() doesn't reliably cancel a PRIOR .start()'s pending
    Tcl-level after-callback, leaving several phase-advance loops nudging the same
    widget. Driving the animation ourselves avoids that: at most ONE of our own
    .after() jobs is ever scheduled (the job id is stored ON the widget, like
    _OWNER_ATTR above, so a second call always cancels the first), and ttk's
    .start()/.stop() is never invoked. mode="indeterminate" is still set (that's what
    makes .step() move a small bouncing thumb instead of filling a determinate bar) --
    only the TIMER driving each step is ours instead of Tcl's."""
    stop_indeterminate_pump(widget)
    widget.configure(mode="indeterminate")

    def _tick():
        widget.step()
        job_id = widget.after(interval_ms, _tick)
        setattr(widget, _PUMP_JOB_ATTR, job_id)

    _tick()


def stop_indeterminate_pump(widget):
    """Cancels a pump_indeterminate() loop started on `widget`, if one is currently
    running -- a safe no-op otherwise. Callers switching `widget` away from
    indeterminate mode (to a real determinate value, or back to the empty resting
    state) MUST call this first: pump_indeterminate() never calls Tcl's own
    Progressbar.stop(), so nothing else would ever cancel our own .after() loop --
    left running, it would keep calling .step() indefinitely and corrupt whatever
    determinate value/mode the caller sets right after."""
    job_id = getattr(widget, _PUMP_JOB_ATTR, None)
    if job_id is not None:
        widget.after_cancel(job_id)
        setattr(widget, _PUMP_JOB_ATTR, None)
