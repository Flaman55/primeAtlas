"""BenchmarkExport -- the Benchmark tab's report exports: the PDF (benchmark.
render_benchmark_pdf()) and, from the "Export" menu, CSV, SVG, an HTML page and an HTML
snippet (report_export.py). Every export follows the tab's view: log scale, references,
hidden lines and pinned axes.

A BenchmarkTab mixin: it uses the tab's rows, points, view toggles, status variable and
translator, so it is never instantiated on its own.
"""
import datetime

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import report_export
from .benchmark import render_benchmark_pdf

_FILETYPES = {"csv": ("CSV", "*.csv"), "svg": ("SVG", "*.svg"), "html": ("HTML", "*.html"),
              "snippet": ("HTML", "*.html")}


class BenchmarkExport:
    def _build_export_controls(self, parent):
        """The "Save PDF" button and the "Export" menu, packed left in `parent`."""
        T = self.T
        ttk.Button(parent, text=T("bench.save_pdf"), command=self._export_benchmark_pdf).pack(
            side="left", padx=(6, 0))
        button = ttk.Menubutton(parent, text=T("bench.export_menu"))
        self.export_menu = tk.Menu(button, tearoff=False)
        for kind in report_export.KINDS:
            self.export_menu.add_command(label=T(f"bench.export_{kind}"),
                                         command=lambda k=kind: self._export_report(k))
        button.configure(menu=self.export_menu)
        button.pack(side="left", padx=(6, 0))

    def _view_options(self):
        return {"translator": self.T, "sieve_points": self._benchmark_sieve_nps_points,
                "references": self.references_var.get(), "log_y": self.log_scale_var.get(),
                "hidden_lines": self._hidden_lines, "y_pins": self._y_pins}

    def _ask_report_path(self, title, extension, filetype):
        T = self.T
        if not self._benchmark_fieldnames or not self._benchmark_rows:
            messagebox.showinfo(title, T("bench.no_data_dialog"))
            return None
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return filedialog.asksaveasfilename(
            title=T("bench.save_dialog_title"), initialdir=self._get_portal_folder(),
            initialfile=f"benchmark_report_{stamp}{extension}", defaultextension=extension,
            filetypes=[filetype, (T("common.all_files"), "*.*")]) or None

    def _report_saved(self, title, path):
        self.status.set(self.T("bench.status_saved", path=path))
        messagebox.showinfo(title, self.T("bench.saved_dialog", path=path))

    def _export_benchmark_pdf(self):
        T = self.T
        title = T("bench.save_pdf")
        path = self._ask_report_path(title, ".pdf", ("PDF", "*.pdf"))
        if not path:
            return
        options = self._view_options()
        try:
            render_benchmark_pdf(path, self._benchmark_growth_points,
                                  self._benchmark_fieldnames, self._benchmark_rows,
                                  points2=self._benchmark_fair_spw_points,
                                  write_points=self._benchmark_write_mbps_points, **options)
        except Exception as exc:
            messagebox.showerror(title, T("bench.save_error", error=exc))
            return
        self._report_saved(title, path)

    def _export_report(self, kind):
        """Writes the report as `kind` (report_export.KINDS) to a path the user picks."""
        T = self.T
        title = T(f"bench.export_{kind}")
        path = self._ask_report_path(title, report_export.EXTENSIONS[kind], _FILETYPES[kind])
        if not path:
            return
        try:
            report_export.export(kind, path, self._benchmark_fieldnames, self._benchmark_rows,
                                 **self._view_options())
        except Exception as exc:
            messagebox.showerror(title, T("bench.save_error", error=exc))
            return
        self._report_saved(title, path)
