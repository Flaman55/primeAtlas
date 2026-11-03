"""
delete_section.py -- DeleteSection, the delete actions of the Backup sub-tab: the
full-database delete and the two per-floor deletes (one floor's prime+constellation
data, or only that floor's constellations -- see FloorWiper in delete_manager.py), each
behind its warning/confirmation dialog.

A SettingsTab mixin: it uses the widgets, Variables and state that SettingsTab and its
other mixins set up, so it is never instantiated on its own.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from .delete_manager import PortalWiper, FloorWiper
from ..core import background


class DeleteSection:
    # ---- delete ---------------------------------------------------------------------------

    def _on_delete_clicked(self):
        portal_folder = self.wsl["get_portal_folder"]()
        wiper = PortalWiper(portal_folder)
        floors, row_count = wiper.plan()
        if not floors and row_count == 0:
            messagebox.showinfo(self.T("settings.delete_title"),
                                 self.T("settings.delete_already_empty"))
            return

        dialog = tk.Toplevel(self)
        dialog.title(self.T("settings.delete_dialog_title"))
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()

        msg = self.T(
            "settings.delete_confirm_msg",
            count=len(floors), names=(", ".join(floors) if floors else "-"),
            rows=row_count, folder=portal_folder)
        ttk.Label(dialog, text=msg, wraplength=480, justify="left").pack(padx=16, pady=16)

        btn_row = ttk.Frame(dialog)
        btn_row.pack(pady=(0, 16))

        def do_backup_and_delete():
            store = self._current_backup_store()
            manifest = store.create()
            self._refresh_backup_list()
            deleted, errors = wiper.execute()
            dialog.destroy()
            self._report_delete_result(deleted, errors, backed_up_as=manifest.name)

        def do_delete_only():
            deleted, errors = wiper.execute()
            dialog.destroy()
            self._report_delete_result(deleted, errors, backed_up_as=None)

        def do_cancel():
            dialog.destroy()

        ttk.Button(btn_row, text=self.T("settings.delete_backup_and_delete"),
                   command=do_backup_and_delete).pack(side="left", padx=6)
        ttk.Button(btn_row, text=self.T("settings.delete_only"),
                   command=do_delete_only).pack(side="left", padx=6)
        ttk.Button(btn_row, text=self.T("settings.delete_cancel"),
                   command=do_cancel).pack(side="left", padx=6)

    def _report_delete_result(self, deleted, errors, backed_up_as):
        lines = []
        if backed_up_as:
            lines.append(self.T("settings.delete_backed_up_as", name=backed_up_as))
        lines.append(self.T(
            "settings.delete_result", count=len(deleted),
            names=(", ".join(deleted) if deleted else "-")))
        if errors:
            lines.append(self.T("settings.delete_errors_header"))
            lines.extend(f"  {e}" for e in errors)
        text = "\n".join(lines)
        self._restore_log(text + "\n")
        if errors:
            messagebox.showwarning(self.T("settings.delete_title"), text)
        else:
            messagebox.showinfo(self.T("settings.delete_title"), text)
        self._refresh_backup_list()
        self._scan_incomplete_restores()
        # Refresh the Prime numbers / Constellations trees after a full-database delete,
        # otherwise they keep showing the deleted floors until a manual Refresh. See
        # wsl_helpers' comment in primeatlas/app/ for why these two callables are passed
        # in rather than imported directly.
        self.wsl["reload_primes_tree"]()
        self.wsl["reload_constellations_tree"]()

    # ---- delete: single floor / that floor's constellations only -------------------------

    def _current_floor_wiper(self):
        # Same "rebuild on every call, don't cache" reasoning as
        # _current_backup_store() -- always reflects whatever storage path is CURRENT.
        return FloorWiper(self.wsl["get_portal_folder"]())

    def _refresh_floor_delete_list(self):
        """Repopulates the floor-picker combobox shared by both per-floor delete
        buttons below -- called at tab-construction time and after every delete (a
        just-emptied floor should disappear from the list, and one added by a
        Generation run in the meantime should appear).

        list_floors() is a cheap top-level os.listdir(), backgrounded for the same
        consistency reasons as _refresh_backup_list right above."""
        wiper = self._current_floor_wiper()
        background.run_in_background(
            self, lambda report_progress: wiper.list_floors(),
            on_done=self._on_refresh_floor_delete_list_done)

    def _on_refresh_floor_delete_list_done(self, floors, error):
        if error is not None:
            messagebox.showerror(self.T("settings.dialog_title"), str(error))
            return
        values = [f"10p{f}" for f in floors]
        self.floor_delete_combo.configure(values=values)
        current = self.floor_delete_var.get()
        if current not in values:
            self.floor_delete_var.set(values[0] if values else "")

    def _selected_delete_floor(self):
        """Parses the combobox's "10p{N}" label back into the int base_exponent, or
        None if nothing valid is selected -- shared by both delete buttons below so
        the "nothing selected" / "bad value" error is worded identically either way."""
        label = self.floor_delete_var.get().strip()
        if not label.startswith("10p") or not label[3:].isdigit():
            return None
        return int(label[3:])

    def _on_delete_floor_clicked(self):
        """Deletes ONE floor entirely (10p{N}/source_primes/ AND
        10p{N}/constellations/ together, since they share that one directory) plus
        that floor's own benchmark_log.csv rows -- see FloorWiper.execute_delete_floor's
        own docstring. Distinct from the whole-database delete above: this clears a
        SINGLE floor someone wants to force-regenerate, without touching any other
        floor's data."""
        base_exponent = self._selected_delete_floor()
        if base_exponent is None:
            messagebox.showinfo(self.T("settings.delete_title"),
                                 self.T("settings.delete_floor_select_first"))
            return
        wiper = self._current_floor_wiper()
        window_count, hit_count = wiper.plan_floor(base_exponent)
        if window_count == 0 and hit_count == 0:
            messagebox.showinfo(self.T("settings.delete_title"),
                                 self.T("settings.delete_already_empty"))
            return
        if not messagebox.askyesno(
                self.T("settings.delete_floor_dialog_title"),
                self.T("settings.delete_floor_confirm", base_exponent=base_exponent,
                        windows=window_count, hits=hit_count)):
            return
        ok, error = wiper.execute_delete_floor(base_exponent)
        self._report_floor_delete_result(base_exponent, ok, error, constellations_only=False)

    def _on_delete_floor_constellations_clicked(self):
        """Deletes ONLY the selected floor's constellations/ subfolder -- its
        source_primes/ (and that floor's own benchmark_log.csv rows, which describe
        prime generation, not constellation-finding) are left untouched. Useful to
        force a clean re-run of constellation_finder_v2_3.py -- e.g. after the pattern
        catalog changes -- without regenerating that floor's (often much more
        expensive to produce) prime data."""
        base_exponent = self._selected_delete_floor()
        if base_exponent is None:
            messagebox.showinfo(self.T("settings.delete_title"),
                                 self.T("settings.delete_floor_select_first"))
            return
        wiper = self._current_floor_wiper()
        hit_count = wiper.plan_constellations(base_exponent)
        if hit_count == 0:
            messagebox.showinfo(self.T("settings.delete_title"),
                                 self.T("settings.delete_constellations_already_empty",
                                         base_exponent=base_exponent))
            return
        if not messagebox.askyesno(
                self.T("settings.delete_floor_dialog_title"),
                self.T("settings.delete_constellations_confirm",
                        base_exponent=base_exponent, hits=hit_count)):
            return
        ok, error = wiper.execute_delete_constellations(base_exponent)
        self._report_floor_delete_result(base_exponent, ok, error, constellations_only=True)

    def _report_floor_delete_result(self, base_exponent, ok, error, constellations_only):
        if error is not None:
            text = self.T("settings.delete_floor_error", base_exponent=base_exponent, error=error)
            self._restore_log(text + "\n")
            messagebox.showwarning(self.T("settings.delete_title"), text)
        elif ok:
            key = ("settings.delete_constellations_done" if constellations_only
                   else "settings.delete_floor_done")
            text = self.T(key, base_exponent=base_exponent)
            self._restore_log(text + "\n")
            messagebox.showinfo(self.T("settings.delete_title"), text)
        # ok=False, error=None means "nothing there" -- already handled by the
        # plan_floor/plan_constellations==0 early-return in the callers above, so
        # there's nothing further to report here (execute_* only returns this
        # combination if the folder vanished between the plan and the click, an
        # acceptable, silent no-op rather than a spurious error).
        self._refresh_floor_delete_list()
        self._refresh_backup_list()
        self._scan_incomplete_restores()
        # Same reasoning as _report_delete_result's own call to these two -- the
        # Prime numbers / Constellations tabs have no way to notice a floor's files
        # disappearing on their own.
        self.wsl["reload_primes_tree"]()
        self.wsl["reload_constellations_tree"]()
