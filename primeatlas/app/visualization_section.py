"""
visualization_section.py -- VisualizationSectionMixin of PortalBrowserApp: the
'Visualization' tab (Rings / Tree / Sphere sub-tabs).
"""
from tkinter import ttk

from primeatlas.app import app_dynamic as _dyn


class VisualizationSectionMixin:
    # --- Tab 5: Visualization --------------------------------------------------

    def _build_visualization_section(self):
        """Same nested-notebook pattern as _build_primes_section(): the top-level
        'Visualization' tab only holds a sub-notebook, one sub-tab per visualization
        (each with its own GPU renderer subprocess and window)."""
        sub = ttk.Notebook(self.visualization_tab)
        sub.pack(fill="both", expand=True)
        self.visualization_sub_notebook = sub
        self.visualization_rings_tab = ttk.Frame(sub)
        sub.add(self.visualization_rings_tab, text=_dyn.T("tabs.visualization_rings"))
        self._build_rings_tab()
        self.visualization_tree_tab = ttk.Frame(sub)
        sub.add(self.visualization_tree_tab, text=_dyn.T("tabs.visualization_tree"))
        self._build_tree_tab()
        self.visualization_sphere_tab = ttk.Frame(sub)
        sub.add(self.visualization_sphere_tab, text=_dyn.T("tabs.visualization_sphere"))
        self._build_sphere_tab()

    def _build_rings_tab(self):
        """Thin wrapper -- the whole sub-tab lives in
        primeatlas/visualization/rings/rings_tab.py's RingsTab, same construction
        pattern as _build_generation_tab above. get_portal_folder is a deferred lambda
        (not the resolved _dyn.PORTAL_FOLDER value) so a later Settings-tab storage-path
        change is picked up on the NEXT launch without this tab needing its own
        change-notification wiring, same reasoning as every other tab's own
        get_portal_folder injection."""
        from primeatlas.visualization.rings.rings_tab import RingsTab

        self.rings_tab_widget = RingsTab(
            self.visualization_rings_tab, get_portal_folder=lambda: _dyn.PORTAL_FOLDER,
            status_var=self.status, translator=_dyn.TRANSLATOR,
            totals_progress=self.totals_progress, app_settings=_dyn.APP_SETTINGS,
            # Lazy: the Visualization tab can be built before the coordinator.
            offer_generate_storage=lambda start, end, on_finished:
                self._generation_offer_coord.offer_fill_storage_range(start, end, on_finished))
        self.rings_tab_widget.pack(fill="both", expand=True)

    def _build_tree_tab(self):
        """Thin wrapper -- the whole sub-tab lives in
        primeatlas/visualization/tree/tree_tab.py's TreeTab, with the tree and the
        assembly visualization modes (its own renderer window and process; it reads
        no storage, but offers the same empty-storage fill as the Rings sub-tab)."""
        from primeatlas.visualization.tree.tree_tab import TreeTab

        self.tree_tab_widget = TreeTab(
            self.visualization_tree_tab, get_portal_folder=lambda: _dyn.PORTAL_FOLDER,
            status_var=self.status, translator=_dyn.TRANSLATOR,
            totals_progress=self.totals_progress, app_settings=_dyn.APP_SETTINGS,
            offer_generate_storage=lambda start, end, on_finished:
                self._generation_offer_coord.offer_fill_storage_range(start, end, on_finished))
        self.tree_tab_widget.pack(fill="both", expand=True)

    def _build_sphere_tab(self):
        """Thin wrapper -- the whole sub-tab lives in
        primeatlas/visualization/sphere/sphere_tab.py's SphereTab (its own renderer
        window and process; it reads the storage as a list of primes around N and
        offers the same empty-storage fill as the Rings sub-tab)."""
        from primeatlas.visualization.sphere.sphere_tab import SphereTab

        self.sphere_tab_widget = SphereTab(
            self.visualization_sphere_tab, get_portal_folder=lambda: _dyn.PORTAL_FOLDER,
            status_var=self.status, translator=_dyn.TRANSLATOR,
            totals_progress=self.totals_progress, app_settings=_dyn.APP_SETTINGS,
            offer_generate_storage=lambda start, end, on_finished:
                self._generation_offer_coord.offer_fill_storage_range(start, end, on_finished))
        self.sphere_tab_widget.pack(fill="both", expand=True)
