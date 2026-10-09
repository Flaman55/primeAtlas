"""
widgets.py -- small, generic tkinter widget helpers with no application-specific state,
shared by more than one tab (e.g. FlowRow, used by the Prime numbers and Constellations
tabs and imported by prime_atlas_v2.py as `from primeatlas.core.widgets import FlowRow
as _FlowRow`).

This is one of a small number of files in primeatlas/ that import tkinter -- see
settings_tab.py's own docstring for the general "pure logic elsewhere" convention this
package otherwise follows; FlowRow is UI-only by nature (it lays out already-built
widgets), so there is no non-tkinter half to split it into.
"""
import tkinter as tk
import tkinter.font as tkfont
import weakref
from tkinter import ttk

from .app_settings import SCROLL_PAD_WIDTH_DEFAULT, clamp_scroll_pad_width


class FlowRow:
    """A button-row container that wraps its children onto additional lines instead of
    running them off the edge of the window. A plain ttk.Frame with every child
    .pack(side="left")'d onto ONE line has this failure mode: on a narrow window (or a
    narrow detail pane after the split-view divider is dragged), the rightmost controls
    simply run past the frame's right edge and become invisible/unreachable, with no way
    to get to them short of resizing the whole window (e.g. the Prime numbers and
    Constellations tabs' preview-navigation rows: Prev / page label / Next / page-goto
    entry).

    Children are added via .add(widget, padx_left=...) instead of widget.pack(...); this
    class lays them out itself using place() (which, unlike pack/grid, doesn't force a
    single line or a fixed grid) and re-flows on every <Configure> of its own frame --
    same 'safe to call again on resize' pattern used by the Benchmark tab's own growth-
    chart canvas binding (see primeatlas/benchmark/benchmark_tab.py's _draw_growth_chart). .frame
    is what the caller packs/grids into its own parent, exactly like a plain ttk.Frame
    would be."""

    ROW_GAP = 4

    def __init__(self, parent):
        self.frame = ttk.Frame(parent)
        self._items = []  # [(widget, padx_left)], in add() order
        self.frame.bind("<Configure>", self._reflow)

    def add(self, widget, padx_left=0):
        self._items.append((widget, padx_left))
        return widget

    def _reflow(self, event):
        width = event.width
        if width <= 1 or not self._items:
            return
        x = 0
        y = 0
        row_height = 0
        for widget, padx_left in self._items:
            widget.update_idletasks()
            w = widget.winfo_reqwidth()
            h = widget.winfo_reqheight()
            if x > 0 and x + padx_left + w > width:
                x = 0
                y += row_height + self.ROW_GAP
                row_height = 0
            widget.place(x=x + padx_left, y=y, width=w, height=h)
            x += padx_left + w
            row_height = max(row_height, h)
        self.frame.configure(height=y + row_height)


def add_page_nav_group(flow_row, T, page_label_var, on_prev, on_next, on_goto=None,
                        label_width=16, group_gap=14,
                        prev_key="common.prev_page", next_key="common.next_page"):
    """Adds a standard page-navigation cluster (Prev / page label / Next, optionally
    followed by a Page: [entry][Go] jump group) to `flow_row` as ATOMIC sub-frames --
    each inner ttk.Frame packs its own children with plain pack(side="left") and is
    handed to FlowRow.add() as a single item, so FlowRow's own wrap-on-resize (see its
    docstring) only ever breaks BETWEEN whole clusters, never in the middle of one.

    Added item by item (Prev/label/Next/"Page:"/entry/Go as six FlowRow items), FlowRow
    could wrap mid-cluster on a narrow pane (Prev/label/Next on one line,
    "Page:"/entry/Go stranded on the next), which reads as an accidental layout. Used by
    the Prime numbers tab's preview-nav row (btn_row), constellations_hits_tab.py and
    constellations_records_tab.py.

    prev_key/next_key default to the generic "common.prev_page"/"common.next_page"
    strings, but callers navigating real hit-FILE pages (as opposed to the small
    in-memory sub-page within one loaded file page) pass
    "const_records.file_page_prev"/"file_page_next" instead, so the two different
    kinds of pagination a pattern can have stay visually distinguishable ("Previous"
    vs. "Prev file page") rather than reading as duplicate controls.

    Returns (prev_btn, next_btn, goto_entry) -- goto_entry is None when on_goto is not
    given (a file-page nav cluster with no jump-to-page entry, just Prev/Next/label).
    Callers still own page_label_var, prev_btn.configure(state=...), etc. -- this only
    replaces how the widgets are BUILT and GROUPED, not who tracks them.

    Layout order is Prev, Next, THEN the label (not Prev/label/Next) -- the two
    buttons read as one pair, with the "page X / Y" count following them rather than
    splitting them apart."""
    nav_frame = ttk.Frame(flow_row.frame)
    prev_btn = ttk.Button(nav_frame, text=T(prev_key), command=on_prev, state="disabled")
    prev_btn.pack(side="left")
    next_btn = ttk.Button(nav_frame, text=T(next_key), command=on_next, state="disabled")
    next_btn.pack(side="left")
    ttk.Label(nav_frame, textvariable=page_label_var, width=label_width,
              anchor="center").pack(side="left")
    flow_row.add(nav_frame, padx_left=group_gap if flow_row._items else 0)

    goto_entry = None
    if on_goto is not None:
        _goto_frame, goto_entry = _build_goto_group(flow_row.frame, T, on_goto)
        flow_row.add(_goto_frame, padx_left=group_gap)

    return prev_btn, next_btn, goto_entry


def _build_goto_group(parent, T, on_goto):
    """Builds the "Page:"/entry/Go jump-to-page cluster shared by add_page_nav_group
    and add_page_nav_row, so
    the ipady height-matching fix below (entry vs. button, see its own comment) lives in
    exactly one place. Returns (goto_frame, goto_entry); the caller packs/adds
    goto_frame itself, since the two callers place it differently (a FlowRow item vs.
    flush against a plain row's right edge)."""
    goto_frame = ttk.Frame(parent)
    ttk.Label(goto_frame, text=T("common.page_prefix")).pack(side="left")
    goto_entry = ttk.Entry(goto_frame, width=6)
    goto_entry.bind("<Return>", lambda _e: on_goto())
    goto_btn = ttk.Button(goto_frame, text=T("common.goto"), command=on_goto)
    # The "clam" theme (see prime_atlas_v2.py's _apply_theme) gives TButton more
    # vertical padding than TEntry, so side by side they sit at visibly
    # different heights. Pad the entry's own height (ipady) up to the button's
    # actual requested height instead of hardcoding a pixel guess, so the two
    # stay level even if the theme/font/DPI scaling changes later.
    goto_frame.update_idletasks()
    extra = max(0, goto_btn.winfo_reqheight() - goto_entry.winfo_reqheight())
    goto_entry.pack(side="left", padx=(4, 4), ipady=extra // 2)
    goto_btn.pack(side="left")
    return goto_frame, goto_entry


def add_page_nav_row(parent, T, page_label_var, on_prev, on_next, on_goto=None,
                      label_width=16, prev_key="common.prev_page",
                      next_key="common.next_page"):
    """Builds ONE full page-nav row as a plain (non-wrapping) ttk.Frame -- Prev/Next/
    label packed on the LEFT, an optional "Page:"/entry/Go jump group flush against
    the RIGHT edge -- instead of FlowRow's left-to-right flow-and-wrap.

    Used where two of these rows stack on top of each other next to a shared tall
    button (Storage's hits_export_btn spanning both) and their jump groups need to
    land at the SAME right edge on both rows for a symmetric look, regardless of how
    much shorter one row's left cluster is than the other's -- FlowRow's flow model
    can't express "flush right", and on a narrow pane it would wrap the second row's
    jump group onto a stray third line, left-anchored under nothing in particular.

    Unlike FlowRow, this never reflows onto extra lines -- callers rely on their
    container never getting narrower than both rows' combined natural width (see e.g.
    constellations_hits_tab.py's own paneconfigure(minsize=...) call, sized from these
    rows' own winfo_reqwidth() after construction); below that width the jump group
    just crowds against the left cluster instead of wrapping.

    Returns (row_frame, prev_btn, next_btn, goto_entry) -- row_frame is what the
    caller packs into its own parent; goto_entry is None when on_goto is not given."""
    row_frame = ttk.Frame(parent)
    left = ttk.Frame(row_frame)
    prev_btn = ttk.Button(left, text=T(prev_key), command=on_prev, state="disabled")
    prev_btn.pack(side="left")
    next_btn = ttk.Button(left, text=T(next_key), command=on_next, state="disabled")
    next_btn.pack(side="left")
    ttk.Label(left, textvariable=page_label_var, width=label_width,
              anchor="center").pack(side="left")
    left.pack(side="left")

    goto_entry = None
    if on_goto is not None:
        goto_frame, goto_entry = _build_goto_group(row_frame, T, on_goto)
        goto_frame.pack(side="right")

    return row_frame, prev_btn, next_btn, goto_entry


def clamp_pane_min_width(paned, pane_widget, min_width):
    """Prevents `pane_widget` (one child of the two-pane horizontal `paned`
    ttk::panedwindow, sash index 0) from ever being dragged narrower than
    `min_width` pixels -- ttk::panedwindow's own pane() only supports a "weight"
    option, not minsize (unlike the classic, unthemed tk.PanedWindow), so there is no
    built-in way to say this directly.

    Used for a detail pane holding an add_page_nav_row() (see its own docstring) --
    that row never wraps onto extra lines, so past this width its right-flush
    "Page:"/entry/Go jump group starts sliding off the pane's own edge and out of
    view entirely, not just crowding the left cluster. Used by the Prime numbers and
    Constellations Storage previews.

    Whenever `pane_widget`'s own width changes (a sash drag included, since dragging
    resizes both panes), the sash is clamped back if it would make `pane_widget`
    narrower than `min_width`. The corrective sashpos() call is deferred via
    after_idle rather than issued straight from the <Configure> handler -- calling it
    synchronously, mid-geometry-pass, leaves sashpos() reporting the corrected value
    while the pane's actual on-screen width stays desynced at the too-narrow size
    until a LATER, unrelated redraw;
    deferring to a fresh idle turn lets Tk finish the geometry pass in progress first."""
    def _clamp_sash(max_allowed_sash):
        paned.sashpos(0, max_allowed_sash)

    def _enforce(_event=None):
        total = paned.winfo_width()
        if total <= 1:
            return
        max_allowed_sash = max(0, total - min_width)
        if paned.sashpos(0) > max_allowed_sash:
            paned.after_idle(_clamp_sash, max_allowed_sash)

    pane_widget.bind("<Configure>", _enforce, add="+")
    pane_widget.after_idle(_enforce)


class HeightGrip:
    """A thin drag handle that sets the height of one or more line-sized widgets (Text,
    Listbox, Treeview -- anything whose `height` option counts lines or rows). Dragging
    it changes every target's height by whole lines, clamped to [min_lines, max_lines];
    on_change (no args) fires once when the drag ends.

    `targets` is a widget, a list of widgets, or a no-argument callable returning either
    (for a widget that is destroyed and rebuilt later). The grip lives in `parent`; when
    `after` is given it is packed right below that widget, otherwise the caller packs it
    with pack()."""

    def __init__(self, parent, targets, *, after=None, min_lines=3, max_lines=200,
                 on_change=None, padx=0, pady=(0, 4)):
        self._targets = targets
        self.min_lines = min_lines
        self.max_lines = max_lines
        self._on_change = on_change
        self._pack_options = {"fill": "x", "padx": padx, "pady": pady}
        self._drag = None
        self.frame = ttk.Frame(parent, height=8, cursor="sb_v_double_arrow")
        line = ttk.Separator(self.frame, orient="horizontal")
        line.place(relx=0.35, rely=0.5, relwidth=0.3)
        for widget in (self.frame, line):
            widget.configure(cursor="sb_v_double_arrow")
            widget.bind("<ButtonPress-1>", self._on_press)
            widget.bind("<B1-Motion>", self._on_drag)
            widget.bind("<ButtonRelease-1>", self._on_release)
        if after is not None:
            self.pack(after=after)

    def pack(self, after=None):
        options = dict(self._pack_options)
        if after is not None:
            options["after"] = after
        self.frame.pack(**options)

    def pack_forget(self):
        self.frame.pack_forget()

    def targets(self):
        targets = self._targets() if callable(self._targets) else self._targets
        if not isinstance(targets, (list, tuple)):
            targets = [targets]
        return [t for t in targets if t is not None and t.winfo_exists()]

    def line_height(self):
        """Pixels per line of the first target: the Treeview style's row height, or the
        target font's line spacing."""
        targets = self.targets()
        if not targets:
            return 1
        target = targets[0]
        if isinstance(target, ttk.Treeview):
            style = target.cget("style") or "Treeview"
            try:
                rowheight = int(ttk.Style(target).lookup(style, "rowheight") or 0)
            except (TypeError, ValueError):
                rowheight = 0
            if rowheight > 0:
                return rowheight
            return tkfont.nametofont("TkDefaultFont", root=target).metrics("linespace") + 4
        return max(1, tkfont.Font(root=target, font=target.cget("font")).metrics("linespace"))

    def _on_press(self, event):
        targets = self.targets()
        if targets:
            self._drag = (event.y_root, [int(t.cget("height")) for t in targets],
                          self.line_height())

    def _on_drag(self, event):
        if self._drag is None:
            return
        start_y, start_lines, line = self._drag
        delta = int((event.y_root - start_y) / line)
        for target, lines in zip(self.targets(), start_lines):
            lines = max(self.min_lines, min(self.max_lines, lines + delta))
            if lines != int(target.cget("height")):
                target.configure(height=lines)

    def _on_release(self, _event):
        if self._drag is None:
            return
        self._drag = None
        if self._on_change is not None:
            self._on_change()


SCROLL_PAD_WIDTH = SCROLL_PAD_WIDTH_DEFAULT
_scroll_pads = weakref.WeakSet()


def set_scroll_pad_width(width):
    """Sets the width (clamped) of every live ScrollPad and the default for pads built
    afterwards."""
    global SCROLL_PAD_WIDTH
    SCROLL_PAD_WIDTH = clamp_scroll_pad_width(width)
    for pad in list(_scroll_pads):
        pad.set_width(SCROLL_PAD_WIDTH)


class ScrollPad:
    """A strip along the right edge of a scrollable page, next to its scrollbar: while the
    pointer is over it the mouse wheel always scrolls the page, whatever self-scrolling
    terminals, lists or tables fill the rest of the page. `scroll(units)` scrolls the
    page by that many canvas units (negative = up). `text` is drawn vertically down the
    strip. The caller packs `.frame` (a Canvas, so the label can be rotated and the
    pointer never enters a child widget, which would fire <Leave> on the strip).

    Bound app-wide (bind_all) only between <Enter> and <Leave>, the same scoping the page
    canvases use for their own wheel handling. attach(widget) gives another widget (the
    page scrollbar next to the strip) the same behavior."""

    _WHEEL_EVENTS = ("<MouseWheel>", "<Button-4>", "<Button-5>")

    def __init__(self, parent, scroll, *, text="", width=None):
        if width is None:
            width = SCROLL_PAD_WIDTH
        self._scroll = scroll
        self.text = text
        style = ttk.Style(parent)
        background = style.lookup("TFrame", "background") or None
        self._foreground = style.lookup("TLabel", "foreground") or "#808080"
        self.frame = tk.Canvas(parent, width=width, highlightthickness=0, borderwidth=1,
                               relief="groove", cursor="sb_v_double_arrow")
        if background:
            self.frame.configure(background=background)
        self.frame.bind("<Enter>", self._on_enter)
        self.frame.bind("<Leave>", self._on_leave)
        self.frame.bind("<Configure>", lambda _e: self._draw_label())
        self.attached = []
        _scroll_pads.add(self)

    def set_width(self, width):
        """No-op (and drops the pad from the live registry) once its widget or its whole
        Tk application is destroyed."""
        try:
            if self.frame.winfo_exists():
                self.frame.configure(width=width)
                self._draw_label()
                return
        except tk.TclError:
            pass
        _scroll_pads.discard(self)

    def attach(self, widget):
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        self.attached.append(widget)

    def _draw_label(self):
        self.frame.delete("label")
        if not self.text:
            return
        width = max(self.frame.winfo_width(), int(self.frame.cget("width")))
        height = max(self.frame.winfo_height(), 1)
        self.frame.create_text(width / 2, height / 2, text=self.text, angle=270,
                               fill=self._foreground, tags="label")

    def wheel(self, event):
        num = getattr(event, "num", 0)
        if num == 4:
            units = -3
        elif num == 5:
            units = 3
        else:
            units = int(-3 * (event.delta / 120))
        if units:
            self._scroll(units)

    def _on_enter(self, _event):
        for sequence in self._WHEEL_EVENTS:
            self.frame.bind_all(sequence, self.wheel)

    def _on_leave(self, _event):
        for sequence in self._WHEEL_EVENTS:
            self.frame.unbind_all(sequence)
