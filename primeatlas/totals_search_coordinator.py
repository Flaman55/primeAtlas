"""
totals_search_coordinator.py -- TotalsSearchCoordinator, the two PersistentWorkers
(floor-totals scanning, prime/constellation search) that used to live directly on
PortalBrowserApp itself in prime_atlas_v1.py.

Extracted on the refactor-phase2 branch (2026-08-26, the "God object" reduction named
as a "Known gap" in README.md's own "GUI module conventions" section) -- Faza 3
(2026-08-23) had already pulled every TAB's own widgets/logic out of
PortalBrowserApp, but PortalBrowserApp itself was still left owning two genuinely
CROSS-tab background workers directly: the floor-totals cache (shared by the Prime
numbers tab's tree AND the Benchmark tab's grand-total line) and the prime/
constellation search worker (shared by the Prime numbers AND Constellations tabs'
search boxes, since only one search should ever run at a time system-wide -- see
_start_search_job's own docstring below for why they share one worker/one progress
bar rather than getting one each).

Same dependency-injection shape as every extracted tab (see primeatlas/primes_tab.py's
own docstring for the general pattern this package follows) -- this class is
constructed once, in PortalBrowserApp.__init__, AFTER every tab widget already exists
(same construction-order requirement the original inline code had: it reaches directly
into primes_tab_widget/constellations_hits_tab_widget rather than through a lazy
getter, since by the time this class is built those two already exist -- see
prime_atlas_v1.py's own __init__ for the exact point).

What stays on PortalBrowserApp instead of moving here: _offer_generate_missing_prime_
window/_offer_generate_missing_constellation/_on_const_search_result (the "reverse-
coupling glue" methods -- see README's own "Known gaps" paragraph) genuinely
coordinate THREE tabs at once (Prime numbers/Constellations-hits/Constellations-calc)
plus the Generation tab's launch machinery, not just the two-worker mechanism this
class owns; on_const_search_result below is the one deliberate seam between the two --
this class reports a finished "const" search back through that single injected
callable instead of reaching for a Constellations-calc-tab reference of its own.
"""
import time
from tkinter import messagebox

from . import floor_meta
from .background import PersistentWorker
from .constellations import find_constellation_participation
from .storage import (
    find_prime_in_floor, format_bytes, format_duration, load_totals_cache,
    save_totals_cache, update_pietro_totals_cache,
)


class TotalsSearchCoordinator:
    def __init__(self, root, get_portal_folder, status_var, totals_progress, translator,
                 primes_tab_widget, constellations_hits_tab_widget, on_const_search_result):
        """
        root: the live Tk widget whose .after() drives both PersistentWorkers' polling
        -- always the app's own root window in practice (PersistentWorker itself only
        ever calls .after() on it, see background.py's own docstring).

        get_portal_folder/status_var/totals_progress/translator: same dependency-
        injection pattern as every tab class -- see primeatlas/primes_tab.py's own
        docstring. totals_progress is genuinely SHARED with the search worker below
        (one progress bar for both features, see _start_search_job's own docstring),
        not one per worker.

        primes_tab_widget/constellations_hits_tab_widget: direct references (not lazy
        getters) to two tab widgets this coordinator updates directly
        (update_floor_row/get_gen_seconds/get_pietro_node_keys on the first,
        hits_search_button/on_prime_search_result on... actually on_prime_search_result
        is the Primes tab's own; the hits tab only lends its search button and hit_set_
        cache) -- safe to take directly rather than via a callable because, by
        construction order in prime_atlas_v1.py's __init__, both tab widgets already
        exist by the time this class is built (all six tabs are built before this).

        on_const_search_result(base_exponent, number, prime_result, participation):
        the one callback this class does NOT resolve itself -- a finished "const"
        search job is genuine three-tab coordination (Constellations-hits AND
        Constellations-calc, see this module's own docstring), so it stays at the app
        level; this class just reports the raw result back once its own worker
        mechanics are done with it.
        """
        self._root = root
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self.totals_progress = totals_progress
        self.T = translator.t
        self._primes_tab_widget = primes_tab_widget
        self._constellations_hits_tab_widget = constellations_hits_tab_widget
        self._on_const_search_result = on_const_search_result

        self._totals_cache = {}
        self._reload_totals_caches()
        self._computing_all_totals = False
        self._totals_batch_size = 0
        self._grand_total_sum = 0
        self._grand_total_bytes = 0
        self._grand_total_seen = set()
        self._grand_total_seconds = 0.0
        self._totals_worker = PersistentWorker(
            root, self._totals_job, on_result=self._on_totals_worker_result,
            on_progress=self._on_pietro_total_start)

        # Status-bar race fix (task #404, real bug -- a floor-totals job submitted
        # BEFORE a search starts can still be sitting in the totals worker's queue
        # when the search finishes; without this, its eventual completion overwrites
        # the just-shown search RESULT with a stale "grand total"/"computing X"
        # message the instant it lands, even though the user is looking at (and asked
        # for) the search result specifically.
        #
        # Two independent mechanisms, for two different kinds of totals status write:
        #
        # 1. _totals_batch_suppressed guards the BULK "compute all floors" batch
        #    (compute_all_pietro_totals(), triggered automatically after every
        #    reload/Refresh) -- see that method's own docstring and start_search_job's.
        #    A timestamp-based check here turned out NOT to be reliable in practice
        #    (2026-08-26): reload_primes_tree() coalesces re-entrant calls (see its own
        #    docstring in prime_atlas_v1.py) into a chain that can settle at an
        #    unpredictable moment relative to a search that started in the meantime --
        #    by the time compute_all_pietro_totals() actually SUBMITS its jobs, that
        #    submit time can legitimately land AFTER the search's own start/finish
        #    timestamps even though the whole reload chain was set in motion BEFORE the
        #    search, which a per-job submit-time comparison can't tell apart from a
        #    genuinely fresh, unrelated batch. A single flag, set the instant a search
        #    starts while this exact batch is either already running OR just about to
        #    start, sidesteps the whole timing question: it's checked and set
        #    synchronously on the GUI thread, so it doesn't itself depend on the
        #    relative order two background threads' results get drained in.
        #
        # 2. _totals_submit_time/_last_search_activity_time (the ORIGINAL, still-used
        #    mechanism) guards the single ad-hoc per-floor case (_on_tree_open
        #    expanding one node) -- a deliberate, single fresh click, for which the
        #    simpler "did this job predate the last search" comparison is adequate
        #    (that submission is never delayed through the multi-hop coalescing chain
        #    the bulk batch goes through).
        self._totals_batch_suppressed = False
        self._totals_submit_time = {}
        self._last_search_activity_time = 0.0

        self._search_busy = False
        self._search_worker = PersistentWorker(
            root, self._search_job, on_result=self._on_search_worker_result,
            on_progress=self._on_search_worker_progress)

    @property
    def search_busy(self):
        return self._search_busy

    # --- Floor-total background worker ------------------------------------------

    def _reload_totals_caches(self):
        """(Re-)loads _totals_cache (the totals worker's OWN incremental-cache copy,
        see update_pietro_totals_cache()) from the current portal folder's own
        .portal_totals_cache.json. See this class's own construction-order comment for
        why the app only ever calls this once, at construction time -- a later
        storage-path change self-heals through _on_primes_tree_scan_done's own fresh
        read instead (prime_atlas_v1.py's reload_primes_tree() docstring)."""
        self._totals_cache = load_totals_cache(self._get_portal_folder())

    def replace_totals_cache(self, new_cache):
        """Swaps in a freshly-read totals_cache dict wholesale -- called from
        prime_atlas_v1.py's _on_primes_tree_scan_done() with the copy its OWN
        background scan (_primes_tree_scan) already read fresh from disk via
        load_totals_cache(), so the totals worker's in-memory copy self-heals after a
        storage-path change or an ordinary Refresh instead of only ever updating
        incrementally through _totals_job's own per-floor reads (see this class's own
        _reload_totals_caches docstring for the self-healing rationale -- this method
        is the actual mechanism that makes it true, not just a nice-to-have)."""
        self._totals_cache = new_cache

    def submit_totals_job(self, base_exponent):
        """Thin public wrapper around the totals worker's own submit() -- PrimesTab
        receives this directly as its own submit_totals_job callable (see that class's
        own docstring), same injection shape it already used when this lived inline on
        PortalBrowserApp. Records the submit time first (see __init__'s own comment on
        _totals_submit_time/_last_search_activity_time -- task #404's status-bar race
        fix) -- compute_all_pietro_totals() below routes its own per-floor submits
        through here too, rather than calling _totals_worker.submit() a second way, so
        every totals job gets this timestamp regardless of which path triggered it."""
        self._totals_submit_time[base_exponent] = time.monotonic()
        self._totals_worker.submit(base_exponent)

    def _totals_job(self, base_exponent, report_progress):
        """Runs on PersistentWorker's own daemon thread, one base_exponent at a time.
        report_progress(base_exponent) fires the INSTANT this request is picked up,
        before the (possibly ~1 minute, for a heavily-populated floor) scan itself
        runs -- without this, the status/progress bar would sit unchanged for that
        whole stretch, making an in-progress scan look like it's not working. Catches
        its own exceptions (rather than letting PersistentWorker's generic error path
        handle it) so the failure can still be attributed to the RIGHT base_exponent."""
        report_progress(base_exponent)
        portal_folder = self._get_portal_folder()
        try:
            total, file_count, new_read, total_bytes = update_pietro_totals_cache(
                portal_folder, base_exponent, self._totals_cache)
            if new_read:
                save_totals_cache(portal_folder, self._totals_cache)
            # A floor physically copied in from another storage (magazyn) brings its
            # own floor_meta.json along -- see floor_meta.py's module docstring. This
            # imports any rows from it that aren't already in the LOCAL
            # benchmark_log.csv, so the Benchmark tab shows that floor's real
            # generation history instead of nothing, exactly as if it had been
            # generated here.
            floor_meta.merge_floor_meta_into_benchmark_log(portal_folder, base_exponent)
            return base_exponent, total, file_count, new_read, None, total_bytes
        except Exception as e:  # noqa: BLE001 -- must never kill the worker thread
            return base_exponent, None, None, None, str(e), None

    def _on_totals_worker_result(self, payload, error):
        """Main-thread callback for _totals_job -- error is only ever non-None for a
        genuine PersistentWorker/framework-level failure (report_progress itself
        raising, say), since _totals_job catches everything else internally and folds
        it into payload's own error slot instead."""
        if error is not None:
            self.status.set(str(error))
            return
        base_exponent, total, file_count, new_read, job_error, total_bytes = payload
        if job_error is not None:
            self.status.set(self.T("primes.status_error_sum", base_exponent=base_exponent,
                                    error=job_error))
        else:
            self._on_pietro_total_ready(base_exponent, total, file_count, new_read, total_bytes)

    def _on_pietro_total_start(self, base_exponent):
        """Fires the moment the worker PICKS UP a request -- see _totals_job's
        docstring for why this exists separately from the completion handler below.
        Skips the status-bar write (but nothing else -- there IS nothing else here)
        per the two mechanisms described in __init__'s own comment (task #404's
        status-bar race fix): _totals_batch_suppressed for the bulk "compute all"
        batch, _totals_status_write_allowed for a single ad-hoc floor request."""
        if self._computing_all_totals:
            if self._totals_batch_suppressed:
                return
            done = len(self._grand_total_seen)
            self.status.set(
                self.T("primes.status_computing_progress", base_exponent=base_exponent,
                       done=done, total=self._totals_batch_size,
                       sum=f"{self._grand_total_sum:,}"))
        else:
            if not self._totals_status_write_allowed(base_exponent):
                return
            self.status.set(self.T("primes.status_computing", base_exponent=base_exponent))

    def _totals_status_write_allowed(self, base_exponent):
        """Guards the single AD-HOC per-floor totals request (_on_tree_open expanding
        one node) -- see __init__'s own comment for why the BULK "compute all" batch
        uses the separate _totals_batch_suppressed flag instead. True unless a search
        has started or finished more recently than this base_exponent's own totals
        job was submitted. Looked up rather than popped here -- the entry itself is
        only removed once the job actually completes, in _on_pietro_total_ready,
        since _on_pietro_total_start (this method's only other caller) fires once per
        job but isn't the last word on it.

        The plain `self._search_busy` check closes a narrower version of the same gap
        _totals_batch_suppressed exists for: a totals job submitted WHILE a search is
        already running has a submit time after the search's own start bump, so the
        timestamp comparison alone would let it through if its completion callback
        happens to be delivered in the same (or an earlier) Tk polling tick as the
        search's own result."""
        if self._search_busy:
            return False
        submit_time = self._totals_submit_time.get(base_exponent, 0.0)
        return submit_time >= self._last_search_activity_time

    def _on_pietro_total_ready(self, base_exponent, total, file_count, new_read, total_bytes):
        """Main-thread completion handler for the totals worker's result -- the actual
        tree-row update, plus the floor-nav page-total label refresh if this floor
        happens to be the active one, is delegated to PrimesTab.update_floor_row (see
        that method's own docstring); this class keeps only the grand-total batch
        bookkeeping and status/progress-bar text, which don't belong to any one tab.

        The status-bar TEXT write is skipped -- via _totals_batch_suppressed for the
        bulk batch branch, _totals_status_write_allowed for the single ad-hoc
        branch -- if this job predates/was interrupted by the most recent search
        activity (task #404's status-bar race fix, see __init__'s own comment). The
        tree-row update, grand-total accumulation, and progress-bar VALUE above still
        always run regardless, since those aren't shared/contested UI and skipping
        them would leave the totals cache/tree silently out of date."""
        self._primes_tab_widget.update_floor_row(base_exponent, total, file_count, total_bytes)
        gen_seconds = self._primes_tab_widget.get_gen_seconds(base_exponent)

        if self._computing_all_totals:
            allow_status_write = not self._totals_batch_suppressed
            if base_exponent not in self._grand_total_seen:
                self._grand_total_seen.add(base_exponent)
                self._grand_total_sum += total
                self._grand_total_seconds += gen_seconds or 0.0
                self._grand_total_bytes += total_bytes or 0
            done = len(self._grand_total_seen)
            expected = self._totals_batch_size
            self.totals_progress.configure(value=done)
            if done >= expected:
                self._computing_all_totals = False
                # Reset back to the same empty (0/1) state totals_progress starts in --
                # left at full/expected otherwise, a completed scan would leave the bar
                # sitting permanently full, which reads as "still busy" even though
                # nothing is running.
                self.totals_progress.configure(maximum=1, value=0)
                if allow_status_write:
                    self.status.set(
                        self.T("primes.status_grand_total", count=expected,
                               sum=f"{self._grand_total_sum:,}",
                               duration=format_duration(self._grand_total_seconds),
                               size=format_bytes(self._grand_total_bytes)))
            elif allow_status_write:
                self.status.set(
                    self.T("primes.status_partial_totals", done=done, total=expected,
                           sum=f"{self._grand_total_sum:,}",
                           size=format_bytes(self._grand_total_bytes)))
        else:
            allow_status_write = self._totals_status_write_allowed(base_exponent)
            self._totals_submit_time.pop(base_exponent, None)
            if allow_status_write:
                extra = self.T("primes.status_extra_new_files", count=new_read) if new_read else ""
                self.status.set(
                    self.T("primes.status_pietro_total", base_exponent=base_exponent,
                           total=f"{total:,}", files=f"{file_count:,}",
                           size=format_bytes(total_bytes), extra=extra))

    def compute_all_pietro_totals(self):
        """Kicks off the bulk "every floor's total" batch -- called automatically
        after every reload_primes_tree()/Refresh (see prime_atlas_v1.py's
        _on_primes_tree_scan_done), not a direct user click on any one floor.

        _totals_batch_suppressed is seeded from _search_busy right here: even though
        reload_primes_tree()'s own coalescing chain (see that method's docstring)
        means THIS exact call can be the delayed tail end of a reload originally
        triggered before any search even started, if a search happens to ALREADY be
        in flight by the time this batch actually begins, its messages should never
        have been shown in the first place -- there's no earlier point to have caught
        that. start_search_job() below handles the opposite ordering (a batch already
        running when a NEW search starts) by flipping this same flag retroactively
        (task #404's status-bar race fix, see __init__'s own comment)."""
        pietra = self._primes_tab_widget.get_pietro_node_keys()
        if not pietra:
            self.status.set(self.T("primes.status_none_to_compute"))
            return
        self._computing_all_totals = True
        self._totals_batch_suppressed = self._search_busy
        self._totals_batch_size = len(pietra)
        self._grand_total_sum = 0
        self._grand_total_seconds = 0.0
        self._grand_total_bytes = 0
        self._grand_total_seen = set()
        self.totals_progress.configure(maximum=len(pietra), value=0)
        self.status.set(self.T("primes.status_batch_start", count=len(pietra)))
        for base_exponent in pietra:
            self.submit_totals_job(base_exponent)

    # --- Search worker -- shared by both "Prime numbers" and "Constellations" search
    # boxes: the two features share one worker thread and one status/progress bar, so
    # only one search runs at a time system-wide -- disabling BOTH search buttons
    # while a job is in flight (see _start_search_job below) is what enforces that. --

    def start_search_job(self, kind, base_exponent, number):
        """Hands the actual (potentially slow) file-scanning work off to this
        coordinator's own search worker thread. Only fast/instant validation
        (isdigit, digit_count_floor, list_pietra's no-I/O floor-existence check)
        happens on the GUI thread, in the caller, before this is ever reached.

        Bumps _last_search_activity_time first, and -- if the bulk "compute all"
        batch happens to be running right now -- flips _totals_batch_suppressed too
        (see __init__'s own comment for why the batch needs its own separate flag
        rather than reusing the timestamp check here; task #404's status-bar race
        fix): any totals job already sitting in the queue at this instant was
        necessarily submitted BEFORE this timestamp, so its eventual completion
        message is suppressed rather than clobbering this search's own status text."""
        self._last_search_activity_time = time.monotonic()
        if self._computing_all_totals:
            self._totals_batch_suppressed = True
        self._search_busy = True
        self._primes_tab_widget.search_button.configure(state="disabled")
        self._constellations_hits_tab_widget.hits_search_button.configure(state="disabled")
        self.totals_progress.stop()
        self.totals_progress.configure(mode="indeterminate")
        self.totals_progress.start(80)
        if kind == "prime":
            self.status.set(self.T("primes.status_searching", number=number,
                                    base_exponent=base_exponent))
        else:
            self.status.set(self.T("const.status_searching", number=number,
                                    base_exponent=base_exponent))
        self._search_worker.submit(
            {"kind": kind, "base_exponent": base_exponent, "number": number})

    def _search_job(self, job, report_progress):
        """Runs on PersistentWorker's own daemon thread. While a "const" job is in
        flight, this thread is ALSO the sole owner of constellations_hits_tab_widget.
        hit_set_cache (the GUI thread never mutates it directly, only reads the
        finished participation list handed back via the result) -- search_busy
        blocking new searches from the GUI side means only one job is ever in flight,
        so this never races against itself."""
        kind = job["kind"]
        base_exponent = job["base_exponent"]
        number = job["number"]
        portal_folder = self._get_portal_folder()
        try:
            if kind == "prime":
                result = find_prime_in_floor(portal_folder, base_exponent, number)
                return ("prime_done", base_exponent, number, result)
            else:
                prime_result = find_prime_in_floor(portal_folder, base_exponent, number)
                if prime_result is None:
                    return ("const_done", base_exponent, number, None, [])

                def _progress(done, total):
                    report_progress(("const_progress", done, total))

                participation = find_constellation_participation(
                    portal_folder, base_exponent, number,
                    self._constellations_hits_tab_widget.hit_set_cache,
                    progress_callback=_progress)
                return ("const_done", base_exponent, number, prime_result, participation)
        except Exception as e:  # noqa: BLE001 -- must never kill the worker thread
            return (f"{kind}_error", base_exponent, number, str(e))

    def _on_search_worker_progress(self, payload):
        """Main-thread callback for _search_job's mid-job progress reports (the only
        kind it ever sends is "const_progress", during find_constellation_participation)."""
        kind = payload[0]
        if kind == "const_progress":
            _kind, done, total = payload
            self.totals_progress.stop()
            self.totals_progress.configure(
                mode="determinate", maximum=max(1, total), value=done)
            self.status.set(self.T("const.status_search_progress", done=done, total=total))

    def _on_search_worker_result(self, payload, error):
        """Main-thread callback for _search_job's return value -- error is only ever
        non-None for a genuine PersistentWorker/framework-level failure, since
        _search_job catches everything else internally (see that method's docstring)."""
        if error is not None:
            self._finish_search_job()
            messagebox.showerror(self.T("common.dialog_search_title"), str(error))
            return
        kind = payload[0]
        if kind == "prime_done":
            _kind, base_exponent, number, result = payload
            self._finish_search_job()
            self._primes_tab_widget.on_prime_search_result(base_exponent, number, result)
        elif kind == "const_done":
            _kind, base_exponent, number, prime_result, participation = payload
            self._finish_search_job()
            self._on_const_search_result(base_exponent, number, prime_result, participation)
        else:  # "prime_error" / "const_error"
            _kind, _base_exponent, _number, job_error = payload
            self._finish_search_job()
            messagebox.showerror(self.T("common.dialog_search_title"), job_error)

    def _finish_search_job(self):
        # Bumped again here (not just at start_search_job's own start) -- see
        # __init__'s own comment on _totals_submit_time/_last_search_activity_time
        # (task #404's status-bar race fix): this runs BEFORE the caller (_on_search_
        # worker_result) writes the actual found/not-found status text below, so any
        # totals job whose completion callback fires from this instant onward is
        # treated as "predating" this search and has its own status write suppressed
        # -- covering the case where a totals job was ALREADY in flight (submitted
        # before the search even started) and only finishes sometime after the search
        # itself already completed.
        self._last_search_activity_time = time.monotonic()
        self._search_busy = False
        self._primes_tab_widget.search_button.configure(state="normal")
        self._constellations_hits_tab_widget.hits_search_button.configure(state="normal")
        self.totals_progress.stop()
        # Same "reset back to the empty 0/1 state" reasoning as _on_pietro_total_
        # ready's grand-total completion branch -- a bar left sitting full/mid-way
        # reads as "still busy" even though nothing is running.
        self.totals_progress.configure(mode="determinate", maximum=1, value=0)
