"""
constellations_tree_coordinator.py -- ConstellationsTreeCoordinator, the background
floor-list scan/reload logic for the Constellations tab's own "Magazyn" hits tree,
that used to live directly on PortalBrowserApp itself in prime_atlas_v1.py
(_constellations_tree_scan/reload_constellations_tree/_on_hits_tree_scan_done).

Extracted on the refactor-phase3 branch (2026-08-27), the direct sibling of
primeatlas/primes_tree_coordinator.py's own PrimesTreeCoordinator (see that module's
docstring for the full "God object" reduction lineage -- TotalsSearchCoordinator on
refactor-phase2, task #410, 2026-08-26). Same shape, same reasoning, just for the
OTHER tree: this tab's own Refresh button can run without reload_primes_tree() ever
running in the same gesture (e.g. right after constellation-finding finishes), so its
own prune/scan is dispatched independently rather than piggy-backing on the other
tree's refresh.

Same dependency-injection shape as PrimesTreeCoordinator -- constructed once in
PortalBrowserApp.__init__, at the same point TotalsSearchCoordinator/
PrimesTreeCoordinator already are (AFTER every tab widget exists, since _on_scan_done
reaches directly into constellations_hits_tab_widget). PortalBrowserApp keeps
reload_constellations_tree as a ONE-LINE delegating method
(`self._constellations_tree_coord.reload()`) for the same "existing callers keep
working unchanged, late-bound class method" reasons PrimesTreeCoordinator's own
docstring explains for reload_primes_tree.

What stays on PortalBrowserApp instead of moving here: the loading-screen completion
check (_loading_startup_pending/_finish_loading_screen), reported back through the
same on_startup_scan_done() seam PrimesTreeCoordinator uses (this class just passes
"constellations" instead of "primes"). _select_constellations_hits_view/
_jump_records_detail_to_hits/_on_const_search_result stay on PortalBrowserApp too --
none of them are part of the tree-scan/reload mechanism this class owns; they're
genuine multi-tab coordination glue (Magazyn <-> Kalkulator konstelacji <-> Tabela
rekordow), the same category of method TotalsSearchCoordinator's own docstring
already explains stays at the app level.
"""
from . import background
from .constellations import floor_has_constellation_hits
from .storage import list_pietra


class ConstellationsTreeCoordinator:
    def __init__(self, root, get_portal_folder, status_var, translator,
                 constellations_hits_tab_widget, prune_empty_pietro_dirs,
                 on_startup_scan_done=None):
        """
        root/get_portal_folder/status_var/translator: same dependency-injection
        pattern as PrimesTreeCoordinator -- see that class's own docstring.

        constellations_hits_tab_widget: direct reference (not a lazy getter), safe
        because -- by construction order in prime_atlas_v1.py's __init__ -- it already
        exists by the time this class is built.

        prune_empty_pietro_dirs: passed in rather than imported directly here --
        see PrimesTreeCoordinator's own docstring for why (its real home is
        primeatlas/restore_job.py, re-exported at the primeatlas package's own top
        level).

        on_startup_scan_done(name): same seam as PrimesTreeCoordinator's own
        constructor parameter, fired with the fixed string "constellations".
        """
        self._root = root
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self.T = translator.t
        self._constellations_hits_tab_widget = constellations_hits_tab_widget
        self._prune_empty_pietro_dirs = prune_empty_pietro_dirs
        self._on_startup_scan_done = on_startup_scan_done

        self._busy = False
        self._pending = False

    def _scan(self, portal_folder, _report_progress):
        """Runs OFF the GUI thread -- ported unchanged from the original inline
        _constellations_tree_scan(). Same idempotent prune_empty_pietro_dirs()
        double-call as PrimesTreeCoordinator's own scan -- now two INDEPENDENT
        background threads may call it back-to-back rather than the same GUI-thread
        call twice in a row, but the function's own try/except around each individual
        os.rmdir() already makes that race harmless: worst case, one of the two calls
        finds a given empty subdir already gone and silently skips it.

        Only floors that actually HAVE at least one detected constellation hit --
        list_pietra() alone would include every floor with prime data, regardless of
        whether the constellation finder has ever been run against it (or ran and
        found nothing), cluttering this tree with entries that only ever expand into
        an empty "no hits" placeholder. See floor_has_constellation_hits()'s own
        docstring."""
        self._prune_empty_pietro_dirs(portal_folder)
        pietra = [be for be in list_pietra(portal_folder)
                  if floor_has_constellation_hits(portal_folder, be)]
        return {"pietra": pietra}

    def reload(self):
        """Rebuilds the constellation-hits floor list from disk. Same async
        split/coalescing/staleness shape as PrimesTreeCoordinator.reload() -- see that
        method's own docstring for the full reasoning; this tree's own busy/pending
        flags are independent of the other tree's."""
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
        busy/pending/staleness handling this implements (identical shape to
        PrimesTreeCoordinator._on_scan_done)."""
        self._busy = False
        stale = portal_folder != self._get_portal_folder()
        if self._pending or stale:
            self._pending = False
            self.reload()
            return
        if error is not None:
            self.status.set(self.T("const.status_reload_error", error=str(error)))
            return
        self._constellations_hits_tab_widget.populate_floors(result["pietra"])

        if self._on_startup_scan_done is not None:
            self._on_startup_scan_done("constellations")
