"""
responsive.py -- the layout coordinator: lays out the elements whose arrangement depends on
their width (wrapping rows, panes pinned to a computed width) top-down, so no element lays
itself out from its own <Configure> events and no two elements can resize each other in a
loop.

Model (Flutter's "constraints go down, sizes go up", CSS container queries):
- an element is registered with add(widget, layout, width=None, key=None); layout(width)
  arranges its content for `width` (the widget's own width unless `width` is a callable),
  and the element's height follows from that;
- a container's width never depends on its content: <Configure> events that change only a
  height are ignored, and a layout runs only when the width or key() (its content sizes)
  differs from the last layout's;
- a pass lays the requested elements out in rounds, outer (shallower) before inner; a
  request made during a round goes to the next one, which accepts only elements deeper than
  the shallowest of the round before (ResizeObserver's rule), and at most MAX_ROUNDS rounds
  run. A refused request or a round over the limit is logged with the widget and dropped;
  the app keeps running.

Triggers: a width change of an element's widget (a window resize, a sash drag), or of a box
it watches (Item.watch) while its widget's width changes too, waits DEBOUNCE_MS after the
last change, so dragging an edge gives one pass once it stops; an element first shown (its
tab selected), one never laid out yet getting its first width, a watched box settling while
the widget keeps its width, or Item.request() runs at the next idle turn. An element not shown
is laid out when it is shown.

width_class() names the window width band (WIDE_MIN, MEDIUM_MIN); elements may use it or
lay out for the exact width. apply_min_width() keeps the app window at least
MIN_WINDOW_WIDTH wide: the narrowest width at which every tab is checked to show all its
controls (unitTests/test_small_screen_layout.py).
"""
import logging

from primeatlas.core import font_scale

log = logging.getLogger("primeatlas.responsive")

# Width bands of the window. Arbitrary: a full-HD window, a 13" full-HD screen at 150 %.
WIDE_MIN = 1600
MEDIUM_MIN = 1280

# Narrowest app window: the narrowest width of the layout map, checked with nothing cut.
MIN_WINDOW_WIDTH = 800

# Pause after the last width change before a pass. Arbitrary: long enough to merge the
# steps of a drag, short enough to look immediate once it stops.
DEBOUNCE_MS = 120

# Rounds one pass may run; a deeper element per round, so this bounds the nesting a chain
# of requests may reach. Arbitrary, above any real nesting of laid-out elements.
MAX_ROUNDS = 12


def width_class(width):
    if width >= WIDE_MIN:
        return "wide"
    if width >= MEDIUM_MIN:
        return "medium"
    return "narrow"


def apply_min_width(root):
    """Sets the window's minimum width to MIN_WINDOW_WIDTH, or the screen's width when that
    is less; the minimum height stays as it is."""
    root.minsize(min(MIN_WINDOW_WIDTH, root.winfo_screenwidth()), root.minsize()[1])


def coordinator(widget):
    """The Coordinator of `widget`'s Tk root, created on first use."""
    root = widget._root()
    found = getattr(root, "_layout_coordinator", None)
    if found is None:
        found = Coordinator(root)
        root._layout_coordinator = found
    return found


class Item:
    """One registered element. `last` is (width, key) of its last layout, None before it."""

    def __init__(self, coordinator, widget, layout, width, key):
        self._coordinator = coordinator
        self.widget = widget
        self.layout = layout
        self._width = width
        self._key = key
        self.depth = str(widget).count(".")
        self.last = None
        self._seen_width = None
        self._laid_width = None  # the widget's own width at the last layout
        widget.bind("<Configure>", self._on_configure, add="+")
        widget.bind("<Map>", lambda _e: self.request(), add="+")

    def request(self):
        """Lays the element out at the next idle turn if its width or content changed."""
        self._coordinator.request(self)

    def watch(self, widget):
        """A width change of `widget` (another box the layout measures) triggers the element:
        at the next idle turn while the element's own widget keeps the width of its last
        layout (the box settles after that layout), after DEBOUNCE_MS while that width
        changes too (a drag)."""
        seen = {"width": None}

        def on_configure(event):
            if event.width != seen["width"]:
                seen["width"] = event.width
                if self.widget.winfo_width() == self._laid_width:
                    self.request()
                else:
                    self._coordinator.resized(self)
        widget.bind("<Configure>", on_configure, add="+")

    def width(self):
        """The width laid out for: `width()` when given, else the widget's own width, on a
        scrollable page never past the page's right edge as it is with the scrollbar shown
        (ScrollablePage.steady_width(), as wrap_label.py measures). Showing or hiding the
        scrollbar then never changes a layout: a layout following it, a debounce late, would
        make the content taller after the page got wider and show and hide the scrollbar
        for ever."""
        if self._width is not None:
            return self._width()
        width = self.widget.winfo_width()
        page = self._page()
        if page is None or page.canvas.winfo_width() <= 1:  # no page, or not sized yet
            return width
        steady_right = page.canvas.winfo_rootx() + page.steady_width()
        return min(width, steady_right - self.widget.winfo_rootx())

    def _page(self):
        """The ScrollablePage (duck-typed: steady_width) the widget is on, or None."""
        if not hasattr(self, "_page_found"):
            node = self.widget.master
            self._page_found = None
            while node is not None:
                target = getattr(node, "wheel_target", None)
                if target is not None and hasattr(target, "steady_width"):
                    self._page_found = target
                    break
                node = node.master
        return self._page_found

    def key(self):
        return self._key() if self._key is not None else None

    def alive(self):
        try:
            return bool(self.widget.winfo_exists())
        except Exception:  # the Tk interpreter itself is gone
            return False

    def _on_configure(self, event):
        if event.width != self._seen_width:
            self._seen_width = event.width
            self._coordinator.resized(self)

    def run(self):
        """Lays out when shown, with a known width, and changed since the last layout."""
        if not self.widget.winfo_ismapped():
            return
        width = self.width()
        if width <= 1 or (width, self.key()) == self.last:
            return
        self.layout(width)
        self.last = (width, self.key())
        self._laid_width = self.widget.winfo_width()


class Coordinator:
    def __init__(self, root):
        self.root = root
        self.items = []
        self.passes = 0
        self._requested = []
        self._idle_job = None
        self._debounce_job = None
        self._running = False

    def add(self, widget, layout, width=None, key=None):
        item = Item(self, widget, layout, width, key)
        self.items.append(item)
        self.request(item)
        return item

    def request(self, item):
        if item not in self._requested:
            self._requested.append(item)
        if not self._running and self._idle_job is None:
            self._idle_job = self.root.after_idle(self._run)

    def resized(self, item):
        if item.last is None:  # never laid out: its first width is not a drag to wait out
            self.request(item)
            return
        if item not in self._requested:
            self._requested.append(item)
        if self._running:
            return
        if self._debounce_job is not None:
            self.root.after_cancel(self._debounce_job)
        self._debounce_job = self.root.after(DEBOUNCE_MS, self._run)

    def _run(self):
        for job in (self._idle_job, self._debounce_job):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        self._idle_job = self._debounce_job = None
        if self._running:
            return
        self._running = True
        try:
            # A display change may have reset the font scale; widgets lay out under it.
            font_scale.check(self.root)
            self._pass()
        finally:
            self._running = False
            self.passes += 1
        self.items = [i for i in self.items if i.alive()]

    def _pass(self):
        floor = -1
        batch = self._requested
        self._requested = []
        rounds = 0
        while batch:
            batch = [i for i in batch if i.alive()]
            refused = [i for i in batch if i.depth <= floor]
            for item in refused:
                log.warning("layout loop: %s asked for another layout in the same pass",
                            item.widget)
            batch = [i for i in batch if i.depth > floor]
            if not batch:
                break
            rounds += 1
            if rounds > MAX_ROUNDS:
                log.warning("layout pass stopped after %d rounds: %s", MAX_ROUNDS,
                            ", ".join(str(i.widget) for i in batch))
                break
            for item in sorted(batch, key=lambda i: i.depth):
                if item.alive():
                    item.run()
            floor = min(i.depth for i in batch)
            batch = self._requested
            self._requested = []
