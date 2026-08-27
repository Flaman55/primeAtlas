"""
primes_tree_coordinator.py -- PrimesTreeCoordinator, the background floor-list scan/
reload logic for the "Prime numbers" tab's own tree, that used to live directly on
PortalBrowserApp itself in prime_atlas_v1.py (_primes_tree_scan/reload_primes_tree/
_on_primes_tree_scan_done).

Extracted on the refactor-phase3 branch (2026-08-27), continuing the same "God object"
reduction TotalsSearchCoordinator started on refactor-phase2 (task #410, 2026-08-26;
see that module's own docstring and README.md's "GUI module conventions" -> "Known
gaps" section) -- these three methods were pure cross-cutting orchestration
(background disk scan + tree/cache resync), not tab composition, so they move out the
same way the two PersistentWorkers already did.

Same dependency-injection shape as TotalsSearchCoordinator -- constructed once in
PortalBrowserApp.__init__, at the same point TotalsSearchCoordinator already is
(AFTER every tab widget exists, since _on_scan_done reaches directly into
primes_tab_widget and totals_search). PortalBrowserApp keeps reload_primes_tree as a
ONE-LINE delegating method (`self._primes_tree_coord.reload()`) -- every other caller
in this codebase (PrimesTab, GenerationTab, _set_portal_folder, the startup kickoff in
__init__) already only ever calls self.reload_primes_tree() and never touches the
scan/done internals directly, so that's the only seam that needs to keep existing
callers working unchanged; being a plain class method (not an instance attribute
assigned in __init__), it also works correctly even if something captures
self.reload_primes_tree as a callable BEFORE self._primes_tree_coord itself is built
(late-bound at call time, same reasoning the original inline version relied on).

What stays on PortalBrowserApp instead of moving here: the loading-screen completion
check (_loading_startup_pending/_finish_loading_screen) is genuinely shared with
ConstellationsTreeCoordinator (both trees must finish their OWN startup scan before
the loading screen goes away) -- rather than duplicate that shared-set bookkeeping in
two coordinator classes (or have one coordinator reach into the other's internals),
this class reports its own startup completion back through a single injected
on_startup_scan_done() callable, the same seam TotalsSearchCoordinator uses for its
own on_const_search_result constructor parameter.
"""
from . import background
from .benchmark import read_benchmark_log
from .storage import (
    aggregate_write_seconds_by_pietro, list_pietra, list_source_filenames,
    load_totals_cache,
)


class PrimesTreeCoordinator:
    def __init__(self, root, get_portal_folder, status_var, translator,
                 primes_tab_widget, totals_search, prune_empty_pietro_dirs,
                 on_startup_scan_done=None):
        """
        root: the live Tk widget background.run_in_background() schedules its .after()
        polling on -- always the app's own root window in practice.

        get_portal_folder/status_var/translator: same dependency-injection pattern as
        every tab class -- see primeatlas/primes_tab.py's own docstring.

        primes_tab_widget/totals_search: direct references (not lazy getters), safe
        because -- by construction order in prime_atlas_v1.py's __init__ -- both
        already exist by the time this class is built (same guarantee
        TotalsSearchCoordinator's own docstring relies on for its own two tab-widget
        constructor arguments).

        prune_empty_pietro_dirs: passed in rather than imported directly here because
        its real home is primeatlas/restore_job.py (re-exported at the primeatlas
        package's own top level) -- passing it through avoids this module needing to
        know that historical detail, matching how prime_atlas_v1.py itself imports it.

        on_startup_scan_done(name): fired once per completed scan with a fixed string
        ("primes") identifying which tree just finished -- PortalBrowserApp uses this
        to discard from its own _loading_startup_pending set and call
        _finish_loading_screen() once both trees (this one and
        ConstellationsTreeCoordinator's own) are done. Safe to omit (defaults to
        None) -- ordinary Refresh-button reloads after startup have nothing meaningful
        to report here, so this class only calls it if the caller actually supplied
        one.
        """
        self._root = root
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self.T = translator.t
        self._primes_tab_widget = primes_tab_widget
        self._totals_search = totals_search
        self._prune_empty_pietro_dirs = prune_empty_pietro_dirs
        self._on_startup_scan_done = on_startup_scan_done

        self._busy = False
        self._pending = False

    def _scan(self, portal_folder, _report_progress):
        """Runs OFF the GUI thread -- every line here is pure disk I/O with no widget
        access, ported unchanged from the original inline _primes_tree_scan(). Returns
        a plain dict; _on_scan_done does all the actual tree/widget mutation back on
        the main thread. portal_folder is passed in explicitly (captured by reload()
        at dispatch time) rather than re-read from get_portal_folder() in here, so a
        storage-path change that happens WHILE this scan is running can never make it
        silently scan the wrong (newly-current) location.

        prune_empty_pietro_dirs() runs unconditionally on every reload, floors with no
        PRIME_WINDOW_*.bin files are filtered out, and the totals caches are reloaded
        fresh from disk every time rather than only once at startup -- see the
        original method's own (now relocated) docstring for the full rationale."""
        self._prune_empty_pietro_dirs(portal_folder)
        pietro_total_known = {}
        for _key, _entry in load_totals_cache(portal_folder).items():
            if _key.startswith("10p") and _key[3:].isdigit():
                pietro_total_known[int(_key[3:])] = (
                    _entry.get("total", 0), _entry.get("file_count", 0),
                    _entry.get("total_bytes", 0))
        totals_cache = load_totals_cache(portal_folder)  # worker-owned copy
        pietro_gen_seconds = aggregate_write_seconds_by_pietro(
            read_benchmark_log(portal_folder)[1])
        pietra = [be for be in list_pietra(portal_folder)
                  if list_source_filenames(portal_folder, be)]
        return {
            "pietro_total_known": pietro_total_known,
            "totals_cache": totals_cache,
            "pietro_gen_seconds": pietro_gen_seconds,
            "pietra": pietra,
        }

    def reload(self):
        """Rebuilds the floor list from disk (picks up newly created/removed 10pN
        folders) AND re-runs the totals scan for every floor -- so pressing Refresh
        after generating new windows is enough to see updated totals, no separate
        button needed. Each floor's total is cached (see
        update_pietro_totals_cache()'s own docstring), so a floor with no new files
        costs one cheap os.listdir() + an in-memory set diff.

        The actual disk scan (_scan) runs on background.run_in_background() -- this
        method just dispatches it and returns immediately; _on_scan_done does the real
        tree-population work once the scan comes back. A busy/pending pair of flags
        coalesces re-entrant calls (e.g. the user mashing Refresh, or a
        generation-finished callback firing while a Refresh is still in flight) into
        at most one extra rerun after the in-flight scan settles, rather than spawning
        a second overlapping scan thread. portal_folder is captured HERE, at dispatch
        time, and compared again in _on_scan_done -- if a storage-path change rebound
        it while this scan was still running, the result is discarded and a fresh scan
        against the NEW folder is queued instead."""
        if self._busy:
            self._pending = True
            return
        self._busy = True
        portal_folder = self._get_portal_folder()
        background.run_in_background(
            self._root, lambda report_progress: self._scan(portal_folder, report_progress),
            on_done=lambda result, error: self._on_scan_done(portal_folder, result, error))

    def _on_scan_done(self, portal_folder, result, error):
        """Main-thread callback for _scan -- see reload()'s own docstring for the
        busy/pending/staleness handling this implements."""
        self._busy = False
        stale = portal_folder != self._get_portal_folder()
        if self._pending or stale:
            self._pending = False
            self.reload()
            return
        if error is not None:
            self.status.set(self.T("primes.status_reload_error", error=str(error)))
            return
        self._totals_search.replace_totals_cache(result["totals_cache"])
        pietra = result["pietra"]
        # The actual tree rebuild (rows, per-floor known totals/gen-seconds display
        # state) is owned by PrimesTab -- see populate_floors()'s own docstring. This
        # coordinator keeps only the totals_cache resync (owned by
        # TotalsSearchCoordinator, unrelated to what any one tab renders), the status
        # text, kicking off the background totals scan, and reporting startup
        # completion.
        self._primes_tab_widget.populate_floors(
            pietra, result["pietro_total_known"], result["pietro_gen_seconds"])
        self.status.set(self.T("app.status_portal_with_count", folder=portal_folder,
                                count=len(pietra)))
        self._totals_search.compute_all_pietro_totals()

        if self._on_startup_scan_done is not None:
            self._on_startup_scan_done("primes")
