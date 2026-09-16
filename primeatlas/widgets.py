"""
widgets.py -- small, generic tkinter widget helpers with no application-specific state,
shared by more than one tab. Extracted from prime_atlas_v1.py during the refactor
branch's Faza 3 (tab-by-tab backend/UI split) when the "Prime numbers" tab
extraction (primeatlas/primes_tab.py) needed FlowRow but the Constellations tab (still
in prime_atlas_v1.py at the time) also uses it -- moving it here instead of duplicating
it into primes_tab.py avoids exactly the kind of copy-paste this whole refactor branch
exists to undo. prime_atlas_v1.py imports it back as `from primeatlas.widgets import
FlowRow as _FlowRow` to keep its own existing call sites unchanged.

This is one of a small number of files in primeatlas/ that import tkinter -- see
settings_tab.py's own docstring for the general "pure logic elsewhere" convention this
package otherwise follows; FlowRow is UI-only by nature (it lays out already-built
widgets), so there is no non-tkinter half to split it into.
"""
from tkinter import ttk


class FlowRow:
    """A button-row container that wraps its children onto additional lines instead of
    running them off the edge of the window. A plain ttk.Frame with every child
    .pack(side="left")'d onto ONE line has this failure mode: on a narrow window (or a
    narrow detail pane after the split-view divider is dragged), the rightmost controls
    simply run past the frame's right edge and become invisible/unreachable, with no way
    to get to them short of resizing the whole window -- this is what the Prime numbers
    and Constellations tabs' preview-navigation rows (Load preview / Prev / page label /
    Next / page-goto entry) hit, e.g. page-nav buttons in the Constellations tab cut off
    outside the app window's right edge.

    Children are added via .add(widget, padx_left=...) instead of widget.pack(...); this
    class lays them out itself using place() (which, unlike pack/grid, doesn't force a
    single line or a fixed grid) and re-flows on every <Configure> of its own frame --
    same 'safe to call again on resize' pattern used by the Benchmark tab's own growth-
    chart canvas binding (see primeatlas/benchmark_tab.py's _draw_growth_chart). .frame
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

    Before this helper, every call site added Prev/label/Next/"Page:"/entry/Go as six
    separate FlowRow items -- on a narrow pane, FlowRow could wrap mid-cluster (e.g.
    Prev/label/Next on one line, "Page:"/entry/Go stranded alone on the next, with no
    visual link between them), which read as an accidental layout rather than a
    deliberate one -- observed on the Prime numbers tab's preview-nav row (btn_row);
    the same duplicated pattern also existed in constellations_hits_tab.py and
    constellations_records_tab.py, fixed here once instead of three times.

    prev_key/next_key default to the generic "common.prev_page"/"common.next_page"
    strings, but callers navigating real hit-FILE pages (as opposed to the small
    in-memory sub-page within one loaded file page) pass
    "const_records.file_page_prev"/"file_page_next" instead, so the two different
    kinds of pagination a pattern can have stay visually distinguishable ("Poprzednia"
    vs. "Poprz. strona pliku") rather than reading as duplicate controls.

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
    """Builds the "Strona:"/entry/Idz jump-to-page cluster shared by add_page_nav_group
    and add_page_nav_row -- factored out when add_page_nav_row was added, so
    the ipady height-matching fix below (entry vs. button, see its own comment) lives in
    exactly one place. Returns (goto_frame, goto_entry); the caller packs/adds
    goto_frame itself, since the two callers place it differently (a FlowRow item vs.
    flush against a plain row's right edge)."""
    goto_frame = ttk.Frame(parent)
    ttk.Label(goto_frame, text=T("common.page_prefix")).pack(side="left")
    goto_entry = ttk.Entry(goto_frame, width=6)
    goto_entry.bind("<Return>", lambda _e: on_goto())
    goto_btn = ttk.Button(goto_frame, text=T("common.goto"), command=on_goto)
    # The "clam" theme (see prime_atlas_v1.py's _apply_theme) gives TButton more
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
    label packed on the LEFT, an optional "Strona:"/entry/Idz jump group flush against
    the RIGHT edge -- instead of FlowRow's left-to-right flow-and-wrap.

    Used where two of these rows stack on top of each other next to a shared tall
    button (Magazyn's hits_export_btn spanning both) and their jump groups need to
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
    "Strona:"/entry/Idz jump group starts sliding off the pane's own edge and out of
    view entirely, not just crowding the left cluster. This use is on the Prime
    numbers tab's own Magazyn preview, added after the same fix had already gone
    into Magazyn/Constellations' own (so this call is the second, not first, use).

    Whenever `pane_widget`'s own width changes (a sash drag included, since dragging
    resizes both panes), the sash is clamped back if it would make `pane_widget`
    narrower than `min_width`. The corrective sashpos() call is deferred via
    after_idle rather than issued straight from the <Configure> handler -- calling it
    synchronously, mid-geometry-pass, left sashpos() reporting the corrected value
    while the pane's actual on-screen width stayed desynced at the too-narrow size
    until a LATER, unrelated redraw (reproduced while building the first use of this);
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
