"""
settings_tab.py -- SettingsTab, the Settings tab: a 3-tab Notebook (General, Backup,
Updates; see _build_widgets) composed from one mixin per area:

  - general_section.py            language, theme, readability, ScrollPad width, storage path
  - restore_section.py            metadata backup list, diff against disk, restore job
  - delete_section.py             full-database and per-floor deletes
  - full_backup_section.py        full-data (compressed) backup and restore
  - storage_integrate_section.py  integrate an external storage folder
  - updates_section.py            library/engine installers, environment re-check, self-update

This class owns the shared state (__init__) and the Notebook layout; the Backup sub-tab's
layout lives here because it stacks four of the mixins' sections.

SettingsTab does not launch WSL jobs on its own: primeatlas/app/ owns that machinery
and hands it in as a dict of callables (`wsl_helpers`) at construction time, so this
package never imports primeatlas/app/ (which imports SettingsTab). Keys used here:
  - get_portal_folder() -> str           current storage path, read at call time
  - set_portal_folder(path) -> None      rebinds the app's global + status label
  - get_loop_defaults() -> dict          current Generation-tab loop form values
  - build_loop_argv, build_constellation_finder_argv, build_wsl_logged_command  (functions)
  - WslLoggedRunner                      (class)
  - generation_log_paths                 (function)
  - is_any_job_running() -> bool         True if a Generation-tab runner is active; read by
                                         the theme/language auto-restart guard
  - repo_dir                             str, the git checkout root, for app_update.py
(PortalBrowserApp's _build_settings_tab() holds the full set.)

Every user-visible string goes through self.T(key, **kwargs) (core/i18n.py). The language
and theme pickers only write AppSettings and then restart the app (app_restart.py), since
relabeling every built widget live is not attempted; while a background job runs, a
"restart required" note is shown instead.
"""

import tkinter as tk
from tkinter import ttk

from ..core.base_tab import BaseTab
from ..core.widgets import HeightGrip, ScrollablePage, set_scroll_pad_width
from ..generation.generation_console import GenerationConsole
from .general_section import GeneralSection
from .restore_section import RestoreSection
from .delete_section import DeleteSection
from .full_backup_section import FullBackupSection
from .storage_integrate_section import StorageIntegrateSection
from .updates_section import UpdatesSection


class SettingsTab(GeneralSection, RestoreSection, DeleteSection, FullBackupSection,
                  StorageIntegrateSection, UpdatesSection, BaseTab):
    def __init__(self, parent, app_settings, wsl_helpers, translator):
        super().__init__(parent, translator)
        self.app_settings = app_settings
        self.wsl = wsl_helpers
        # Pads built before this tab are resized, pads built after use it as default.
        set_scroll_pad_width(app_settings.scroll_pad_width)

        self._backups = []              # [(name, path)], newest first
        self._selected_backup_name = None
        self._diff_cache = None         # last "check differences" result for the selection
        # True only while _on_check_diff()'s background scan is running -- see that
        # method's own docstring.
        self._diff_check_running = False

        self._active_job = None         # RestoreJob currently driving, or None
        self._active_job_runner_kind = None  # "loop" / "constellation" / None (in flight)
        self._restore_runner = None
        self._restore_queue = None
        self._step_retry_counts = {}    # {(base_exponent, kind): count}
        # "windows" / "hits" / None -- which phase _drive_restore() last announced (see
        # that method's docstring for why windows-for-every-floor strictly precedes
        # hits-for-every-floor now). Reset whenever a job starts/resumes so the banner
        # re-announces itself for a freshly (re)started run.
        self._restore_phase = None
        # True while the loop run currently in flight is a low-floor (0-6) combined
        # batch -- read by _on_step_stage_done() to decide whether to also reconcile
        # sibling low-floor steps (see _drive_windows_phase's docstring).
        self._restore_low_floor_batch = False
        # base_exponents whose windows/hits restore has exhausted MAX_STAGE_RETRIES --
        # excluded from _drive_restore()'s phase selection so a permanently-failing
        # floor doesn't loop forever; the step itself is still finished (best-effort,
        # gap logged) once neither phase has anything left to select. Reset alongside
        # _step_retry_counts.
        self._given_up_windows = set()
        self._given_up_hits = set()
        self._incomplete_jobs = []

        # Optional-library installer -- sympy, used by the Primality tests
        # tab's factorize() for a faster/more complete result when installed (see
        # primeatlas/primality/primality.py's own docstring). _libs_runner/_libs_queue mirror the
        # restore driver's _restore_runner/_restore_queue shape one-for-one, but drive a
        # single local (non-WSL) `pip install` subprocess instead.
        self._libs_install_running = False
        self._libs_runner = None
        self._libs_queue = None

        # CUDASieve (GPU engine) installer. A quick WSL call clones/updates the repo and reads
        # back its OWN current License file (GPLv3, third-party, NOT this project's
        # license -- see prime_sieve_cudasieve.py's module header), shown to the user
        # for explicit accept/decline BEFORE the longer `make` build step
        # (WslLoggedRunner, same shape as every Generation-tab job) ever runs.
        # _cudasieve_status_running guards the quick status probe; _cudasieve_install_running
        # spans the WHOLE fetch-license -> consent -> build sequence (not just the build
        # step) so a second click can't start an overlapping sequence while a consent
        # dialog is still open. No separate "download only" flow -- Install clones/
        # updates on its own; Open on GitHub below just links to the real repo page.
        self._cudasieve_status_running = False
        self._cudasieve_install_running = False
        self._cudasieve_runner = None
        self._cudasieve_queue = None

        # App self-update (primeatlas/settings/app_update.py) -- guard flags for the
        # same "daemon thread + self.after(0, ...) callback" shape every other
        # WSL/network-touching probe in updates_section.py uses, see its
        # _check_for_app_update()/_download_app_update().
        self._app_update_check_running = False
        self._app_update_download_running = False

        # Full-data (compressed) backup, primeatlas/settings/full_backup.py -- see
        # full_backup_section.py's docstring for the threading shape. _full_backup_job_running gates the
        # buttons (only one backup/restore job at a time); _full_backup_stop_event is a
        # fresh threading.Event per job (should_stop callback for copy_floor_increment/
        # restore_floor_from_full_backup), _full_backup_queue is that job's own
        # queue.Queue, polled by _poll_full_backup_queue.
        self._full_backup_job_running = False
        self._full_backup_stop_event = None
        self._full_backup_queue = None
        self._full_backup_suggested = set()   # base_exponents currently >= threshold

        # Integrate-external-storage (primeatlas/settings/storage_integrate.py) -- the systemic
        # fix for manually merging a whole external archive folder-by-folder (see that
        # module's own docstring). _storage_integrate_plan caches the last dry-run
        # preview (plan_integration()'s result) so the Integrate button acts on exactly
        # what was previewed, not a value that may have drifted since; same
        # job-running/stop-event/queue shape as the full-data backup section above.
        self._storage_integrate_plan = []
        self._storage_integrate_job_running = False
        self._storage_integrate_stop_event = None
        self._storage_integrate_queue = None
        # True only while the PREVIEW/plan scan itself is running in the background --
        # separate from _storage_integrate_job_running above, which tracks the actual
        # copy job. See _on_preview_storage_integrate()'s own docstring: plan_integration()
        # does a full dual-tree scan and must not run synchronously on the GUI thread.
        self._storage_integrate_preview_running = False

        self._build_widgets()
        self._refresh_backup_list()
        self._scan_incomplete_restores()
        self._refresh_libs_status()
        self._refresh_floor_delete_list()
        self._refresh_full_backup_floor_picker()
        self._refresh_full_backup_entries()
        # Does NOT probe WSL here: probing from __init__ would pay a WSL round-trip on
        # every app launch for a GPU-only, opt-in engine most sessions never touch, and
        # a background thread's self.after(...) callback can land before mainloop() has
        # started (RuntimeError: main thread is not in main loop). Only probe when the
        # user explicitly asks (Check status/Download/Install); until then, show
        # whatever the LAST real probe found, persisted in app_settings so it survives a
        # restart -- see AppSettings.cudasieve_status. No thread, no WSL call, no
        # mainloop race: this just reads a dict.
        self._show_cached_cudasieve_status()

    # ---- widget construction ---------------------------------------------------------------

    def _build_widgets(self):
        """A single long scroll-less column of Labelframes doesn't scale once
        backup/restore/delete grow alongside language+path+libs: the bottom sections
        (the whole-database delete button in particular) run off the bottom of the
        window with no way to reach them. Split into a Notebook with three sub-tabs
        instead of trying to shrink anything: General (language + storage path -- the
        two settings someone touches once and rarely again), Backup (backup/restore/
        delete, all storage-destructive or storage-preserving operations grouped
        together), Updates (optional-library installer, CUDASieve installer, WSL
        environment re-check, and PrimeAtlas's own self-update).

        Splitting into sub-tabs alone isn't enough, though -- Backup on its own
        (backup list + restore controls/log + per-floor delete + whole-database
        delete) can still be taller than a non-maximized window. Every sub-tab is
        wrapped in a ScrollablePage, so ANY tab that grows past the window's current
        height gets a scrollbar automatically, and loses it again once it fits."""
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True, padx=6, pady=6)

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)

        general_tab = ttk.Frame(notebook)
        backup_tab = ttk.Frame(notebook)
        updates_tab = ttk.Frame(notebook)
        notebook.add(general_tab, text=self.T("settings.tab_general"))
        notebook.add(backup_tab, text=self.T("settings.tab_backup"))
        notebook.add(updates_tab, text=self.T("settings.tab_updates"))

        self._scroll_pages = []
        self._scroll_pads = []
        self._build_general_tab(self._make_scrollable_tab(general_tab))
        self._build_backup_tab(self._make_scrollable_tab(backup_tab))
        self._build_updates_tab(self._make_scrollable_tab(updates_tab))

    def _make_scrollable_tab(self, notebook_tab):
        """Wraps a Notebook-tab Frame in a ScrollablePage and returns the frame content is
        packed into."""
        page = ScrollablePage(notebook_tab, pad_text=self.T("common.scroll_pad"))
        self._scroll_pages.append(page)
        self._scroll_pads.append(page.pad)
        return page.body

    def _build_backup_tab(self, parent):
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True, padx=6, pady=6)

        backup_frame = ttk.Labelframe(outer, text=self.T("settings.backup_frame"))
        backup_frame.pack(fill="x", pady=(0, 8))
        btn_row = ttk.Frame(backup_frame)
        btn_row.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Button(btn_row, text=self.T("settings.backup_create"),
                   command=self._on_create_backup).pack(side="left")
        ttk.Button(btn_row, text=self.T("settings.backup_refresh"),
                   command=self._refresh_backup_list).pack(side="left", padx=(6, 0))
        ttk.Button(btn_row, text=self.T("settings.backup_delete"),
                   command=self._on_delete_backup).pack(side="left", padx=(6, 0))
        self.backup_status_var = tk.StringVar(value="")
        ttk.Label(btn_row, textvariable=self.backup_status_var).pack(side="left", padx=(12, 0))

        list_row = ttk.Frame(backup_frame)
        list_row.pack(fill="x", padx=6, pady=(0, 6))
        self.backup_listbox = tk.Listbox(list_row, height=5, exportselection=False)
        self.backup_listbox.pack(side="left", fill="x", expand=True)
        self.backup_listbox.bind("<<ListboxSelect>>", self._on_backup_selected)
        scrollbar = ttk.Scrollbar(list_row, orient="vertical", command=self.backup_listbox.yview)
        scrollbar.pack(side="left", fill="y")
        self.backup_listbox.configure(yscrollcommand=scrollbar.set)
        self.backup_list_grip = HeightGrip(backup_frame, self.backup_listbox, after=list_row,
                                           padx=6)

        restore_frame = ttk.Labelframe(outer, text=self.T("settings.restore_frame"))
        restore_frame.pack(fill="both", expand=True, pady=(0, 8))

        restore_btn_row = ttk.Frame(restore_frame)
        restore_btn_row.pack(fill="x", padx=6, pady=(6, 2))
        self.restore_diff_btn = ttk.Button(
            restore_btn_row, text=self.T("settings.restore_check_diff"), command=self._on_check_diff)
        self.restore_diff_btn.pack(side="left")
        self.restore_start_btn = ttk.Button(
            restore_btn_row, text=self.T("settings.restore_start"), command=self._on_start_restore,
            state="disabled")
        self.restore_start_btn.pack(side="left", padx=(6, 0))
        self.restore_pause_btn = ttk.Button(
            restore_btn_row, text=self.T("settings.restore_pause"), command=self._on_restore_pause,
            state="disabled")
        self.restore_pause_btn.pack(side="left", padx=(6, 0))
        self.restore_resume_btn = ttk.Button(
            restore_btn_row, text=self.T("settings.restore_resume"), command=self._on_restore_resume,
            state="disabled")
        self.restore_resume_btn.pack(side="left", padx=(6, 0))
        self.restore_cancel_btn = ttk.Button(
            restore_btn_row, text=self.T("settings.restore_cancel"), command=self._on_restore_cancel,
            state="disabled")
        self.restore_cancel_btn.pack(side="left", padx=(6, 0))

        self.restore_progress = ttk.Progressbar(
            restore_frame, orient="horizontal", mode="determinate", maximum=1, value=0)
        self.restore_progress.pack(fill="x", padx=6, pady=(2, 2))
        self.restore_progress_label = tk.StringVar(value="")
        ttk.Label(restore_frame, textvariable=self.restore_progress_label).pack(
            anchor="w", padx=6)

        incomplete_row = ttk.Frame(restore_frame)
        incomplete_row.pack(fill="x", padx=6, pady=(4, 2))
        ttk.Label(incomplete_row, text=self.T("settings.restore_incomplete_label")).pack(anchor="w")
        self.incomplete_listbox = tk.Listbox(incomplete_row, height=3, exportselection=False)
        self.incomplete_listbox.pack(fill="x", side="left", expand=True)
        ttk.Button(incomplete_row, text=self.T("settings.restore_resume_selected"),
                   command=self._on_resume_incomplete).pack(side="left", padx=(6, 0))
        ttk.Button(incomplete_row, text=self.T("settings.restore_delete_selected"),
                   command=self._on_delete_incomplete).pack(side="left", padx=(6, 0))
        self.incomplete_list_grip = HeightGrip(restore_frame, self.incomplete_listbox,
                                               after=incomplete_row, min_lines=2, padx=6)

        self.restore_console = GenerationConsole(
            restore_frame, self.T, height=8, start_visible=True,
            window_title=self.T("settings.restore_frame"))
        self.restore_output = self.restore_console.text

        self._build_full_backup_section(outer)
        self._build_storage_integrate_section(outer)

        # Per-floor delete -- narrower than the whole-database delete below: clears
        # ONE floor (source_primes + constellations together) to force a clean
        # regeneration, or ONLY that floor's constellations (keeping its prime data)
        # to force a clean constellation_finder_v2_2.py re-run. Shares ONE floor picker
        # between both buttons -- see _selected_delete_floor()'s own docstring.
        floor_delete_frame = ttk.Labelframe(outer, text=self.T("settings.delete_floor_frame"))
        floor_delete_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(
            floor_delete_frame, text=self.T("settings.delete_floor_hint"),
            style="Hint.TLabel", wraplength=760, justify="left").pack(
            anchor="w", padx=6, pady=(6, 4))
        floor_pick_row = ttk.Frame(floor_delete_frame)
        floor_pick_row.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(floor_pick_row, text=self.T("settings.delete_floor_label")).pack(side="left")
        self.floor_delete_var = tk.StringVar(value="")
        self.floor_delete_combo = ttk.Combobox(
            floor_pick_row, textvariable=self.floor_delete_var, state="readonly", width=12)
        self.floor_delete_combo.pack(side="left", padx=(6, 6))
        ttk.Button(floor_pick_row, text=self.T("common.refresh"),
                   command=self._refresh_floor_delete_list).pack(side="left")
        floor_delete_btn_row = ttk.Frame(floor_delete_frame)
        floor_delete_btn_row.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(floor_delete_btn_row, text=self.T("settings.delete_floor_button"),
                   command=self._on_delete_floor_clicked).pack(side="left")
        ttk.Button(floor_delete_btn_row, text=self.T("settings.delete_constellations_button"),
                   command=self._on_delete_floor_constellations_clicked).pack(
            side="left", padx=(6, 0))

        delete_frame = ttk.Labelframe(outer, text=self.T("settings.delete_frame"))
        delete_frame.pack(fill="x")
        ttk.Label(
            delete_frame, text=self.T("settings.delete_warning"),
            foreground="#a33", wraplength=760, justify="left").pack(
            anchor="w", padx=6, pady=(6, 4))
        ttk.Button(delete_frame, text=self.T("settings.delete_button"),
                   command=self._on_delete_clicked).pack(anchor="w", padx=6, pady=(0, 6))
