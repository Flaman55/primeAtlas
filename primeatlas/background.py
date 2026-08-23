"""
background.py -- one small, reusable way to run a slow function off the Tk main thread
and get its result (or an error) back safely, instead of hand-rolling a fresh
thread+queue+self.after()-poll block per feature.

Why this exists (refactor branch, Faza 1, 2026-08-23): an audit of prime_atlas_v1.py and
primeatlas/settings_tab.py found SIX independently-duplicated persistent worker-thread
patterns (totals/search/primesieve_calc/primality/goldbach/const_records -- one
threading.Thread + two queue.Queue + one self.after(150, poll) block each, all doing the
same thing with different payload shapes) plus several settings_tab.py functions that
did comparably slow full-storage-tree scans SYNCHRONOUSLY on the GUI thread with no
threading at all (_on_check_diff, _on_preview_storage_integrate, and the refresh
functions for the backup/full-backup/floor-delete lists) -- freezing the whole window
for however long those scans took, inconsistently with the properly-backgrounded
actions right next to them. See task history around 2026-08-23 for the full audit.

Design: exactly one moving part, run_in_background(). No class to instantiate, no
worker thread kept alive across calls -- a fresh daemon thread per call is simpler to
reason about than a persistent worker+queue, and matches how roughly half of this
project's existing patterns already worked (settings_tab.py's backup/restore/storage-
integrate EXECUTION workers, as opposed to their un-backgrounded preview/plan steps).
Threads are cheap enough at this project's real call frequency (occasional,
few-hundred-ms-to-few-minute jobs triggered by a click or a periodic scan -- not
thousands of jobs per second) that spawning one per call costs nothing worth optimizing
away with a persistent pool.
"""
import queue
import threading


def run_in_background(widget, fn, *, on_done=None, on_progress=None, poll_ms=100):
    """Runs fn(report_progress) on a new daemon thread; polls for its outcome via
    widget.after(poll_ms, ...) and delivers everything back on the MAIN thread.

    fn receives exactly one positional argument: report_progress, a callable it may
    invoke any number of times with any single payload (a string, a dict, a tuple --
    whatever on_progress expects) to report incremental progress. Each call is
    delivered, in order, to on_progress(payload) on the main thread. A caller with an
    existing plain function that takes no such argument should wrap it in a lambda,
    e.g. `run_in_background(self, lambda report_progress: si.plan_integration(a, b),
    on_done=...)` -- report_progress simply goes unused in that case.

    When fn returns normally, on_done(result, None) fires on the main thread exactly
    once. If fn raises, on_done(None, exception) fires instead -- fn's own exception
    never escapes onto the worker thread silently; every caller gets a chance to show
    it to the user (or log it) rather than losing it into a daemon thread's traceback
    that nothing ever reads.

    widget: any live Tk widget whose .after() method should drive the polling --
    typically the app's root window, but a Toplevel that owns its own one-shot job
    works identically, since this function holds no state of its own beyond the local
    closures below (no shared/global registry to leak into).

    Cancellation is deliberately NOT handled here: some jobs are safely resumable
    mid-way (checked via a threading.Event inside fn's own loop, exactly like the
    existing backup/restore/storage-integrate workers already do) and some aren't --
    baking one specific policy into this shared helper would fight at least one real
    caller. Build cancellation into fn itself (accept a stop_event as one of the extra
    arguments in your lambda/closure) exactly as those existing workers already do.

    Returns the queue.Queue used internally. Callers don't normally need it -- it's
    exposed so tests can drain it directly without a live Tk event loop."""
    result_queue = queue.Queue()

    def report_progress(payload):
        result_queue.put(("progress", payload))

    def worker():
        try:
            result = fn(report_progress)
        except Exception as exc:  # noqa: BLE001 -- must reach on_done, never die silently
            result_queue.put(("error", exc))
        else:
            result_queue.put(("result", result))

    threading.Thread(target=worker, daemon=True).start()

    def poll():
        try:
            while True:
                kind, payload = result_queue.get_nowait()
                if kind == "progress":
                    if on_progress is not None:
                        on_progress(payload)
                elif kind == "result":
                    if on_done is not None:
                        on_done(payload, None)
                    return  # job finished -- stop polling
                elif kind == "error":
                    if on_done is not None:
                        on_done(None, payload)
                    return
        except queue.Empty:
            pass
        widget.after(poll_ms, poll)

    widget.after(poll_ms, poll)
    return result_queue
