"""
benchmark_tab.py -- BenchmarkTab, the tkinter widgets for the Benchmark tab: a small
dependency-free growth chart (numbers/s vs. floor depth, one point per floor -- latest
logged run wins) plus a phase-breakdown chart (sieve-numbers/s + write-MB/s), above a
paginated, lazily-expandable tree view of the full benchmark_log.csv (written by
orchestrator_v1.py's print_benchmark_summary()); a "Save PDF" button renders the same
chart(s) + full table into a standalone PDF report.

Extracted from prime_atlas_v1.py during the refactor branch's Faza 3 (tab-by-tab
backend/UI split, 2026-08-23) -- the Benchmark tab was the smallest of the five tabs
still living directly in that file, so it went first (see task history around
2026-08-23). All the pure-logic reduction/PDF-rendering work lives in
primeatlas/benchmark.py; this module only owns the widgets and the tkinter-specific
on-screen chart drawing (_draw_growth_chart below).

This is one of only two files in primeatlas/ that import tkinter -- the other is
settings_tab.py (see that module's own docstring for the general "pure logic
elsewhere" convention this package follows).

BenchmarkTab does not know how PORTAL_FOLDER is stored or how the app's shared status
bar/translator are constructed -- it receives everything it needs at construction time
(get_portal_folder, status_var, translator, update_nav_controls) instead of importing
prime_atlas_v1.py directly, which would be circular (that file imports BenchmarkTab
from this module). update_nav_controls in particular is prime_atlas_v1.py's own small
shared pagination-label/button helper, used identically by every OTHER tab's own
pagination (Prime numbers, Constellations, Goldbach, ...) -- it stays put there rather
than being duplicated or promoted to its own module just for this one extraction, and
is passed in exactly like SettingsTab's wsl_helpers callables are.
"""
import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter import font as tkfont

from .base_tab import BaseTab
from .benchmark import (
    BENCHMARK_PAGE_SIZE, BENCHMARK_TREE_HIDDEN_COLUMNS,
    _order_benchmark_tree_columns, aggregate_benchmark_fair_spw,
    aggregate_benchmark_growth, aggregate_benchmark_sieve_nps,
    aggregate_benchmark_write_mbps, benchmark_row_stats,
    group_benchmark_rows_by_pietro, read_benchmark_log, render_benchmark_pdf,
)
from .i18n import Translator, DEFAULT_LANGUAGE


def _nearest_hover_point(hover_points, x, y, max_distance=14.0):
    """Picks which (if any) of hover_points the cursor at (x, y) is "over" -- the one
    decision _bind_chart_hover's <Motion> handler needs to make, pulled out as a
    plain function with no canvas/tkinter dependency so it's directly unit-testable.
    (Added 2026-08-26: driving this through a real OS-level synthetic mouse event in
    a test turned out to behave inconsistently across platforms/Tk versions -- e.g.
    Windows Python 3.13 delivered <Motion> coordinates that didn't reliably land
    within max_distance of a dot even when targeted at its exact pixel center --
    whereas this pure function is deterministic and needs no live display at all.)

    hover_points: see _bind_chart_hover's own docstring for the tuple shape.
    Returns (px, py, x_val, y_val, fmt, color) for the closest point within
    max_distance pixels, or None if every point is farther than that (or the list
    is empty)."""
    best = None
    best_d2 = max_distance ** 2
    for px, py, x_val, y_val, fmt, color, _label_key in hover_points:
        d2 = (x - px) ** 2 + (y - py) ** 2
        if d2 <= best_d2:
            best_d2 = d2
            best = (px, py, x_val, y_val, fmt, color)
    return best


def _bind_chart_hover(canvas, hover_points, t, fg_color, bg_color):
    """Wires a single-tooltip hover interaction onto `canvas` instead of drawing every
    point's value permanently next to its dot -- with a couple dozen closely-spaced
    floors, the always-on labels used to stack on top of each other into an unreadable
    smear (real bug report, 2026-08-26 screenshot). Only the point nearest the cursor
    (within a small pixel radius) gets a label, drawn fresh on every mouse move and
    cleared on <Leave>, so exactly one value is legible at a time no matter how dense
    the series is.

    hover_points: a flat list of (px, py, x_val, y_val, fmt, color, unused_label_key)
    tuples in CANVAS pixel space, built by the caller from whichever series (primary
    and/or secondary) it already computed pixel coordinates for -- this function itself
    has no notion of axes/scales, just "here are some labeled dots".

    Rebinding on every redraw (this is called once per _draw_growth_chart invocation,
    i.e. every resize/data refresh) is intentional and cheap: tkinter's bind() replaces
    the previous callback for the same event sequence on the same widget rather than
    stacking a new one alongside it, so this never leaks handlers, and each new callback
    closes over the CURRENT hover_points/scale rather than a stale one."""

    def _clear_tip():
        canvas.delete("hover_tip")

    def _on_leave(_event):
        _clear_tip()

    def _on_motion(event):
        _clear_tip()
        best = _nearest_hover_point(hover_points, event.x, event.y)
        if best is None:
            return
        px, py, x_val, y_val, fmt, color = best
        text = f"{t('bench.axis_pietro')} {x_val}: {fmt.format(y_val)}"
        canvas.create_oval(px - 6, py - 6, px + 6, py + 6, outline=color, width=2,
                            tags="hover_tip")
        tx, ty = px + 12, py - 12
        text_id = canvas.create_text(tx, ty, text=text, anchor="w", fill=color,
                                      font=("Consolas", 9, "bold"), tags="hover_tip")
        bbox = canvas.bbox(text_id)
        if bbox:
            pad = 4
            box_id = canvas.create_rectangle(
                bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad,
                fill=bg_color, outline=color, tags="hover_tip")
            canvas.tag_lower(box_id, text_id)

    canvas.bind("<Motion>", _on_motion)
    canvas.bind("<Leave>", _on_leave)


def _draw_growth_chart(canvas, points, width, height, points2=None, translator=None,
                        label_key1="bench.axis_nps", label_key2="bench.axis_spw",
                        fmt1="{:,.0f}", fmt2="{:,.3f}",
                        bg_color="#ffffff", fg_color="#000000", grid_color="#666666"):
    """Draws (base_exponent, primary-series) points onto `canvas` as a simple axes +
    connected-scatter chart -- x = floor depth, y = the primary series (by default numbers
    swept per second, real session-level wall-clock throughput, higher is better). Plain
    tk.Canvas drawing, no charting library: this app is deliberately zero-extra-installs
    (see prime_atlas_v1.py's module header), and a handful of axis lines + dots doesn't
    need one. Clears the canvas first, so this is safe to call again on refresh/resize
    (bound to <Configure>).

    points2 (optional): a SECOND series sharing the x-axis -- by default the 'fair'
    loop_seconds_per_window figure shown alongside n/s, but label_key2/fmt2 (see below) let
    a caller reuse this for a different pair, e.g. sieve-numbers/s + write-MB/s. Drawn as a
    red line on its own right-hand y-axis with an independent scale (see
    primeatlas.benchmark._pdf_chart_ops()'s docstring for why it needs its own axis rather
    than sharing the primary one).

    label_key1/label_key2/fmt1/fmt2: same meaning and defaults as
    primeatlas.benchmark._pdf_chart_ops()'s matching parameters -- i18n keys for the two
    axis titles, and str.format() templates for tick/point value labels -- so the PDF
    export and this on-screen chart stay visually consistent for any series pair, not just
    the original n/s + s/window one.

    translator (optional): a primeatlas.i18n.Translator instance -- unlike the ORIGINAL
    version of this function (prime_atlas_v1.py, pre-Faza-3), which read the module-level
    global T() directly, this module has no such global to read (see this file's own
    docstring on why cross-module globals would be circular here) -- defaults to
    DEFAULT_LANGUAGE if not given, same fallback _pdf_chart_ops() already uses.

    bg_color/fg_color/grid_color (added 2026-08-26, real bug report): lets the caller
    theme this canvas instead of it staying hardcoded to a light-mode palette regardless
    of the app's actual theme setting -- BenchmarkTab passes its constructor's
    theme_palette through here (console_bg/console_fg/border, the same keys already used
    for the app's other canvas-like widgets) so the chart's background and text actually
    go dark under the dark theme. Defaults match the ORIGINAL hardcoded colors, so any
    other caller (tests, etc.) that doesn't pass them sees identical output to before."""
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    canvas.configure(background=bg_color)
    canvas.delete("all")
    if width <= 1 or height <= 1:
        return  # not yet realized/sized
    points = points or []
    points2 = points2 or []
    if not points and not points2:
        canvas.create_text(width / 2, height / 2, text=t("bench.no_data_chart"),
                            fill="#888888")
        return

    has_secondary = bool(points2)
    pad_top, pad_bottom = 40, 40
    # pad_top has room ABOVE the topmost y-tick (which sits right at pad_top) for the axis
    # title below -- it used to sit almost on top of that tick's label (both landed within
    # a few px of each other near the top-left corner) and visually merged into one
    # unreadable blob.

    all_xs = sorted({p[0] for p in points} | {p[0] for p in points2})
    x_min, x_max = min(all_xs), max(all_xs)
    if x_min == x_max:
        x_min -= 1
        x_max += 1

    def y_bounds(pts):
        ys = [p[1] for p in pts]
        ylo, yhi = min(ys), max(ys)
        if ylo == yhi:
            pad = max(1.0, abs(ylo) * 0.1)
            ylo -= pad
            yhi += pad
        return min(ylo, 0), yhi  # anchor at (or below) zero -- growth should read honest

    if points:
        y_min, y_max = y_bounds(points)
    if has_secondary:
        y2_min, y2_max = y_bounds(points2)

    # pad_left/pad_right used to be fixed guesses (70px) -- fine for short numbers, but
    # real benchmark throughput easily reaches 9-11 digit n/s figures ("71,556,448"),
    # which at that width no longer fit and got clipped against the canvas edge (real
    # bug report, 2026-08-26 screenshot). Measuring the actual tick label strings with
    # the real font instead of guessing a fixed width fixes that for any data range,
    # not just the one in the screenshot.
    tick_font = tkfont.Font(family="Consolas", size=8)

    def _max_tick_label_width(y_lo, y_hi, fmt):
        labels = [fmt.format(y_lo + (y_hi - y_lo) * i / 5) for i in range(6)]
        return max((tick_font.measure(s) for s in labels), default=0)

    pad_left = 24
    if points:
        pad_left = max(50, _max_tick_label_width(y_min, y_max, fmt1) + 24)
    pad_right = 24
    if has_secondary:
        pad_right = max(50, _max_tick_label_width(y2_min, y2_max, fmt2) + 28)

    plot_w = max(1, width - pad_left - pad_right)
    plot_h = max(1, height - pad_top - pad_bottom)

    # Same horizontal inset as _pdf_chart_ops() -- see that function's comment for why.
    inset_x = max(15.0, plot_w * 0.05)

    def sx(x):
        return pad_left + inset_x + (x - x_min) / (x_max - x_min) * (plot_w - 2 * inset_x)

    def sy(y):
        return pad_top + plot_h - (y - y_min) / (y_max - y_min) * plot_h

    def sy2(y):
        return pad_top + plot_h - (y - y2_min) / (y2_max - y2_min) * plot_h

    canvas.create_line(pad_left, pad_top, pad_left, pad_top + plot_h, fill=grid_color)
    canvas.create_line(pad_left, pad_top + plot_h, pad_left + plot_w, pad_top + plot_h,
                        fill=grid_color)
    if has_secondary:
        canvas.create_line(pad_left + plot_w, pad_top, pad_left + plot_w, pad_top + plot_h,
                            fill="#c0504d")

    if points:
        for i in range(6):
            y_val = y_min + (y_max - y_min) * i / 5
            y_px = sy(y_val)
            canvas.create_line(pad_left - 4, y_px, pad_left, y_px, fill=grid_color)
            canvas.create_text(pad_left - 8, y_px, text=fmt1.format(y_val), anchor="e",
                                font=("Consolas", 8), fill=fg_color)

    if has_secondary:
        for i in range(6):
            y_val = y2_min + (y2_max - y2_min) * i / 5
            y_px = sy2(y_val)
            canvas.create_line(pad_left + plot_w, y_px, pad_left + plot_w + 4, y_px,
                                fill="#c0504d")
            canvas.create_text(pad_left + plot_w + 8, y_px, text=fmt2.format(y_val), anchor="w",
                                font=("Consolas", 8), fill="#c0504d")

    for x_val in all_xs:
        x_px = sx(x_val)
        canvas.create_line(x_px, pad_top + plot_h, x_px, pad_top + plot_h + 4, fill=grid_color)
        canvas.create_text(x_px, pad_top + plot_h + 8, text=str(x_val), anchor="n",
                            font=("Consolas", 8), fill=fg_color)

    canvas.create_text(pad_left + plot_w / 2, height - 8, text=t("bench.axis_pietro"),
                        font=("Consolas", 8, "bold"), fill=fg_color)
    # Sits in the padding strip ABOVE the plot area (not overlapping any tick label, which
    # all live at y >= pad_top) -- anchored "sw" so its BOTTOM edge, not its top, is what's
    # positioned, keeping a consistent small gap above the topmost tick regardless of font
    # metrics.
    if points:
        canvas.create_text(4, pad_top - 10, text=t(label_key1), anchor="sw",
                            font=("Consolas", 8, "bold"), fill=fg_color)
    if has_secondary:
        canvas.create_text(width - 4, pad_top - 10, text=t(label_key2), anchor="se",
                            font=("Consolas", 8, "bold"), fill="#c0504d")

    # Per-point value labels used to be drawn permanently next to every dot -- with
    # dense series (a couple dozen floors close together) they overlapped into an
    # unreadable smear (real bug report, 2026-08-26 screenshot). Now only the dots/line
    # are drawn unconditionally; the actual value is shown on hover via a single
    # tooltip (see _bind_chart_hover below), so exactly one label is ever visible.
    hover_points = []

    if points:
        if len(points) > 1:
            coords = []
            for x_val, y_val in points:
                coords.extend([sx(x_val), sy(y_val)])
            canvas.create_line(*coords, fill="#4a90d9", width=2)

        r = 4
        for x_val, y_val in points:
            cx, cy = sx(x_val), sy(y_val)
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#1c5fa8", outline="")
            hover_points.append((cx, cy, x_val, y_val, fmt1, "#1c5fa8", label_key1))

    if has_secondary:
        if len(points2) > 1:
            coords2 = []
            for x_val, y_val in points2:
                coords2.extend([sx(x_val), sy2(y_val)])
            canvas.create_line(*coords2, fill="#c0504d", width=2)

        r = 4
        for x_val, y_val in points2:
            cx, cy = sx(x_val), sy2(y_val)
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#c0504d", outline="")
            hover_points.append((cx, cy, x_val, y_val, fmt2, "#c0504d", label_key2))

    _bind_chart_hover(canvas, hover_points, t, fg_color, bg_color)


class BenchmarkTab(BaseTab):
    def __init__(self, parent, get_portal_folder, status_var, translator, update_nav_controls,
                 theme_palette):
        """
        theme_palette: the CURRENT theme's color dict (primeatlas.theme.palette_for()'s
        return value, e.g. {"fg": ..., "tree_group_bg": ..., "tree_stat_bg": ..., ...}),
        passed in explicitly rather than read from a bare global -- same dependency-
        injection reasoning as every other constructor parameter here. Needed because
        this tab's own tree "pietro"/"stat" row-highlight tags (see _build_widgets'
        own tag_configure calls) are a per-item ttk.Treeview override that
        PortalBrowserApp._apply_theme()'s ttk.Style() calls can never reach -- see
        primeatlas/theme.py's own docstring on tree_group_bg/tree_stat_bg for the bug
        this fixes (light-hardcoded row highlights were unreadable in dark mode)."""
        super().__init__(parent, translator)
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self._update_nav_controls = update_nav_controls
        self._theme_palette = theme_palette

        self._build_widgets()

    def _build_widgets(self):
        T = self.T

        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Button(top, text=T("common.refresh"), command=self.reload_benchmark_log).pack(side="left")
        ttk.Button(top, text=T("bench.save_pdf"), command=self._export_benchmark_pdf).pack(
            side="left", padx=(6, 0))
        ttk.Label(top, text=T("bench.chart_hint")).pack(side="left")

        chart_frame = ttk.Frame(self)
        chart_frame.pack(fill="x", padx=6, pady=(0, 4))
        # Canvas colors come from the CURRENT theme (console_bg/border -- same keys the
        # app's other canvas-like widgets already use for their own dark/light styling)
        # instead of being hardcoded to white/light-grey -- real bug report, 2026-08-26:
        # the "dark" theme left this chart looking unchanged (light chart on an otherwise
        # dark window). _draw_growth_chart's own bg_color/fg_color/grid_color params
        # (see _redraw_benchmark_chart/_redraw_benchmark_chart2 below) keep the drawn
        # content -- ticks, axis titles -- readable against whichever background this is.
        p = self._theme_palette
        self.benchmark_chart = tk.Canvas(chart_frame, height=220, background=p["console_bg"],
                                          highlightthickness=1, highlightbackground=p["border"])
        self.benchmark_chart.pack(fill="x")
        self.benchmark_chart.bind("<Configure>", lambda _e: self._redraw_benchmark_chart())

        # Second chart: sieve-numbers/s + write-MB/s -- the phase-breakdown counterpart
        # to the growth chart above, populated only from prime_sieve_v4_1.py rows (see
        # aggregate_benchmark_sieve_nps()/aggregate_benchmark_write_mbps()). Always
        # visible, same as the first chart -- _draw_growth_chart() already shows its own
        # "no data yet" placeholder when both series are empty, so a project that hasn't
        # re-benchmarked with v4.1 yet just sees that placeholder rather than the tab
        # silently hiding/showing a whole section.
        chart_frame2 = ttk.Frame(self)
        chart_frame2.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(chart_frame2, text=T("bench.chart2_hint")).pack(anchor="w")
        self.benchmark_chart2 = tk.Canvas(chart_frame2, height=180, background=p["console_bg"],
                                           highlightthickness=1, highlightbackground=p["border"])
        self.benchmark_chart2.pack(fill="x")
        self.benchmark_chart2.bind("<Configure>", lambda _e: self._redraw_benchmark_chart2())

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=6, pady=4)

        # Floor pagination -- ABOVE the tree, same Prev/label/Next/goto layout as the
        # "Prime numbers" tab's floor nav (see that tab's own _build_primes_tab for the
        # full rationale). benchmark_log.csv now gets a row per orchestrator run
        # (including cheap, repeatable count-only benchmarking runs -- see the
        # write_files toggle), so a floor can accumulate dozens-to-hundreds of rows;
        # expanding a floor only lists/groups rows already in memory (cheap -- the
        # whole CSV is small text) but only INSERTS one page's worth of Treeview rows at
        # a time, which is the part that used to freeze the old flat, ever-growing table.
        benchmark_nav = ttk.Frame(tree_frame)
        benchmark_nav.pack(fill="x", pady=(0, 4))
        self.benchmark_prev_btn = ttk.Button(
            benchmark_nav, text=T("common.prev_page"), command=self._prev_benchmark_page,
            state="disabled")
        self.benchmark_prev_btn.pack(side="left")
        self.benchmark_page_label = tk.StringVar(value="")
        ttk.Label(benchmark_nav, textvariable=self.benchmark_page_label, width=16,
                  anchor="center").pack(side="left")
        self.benchmark_next_btn = ttk.Button(
            benchmark_nav, text=T("common.next_page"), command=self._next_benchmark_page,
            state="disabled")
        self.benchmark_next_btn.pack(side="left")
        ttk.Label(benchmark_nav, text=T("common.page_prefix")).pack(side="left", padx=(10, 0))
        self.benchmark_goto_entry = ttk.Entry(benchmark_nav, width=6)
        self.benchmark_goto_entry.pack(side="left", padx=(4, 0))
        self.benchmark_goto_entry.bind("<Return>", lambda _e: self._goto_benchmark_page())
        ttk.Button(benchmark_nav, text=T("common.goto"), command=self._goto_benchmark_page).pack(
            side="left", padx=(4, 0))

        self.benchmark_tree = ttk.Treeview(tree_frame, show="tree headings")
        self.benchmark_tree.heading("#0", text=T("bench.col_pietro"))
        self.benchmark_tree.column("#0", width=170, stretch=False)
        # Horizontal scrollbar -- with 11 data columns + #0, the row is wider than the
        # tab, and without this the only way to see the columns off the right edge was
        # shrinking every column's width by hand. stretch=False on every column (set
        # below, in reload_benchmark_log()) keeps each column at its given width instead
        # of Tk auto-stretching the last one to fill the widget, which is what makes the
        # row properly wider than the view and the scrollbar actually needed/usable.
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.benchmark_tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.benchmark_tree.xview)
        self.benchmark_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.benchmark_tree.pack(side="left", fill="both", expand=True)

        # Explicit foreground alongside each background -- a tag's own colors
        # override the base "Treeview" ttk.Style() colors per-row (see this
        # constructor's own docstring), so without pairing them here, dark mode
        # would keep the (light) style-level foreground on top of these
        # theme-appropriate backgrounds and still be unreadable.
        p = self._theme_palette
        self.benchmark_tree.tag_configure("pietro", background=p["tree_group_bg"], foreground=p["fg"])
        self.benchmark_tree.tag_configure("stat", background=p["tree_stat_bg"], foreground=p["fg"])

        self.benchmark_tree.bind("<<TreeviewOpen>>", self._on_benchmark_tree_open)
        self.benchmark_tree.bind("<<TreeviewClose>>", self._on_benchmark_tree_close)
        self.benchmark_tree.bind("<<TreeviewSelect>>", self._on_benchmark_tree_select)

        self._benchmark_growth_points = []
        self._benchmark_fair_spw_points = []  # loop_seconds_per_window, second chart line
        self._benchmark_sieve_nps_points = []   # sieve-phase numbers/s, second CHART's
                                                 # primary line (prime_sieve_v4_1.py rows
                                                 # only -- see aggregate_benchmark_sieve_nps)
        self._benchmark_write_mbps_points = []  # write-phase MB/s, second chart's
                                                 # secondary line (same v4.1-only caveat)
        self._benchmark_fieldnames = []  # kept in sync by reload_benchmark_log() --
        self._benchmark_tree_fieldnames = []  # same, minus BENCHMARK_TREE_HIDDEN_COLUMNS
                                          # -- what the tree itself actually displays
        self._benchmark_rows = []        # _export_benchmark_pdf reads these (the FULL,
                                          # ungrouped data) instead of re-parsing the CSV,
                                          # so the PDF always exports everything, even
                                          # rows not currently paged into view.
        self._benchmark_rows_by_pietro = {}   # base_exponent -> [rows...], built by
                                               # reload_benchmark_log() via
                                               # group_benchmark_rows_by_pietro()
        self._benchmark_pietro_state = {}     # tree item id -> {base_exponent, rows,
                                               # stats, page, total_pages} -- lazily
                                               # populated on <<TreeviewOpen>>, dropped on
                                               # <<TreeviewClose>>, same lifecycle as the
                                               # primes tab's _pietro_state.
        self._active_benchmark_node = None    # which floor's page the nav buttons above
                                               # currently operate on

    def _redraw_benchmark_chart(self):
        # Before the window has actually been mapped/laid out by the OS window manager
        # (e.g. the very first draw, triggered from reload_benchmark_log() during
        # __init__), winfo_width()/height() can still report the Tk default of 1x1 --
        # <Configure> will fire and redraw properly once real geometry is assigned, but
        # falling back to a reasonable size here means the chart doesn't sit blank in
        # the meantime.
        width = self.benchmark_chart.winfo_width()
        height = self.benchmark_chart.winfo_height()
        if width <= 1:
            width = 900
        if height <= 1:
            height = 220
        p = self._theme_palette
        _draw_growth_chart(self.benchmark_chart, self._benchmark_growth_points, width, height,
                            points2=self._benchmark_fair_spw_points, translator=self.T,
                            bg_color=p["console_bg"], fg_color=p["console_fg"],
                            grid_color=p["border"])

    def _redraw_benchmark_chart2(self):
        """Same fallback-size handling as _redraw_benchmark_chart() (see that method's own
        comment) -- draws the sieve-numbers/s + write-MB/s phase-breakdown chart onto its
        own canvas, right below the growth chart."""
        width = self.benchmark_chart2.winfo_width()
        height = self.benchmark_chart2.winfo_height()
        if width <= 1:
            width = 900
        if height <= 1:
            height = 180
        p = self._theme_palette
        _draw_growth_chart(self.benchmark_chart2, self._benchmark_sieve_nps_points, width,
                            height, points2=self._benchmark_write_mbps_points,
                            label_key1="bench.axis_sieve_nps",
                            label_key2="bench.axis_write_mbps",
                            fmt1="{:,.0f}", fmt2="{:,.1f}", translator=self.T,
                            bg_color=p["console_bg"], fg_color=p["console_fg"],
                            grid_color=p["border"])

    def reload_benchmark_log(self):
        T = self.T
        fieldnames, rows = read_benchmark_log(self._get_portal_folder())
        self._benchmark_fieldnames = fieldnames  # FULL list -- PDF export/growth chart
                                                   # still use every column, unaffected
                                                   # by what the tree itself displays
        self._benchmark_rows = rows
        self._benchmark_rows_by_pietro = group_benchmark_rows_by_pietro(rows)
        self._benchmark_tree_fieldnames = _order_benchmark_tree_columns(
            [c for c in fieldnames if c not in BENCHMARK_TREE_HIDDEN_COLUMNS])

        self._benchmark_growth_points = aggregate_benchmark_growth(rows)
        self._benchmark_fair_spw_points = aggregate_benchmark_fair_spw(rows)
        self._redraw_benchmark_chart()

        self._benchmark_sieve_nps_points = aggregate_benchmark_sieve_nps(rows)
        self._benchmark_write_mbps_points = aggregate_benchmark_write_mbps(rows)
        self._redraw_benchmark_chart2()

        self.benchmark_tree.delete(*self.benchmark_tree.get_children())
        self._benchmark_pietro_state = {}
        self._active_benchmark_node = None
        self._refresh_benchmark_nav_controls()

        tree_fieldnames = self._benchmark_tree_fieldnames
        self.benchmark_tree["columns"] = tree_fieldnames
        for col in tree_fieldnames:
            self.benchmark_tree.heading(col, text=col)
            self.benchmark_tree.column(col, width=120, anchor="center", stretch=False)

        if not fieldnames or not self._benchmark_rows_by_pietro:
            self.benchmark_tree.insert("", "end", text=T("bench.no_data_row"))
            return

        for base_exponent in sorted(self._benchmark_rows_by_pietro):
            count = len(self._benchmark_rows_by_pietro[base_exponent])
            node = self.benchmark_tree.insert(
                "", "end", text=T("bench.pietro_measurements", base_exponent=base_exponent, count=count),
                values=["" for _ in tree_fieldnames], open=False, tags=("pietro",))
            self.benchmark_tree.insert(node, "end", text=T("common.loading"))

    def _on_benchmark_tree_open(self, _event):
        node = self.benchmark_tree.focus()
        self._populate_benchmark_pietro_node(node)
        self._set_active_benchmark_node(node)

    def _on_benchmark_tree_close(self, _event):
        """Same lifecycle as the primes tab's _on_tree_close(): collapsing a floor drops
        its row/page state and resets to a single "(loading...)" placeholder, so a floor
        that's never re-expanded doesn't hold onto its (already in-memory, but still
        worth not duplicating into tree-item state) rows indefinitely."""
        node = self.benchmark_tree.focus()
        if node not in self._benchmark_pietro_state:
            return
        del self._benchmark_pietro_state[node]
        self.benchmark_tree.delete(*self.benchmark_tree.get_children(node))
        self.benchmark_tree.insert(node, "end", text=self.T("common.loading"))
        if self._active_benchmark_node == node:
            self._active_benchmark_node = None
            self._refresh_benchmark_nav_controls()

    def _on_benchmark_tree_select(self, _event):
        """Clicking a floor header (whether just opened or already expanded) makes it
        the target of the pagination controls above the tree -- same behavior as the
        primes tab's floor nav."""
        selection = self.benchmark_tree.selection()
        if not selection:
            return
        item = selection[0]
        if "pietro" in self.benchmark_tree.item(item, "tags"):
            self._set_active_benchmark_node(item)

    def _populate_benchmark_pietro_node(self, node):
        if node in self._benchmark_pietro_state:
            return  # already prepared this session -- nothing to redo
        children = self.benchmark_tree.get_children(node)
        if len(children) == 1 and self.benchmark_tree.item(children[0], "text") == self.T("common.loading"):
            self.benchmark_tree.delete(children[0])

        text = self.benchmark_tree.item(node, "text")  # "10p{N} (M measurement(s))"
        base_exponent = int(text[3:].split(" ", 1)[0])
        rows = self._benchmark_rows_by_pietro.get(base_exponent, [])
        stats = benchmark_row_stats(rows)
        total_pages = max(1, (len(rows) + BENCHMARK_PAGE_SIZE - 1) // BENCHMARK_PAGE_SIZE)
        self._benchmark_pietro_state[node] = {
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
        which costs nothing since it's a single row) -- see benchmark_row_stats()."""
        T = self.T
        state = self._benchmark_pietro_state.get(node)
        if not state:
            return
        total_pages = state["total_pages"]
        page = max(0, min(page, total_pages - 1))
        state["page"] = page

        self.benchmark_tree.delete(*self.benchmark_tree.get_children(node))
        fieldnames = self._benchmark_tree_fieldnames  # display columns only -- see
                                                        # BENCHMARK_TREE_HIDDEN_COLUMNS

        stats = state["stats"]
        stat_values = ["" for _ in fieldnames]
        if stats and "seconds_per_window" in fieldnames:
            idx = fieldnames.index("seconds_per_window")
            stat_values[idx] = T("bench.stat_summary", avg=f"{stats['avg']:.4f}",
                                  min=f"{stats['min']:.4f}", max=f"{stats['max']:.4f}")
            stat_text = T("bench.stat_row_label", count=stats['count'])
        else:
            stat_text = T("bench.stat_no_data")
        self.benchmark_tree.insert(node, "end", text=stat_text, values=stat_values,
                                    tags=("stat",))

        rows = state["rows"]
        start = page * BENCHMARK_PAGE_SIZE
        end = min(start + BENCHMARK_PAGE_SIZE, len(rows))
        for row in rows[start:end]:
            # #0 shows the run's timestamp for individual rows -- run_timestamp_utc is
            # excluded from the columns list (BENCHMARK_TREE_HIDDEN_COLUMNS) precisely
            # so it can live here instead, in the column that would otherwise sit empty
            # for every data row (target_idx_start/target_idx_end are already their own
            # columns, so #0 had nothing else useful to show).
            label = row.get("run_timestamp_utc", "")
            values = [row.get(c, "") for c in fieldnames]
            self.benchmark_tree.insert(node, "end", text=label, values=values, tags=("row",))

        if self._active_benchmark_node == node:
            self._refresh_benchmark_nav_controls()

    def _set_active_benchmark_node(self, node):
        self._active_benchmark_node = node
        self._refresh_benchmark_nav_controls()

    def _refresh_benchmark_nav_controls(self):
        node = self._active_benchmark_node
        state = self._benchmark_pietro_state.get(node) if node is not None else None
        if not state:
            self.benchmark_page_label.set("")
            self.benchmark_prev_btn.configure(state="disabled")
            self.benchmark_next_btn.configure(state="disabled")
            return
        self._update_nav_controls(self.benchmark_page_label, state["page"], state["total_pages"],
                                   self.benchmark_prev_btn, self.benchmark_next_btn)

    def _prev_benchmark_page(self):
        node = self._active_benchmark_node
        if node is not None and self._benchmark_pietro_state.get(node):
            self._show_benchmark_page(node, self._benchmark_pietro_state[node]["page"] - 1)

    def _next_benchmark_page(self):
        node = self._active_benchmark_node
        if node is not None and self._benchmark_pietro_state.get(node):
            self._show_benchmark_page(node, self._benchmark_pietro_state[node]["page"] + 1)

    def _goto_benchmark_page(self):
        raw = self.benchmark_goto_entry.get().strip()
        if not raw.isdigit():
            return
        node = self._active_benchmark_node
        if node is not None and self._benchmark_pietro_state.get(node):
            self._show_benchmark_page(node, int(raw) - 1)

    def _export_benchmark_pdf(self):
        T = self.T
        if not self._benchmark_fieldnames or not self._benchmark_rows:
            messagebox.showinfo(
                T("bench.save_pdf"),
                T("bench.no_data_dialog"))
            return
        default_name = f"benchmark_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        path = filedialog.asksaveasfilename(
            title=T("bench.save_dialog_title"),
            initialdir=self._get_portal_folder(),
            initialfile=default_name,
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf"), (T("common.all_files"), "*.*")])
        if not path:
            return
        try:
            render_benchmark_pdf(path, self._benchmark_growth_points,
                                  self._benchmark_fieldnames, self._benchmark_rows,
                                  points2=self._benchmark_fair_spw_points,
                                  translator=self.T,
                                  sieve_points=self._benchmark_sieve_nps_points,
                                  write_points=self._benchmark_write_mbps_points)
        except Exception as exc:
            messagebox.showerror(T("bench.save_pdf"), T("bench.save_error", error=exc))
            return
        self.status.set(T("bench.status_saved", path=path))
        messagebox.showinfo(T("bench.save_pdf"), T("bench.saved_dialog", path=path))
