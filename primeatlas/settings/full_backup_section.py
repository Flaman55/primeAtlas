"""
full_backup_section.py -- FullBackupSection, the full-data (compressed) backup part of the
Backup sub-tab (full_backup.py holds the design).

copy_floor_increment()/restore_floor_from_full_backup() are in-process Python functions
(local file I/O, no subprocess), so each job runs on a one-shot threading.Thread that
puts results on a queue.Queue polled with self.after(150, ...); only one full-data job
is in flight at a time.

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
from . import full_backup as fb
from ..core import background


class FullBackupSection:
    # ---- full-data (compressed) backup, primeatlas/settings/full_backup.py ------------------------
    #
    # Distinct from the metadata-only BackupManifest above: this copies real, gzip-
    # compressed file bytes to a destination OUTSIDE the live storage, one persistent
    # entry per floor (see full_backup.py's own docstring for the full design). Two
    # independent pickers share one destination-path row and one progress/log area
    # below:
    #   - the LIVE floor list (self.full_backup_floor_listbox) -- pick floors to back up
    #   - the DESTINATION entry list (self.full_backup_entries_listbox) -- pick already-
    #     backed-up floors to restore from or delete

    def _full_backup_destination(self):
        return self.full_backup_dest_var.get().strip()

    def _on_browse_full_backup_dest(self):
        chosen = filedialog.askdirectory(
            initialdir=self._full_backup_destination() or self.wsl["get_portal_folder"](),
            title=self.T("settings.full_backup_browse_title"))
        if chosen:
            self.full_backup_dest_var.set(chosen)
            self.app_settings.set_full_backup_destination(chosen)
            self._refresh_full_backup_entries()

    def _validate_full_backup_destination(self, show_error=True):
        """Returns the destination path string if valid, or None (after showing a
        translated error, unless show_error=False) -- shared by every action below so
        the same hard rule (validate_destination_path()) is checked at the same point
        every time, never bypassed by a stale/edited-but-not-yet-saved Entry value."""
        destination = self._full_backup_destination()
        storage_path = self.wsl["get_portal_folder"]()
        reason = fb.validate_destination_path(storage_path, destination)
        if reason is not None:
            if show_error:
                key = {
                    "empty": "settings.full_backup_dest_empty",
                    "same_as_storage": "settings.full_backup_dest_same_as_storage",
                    "inside_storage": "settings.full_backup_dest_inside_storage",
                    "storage_inside_destination": "settings.full_backup_dest_wraps_storage",
                }.get(reason, "settings.full_backup_dest_invalid")
                messagebox.showerror(self.T("settings.dialog_title"), self.T(key))
            return None
        return destination

    def _refresh_full_backup_floor_picker(self):
        """Repopulates the live-floor picker (source side of a backup) -- suggested
        floors (suggest_full_backup_floors(), measured generation time over the 1h
        default threshold) are marked with a leading marker and pre-selected, so the
        person sees which floors are actually expensive to regenerate rather than
        guessing from the bare floor number (see full_backup.py's own docstring).

        list_floors() is cheap, but suggest_full_backup_floors() parses the WHOLE
        benchmark_log.csv (can grow to many thousands of rows over a long project
        lifetime) -- both are fetched together on one background thread since the
        listbox render needs both at once anyway."""
        portal_folder = self.wsl["get_portal_folder"]()
        wiper = self._current_floor_wiper()

        def job(report_progress):
            floors = wiper.list_floors()
            suggested = set(fb.suggest_full_backup_floors(portal_folder))
            return floors, suggested

        background.run_in_background(self, job, on_done=self._on_refresh_full_backup_floor_picker_done)

    def _on_refresh_full_backup_floor_picker_done(self, result, error):
        if error is not None:
            messagebox.showerror(self.T("settings.dialog_title"), str(error))
            return
        floors, suggested = result
        self._full_backup_suggested = suggested
        self.full_backup_floor_listbox.delete(0, "end")
        for base_exponent in floors:
            label = f"10p{base_exponent}"
            if base_exponent in suggested:
                label += "  " + self.T("settings.full_backup_suggested_marker")
            self.full_backup_floor_listbox.insert("end", label)
        for i, base_exponent in enumerate(floors):
            if base_exponent in suggested:
                self.full_backup_floor_listbox.selection_set(i)

    def _selected_live_floors(self):
        floors = self._current_floor_wiper().list_floors()
        return [floors[i] for i in self.full_backup_floor_listbox.curselection()]

    def _refresh_full_backup_entries(self):
        """Repopulates the destination-side listbox -- what's actually backed up
        already, per list_full_backup_floors(), with each entry's own updated_at/file
        counts so it's clear this is a snapshot of the DESTINATION, not the live
        storage. Silently shows nothing if the destination isn't valid/reachable yet
        (e.g. freshly typed, not saved) -- this is a passive refresh, not an action, so
        it shouldn't pop up an error dialog on every keystroke.

        list_full_backup_floors() reads one JSON meta file per already-backed-up floor
        from `destination`, which is often an external/removable/network drive by design
        (see full_backup.py's own docstring) -- exactly the kind of slow-storage scan
        that justifies running this in the background. The listbox is cleared/repopulated
        entirely inside the done-callback (not here) so two rapid calls can't interleave
        and leave stale rows mixed with fresh ones."""
        destination = self._full_backup_destination()
        if not destination or not os.path.isdir(destination):
            self._full_backup_entries = []
            self.full_backup_entries_listbox.delete(0, "end")
            return
        background.run_in_background(
            self, lambda report_progress: fb.list_full_backup_floors(destination),
            on_done=self._on_refresh_full_backup_entries_done)

    def _on_refresh_full_backup_entries_done(self, entries, error):
        if error is not None:
            messagebox.showerror(self.T("settings.dialog_title"), str(error))
            return
        self._full_backup_entries = entries
        self.full_backup_entries_listbox.delete(0, "end")
        for base_exponent, meta in entries:
            self.full_backup_entries_listbox.insert("end", self.T(
                "settings.full_backup_entry_row", base_exponent=base_exponent,
                updated_at=meta.get("updated_at", "?"),
                windows=meta.get("source_window_count", 0),
                hits=meta.get("hit_file_count", 0)))

    def _selected_backup_entry_floor(self):
        sel = self.full_backup_entries_listbox.curselection()
        if not sel or sel[0] >= len(getattr(self, "_full_backup_entries", [])):
            return None
        return self._full_backup_entries[sel[0]][0]

    def _update_full_backup_buttons(self):
        running = self._full_backup_job_running
        state = "disabled" if running else "normal"
        self.full_backup_start_btn.configure(state=state)
        self.full_backup_restore_btn.configure(state=state)
        self.full_backup_delete_entry_btn.configure(state=state)
        self.full_backup_cancel_btn.configure(state=("normal" if running else "disabled"))

    def _on_start_full_backup(self):
        self._start_full_backup_job(mode="backup")

    def _on_start_full_restore(self):
        floor = self._selected_backup_entry_floor()
        if floor is None:
            messagebox.showinfo(self.T("settings.dialog_title"),
                                 self.T("settings.full_backup_select_entry_first"))
            return
        self._start_full_backup_job(mode="restore", floors=[floor])

    def _start_full_backup_job(self, mode, floors=None):
        if self._full_backup_job_running:
            return
        if floors is None:
            floors = self._selected_live_floors()
        if not floors:
            messagebox.showinfo(self.T("settings.dialog_title"),
                                 self.T("settings.full_backup_select_floor_first"))
            return
        destination = self._validate_full_backup_destination()
        if destination is None:
            return
        storage_path = self.wsl["get_portal_folder"]()

        self._full_backup_stop_event = threading.Event()
        self._full_backup_job_running = True
        self._update_full_backup_buttons()
        self.full_backup_progress.configure(mode="determinate", maximum=len(floors), value=0)
        self.full_backup_status_var.set(self.T(
            "settings.full_backup_status_starting",
            mode=self.T(f"settings.full_backup_mode_{mode}")))
        self.full_backup_file_status_var.set("")

        q = queue.Queue()
        self._full_backup_queue = q
        thread = threading.Thread(
            target=self._full_backup_worker,
            args=(mode, storage_path, destination, floors, self._full_backup_stop_event, q),
            daemon=True)
        thread.start()
        self._poll_full_backup_queue(mode)

    def _full_backup_worker(self, mode, storage_path, destination, floors, stop_event, q):
        """Runs off the main thread (see this module's docstring for the reasoning) --
        processes `floors` in order, one at a time, pushing progress/result messages onto
        `q` for _poll_full_backup_queue to pick up. Never touches any tkinter widget
        directly (that would be a cross-thread Tk call, unsafe) -- only the queue."""
        should_stop = stop_event.is_set
        for idx, base_exponent in enumerate(floors):
            q.put(("floor_start", base_exponent, idx, len(floors)))

            def progress_cb(phase, name, i, total, base_exponent=base_exponent):
                q.put(("file_progress", base_exponent, phase, name, i, total))

            try:
                if mode == "backup":
                    result = fb.copy_floor_increment(
                        storage_path, destination, base_exponent,
                        progress_cb=progress_cb, should_stop=should_stop)
                else:
                    result = fb.restore_floor_from_full_backup(
                        storage_path, destination, base_exponent,
                        progress_cb=progress_cb, should_stop=should_stop)
                q.put(("floor_done", base_exponent, result, None))
            except Exception as e:  # noqa: BLE001 -- must never kill this thread silently
                q.put(("floor_done", base_exponent, None, str(e)))
            if stop_event.is_set():
                break
        q.put(("__job_done__", stop_event.is_set()))

    def _poll_full_backup_queue(self, mode):
        try:
            while True:
                item = self._full_backup_queue.get_nowait()
                kind = item[0]
                if kind == "__job_done__":
                    self._on_full_backup_job_finished(mode, cancelled=item[1])
                    return
                elif kind == "floor_start":
                    _, base_exponent, idx, total_floors = item
                    self.full_backup_progress.configure(value=idx)
                    self.full_backup_status_var.set(self.T(
                        "settings.full_backup_status_floor",
                        base_exponent=base_exponent, idx=idx + 1, total=total_floors,
                        mode=self.T(f"settings.full_backup_mode_{mode}")))
                elif kind == "file_progress":
                    _, base_exponent, phase, name, i, total = item
                    self.full_backup_file_status_var.set(self.T(
                        "settings.full_backup_status_file",
                        phase=self.T(f"settings.full_backup_phase_{phase}"),
                        name=name, idx=i + 1, total=max(total, 1)))
                elif kind == "floor_done":
                    _, base_exponent, result, error = item
                    self._full_backup_log_floor_result(mode, base_exponent, result, error)
        except queue.Empty:
            pass
        self.after(150, lambda: self._poll_full_backup_queue(mode))

    def _full_backup_log_floor_result(self, mode, base_exponent, result, error):
        if error is not None:
            text = self.T("settings.full_backup_floor_error",
                           base_exponent=base_exponent, error=error)
        elif mode == "backup":
            text = self.T("settings.full_backup_floor_done",
                           base_exponent=base_exponent,
                           windows=result["copied_windows"], hits=result["copied_hits"])
        else:
            text = self.T("settings.full_backup_restore_floor_done",
                           base_exponent=base_exponent,
                           windows=result["restored_windows"], hits=result["restored_hits"])
        self._full_backup_log(text + "\n")

    def _on_full_backup_job_finished(self, mode, cancelled):
        self._full_backup_job_running = False
        self.full_backup_progress.configure(value=self.full_backup_progress["maximum"])
        self.full_backup_file_status_var.set("")
        self.full_backup_status_var.set(self.T(
            "settings.full_backup_status_cancelled" if cancelled
            else "settings.full_backup_status_done"))
        self._update_full_backup_buttons()
        self._refresh_full_backup_entries()
        self._refresh_full_backup_floor_picker()
        if mode == "restore":
            # Same reasoning as every other restore/delete path in this file -- a
            # restore writes real files onto disk that the Prime numbers /
            # Constellations tabs have no way to notice on their own.
            self.wsl["reload_primes_tree"]()
            self.wsl["reload_constellations_tree"]()

    def _on_cancel_full_backup(self):
        if self._full_backup_stop_event is not None:
            self._full_backup_stop_event.set()

    def _on_delete_full_backup_entry(self):
        base_exponent = self._selected_backup_entry_floor()
        if base_exponent is None:
            messagebox.showinfo(self.T("settings.dialog_title"),
                                 self.T("settings.full_backup_select_entry_first"))
            return
        destination = self._validate_full_backup_destination()
        if destination is None:
            return
        if not messagebox.askyesno(
                self.T("settings.dialog_title"),
                self.T("settings.full_backup_delete_entry_confirm", base_exponent=base_exponent)):
            return
        fb.delete_full_backup_floor(destination, base_exponent)
        self._full_backup_log(self.T(
            "settings.full_backup_entry_deleted", base_exponent=base_exponent) + "\n")
        self._refresh_full_backup_entries()

    def _full_backup_log(self, text):
        self.full_backup_console.append(text)

    def _build_full_backup_section(self, outer):
        """Full-data (compressed) backup, primeatlas/settings/full_backup.py -- see this module's
        docstring and that module's for the design. Own Labelframe inside the
        Backup tab's already-scrollable outer frame (see _build_widgets' own docstring
        for why every sub-tab is wrapped in a scrollable canvas), between the
        metadata-only backup/restore section above and the per-floor delete section
        below."""
        frame = ttk.Labelframe(outer, text=self.T("settings.full_backup_frame"))
        frame.pack(fill="both", expand=True, pady=(0, 8))
        ttk.Label(
            frame, text=self.T("settings.full_backup_hint"),
            style="Hint.TLabel", wraplength=760, justify="left").pack(
            anchor="w", padx=6, pady=(6, 4))

        dest_row = ttk.Frame(frame)
        dest_row.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(dest_row, text=self.T("settings.full_backup_dest_label")).pack(side="left")
        self.full_backup_dest_var = tk.StringVar(
            value=self.app_settings.full_backup_destination or "")
        ttk.Entry(dest_row, textvariable=self.full_backup_dest_var, width=48).pack(
            side="left", padx=(6, 6), fill="x", expand=True)
        ttk.Button(dest_row, text=self.T("settings.full_backup_browse_button"),
                   command=self._on_browse_full_backup_dest).pack(side="left")
        ttk.Button(dest_row, text=self.T("common.refresh"),
                   command=self._refresh_full_backup_entries).pack(side="left", padx=(6, 0))

        lists_row = ttk.Frame(frame)
        lists_row.pack(fill="both", expand=True, padx=6, pady=(0, 4))

        live_col = ttk.Frame(lists_row)
        live_col.pack(side="left", fill="both", expand=True, padx=(0, 4))
        ttk.Label(live_col, text=self.T("settings.full_backup_live_label")).pack(anchor="w")
        live_list_row = ttk.Frame(live_col)
        live_list_row.pack(fill="both", expand=True)
        self.full_backup_floor_listbox = tk.Listbox(
            live_list_row, height=5, exportselection=False, selectmode="extended")
        self.full_backup_floor_listbox.pack(side="left", fill="both", expand=True)
        live_scroll = ttk.Scrollbar(
            live_list_row, orient="vertical", command=self.full_backup_floor_listbox.yview)
        live_scroll.pack(side="left", fill="y")
        self.full_backup_floor_listbox.configure(yscrollcommand=live_scroll.set)
        self.full_backup_start_btn = ttk.Button(
            live_col, text=self.T("settings.full_backup_start_button"),
            command=self._on_start_full_backup)
        self.full_backup_start_btn.pack(anchor="w", pady=(4, 0))

        entries_col = ttk.Frame(lists_row)
        entries_col.pack(side="left", fill="both", expand=True, padx=(4, 0))
        ttk.Label(entries_col, text=self.T("settings.full_backup_entries_label")).pack(anchor="w")
        entries_list_row = ttk.Frame(entries_col)
        entries_list_row.pack(fill="both", expand=True)
        self.full_backup_entries_listbox = tk.Listbox(
            entries_list_row, height=5, exportselection=False)
        self.full_backup_entries_listbox.pack(side="left", fill="both", expand=True)
        entries_scroll = ttk.Scrollbar(
            entries_list_row, orient="vertical", command=self.full_backup_entries_listbox.yview)
        entries_scroll.pack(side="left", fill="y")
        self.full_backup_entries_listbox.configure(yscrollcommand=entries_scroll.set)
        # One grip under each column; both resize the two lists together so they stay
        # level side by side.
        full_backup_lists = [self.full_backup_floor_listbox, self.full_backup_entries_listbox]
        self.full_backup_lists_grip = HeightGrip(live_col, full_backup_lists,
                                                 after=live_list_row)
        self.full_backup_entries_grip = HeightGrip(entries_col, full_backup_lists,
                                                   after=entries_list_row)
        entries_btn_row = ttk.Frame(entries_col)
        entries_btn_row.pack(anchor="w", pady=(4, 0))
        self.full_backup_restore_btn = ttk.Button(
            entries_btn_row, text=self.T("settings.full_backup_restore_button"),
            command=self._on_start_full_restore)
        self.full_backup_restore_btn.pack(side="left")
        self.full_backup_delete_entry_btn = ttk.Button(
            entries_btn_row, text=self.T("settings.full_backup_delete_entry_button"),
            command=self._on_delete_full_backup_entry)
        self.full_backup_delete_entry_btn.pack(side="left", padx=(6, 0))

        progress_row = ttk.Frame(frame)
        progress_row.pack(fill="x", padx=6, pady=(4, 2))
        self.full_backup_progress = ttk.Progressbar(
            progress_row, orient="horizontal", mode="determinate", maximum=1, value=0)
        self.full_backup_progress.pack(fill="x")
        self.full_backup_cancel_btn = ttk.Button(
            frame, text=self.T("settings.full_backup_cancel_button"),
            command=self._on_cancel_full_backup, state="disabled")
        self.full_backup_cancel_btn.pack(anchor="w", padx=6, pady=(0, 2))
        self.full_backup_status_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.full_backup_status_var).pack(anchor="w", padx=6)
        self.full_backup_file_status_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.full_backup_file_status_var, style="Hint.TLabel").pack(
            anchor="w", padx=6, pady=(0, 4))

        self.full_backup_console = GenerationConsole(
            frame, self.T, height=5, start_visible=True,
            window_title=self.T("settings.full_backup_frame"))
        self.full_backup_output = self.full_backup_console.text
