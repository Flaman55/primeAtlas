"""
storage_integrate_section.py -- StorageIntegrateSection, the integrate-external-storage
part of the Backup sub-tab (storage_integrate.py): a background dry-run preview, then
the copy job of exactly the previewed plan, with the same thread/queue shape as
full_backup_section.py.

A SettingsTab mixin: it uses the widgets, Variables and state that SettingsTab and its
other mixins set up, so it is never instantiated on its own.
"""
import os
import queue
import threading

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from ..core.widgets import HeightGrip
from ..generation.generation_console import GenerationConsole
from . import storage_integrate as si
from ..core import background


class StorageIntegrateSection:
    # ---- integrate external storage, primeatlas/settings/storage_integrate.py ---------------------
    #
    # Folds a whole external archive (downloaded from GitHub, copied from another
    # machine) into the current one, WITHOUT the person having to resolve file-copy
    # conflicts on benchmark_log.csv/.portal_totals_cache.json/
    # .portal_generation_settings.json themselves -- this section never touches any of
    # those three, only floor folders (see storage_integrate.py's own docstring).
    # Operates on the whole external storage at once (no per-floor picker, unlike the
    # full-data backup section above), always preview-then-confirm.

    def _on_browse_storage_integrate_source(self):
        chosen = filedialog.askdirectory(
            initialdir=self.storage_integrate_source_var.get() or self.wsl["get_portal_folder"](),
            title=self.T("settings.storage_integrate_browse_title"))
        if chosen:
            self.storage_integrate_source_var.set(chosen)
            self._storage_integrate_plan = []
            self._update_storage_integrate_buttons()
            self.storage_integrate_results_listbox.delete(0, "end")
            self.storage_integrate_totals_var.set("")

    def _on_preview_storage_integrate(self):
        """Validates inputs synchronously (cheap -- just os.path.isdir/realpath, no tree
        scan), then runs the actual si.plan_integration() dry-run scan (a full walk of
        BOTH the destination and external trees -- see that function's own docstring)
        on a background thread via primeatlas/core/background.py's run_in_background(),
        instead of blocking the GUI thread for however long that scan takes.

        Calling si.plan_integration() directly, inline, on the GUI thread would freeze
        the window for the full dual-tree scan -- the exact kind of freeze the
        properly-threaded copy job right next to it (_on_start_storage_integrate below)
        never had. This method is also called from _on_storage_integrate_job_finished()
        to refresh the plan after a copy run completes, so backgrounding it here covers
        both call sites at once."""
        external_path = self.storage_integrate_source_var.get().strip()
        if not external_path or not os.path.isdir(external_path):
            messagebox.showerror(self.T("settings.dialog_title"),
                                  self.T("settings.storage_integrate_source_invalid"))
            return
        destination = self.wsl["get_portal_folder"]()
        storage_real = os.path.normcase(os.path.realpath(destination))
        external_real = os.path.normcase(os.path.realpath(external_path))
        if storage_real == external_real:
            messagebox.showerror(self.T("settings.dialog_title"),
                                  self.T("settings.storage_integrate_source_same_as_storage"))
            return
        if self._storage_integrate_preview_running or self._storage_integrate_job_running:
            return
        self._storage_integrate_preview_running = True
        self._update_storage_integrate_buttons()
        background.run_in_background(
            self, lambda report_progress: si.plan_integration(destination, external_path),
            on_done=self._on_storage_integrate_preview_done)

    def _on_storage_integrate_preview_done(self, plan, error):
        """Main-thread callback for _on_preview_storage_integrate()'s background scan.
        A raised exception is surfaced to the user like any other failure in this tab
        (instead of propagating out of a Tk callback as console noise)."""
        self._storage_integrate_preview_running = False
        if error is not None:
            messagebox.showerror(self.T("settings.dialog_title"), str(error))
            self._update_storage_integrate_buttons()
            return
        self._storage_integrate_plan = plan
        self.storage_integrate_results_listbox.delete(0, "end")
        if not self._storage_integrate_plan:
            self.storage_integrate_totals_var.set(self.T("settings.storage_integrate_nothing_to_do"))
            self._update_storage_integrate_buttons()
            return
        total_windows = total_hits = total_bytes = 0
        for entry in self._storage_integrate_plan:
            windows = len(entry["missing_windows"])
            hits = len(entry["missing_hits"])
            total_windows += windows
            total_hits += hits
            total_bytes += entry["missing_bytes"]
            key = ("settings.storage_integrate_row_new" if entry["is_new_floor"]
                   else "settings.storage_integrate_row_extend")
            self.storage_integrate_results_listbox.insert("end", self.T(
                key, base_exponent=entry["base_exponent"], windows=windows, hits=hits,
                mb=entry["missing_bytes"] / (1024 * 1024)))
        self.storage_integrate_totals_var.set(self.T(
            "settings.storage_integrate_totals", floors=len(self._storage_integrate_plan),
            windows=total_windows, hits=total_hits, mb=total_bytes / (1024 * 1024)))
        self._update_storage_integrate_buttons()

    def _update_storage_integrate_buttons(self):
        running = self._storage_integrate_job_running
        busy = running or self._storage_integrate_preview_running
        has_plan = bool(self._storage_integrate_plan)
        self.storage_integrate_preview_btn.configure(state=("disabled" if busy else "normal"))
        self.storage_integrate_start_btn.configure(
            state=("normal" if (has_plan and not busy) else "disabled"))
        self.storage_integrate_cancel_btn.configure(state=("normal" if running else "disabled"))

    def _on_start_storage_integrate(self):
        if self._storage_integrate_job_running or not self._storage_integrate_plan:
            return
        external_path = self.storage_integrate_source_var.get().strip()
        destination = self.wsl["get_portal_folder"]()
        floors = [entry["base_exponent"] for entry in self._storage_integrate_plan]

        self._storage_integrate_stop_event = threading.Event()
        self._storage_integrate_job_running = True
        self._update_storage_integrate_buttons()
        self.storage_integrate_progress.configure(mode="determinate", maximum=len(floors), value=0)
        self.storage_integrate_status_var.set(self.T("settings.storage_integrate_status_starting"))
        self.storage_integrate_file_status_var.set("")

        q = queue.Queue()
        self._storage_integrate_queue = q
        thread = threading.Thread(
            target=self._storage_integrate_worker,
            args=(destination, external_path, floors, self._storage_integrate_stop_event, q),
            daemon=True)
        thread.start()
        self._poll_storage_integrate_queue()

    def _storage_integrate_worker(self, destination, external_path, floors, stop_event, q):
        """Off the main thread -- see _full_backup_worker's own docstring for the same
        reasoning (no tkinter calls here, only queue.put)."""
        should_stop = stop_event.is_set
        for idx, base_exponent in enumerate(floors):
            q.put(("floor_start", base_exponent, idx, len(floors)))

            def progress_cb(phase, name, i, total, base_exponent=base_exponent):
                q.put(("file_progress", base_exponent, phase, name, i, total))

            try:
                result = si.integrate_floor(
                    destination, external_path, base_exponent,
                    progress_cb=progress_cb, should_stop=should_stop)
                q.put(("floor_done", base_exponent, result, None))
            except Exception as e:  # noqa: BLE001 -- must never kill this thread silently
                q.put(("floor_done", base_exponent, None, str(e)))
            if stop_event.is_set():
                break
        q.put(("__job_done__", stop_event.is_set()))

    def _poll_storage_integrate_queue(self):
        try:
            while True:
                item = self._storage_integrate_queue.get_nowait()
                kind = item[0]
                if kind == "__job_done__":
                    self._on_storage_integrate_job_finished(cancelled=item[1])
                    return
                elif kind == "floor_start":
                    _, base_exponent, idx, total_floors = item
                    self.storage_integrate_progress.configure(value=idx)
                    self.storage_integrate_status_var.set(self.T(
                        "settings.storage_integrate_status_floor",
                        base_exponent=base_exponent, idx=idx + 1, total=total_floors))
                elif kind == "file_progress":
                    _, base_exponent, phase, name, i, total = item
                    self.storage_integrate_file_status_var.set(self.T(
                        "settings.full_backup_status_file",
                        phase=self.T(f"settings.full_backup_phase_{phase}"),
                        name=name, idx=i + 1, total=max(total, 1)))
                elif kind == "floor_done":
                    _, base_exponent, result, error = item
                    self._storage_integrate_log_floor_result(base_exponent, result, error)
        except queue.Empty:
            pass
        self.after(150, self._poll_storage_integrate_queue)

    def _storage_integrate_log_floor_result(self, base_exponent, result, error):
        if error is not None:
            text = self.T("settings.storage_integrate_floor_error",
                           base_exponent=base_exponent, error=error)
        else:
            text = self.T("settings.storage_integrate_floor_done",
                           base_exponent=base_exponent,
                           windows=result["copied_windows"], hits=result["copied_hits"])
        self._storage_integrate_log(text + "\n")

    def _on_storage_integrate_job_finished(self, cancelled):
        self._storage_integrate_job_running = False
        self.storage_integrate_progress.configure(value=self.storage_integrate_progress["maximum"])
        self.storage_integrate_file_status_var.set("")
        self.storage_integrate_status_var.set(self.T(
            "settings.full_backup_status_cancelled" if cancelled
            else "settings.full_backup_status_done"))
        # Re-preview against the same source -- floors that are now fully integrated
        # drop off the list, so the picture always reflects what's ACTUALLY still
        # missing, not the (now stale) plan the job just acted on.
        self._on_preview_storage_integrate()
        self._update_storage_integrate_buttons()
        self.wsl["reload_primes_tree"]()
        self.wsl["reload_constellations_tree"]()

    def _on_cancel_storage_integrate(self):
        if self._storage_integrate_stop_event is not None:
            self._storage_integrate_stop_event.set()

    def _storage_integrate_log(self, text):
        self.storage_integrate_console.append(text)

    def _build_storage_integrate_section(self, outer):
        """Integrate-external-storage, primeatlas/settings/storage_integrate.py -- see that
        module's and this module's docstrings. Always preview-then-confirm: the
        Integrate button stays disabled until a fresh dry-run has populated
        self._storage_integrate_plan."""
        frame = ttk.Labelframe(outer, text=self.T("settings.storage_integrate_frame"))
        frame.pack(fill="both", expand=True, pady=(0, 8))
        ttk.Label(
            frame, text=self.T("settings.storage_integrate_hint"),
            style="Hint.TLabel", wraplength=760, justify="left").pack(
            anchor="w", padx=6, pady=(6, 4))

        source_row = ttk.Frame(frame)
        source_row.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(source_row, text=self.T("settings.storage_integrate_source_label")).pack(
            side="left")
        self.storage_integrate_source_var = tk.StringVar(value="")
        ttk.Entry(source_row, textvariable=self.storage_integrate_source_var, width=48).pack(
            side="left", padx=(6, 6), fill="x", expand=True)
        ttk.Button(source_row, text=self.T("settings.full_backup_browse_button"),
                   command=self._on_browse_storage_integrate_source).pack(side="left")
        self.storage_integrate_preview_btn = ttk.Button(
            source_row, text=self.T("settings.storage_integrate_preview_button"),
            command=self._on_preview_storage_integrate)
        self.storage_integrate_preview_btn.pack(side="left", padx=(6, 0))

        results_list_row = ttk.Frame(frame)
        results_list_row.pack(fill="both", expand=True, padx=6, pady=(0, 2))
        self.storage_integrate_results_listbox = tk.Listbox(results_list_row, height=5)
        self.storage_integrate_results_listbox.pack(side="left", fill="both", expand=True)
        results_scroll = ttk.Scrollbar(
            results_list_row, orient="vertical",
            command=self.storage_integrate_results_listbox.yview)
        results_scroll.pack(side="left", fill="y")
        self.storage_integrate_results_listbox.configure(yscrollcommand=results_scroll.set)
        self.storage_integrate_results_grip = HeightGrip(
            frame, self.storage_integrate_results_listbox, after=results_list_row, padx=6)

        self.storage_integrate_totals_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.storage_integrate_totals_var).pack(
            anchor="w", padx=6, pady=(0, 4))

        action_row = ttk.Frame(frame)
        action_row.pack(fill="x", padx=6, pady=(0, 2))
        self.storage_integrate_start_btn = ttk.Button(
            action_row, text=self.T("settings.storage_integrate_start_button"),
            command=self._on_start_storage_integrate, state="disabled")
        self.storage_integrate_start_btn.pack(side="left")
        self.storage_integrate_cancel_btn = ttk.Button(
            action_row, text=self.T("settings.full_backup_cancel_button"),
            command=self._on_cancel_storage_integrate, state="disabled")
        self.storage_integrate_cancel_btn.pack(side="left", padx=(6, 0))

        self.storage_integrate_progress = ttk.Progressbar(
            frame, orient="horizontal", mode="determinate", maximum=1, value=0)
        self.storage_integrate_progress.pack(fill="x", padx=6, pady=(4, 2))
        self.storage_integrate_status_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.storage_integrate_status_var).pack(anchor="w", padx=6)
        self.storage_integrate_file_status_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.storage_integrate_file_status_var,
                  style="Hint.TLabel").pack(anchor="w", padx=6, pady=(0, 4))

        self.storage_integrate_console = GenerationConsole(
            frame, self.T, height=4, start_visible=True,
            window_title=self.T("settings.storage_integrate_frame"))
        self.storage_integrate_output = self.storage_integrate_console.text
