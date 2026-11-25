"""
benchmark_tab.py -- BenchmarkTab, the tkinter widgets for the Benchmark tab: a small
dependency-free growth chart (numbers/s vs. floor depth, one point per floor -- latest
logged run wins) plus a phase-breakdown chart (sieve-numbers/s + write-MB/s), above a
paginated, lazily-expandable tree view of the full benchmark_log.csv (written by
orchestrator_v3.py's print_benchmark_summary()); a "Save PDF" button renders the same
chart(s) + full table into a standalone PDF report.

Split out of PortalBrowserApp's tab-by-tab backend/UI separation: this module owns
only the widgets; the on-screen chart drawing is chart_canvas.py (_draw_growth_chart).
All the pure-logic reduction/PDF-rendering work lives in
primeatlas/benchmark/benchmark.py.

This module imports tkinter; the pure logic it shows lives in benchmark.py, the
"pure logic elsewhere" convention the package follows.

BenchmarkTab does not know how PORTAL_FOLDER is stored or how the app's shared status
bar/translator are constructed -- it receives everything it needs at construction time
(get_portal_folder, status_var, translator, update_nav_controls) instead of importing
primeatlas/app/ directly, which would be circular (that file imports BenchmarkTab
from this module). update_nav_controls in particular is PortalBrowserApp's own small
shared pagination-label/button helper, used identically by every OTHER tab's own
pagination (Prime numbers, Constellations, Goldbach, ...) -- it stays put there rather
than being duplicated or promoted to its own module just for this one extraction, and
is passed in exactly like SettingsTab's wsl_helpers callables are.
"""
import tkinter as tk
from tkinter import ttk

from ..core import number_field
from ..core.number_text import plain_number
from ..core.base_tab import BaseTab
from ..core.ui_state import remember
from ..core.widgets import FitLabel, FlowRow, HeightGrip, StripedTreeview
from .benchmark import (
    BENCHMARK_PAGE_SIZE, aggregate_benchmark_fair_spw,
    aggregate_benchmark_growth, aggregate_benchmark_sieve_nps,
    aggregate_benchmark_write_mbps, benchmark_series, mixed_width_floors,
    group_benchmark_rows_by_floor, read_benchmark_log,
)
from .chart_series import axis_pins, clear_pins, pin_bound, toggle_keys
from . import chart_canvas, chart_view, computer_names
from .benchmark_chart_windows import BenchmarkChartWindows
from .benchmark_export import BenchmarkExport
from .benchmark_filter import BenchmarkFilter
from .benchmark_line_colors import BenchmarkLineColors
from .benchmark_points import BenchmarkPoints
from .benchmark_table_copy import BenchmarkTableCopy
from .benchmark_table_layout import BenchmarkTableLayout
from .benchmark_view_state import BenchmarkViewState
from .computer_cell import ComputerCell
from .benchmark_ram_chart import BenchmarkRamChart
from .chart_zoom_controls import BenchmarkChartZoom
from . import sieve_measure, table_columns
from .reference_points import reference_series


class BenchmarkTab(BenchmarkExport, BenchmarkFilter, BenchmarkLineColors, BenchmarkPoints,
                   BenchmarkRamChart, BenchmarkChartZoom, BenchmarkChartWindows,
                   BenchmarkViewState, BenchmarkTableCopy, BenchmarkTableLayout,
                   BaseTab):
    def __init__(self, parent, get_portal_folder, status_var, translator, update_nav_controls,
                 theme_palette, on_rows_loaded=None):
        """
        on_rows_loaded(rows): called with the log's rows after every reload (the app's
        about.machine_prompt.MachinePrompt.after_rows).

        theme_palette: the CURRENT theme's color dict (primeatlas.core.theme.palette_for()'s
        return value, e.g. {"fg": ..., "tree_group_bg": ..., "tree_stat_bg": ..., ...}),
        passed in explicitly rather than read from a bare global -- same dependency-
        injection reasoning as every other constructor parameter here. Needed because
        this tab's own tree "floor"/"stat" row-highlight tags (see _build_widgets'
        own tag_configure calls) are a per-item ttk.Treeview override that
        PortalBrowserApp._apply_theme()'s ttk.Style() calls can never reach -- see
        primeatlas/core/theme.py's own docstring on tree_group_bg/tree_stat_bg for the bug
        this fixes (light-hardcoded row highlights were unreadable in dark mode)."""
        super().__init__(parent, translator)
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self._update_nav_controls = update_nav_controls
        self._theme_palette = theme_palette
        self._on_rows_loaded = on_rows_loaded
        self._init_points()
        self._init_filter()
        self._init_chart_windows()
        self._init_chart_zoom()

        self._build_widgets()
        self._load_view()

    def _build_widgets(self):
        T = self.T

        # Controls wrap whole onto the next line in a narrow window.
        top = FlowRow(self)
        top.frame.pack(fill="x", padx=6, pady=4)
        # "Points of different widths on floor N" under each chart, set by its redraw.
        self.mixed_widths_vars = {"run": tk.StringVar(), "sieve": tk.StringVar(),
                                  "ram": tk.StringVar()}
        # Chart view toggles; every export follows them, the lines hidden from each chart's
        # legend ({chart: set of line_key()}, kept across restarts: benchmark_view_state.py)
        # and the pinned y-axis bounds ({chart: {axis: (min, max)}}, set from the
        # right-click menu, kept for the session).
        self._hidden_lines = {"run": set(), "sieve": set(), "ram": set()}
        self._y_pins = {"run": {}, "sieve": {}, "ram": {}}
        self.log_scale_var = tk.BooleanVar(value=False)
        self.references_var = tk.BooleanVar(value=False)
        remember("benchmark.log_scale", self.log_scale_var)
        remember("benchmark.show_references", self.references_var)
        top.add(ttk.Button(top.frame, text=T("common.refresh"),
                           command=self.reload_benchmark_log))
        export_group = ttk.Frame(top.frame)
        self._build_export_controls(export_group)
        top.add(export_group)
        top.add(ttk.Button(top.frame, text=T("bench.filter_button"),
                           command=self._open_filter_window), padx_left=6)
        top.add(FitLabel(top.frame, textvariable=self.filter_summary_var,
                         style="Status.TLabel"), padx_left=6)
        self.filter_summary_var.trace_add("write", lambda *_a: top.relayout())
        toggles = ttk.Frame(top.frame)
        ttk.Checkbutton(toggles, text=T("bench.show_references"), variable=self.references_var,
                        command=self._redraw_charts).pack(side="left")
        ttk.Checkbutton(toggles, text=T("bench.log_scale"), variable=self.log_scale_var,
                        command=self._redraw_charts).pack(side="left", padx=(8, 0))
        top.add(toggles, padx_left=12)

        # The charts stand one under another, full width: the sieve, the whole run (sieve
        # + write), RAM. Canvas colors come from the CURRENT theme (console_bg/border, the
        # keys the app's other canvas-like widgets use) so the dark theme does not keep a
        # light chart; chart_canvas._draw_growth_chart's bg_color/fg_color/grid_color (passed by
        # _draw_chart below) keep ticks and axis titles readable on it. Each chart is
        # always shown: _draw_growth_chart() draws a "no data yet" placeholder when its
        # series are empty. A mixed-width note is packed under its chart only while it
        # has text, so an empty one takes no height. Each chart's height is its grip's
        # (layout_const: one default for the three, remembered per chart).
        p = self._theme_palette
        self._mixed_widths_labels = {}
        chart_frame2 = self._chart_frame("sieve")
        self.benchmark_chart2 = tk.Canvas(chart_frame2, background=p["console_bg"],
                                           highlightthickness=1, highlightbackground=p["border"])
        self.benchmark_chart2.pack(fill="x")
        sieve_grip = HeightGrip(chart_frame2, self.benchmark_chart2,
                                after=self.benchmark_chart2, place="benchmark.sieve_chart")
        self.benchmark_chart2.bind("<Configure>", lambda _e: self._redraw_benchmark_chart2())
        self._bind_chart_zoom(self.benchmark_chart2, "sieve")
        self._mixed_widths_labels["sieve"] = (
            ttk.Label(chart_frame2, style="Status.TLabel",
                      textvariable=self.mixed_widths_vars["sieve"]), sieve_grip.frame)

        chart_frame = self._chart_frame("run")
        self.benchmark_chart = tk.Canvas(chart_frame, background=p["console_bg"],
                                          highlightthickness=1, highlightbackground=p["border"])
        self.benchmark_chart.pack(fill="x")
        run_grip = HeightGrip(chart_frame, self.benchmark_chart, after=self.benchmark_chart,
                              place="benchmark.run_chart")
        self.benchmark_chart.bind("<Configure>", lambda _e: self._redraw_benchmark_chart())
        self._bind_chart_zoom(self.benchmark_chart, "run")
        self._mixed_widths_labels["run"] = (
            ttk.Label(chart_frame, style="Status.TLabel",
                      textvariable=self.mixed_widths_vars["run"]), run_grip.frame)

        self._build_ram_chart(self._chart_frame("ram"))

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="x", padx=6, pady=(4, 0))

        # Floor pagination -- ABOVE the tree, same Prev/label/Next/goto layout as the
        # "Prime numbers" tab's floor nav (see that tab's own _build_primes_tab for the
        # full rationale). benchmark_log.csv gets a row per orchestrator run
        # (including cheap, repeatable count-only benchmarking runs -- see the
        # write_files toggle), so a floor can accumulate dozens-to-hundreds of rows;
        # expanding a floor only lists/groups rows already in memory (cheap -- the
        # whole CSV is small text) and INSERTS one page's worth of Treeview rows at a
        # time (inserting all of them is what would freeze the GUI).
        # Its groups wrap whole onto the next line in a narrow window.
        benchmark_nav = FlowRow(tree_frame)
        benchmark_nav.frame.pack(fill="x", pady=(0, 4))
        pages = ttk.Frame(benchmark_nav.frame)
        self.benchmark_prev_btn = ttk.Button(
            pages, text=T("common.prev_page"), command=self._prev_benchmark_page,
            state="disabled")
        self.benchmark_prev_btn.pack(side="left")
        self.benchmark_page_label = tk.StringVar(value="")
        ttk.Label(pages, textvariable=self.benchmark_page_label, width=16,
                  anchor="center").pack(side="left")
        self.benchmark_next_btn = ttk.Button(
            pages, text=T("common.next_page"), command=self._next_benchmark_page,
            state="disabled")
        self.benchmark_next_btn.pack(side="left")
        benchmark_nav.add(pages)
        goto = ttk.Frame(benchmark_nav.frame)
        ttk.Label(goto, text=T("common.page_prefix")).pack(side="left")
        self.benchmark_goto_entry = ttk.Entry(goto, width=6)
        number_field.attach(self.benchmark_goto_entry, self.T, "field_tip.goto_page", minimum=1)
        self.benchmark_goto_entry.pack(side="left", padx=(4, 0))
        self.benchmark_goto_entry.bind("<Return>", lambda _e: self._goto_benchmark_page())
        ttk.Button(goto, text=T("common.goto"), command=self._goto_benchmark_page).pack(
            side="left", padx=(4, 0))
        benchmark_nav.add(goto, padx_left=10)
        hint = ttk.Frame(benchmark_nav.frame)
        self._build_table_copy_hint(hint)
        benchmark_nav.add(hint, padx_left=16)

        # The tree's height is its grip's (under the tree frame), never stretched to the
        # page.
        self.benchmark_tree = StripedTreeview(tree_frame, show="tree headings", height=10)
        self.benchmark_tree.heading("#0", text=T("bench.col_floor"))
        self.benchmark_tree.column("#0", width=170, stretch=False)
        # Horizontal scrollbar -- with 11 data columns + #0, the row is wider than the
        # tab, and without this the only way to see the columns off the right edge was
        # shrinking every column's width by hand. stretch=False on every column (set
        # below, in reload_benchmark_log()) keeps each column at its given width instead
        # of Tk auto-stretching the last one to fill the widget, which is what makes the
        # row properly wider than the view and the scrollbar actually needed/usable.
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.benchmark_tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.benchmark_tree.xview)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.benchmark_tree.configure(yscrollcommand=vsb.set,
                                      xscrollcommand=self._build_table_heading(tree_frame, hsb.set))
        self.benchmark_tree.pack(side="left", fill="both", expand=True)
        HeightGrip(self, self.benchmark_tree, after=tree_frame, padx=6, pady=(2, 4),
                   place="benchmark.table")

        # Explicit foreground alongside each background -- a tag's own colors
        # override the base "Treeview" ttk.Style() colors per-row (see this
        # constructor's own docstring), so without pairing them here, dark mode
        # would keep the (light) style-level foreground on top of these
        # theme-appropriate backgrounds and still be unreadable.
        p = self._theme_palette
        self.benchmark_tree.tag_configure("floor", background=p["tree_group_bg"], foreground=p["fg"])
        self.benchmark_tree.tag_configure("stat", background=p["tree_stat_bg"], foreground=p["fg"])

        self.benchmark_tree.bind("<<TreeviewOpen>>", self._on_benchmark_tree_open)
        self.benchmark_tree.bind("<<TreeviewClose>>", self._on_benchmark_tree_close)
        self.benchmark_tree.bind("<<TreeviewSelect>>", self._on_benchmark_tree_select)
        self._bind_tree_points()
        self._bind_table_copy()
        self.computer_cell = ComputerCell(self.benchmark_tree, self.T, self._get_portal_folder,
                                          lambda item: self._tree_item_rows.get(item))
        self._machines = {}

        self._benchmark_growth_points = []
        self._benchmark_fair_spw_points = []  # loop_seconds_per_window, second chart line
        self._benchmark_sieve_nps_points = []   # sieve-phase numbers/s, second CHART's
                                                 # primary line (v4.1 and v5 engine rows
                                                 # only -- see aggregate_benchmark_sieve_nps)
        self._benchmark_write_mbps_points = []  # write-phase MB/s, second chart's
                                                 # secondary line (same v4.1/v5-only caveat)
        self._benchmark_fieldnames = []  # kept in sync by reload_benchmark_log() --
        self._benchmark_rows = []        # _export_benchmark_pdf reads these (the FULL,
                                          # ungrouped data) instead of re-parsing the CSV,
                                          # so the PDF always exports everything, even
                                          # rows not currently paged into view.
        self._benchmark_rows_by_floor = {}   # base_exponent -> [rows...], built by
                                               # reload_benchmark_log() via
                                               # group_benchmark_rows_by_floor()
        self._tree_floor_nodes = {}          # floor item id -> base_exponent
        self._benchmark_floor_state = {}     # tree item id -> {base_exponent, rows,
                                               # stats, page, total_pages} -- lazily
                                               # populated on <<TreeviewOpen>>, dropped on
                                               # <<TreeviewClose>>, same lifecycle as the
                                               # primes tab's _floor_state.
        self._active_benchmark_node = None    # which floor's page the nav buttons above
                                               # currently operate on

    def _redraw_benchmark_chart(self):
        # Before the window has actually been mapped/laid out by the OS window manager
        # (e.g. the very first draw, triggered from reload_benchmark_log() during
        # __init__), winfo_width()/height() can still report the Tk default of 1x1 --
        # <Configure> will fire and redraw properly once real geometry is assigned, but
        # falling back to a reasonable size here means the chart doesn't sit blank in
        # the meantime.
        self._show_mixed_widths("run", ("growth", "write"))
        self._draw_chart("run", self.benchmark_chart, self._benchmark_growth_points, (900, 180),
                         points2=self._benchmark_write_mbps_points,
                         label_key1="bench.axis_total_nps",
                         label_key2="bench.axis_write_mbps", places2=1,
                         series1=self._chart_series("growth"),
                         series2=self._chart_series("write"),
                         marks=self._chart_marks("growth", "write"))

    def _draw_chart(self, chart, canvas, points, default_size, **kwargs):
        """chart_canvas._draw_growth_chart() on `canvas` and on the chart's open window
        (benchmark_chart_windows.py) with the view state of `chart` ("run", "sieve", "ram"):
        log scale, hidden lines, pinned axes, the zoomed floor range, theme colors;
        `default_size` (width, height) stands in while a canvas is not laid out yet."""
        p = self._theme_palette
        for target in [canvas] + self._chart_window_canvases(chart):
            width, height = target.winfo_width(), target.winfo_height()
            width = default_size[0] if width <= 1 else width
            height = default_size[1] if height <= 1 else height
            chart_canvas._draw_growth_chart(
                target, points, width, height, translator=self.T,
                log_y=self.log_scale_var.get(), hidden=self._hidden_lines[chart],
                on_toggle=lambda keys: self._toggle_lines(chart, keys),
                pins1=axis_pins(self._y_pins[chart], "primary"),
                pins2=axis_pins(self._y_pins[chart], "secondary"),
                on_pin_menu=lambda *a: self._on_pin_menu(chart, *a),
                on_color_menu=self._on_color_menu,
                bg_color=p["console_bg"], fg_color=p["console_fg"],
                grid_color=p["border"], x_view=self._x_view,
                y_view=self._y_views[chart], x_mode=self._x_mode, **kwargs)

    def _chart_series(self, metric, references=False):
        """One Series per engine for a chart metric; with references=True, the reference
        lines too while the "Reference points" toggle is on. PARI/GP writes nothing, so the
        references go on the sieve chart."""
        series = benchmark_series(self._filtered_rows(), metric, self._metric_view(metric))
        if references and self.references_var.get():
            series += reference_series(self.T)
        return series

    def _toggle_lines(self, chart, keys):
        """Legend click on the "run", "sieve" or "ram" chart: flips those keys (chart_series)."""
        self._hidden_lines[chart] = toggle_keys(self._hidden_lines[chart], keys)
        self._save_view()
        self._redraw_chart(chart)

    def _redraw_chart(self, chart):
        if chart == "run":
            self._redraw_benchmark_chart()
        elif chart == "ram":
            self._redraw_benchmark_chart3()
        else:
            self._redraw_benchmark_chart2()

    def _redraw_charts(self):
        self._redraw_benchmark_chart()
        self._redraw_benchmark_chart2()
        self._redraw_benchmark_chart3()

    def _show_mixed_widths(self, chart, metrics):
        floors = sorted({f for m in metrics
                         for f in mixed_width_floors(self._filtered_rows(), m,
                                                     self._metric_view(m))
                         if chart_view.contains(self._x_view, f)})
        notes = [self.T("bench.mixed_widths", floors=", ".join(map(str, floors)))] if floors else []
        notes += [note for note in (self._unplaced_note(metrics),) if note]
        self.mixed_widths_vars[chart].set("  |  ".join(notes))
        label, grip_frame = self._mixed_widths_labels[chart]
        if notes:
            label.pack(anchor="w", after=grip_frame)
        else:
            label.pack_forget()

    def _set_pins(self, chart, pins):
        self._y_pins[chart] = pins
        self._redraw_chart(chart)

    def _pin_menu_entries(self, chart, target):
        """[(label, command, enabled) or None for a separator] of the right-click menu: the
        chart's point choices (_point_menu_entries()), the axis toggles
        (_axis_menu_entries()), a point's pins, the three resets;
        target: see _draw_growth_chart's on_pin_menu. A point offers its value as its axis'
        max or min; a reset is enabled while its axis has a pin."""
        T, pins = self.T, self._y_pins[chart]
        entries = (self._point_menu_entries(chart) + [None]
                   + self._axis_menu_entries(chart) + [None])
        if target:
            axis, value, text = target
            for which in ("max", "min"):
                entries.append((T("bench.pin_" + which, value=text),
                                lambda w=which, a=axis: self._set_pins(
                                    chart, pin_bound(self._y_pins[chart], a, w, value)),
                                True))
            entries.append(None)
        for axis in ("primary", "secondary"):
            entries.append((T("bench.pin_reset_" + axis),
                            lambda a=axis: self._set_pins(
                                chart, clear_pins(self._y_pins[chart], a)),
                            axis in pins))
        entries.append((T("bench.pin_reset_chart"), lambda: self._set_pins(chart, {}),
                        bool(pins)))
        return entries

    def _on_pin_menu(self, chart, target, x_root, y_root):
        self._post_menu(self._pin_menu_entries(chart, target), x_root, y_root)

    def _post_menu(self, entries, x_root, y_root):
        menu = tk.Menu(self, tearoff=False)
        for entry in entries:
            if entry is None:
                menu.add_separator()
                continue
            label, command, enabled = entry
            menu.add_command(label=label, command=command,
                             state="normal" if enabled else "disabled")
        try:
            menu.tk_popup(x_root, y_root)
        finally:
            menu.grab_release()

    def _redraw_benchmark_chart2(self):
        """Same fallback-size handling as _redraw_benchmark_chart() (see that method's own
        comment) -- draws the sieve chart of the Filter window's sieve measure
        (sieve_measure.chart(): n/s and s/window, with reference points, or the startup
        overhead) onto its own canvas, the top one, above the whole-run chart."""
        spec = sieve_measure.chart(self._sieve_measure)
        self._show_mixed_widths("sieve", (spec.metric1, spec.metric2))
        self._draw_chart("sieve", self.benchmark_chart2, self._benchmark_sieve_nps_points,
                         (900, 220), label_key1=spec.label_key1, label_key2=spec.label_key2,
                         places1=spec.places1, places2=spec.places2,
                         series1=self._chart_series(spec.metric1, spec.references),
                         series2=self._chart_series(spec.metric2),
                         marks=self._chart_marks(spec.metric1, spec.metric2))

    def reload_benchmark_log(self):
        fieldnames, rows = read_benchmark_log(self._get_portal_folder())
        self._benchmark_fieldnames = fieldnames  # FULL list -- PDF export/growth chart
                                                   # still use every column, unaffected
                                                   # by what the tree itself displays
        self._machines = self.computer_cell.load()
        computer_names.annotate(rows, self._machines)
        self._benchmark_rows = rows
        self._prune_filter()

        self._benchmark_growth_points = aggregate_benchmark_growth(rows)
        self._benchmark_fair_spw_points = aggregate_benchmark_fair_spw(rows)
        self._redraw_benchmark_chart()

        self._benchmark_sieve_nps_points = aggregate_benchmark_sieve_nps(rows)
        self._benchmark_write_mbps_points = aggregate_benchmark_write_mbps(rows)
        self._redraw_benchmark_chart2()
        self._redraw_benchmark_chart3()

        self.benchmark_tree.delete(*self.benchmark_tree.get_children())
        self._set_copy_columns(table_columns.TREE_COLUMNS)
        for col in table_columns.TREE_COLUMNS:
            self.benchmark_tree.heading(col, text=self.T(table_columns.header_key(col)))
            self.benchmark_tree.column(col, anchor="center", stretch=False)
        self._rebuild_benchmark_tree()
        if self._on_rows_loaded is not None:
            self._on_rows_loaded(rows)

    def _rebuild_benchmark_tree(self):
        """Lists the runs the Filter window keeps (_filtered_rows()), grouped per floor; a
        floor with no kept run is left out. Called on reload and on every filter change, which
        keeps the columns and fits their widths to the kept runs (benchmark_table_layout.py)."""
        T = self.T
        fieldnames = self._benchmark_fieldnames
        self._benchmark_rows_by_floor = group_benchmark_rows_by_floor(self._filtered_rows())
        self.benchmark_tree.delete(*self.benchmark_tree.get_children())
        self._tree_item_rows = {}
        self._tree_floor_nodes = {}
        self._benchmark_floor_state = {}
        self._copy_marks = set()
        self._active_benchmark_node = None
        self._fit_table_columns()
        self._refresh_benchmark_nav_controls()

        tree_fieldnames = table_columns.TREE_COLUMNS
        if not fieldnames or not self._benchmark_rows:
            self.benchmark_tree.insert("", "end", text=T("bench.no_data_row"))
            return
        if not self._benchmark_rows_by_floor:
            self.benchmark_tree.insert("", "end", text=T("bench.filter_no_rows"))
            return

        for base_exponent in sorted(self._benchmark_rows_by_floor):
            count = len(self._benchmark_rows_by_floor[base_exponent])
            node = self.benchmark_tree.insert(
                "", "end", text=T("bench.floor_measurements", base_exponent=base_exponent, count=count),
                values=["" for _ in tree_fieldnames], open=False, tags=("floor",))
            self._tree_floor_nodes[node] = base_exponent
            self.benchmark_tree.insert(node, "end", text=T("common.loading"))
        self._show_copy_marks()

    def _on_benchmark_tree_open(self, _event):
        node = self.benchmark_tree.focus()
        self._populate_benchmark_floor_node(node)
        self._set_active_benchmark_node(node)

    def _on_benchmark_tree_close(self, _event):
        """Same lifecycle as the primes tab's _on_tree_close(): collapsing a floor drops
        its row/page state and resets to a single "(loading...)" placeholder, so a floor
        that's never re-expanded doesn't hold onto its (already in-memory, but still
        worth not duplicating into tree-item state) rows indefinitely."""
        node = self.benchmark_tree.focus()
        if node not in self._benchmark_floor_state:
            return
        del self._benchmark_floor_state[node]
        self.benchmark_tree.delete(*self.benchmark_tree.get_children(node))
        self.benchmark_tree.insert(node, "end", text=self.T("common.loading"))
        if self._active_benchmark_node == node:
            self._active_benchmark_node = None
            self._refresh_benchmark_nav_controls()

    def _on_benchmark_tree_select(self, _event):
        """Clicking a floor header (whether just opened or already expanded) makes it
        the target of the pagination controls above the tree -- same behavior as the
        primes tab's floor nav. The selected row scrolls to the top, under the headings,
        once the click or key that selected it has been handled."""
        selection = self.benchmark_tree.selection()
        if not selection:
            return
        item = selection[0]
        self.benchmark_tree.after_idle(self.benchmark_tree.scroll_to_top, item)
        if "floor" in self.benchmark_tree.item(item, "tags"):
            self._set_active_benchmark_node(item)
        else:
            self._on_tree_row_selected(item)

    def _populate_benchmark_floor_node(self, node):
        if node in self._benchmark_floor_state:
            return  # already prepared this session -- nothing to redo
        children = self.benchmark_tree.get_children(node)
        if len(children) == 1 and self.benchmark_tree.item(children[0], "text") == self.T("common.loading"):
            self.benchmark_tree.delete(children[0])

        base_exponent = self._tree_floor_nodes[node]
        rows = self._benchmark_rows_by_floor.get(base_exponent, [])
        stats = table_columns.stats(rows)
        total_pages = max(1, (len(rows) + BENCHMARK_PAGE_SIZE - 1) // BENCHMARK_PAGE_SIZE)
        self._benchmark_floor_state[node] = {
            "base_exponent": base_exponent,
            "rows": rows,
            "stats": stats,
            "page": 0,
            "total_pages": total_pages,
        }
        self._show_benchmark_page(node, 0)

    def _show_benchmark_page(self, node, page):
        """Renders page `page` (0-indexed) of a floor's benchmark rows, PLUS a
        standalone stats row at the top (min/avg/max seconds_per_window across ALL of
        that floor's rows, not just the current page -- re-inserted on every page turn,
        which costs nothing since it's a single row) -- see table_columns.stats()."""
        T = self.T
        state = self._benchmark_floor_state.get(node)
        if not state:
            return
        total_pages = state["total_pages"]
        page = max(0, min(page, total_pages - 1))
        state["page"] = page

        for item in self.benchmark_tree.get_children(node):
            self._tree_item_rows.pop(item, None)
        self.benchmark_tree.delete(*self.benchmark_tree.get_children(node))
        fieldnames = table_columns.TREE_COLUMNS

        stats = state["stats"]
        stat_values = ["" for _ in fieldnames]
        if stats and "seconds_per_window" in fieldnames:
            idx = fieldnames.index("seconds_per_window")
            stat_values[idx] = table_columns.summary_text(stats, T)
            stat_text = T("bench.stat_row_label", count=stats['count'])
        else:
            stat_text = T("bench.stat_no_data")
        self.benchmark_tree.insert(node, "end", text=stat_text, values=stat_values,
                                    tags=("stat",))

        rows = state["rows"]
        start = page * BENCHMARK_PAGE_SIZE
        end = min(start + BENCHMARK_PAGE_SIZE, len(rows))
        for row in rows[start:end]:
            # #0 names the run by its timestamp; the engine has its own column.
            label = row.get("run_timestamp_utc", "")
            values = [table_columns.shown(row, c, T) for c in fieldnames]
            item = self.benchmark_tree.insert(node, "end", text=label, values=values,
                                              tags=("row",))
            self._remember_tree_row(item, row)
        self._show_copy_marks()

        if self._active_benchmark_node == node:
            self._refresh_benchmark_nav_controls()

    def _set_active_benchmark_node(self, node):
        self._active_benchmark_node = node
        self._refresh_benchmark_nav_controls()

    def _refresh_benchmark_nav_controls(self):
        node = self._active_benchmark_node
        state = self._benchmark_floor_state.get(node) if node is not None else None
        if not state:
            self.benchmark_page_label.set("")
            self.benchmark_prev_btn.configure(state="disabled")
            self.benchmark_next_btn.configure(state="disabled")
            return
        self._update_nav_controls(self.benchmark_page_label, state["page"], state["total_pages"],
                                   self.benchmark_prev_btn, self.benchmark_next_btn)

    def _prev_benchmark_page(self):
        node = self._active_benchmark_node
        if node is not None and self._benchmark_floor_state.get(node):
            self._show_benchmark_page(node, self._benchmark_floor_state[node]["page"] - 1)

    def _next_benchmark_page(self):
        node = self._active_benchmark_node
        if node is not None and self._benchmark_floor_state.get(node):
            self._show_benchmark_page(node, self._benchmark_floor_state[node]["page"] + 1)

    def _goto_benchmark_page(self):
        raw = plain_number(self.benchmark_goto_entry.get())
        if not raw.isdigit():
            return
        node = self._active_benchmark_node
        if node is not None and self._benchmark_floor_state.get(node):
            self._show_benchmark_page(node, int(raw) - 1)
