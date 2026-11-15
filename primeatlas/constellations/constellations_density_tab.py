"""
constellations_density_tab.py -- ConstellationsDensityTab, the Constellations tab's "Density"
sub-tab: for a chosen k (and an optional floor range), the hits of each variant inside the
spans the constellation finder has scanned next to the Hardy-Littlewood prediction for the
same spans (density_scan.py), as a table of floor x variant rows plus a sum row per floor
when k has several variants, and a chart of hits / prediction per floor for the row
selected in the table.

The scan runs on its own background.PersistentWorker; Stop sets a threading.Event the scan
checks between windows and pages, and the floors finished before it are shown. The shared
status/progress bar shows floors done out of floors in range.
"""
import threading

import tkinter as tk
from tkinter import ttk, messagebox

import pattern_catalog_v1

from ..core import background, theme_dynamic
from ..core.base_tab import BaseTab
from ..core.progress_bar_owner import claim_progress_bar
from ..core.theme import palette_for
from ..core.ui_state import remember
from ..core.widgets import HeightGrip, StripedTreeview
from .density_chart import draw_ratio_chart
from .density_scan import scan_density

COLUMNS = ("floor", "pattern", "width", "hits", "expected", "ratio", "sigma")
_WIDTHS = {"floor": 70, "pattern": 90, "width": 170, "hits": 90, "expected": 110,
           "ratio": 180, "sigma": 120}
DASH = "—"


def format_width(width):
    return f"{width:,}" if width < 10 ** 15 else f"{width:.4e}"


def format_row(row):
    """Table cells of one scan row, without the pattern label."""
    ratio, sigma = row["ratio"], row["sigma"]
    return (f"10p{row['base_exponent']}", format_width(row["width"]), f"{row['hits']:,}",
            f"{row['expected']:.4g}", DASH if ratio is None else f"{ratio:.4f}",
            DASH if sigma is None else f"{sigma:+.2f}")


class ConstellationsDensityTab(BaseTab):
    def __init__(self, parent, get_portal_folder, status_var, translator, eval_quick_number,
                 totals_progress):
        """get_portal_folder/status_var/translator/eval_quick_number/totals_progress: as
        ConstellationsRecordsTab takes them."""
        super().__init__(parent, translator)
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self._eval_quick_number = eval_quick_number
        self.totals_progress = totals_progress
        self.palette = palette_for(theme_dynamic.THEME)
        self._busy = False
        self._stop_event = threading.Event()
        self.rows = []
        self.series_key = None  # (k, variant_id or None) drawn in the chart
        self._row_keys = {}  # tree item -> (k, variant_id)
        self._worker = background.PersistentWorker(
            self, self._job, on_result=self._on_result, on_progress=self._on_progress)
        self._build_widgets()

    def _build_widgets(self):
        T = self.T
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=12, pady=12)

        top_row = ttk.Frame(container)
        top_row.pack(fill="x", pady=(0, 8))
        ttk.Label(top_row, text=T("const_records.field_k")).pack(side="left")
        self.k_combo = ttk.Combobox(top_row, state="readonly", width=6,
                                    values=[str(k) for k in pattern_catalog_v1.all_k()])
        self.k_combo.pack(side="left", padx=(6, 16))
        ttk.Label(top_row, text=T("const_records.field_floor_from")).pack(side="left")
        self.floor_from_entry = ttk.Entry(top_row, width=8)
        self.floor_from_entry.pack(side="left", padx=(6, 12))
        ttk.Label(top_row, text=T("const_records.field_floor_to")).pack(side="left")
        self.floor_to_entry = ttk.Entry(top_row, width=8)
        self.floor_to_entry.pack(side="left", padx=(6, 16))
        self.scan_button = ttk.Button(top_row, text=T("const_records.scan_button"),
                                      command=self._on_scan_clicked)
        self.scan_button.pack(side="left")
        self.stop_button = ttk.Button(top_row, text=T("common.stop"), state="disabled",
                                      command=self._on_stop_clicked)
        self.stop_button.pack(side="left", padx=(6, 0))

        ttk.Label(container, text=T("const_density.hint"), wraplength=760, justify="left",
                  style="Hint.TLabel").pack(anchor="w", pady=(0, 8))

        self.tree_frame = ttk.Frame(container)
        self.tree_frame.pack(fill="x")
        self.tree = StripedTreeview(self.tree_frame, columns=COLUMNS, show="headings",
                                    height=8, selectmode="browse")
        for col in COLUMNS:
            self.tree.heading(col, text=T(f"const_density.col_{col}"))
            self.tree.column(col, width=_WIDTHS[col], stretch=False,
                             anchor="w" if col == "pattern" else "e")
        vsb = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self.tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        HeightGrip(container, self.tree, after=self.tree_frame, pady=(2, 4))

        self.notes_var = tk.StringVar(value="")
        ttk.Label(container, textvariable=self.notes_var, wraplength=760, justify="left",
                  style="Hint.TLabel").pack(anchor="w", pady=(0, 6))

        self.canvas = tk.Canvas(container, width=640, height=260,
                                background=self.palette["console_bg"], highlightthickness=1,
                                highlightbackground=self.palette["border"])
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.redraw_chart())

        if pattern_catalog_v1.all_k():
            self.k_combo.current(0)
        remember("constellations.density.k", self.k_combo)
        remember("constellations.density.floor_from", self.floor_from_entry)
        remember("constellations.density.floor_to", self.floor_to_entry)
        self.redraw_chart()

    # --- scan ------------------------------------------------------------------------

    def _on_scan_clicked(self):
        if self._busy:
            return
        T = self.T
        k_str = self.k_combo.get()
        if not k_str:
            messagebox.showerror(T("const_records.error_dialog_title"),
                                 T("const_calc.error_no_pattern"))
            return
        floor_min = self._eval_quick_number(self.floor_from_entry.get())
        floor_max = self._eval_quick_number(self.floor_to_entry.get())
        if floor_min is not None and floor_max is not None and floor_min > floor_max:
            messagebox.showerror(T("const_records.error_dialog_title"),
                                 T("const_records.error_invalid_range"))
            return
        k = int(k_str)
        self._busy = True
        self._stop_event = threading.Event()
        self.scan_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._start_busy_progress()
        self.status.set(T("const_density.status_scanning", k=k))
        self._worker.submit({"k": k, "floor_min": floor_min, "floor_max": floor_max,
                             "stop_event": self._stop_event})

    def _on_stop_clicked(self):
        if self._busy:
            self._stop_event.set()
            self.stop_button.configure(state="disabled")

    def _job(self, job, report_progress):
        """Worker thread: (k, rows, notes, stopped), or (k, None, error text, False)."""
        try:
            rows, notes, stopped = scan_density(
                self._get_portal_folder(), job["k"], job["floor_min"], job["floor_max"],
                stop_event=job["stop_event"], report_progress=report_progress)
            return job["k"], rows, notes, stopped
        except Exception as e:  # noqa: BLE001 -- must never kill this thread
            return job["k"], None, str(e), False

    def _on_progress(self, payload):
        done, total = payload
        if self._busy and claim_progress_bar(self.totals_progress, self):
            self.totals_progress.stop()
            self.totals_progress.configure(mode="determinate", maximum=max(1, total), value=done)

    def _on_result(self, payload, error):
        T = self.T
        self._busy = False
        self.scan_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self._stop_busy_progress()
        if error is not None or payload[1] is None:
            self.status.set(T("const_records.status_error"))
            messagebox.showerror(T("const_records.error_dialog_title"),
                                 str(error if error is not None else payload[2]))
            return
        k, rows, notes, stopped = payload
        self.show_results(k, rows, notes)
        floors = len({r["base_exponent"] for r in rows})
        if stopped:
            self.status.set(T("const_density.status_stopped", floors=floors))
        else:
            self.status.set(T("const_density.status_done", rows=len(rows), floors=floors))

    # --- results ---------------------------------------------------------------------

    def pattern_label(self, k, variant_id):
        if variant_id is None:
            return self.T("const_density.sum_label", k=k)
        return self.T("const_calc.variant_label", id=variant_id)

    def show_results(self, k, rows, notes):
        T = self.T
        self.rows = rows
        self.tree.delete(*self.tree.get_children())
        self._row_keys = {}
        for row in rows:
            cells = format_row(row)
            item = self.tree.insert("", "end", values=(
                cells[0], self.pattern_label(k, row["variant_id"])) + cells[1:])
            self._row_keys[item] = (k, row["variant_id"])
        keys = [(k, r["variant_id"]) for r in rows]
        self.series_key = (k, None) if (k, None) in keys else (keys[0] if keys else None)
        scanned = [info for _f, info in notes if info["done"]]
        if not rows:
            self.notes_var.set(T("const_density.no_rows"))
        else:
            self.notes_var.set(T(
                "const_density.notes", floors=len(notes), scanned=len(scanned),
                done=sum(i["done"] for i in scanned), windows=sum(i["windows"] for i in scanned),
                decoded=sum(i["decoded"] for i in scanned),
                unreadable=sum(i["unreadable"] for _f, i in notes)))
        self.redraw_chart()

    def _on_select(self, _event=None):
        selected = self.tree.selection()
        if selected and selected[0] in self._row_keys:
            self.series_key = self._row_keys[selected[0]]
            self.redraw_chart()

    def chart_points(self):
        """(floor, ratio, 1/sqrt(expected)) for the rows of the series in the chart."""
        if self.series_key is None:
            return []
        k, vid = self.series_key
        return [(r["base_exponent"], r["ratio"], r["expected"] ** -0.5) for r in self.rows
                if r["k"] == k and r["variant_id"] == vid and r["ratio"] is not None]

    def redraw_chart(self):
        T = self.T
        if self.series_key is None:
            title = T("const_density.chart_title_none")
        else:
            k, vid = self.series_key
            pattern = self.pattern_label(k, vid) if vid is None else (
                f"k={k} {self.pattern_label(k, vid)}")
            title = T("const_density.chart_title", pattern=pattern)
        draw_ratio_chart(self.canvas, self.chart_points(), self.palette, title,
                         T("const_density.chart_empty"))
