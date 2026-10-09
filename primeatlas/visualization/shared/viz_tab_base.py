"""
viz_tab_base.py -- VizTabBase(BaseTab), the Tk side every visualization sub-tab shares:
launching primeatlas/visualization/shared/renderer.py as a separate native Windows
subprocess (LocalLoggedRunner, live stdout capture on a background thread), the live
console, the HUD panel fed by renderer.py's HUD_STATE lines, live pause/resume over
stdin, Reset, the Start/Resume "reopen where playback left off" N, and the vertically
scrollable container. A sub-tab builds its own launch form and renderer argv, then
calls _launch_renderer().

Subclasses provide: `LOCALE_PREFIX` (its translation-key namespace, e.g. "rings"; the
keys console_launching/status_launching/hud_panel_placeholder/console_closed_ok/
status_closed/console_closed_error/status_error/status_paused/console_paused/
status_running/console_resumed/hud_status_running/hud_status_stopped/hud_header must
exist under it), the widgets `open_button`, `stop_button`, `console`, `hud_var`, and
the methods `_set_launch_params_readonly(readonly)` and `_restore_last_n(n)`.
"""
import json
import queue
import tkinter as tk
from tkinter import ttk

from ...core.base_tab import BaseTab
from ...core.widgets import ScrollPad
from ...generation.generation import _eval_quick_number
from .window_mode import center_tk_window

# Must match renderer.py's own emit_hud_state()
# print prefix exactly -- kept as one shared constant name (renderer.py runs as a
# separate subprocess and can't import a shared constant from here) so a future
# rename doesn't silently desync the two string literals.
_HUD_STATE_PREFIX = "HUD_STATE:"

# Must match renderer.py's own two plain
# print("RING_VIZ_PAUSED"/"RING_VIZ_RESUMED") lines exactly -- these are NOT
# JSON payloads like _HUD_STATE_PREFIX, just bare sentinel lines, since
# there's no data to carry, only a state transition to react to.
_RING_VIZ_PAUSED_LINE = "RING_VIZ_PAUSED"
_RING_VIZ_RESUMED_LINE = "RING_VIZ_RESUMED"


def parse_generate_range(raw_from, raw_to):
    """The empty-storage generate dialog's From/To fields as (start, end_inclusive), or
    the error key (under the tab's LOCALE_PREFIX) to show. "To" is required and >= 2;
    an empty "From" means 2; both accept the app's number forms (10**7, 1e7)."""
    raw_from, raw_to = raw_from.strip(), raw_to.strip()
    end = _eval_quick_number(raw_to) if raw_to else None
    if end is None or end < 2:
        return "error_generate_to_required"
    if raw_from:
        start = _eval_quick_number(raw_from)
        if start is None or start < 0:
            return "error_generate_from_invalid"
    else:
        start = 2
    if start > end:
        return "error_generate_order"
    return start, end


class VizTabBase(BaseTab):
    LOCALE_PREFIX = None

    def __init__(self, parent, get_portal_folder, status_var, translator, totals_progress,
                 app_settings=None):
        super().__init__(parent, translator)
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self.totals_progress = totals_progress
        # Backs the "start from where you left off" behavior --
        # see _build_ui's own use of ring_viz_params and _on_open's save call below.
        # None in unit tests that construct RingsTab directly without an AppSettings
        # (see test_rings_tab.py) -- every persistence call below is a no-op then, and
        # _build_ui falls back to the same hardcoded first-run defaults it always had.
        self._app_settings = app_settings
        self._runner = None
        self._queue = None
        # Last N seen in a HUD_STATE line from the most
        # recently running process (see _apply_hud_state/_poll_queue below).
        # Powers the Start/Resume button: when the GL
        # window closes on its own (Esc, window-close control, or a crash)
        # rather than via an explicit Reset click, the N field is updated to
        # this value so the next launch reopens right where playback left
        # off, instead of wherever the field happened to still say. Cleared
        # by _on_reset, which is the one path that deliberately discards it.
        self._last_hud_n = None
        # True while the running renderer.py
        # process is alive but hidden/idling, waiting for a RESUME command
        # (see _poll_queue's RING_VIZ_PAUSED/RESUMED handling below and
        # renderer.py's own start_stdin_command_reader doc-comment for the
        # full protocol). Distinct from "not running at all" -- open_button
        # is re-enabled in BOTH cases, but only this one sends "RESUME"
        # over stdin instead of launching a brand new subprocess.
        self._paused = False
        # The app's storage-fill offer (GenerationOfferCoordinator.offer_fill_storage_
        # range), injected by tabs that read storage; None = no offer, Start launches
        # as is even with empty storage.
        self._offer_generate_storage = None

    def _ask_generate_range(self, default_from, default_to):
        """Modal dialog shown when Start finds the storage empty: explains it and asks
        for the range to generate, prefilled with `default_from`/`default_to`. Returns
        (start, end_inclusive) on Generate, None on Cancel/close. Invalid input is
        reported inside the dialog, which stays open."""
        dialog = tk.Toplevel(self)
        dialog.title(self._tk("empty_storage_title"))
        dialog.transient(self.winfo_toplevel())
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=self._tk("empty_storage_message"), wraplength=460,
                  justify="left").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Label(body, text=self._tk("empty_storage_from")).grid(row=1, column=0, sticky="w")
        from_entry = ttk.Entry(body, width=30)
        from_entry.insert(0, default_from)
        from_entry.grid(row=1, column=1, sticky="w", padx=(6, 0), pady=2)
        ttk.Label(body, text=self._tk("empty_storage_to")).grid(row=2, column=0, sticky="w")
        to_entry = ttk.Entry(body, width=30)
        to_entry.insert(0, default_to)
        to_entry.grid(row=2, column=1, sticky="w", padx=(6, 0), pady=2)
        ttk.Label(body, text=self._tk("empty_storage_hint"), foreground="#888888", wraplength=460,
                  justify="left").grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        error_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=error_var, foreground="#cc3333", wraplength=460,
                  justify="left").grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
        result = {"value": None}

        def on_generate():
            parsed = parse_generate_range(from_entry.get(), to_entry.get())
            if isinstance(parsed, str):
                error_var.set(self._tk(parsed))
                return
            result["value"] = parsed
            dialog.destroy()

        buttons = ttk.Frame(body)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text=self._tk("empty_storage_generate"), command=on_generate).pack(side="left")
        ttk.Button(buttons, text=self._tk("empty_storage_cancel"), command=dialog.destroy).pack(
            side="left", padx=(6, 0))
        dialog.bind("<Return>", lambda _e: on_generate())
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        to_entry.focus_set()
        center_tk_window(dialog)
        dialog.grab_set()
        self.wait_window(dialog)
        return result["value"]

    def _offer_storage_fill(self, default_from, default_to, relaunch, on_cancel=None):
        """Empty storage on Start: asks for a range (see _ask_generate_range) and hands
        it to the injected `_offer_generate_storage(start, end_inclusive,
        on_finished)`. A successful fill calls `relaunch()` (the original Start); a
        failed or stopped one only reports. Cancel calls `on_cancel()` when given."""
        answer = self._ask_generate_range(default_from, default_to)
        if answer is None:
            if on_cancel is not None:
                on_cancel()
            return
        start, end = answer

        def on_finished(success):
            if success:
                self.status.set(self._tk("status_storage_ready"))
                relaunch()
            else:
                self.status.set(self._tk("status_storage_fill_failed"))

        if self._offer_generate_storage(start, end, on_finished):
            self.status.set(self._tk("status_generating_storage", start=f"{start:,}", end=f"{end:,}"))

    def _tk(self, key, **kwargs):
        """This sub-tab's own translation (`LOCALE_PREFIX`.`key`)."""
        return self.T(f"{self.LOCALE_PREFIX}.{key}", **kwargs)

    def _build_scrollable_container(self, parent):
        """Wraps `parent` in a vertically-scrollable canvas+frame and returns the
        inner ttk.Frame -- pack the tab's REAL content into that returned frame
        instead of into `parent` directly; everything else (canvas, scrollbar,
        width sync, mousewheel binding) is handled here.

        Same idiom as generation_tab.py's `_build_scrollable_container` and
        settings_tab.py's `_make_scrollable_tab`, kept as a self-contained copy per
        tkinter-importing tab module (this codebase's convention). With every
        section (Windows & tracking / Appearance / Audio) plus the HUD console
        visible, the tab can be taller than the window; the wrapper makes the
        overflow reachable via scrollbar/mousewheel instead of clipping it.

        Standard canvas-scrollregion idiom: an inner frame is placed on a canvas
        via create_window; the inner frame's own <Configure> (fires whenever its
        packed children change its natural size) updates the canvas' scrollregion
        to match, and the canvas' own <Configure> (fires on window resize) keeps
        the inner frame exactly as WIDE as the visible canvas so fill="x" widgets
        inside it span the full width instead of collapsing to their minimum
        content width. Mousewheel
        scrolling is bound only while the pointer is actually over this canvas
        (bound on <Enter>, unbound on <Leave>) so it doesn't steal wheel events
        from other scrollable widgets on other tabs. <MouseWheel> covers
        Windows/Mac; <Button-4>/<Button-5> cover X11 (Linux) which reports the
        wheel as button clicks instead of a delta.

        Returns `(inner, register_exclude)`
        instead of just `inner` -- `register_exclude(widget)` marks `widget` (and
        every descendant of it) as having its OWN independent scrolling (e.g. the
        HUD console's GenerationConsole.text.frame, which wraps a ScrolledText
        with its own native mousewheel handling), so the wheel/button handlers
        below skip scrolling THIS canvas whenever the event originates inside one
        of those subtrees -- the Enter/Leave-based bind_all/unbind_all toggling
        above only scopes scrolling to "pointer somewhere over the tab", it does
        NOT stop the global handler from ALSO firing (double-scrolling, on top of
        the console's own scroll) once the pointer is specifically over a nested
        widget that has its own competing scroll behavior."""
        exclude_roots = []

        def register_exclude(widget):
            exclude_roots.append(widget)

        def _event_over_excluded(event):
            widget = event.widget
            while widget is not None:
                if widget in exclude_roots:
                    return True
                widget = getattr(widget, "master", None)
            return False

        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, highlightthickness=0)
        # Tk's
        # Canvas defaults to yscrollincrement=0, which makes any "scroll N units" call (mousewheel,
        # scrollbar arrows) jump by ~10% of the canvas's CURRENT VIEWPORT height
        # instead of a small fixed pixel step, and doesn't clamp the view back to
        # 0 when content is shorter than the viewport. A small fixed increment
        # alone doesn't fully fix this, so scrolling is also hard-disabled below
        # whenever content already fits the viewport (see _content_fits()).
        canvas.configure(yscrollincrement=20)

        # `scroll_state["user_scrolled"]` starts False and flips to True the first
        # time the person actually drags the scrollbar or spins the wheel (see the
        # three handlers below). Until that happens, `_sync_scrollregion()` keeps
        # re-pinning the view to the top -- see that function's own comment for why
        # this is needed, not just the scrollregion-size fix below it.
        scroll_state = {"user_scrolled": False}

        def _content_fits():
            # Nothing to scroll to -- content already fits inside the visible
            # canvas. winfo_height() is 0/1 before the widget is first mapped,
            # so treat that as "doesn't fit yet" rather than "fits".
            canvas_h = canvas.winfo_height()
            return canvas_h > 1 and inner.winfo_reqheight() <= canvas_h

        def _on_scrollbar(*args):
            if _content_fits():
                return
            scroll_state["user_scrolled"] = True
            canvas.yview(*args)

        vsb = ttk.Scrollbar(outer, orient="vertical", command=_on_scrollbar)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        def _scroll_page(units):
            if _content_fits():
                return
            scroll_state["user_scrolled"] = True
            canvas.yview_scroll(units, "units")

        # Wheel over this strip and over the scrollbar always scrolls the page, see
        # ScrollPad.
        self._scroll_pad = ScrollPad(outer, _scroll_page, text=self.T("common.scroll_pad"))
        self._scroll_pad.frame.pack(side="right", fill="y")
        self._scroll_pad.attach(vsb)

        inner = ttk.Frame(canvas)
        inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        # NOTE (ported from generation_tab.py/settings_tab.py):
        # scrollregion is set from inner.winfo_reqwidth()/reqheight() -- NOT
        # canvas.bbox("all"), which can end up taller than the frame's actual
        # current content (mid-reflow right after a width change, before layout
        # has fully settled) and let yview scroll into stale leftover blank
        # space. Querying the frame's own requested size directly is always in
        # sync with what's actually packed inside it right now.
        #
        # That alone isn't enough either: this tab's content keeps changing
        # height after it first draws (mode switch greys out/re-enables the
        # Load Range fields, HUD panel text grows/shrinks per HUD_STATE line,
        # GenerationConsole's own collapsible pane) and Tk does not guarantee
        # the view stays pinned to the top pixel across a scrollregion resize.
        # So: as long as the person hasn't manually scrolled yet -- OR content
        # fits and there's nothing to scroll to regardless -- force the view
        # back to the top on every resync.
        def _sync_scrollregion():
            canvas.configure(scrollregion=(0, 0, inner.winfo_reqwidth(), inner.winfo_reqheight()))
            canvas_h = canvas.winfo_height()
            natural_h = inner.winfo_reqheight()
            if canvas_h > 1 and natural_h <= canvas_h:
                canvas.itemconfigure(inner_window, height=canvas_h)
            elif natural_h > 0:
                canvas.itemconfigure(inner_window, height=natural_h)
            if not scroll_state["user_scrolled"] or _content_fits():
                canvas.yview_moveto(0.0)

        def _on_inner_configure(_event):
            _sync_scrollregion()
        inner.bind("<Configure>", _on_inner_configure)

        def _on_canvas_configure(event):
            canvas.itemconfigure(inner_window, width=event.width)
            # Width change can immediately change required height (wraplength'd
            # Labels reflow) -- resync right away instead of waiting on inner's
            # own <Configure> so a window resize can't leave a stale scrollregion
            # behind for even one frame.
            canvas.after_idle(_sync_scrollregion)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            if _event_over_excluded(event) or _content_fits():
                return
            scroll_state["user_scrolled"] = True
            canvas.yview_scroll(int(-3 * (event.delta / 120)), "units")

        def _on_button4(event):
            if _event_over_excluded(event) or _content_fits():
                return
            scroll_state["user_scrolled"] = True
            canvas.yview_scroll(-3, "units")

        def _on_button5(event):
            if _event_over_excluded(event) or _content_fits():
                return
            scroll_state["user_scrolled"] = True
            canvas.yview_scroll(3, "units")

        def _bind_mousewheel(_event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            canvas.bind_all("<Button-4>", _on_button4)
            canvas.bind_all("<Button-5>", _on_button5)

        def _unbind_mousewheel(_event):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", _bind_mousewheel)
        canvas.bind("<Leave>", _unbind_mousewheel)

        return inner, register_exclude

    def _resume_if_paused(self):
        """Start/Resume click while a renderer process already exists. Returns True when
        the click is fully handled here (a paused process got RESUME, or a running one
        needs nothing), False when the caller should launch a new process."""
        # Live resume path: the process never
        # actually exited, it's just idling with its window hidden (see
        # renderer.py's own PAUSE/RESUME protocol) -- send it a command
        # instead of launching a brand new one, so N, playback state,
        # tempo, LCM cache, and (the whole point) audio all continue
        # exactly as they were, with zero discontinuity. is_running() is
        # still True here (the OS process never died), which is exactly
        # why self._paused is tracked as its own flag rather than reusing
        # that check.
        if self._runner is not None and self._paused:
            self._runner.send_line("RESUME")
            return True
        if self._runner is not None and self._runner.is_running():
            return True
        return False

    def _launch_renderer(self, argv, n, runner_cls):
        """Starts renderer.py with `argv` (`n` is the opening N, for the console line)
        via `runner_cls` (LocalLoggedRunner, passed in by the caller), locks the
        launch-time fields, and starts polling its output."""
        q = queue.Queue()
        # pipe_stdin=True so send_line("RESUME")
        # (see _resume_if_paused) has
        # an actual pipe to write to -- see LocalLoggedRunner's own
        # doc-comment for why this is opt-in rather than the default.
        runner = runner_cls(argv, q, pipe_stdin=True)
        self._runner = runner
        self._queue = q
        self._paused = False
        self.open_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        # Lock the launch-time-only fields the moment a
        # process is actually launched, not only once it's paused -- the
        # block should already be active right after opening the window.
        # They stay locked through running AND paused AND resumed -- Reset
        # is the only path that unlocks them again (see _on_reset), aside from the
        # process dying on its own (see _poll_queue's __exit__ branch, which
        # is the one other case where there's genuinely no live process left
        # to protect these fields' meaning against).
        self._set_launch_params_readonly(True)
        self.console.show()
        self.console.append(self._tk("console_launching", n=f"{n:,}") + "\n")
        self.status.set(self._tk("status_launching"))
        # Reset the HUD panel back to its placeholder text
        # on every new launch -- otherwise a stale snapshot from a PREVIOUS
        # run (different N entirely) would sit there until the new
        # process's first rebuild happens to emit its own HUD_STATE line.
        self.hud_var.set(self._tk("hud_panel_placeholder"))
        runner.start()
        self._poll_queue()

    def _on_reset(self):
        """Closes the GL window's process and unlocks every launch-time field
        again
        (see _set_launch_params_readonly), which is what distinguishes an
        explicit Reset click from just closing the GL window yourself (Esc /
        the window's own close control): a plain close is handled by
        _poll_queue's own __exit__ branch below, which treats it as an
        implicit pause and drops the last-seen live N into the N field for
        the Start/Resume button; THIS path discards that live-resume state
        instead (_last_hud_n below).

        Reset does not touch any field's contents, only unlocking them --
        forcing fields back to hardcoded defaults would fight against every
        field otherwise remembering its last-used value across launches (see
        ring_viz_params in app_settings.py). "Start clean" here means
        unlocked and ready to relaunch with the SAME values, not wiped ones;
        typing a new value (or the Esc/window-close implicit-resume path
        above) are the only ways any field's contents actually change."""
        if self._runner is not None:
            self._runner.stop()
        self._last_hud_n = None
        # terminate() kills the OS process
        # outright regardless of whether it's currently idling in the
        # hidden-window pause loop or actively rendering -- no special-
        # casing needed there -- but the Tkinter-side _paused flag is only
        # ever cleared by a RING_VIZ_RESUMED line, which will never arrive
        # for a process we just killed, so it must be reset explicitly here.
        self._paused = False
        # Don't wait for the async __exit__ queue item to re-enable these --
        # Reset is a deliberate "I'm done with this run" click, so the
        # fields should read as editable again immediately, not lag a poll
        # cycle behind terminate()'s own OS-level kill.
        self._set_launch_params_readonly(False)

    def _poll_queue(self):
        if self._queue is None:
            return
        try:
            while True:
                item = self._queue.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__exit__":
                    code = item[1]
                    # The process is actually
                    # gone now (proc.wait() returned), whether it was paused
                    # or not -- clear the flag so a later _on_open never
                    # mistakes a brand-new launch for a resume.
                    self._paused = False
                    self.open_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    # A real exit always means the fields are editable again
                    # -- covers both "exited while paused" (readonly was
                    # True) and the ordinary running-then-exits case (already
                    # editable, this is just a harmless no-op then).
                    self._set_launch_params_readonly(False)
                    if code == 0:
                        self.console.append(self._tk("console_closed_ok") + "\n")
                        self.status.set(self._tk("status_closed"))
                    else:
                        self.console.append(self._tk("console_closed_error", code=code) + "\n")
                        self.status.set(self._tk("status_error"))
                    # Implicit-pause resume: this branch
                    # fires whether the process ended by itself (Esc / the
                    # GL window's own close control / a crash) or via the
                    # Reset button (_on_reset) -- but _on_reset already
                    # cleared _last_hud_n to None BEFORE calling
                    # runner.stop(), so it always reads None here and this
                    # is a no-op on that path. Any other exit means the user
                    # didn't explicitly ask to discard progress, so drop the
                    # last N seen in a HUD_STATE line into the N field --
                    # the Start/Resume button's next click reopens right
                    # there instead of at whatever the field last said.
                    if self._last_hud_n is not None:
                        self._restore_last_n(self._last_hud_n)
                    self._runner = None
                    self._queue = None
                    return
                # renderer.py's own
                # emit_hud_state() prints exactly one such line per HUD
                # refresh (see that function's own doc-comment) --
                # LocalLoggedRunner's _read_loop puts one whole stdout
                # line per queue item (confirmed against its own
                # `for line in self.proc.stdout` body), so a plain
                # startswith check is reliable here, no partial-line
                # reassembly needed. Routed to the HUD panel INSTEAD OF
                # the scrolling console -- a raw JSON blob in the log
                # would just be noise next to the human-readable HUD
                # lines that already print alongside it.
                # The process is idling with its
                # window hidden, not exiting -- so this does NOT go through
                # the __exit__ branch above (the OS process is still alive,
                # LocalLoggedRunner's _read_loop only puts __exit__ once
                # proc.wait() actually returns). open_button is re-enabled so
                # Start/Resume becomes clickable again, but stop_button stays
                # enabled too since Reset must still be able to kill a paused
                # process (LocalLoggedRunner.stop()'s terminate() call works
                # regardless of what the subprocess's Python code is doing).
                if item.strip() == _RING_VIZ_PAUSED_LINE:
                    self._paused = True
                    self.open_button.configure(state="normal")
                    self.status.set(self._tk("status_paused"))
                    self.console.append(self._tk("console_paused") + "\n")
                    # The fields are already locked since _on_open's initial
                    # launch; pausing doesn't change that.
                    continue
                if item.strip() == _RING_VIZ_RESUMED_LINE:
                    self._paused = False
                    self.open_button.configure(state="disabled")
                    self.status.set(self._tk("status_running"))
                    self.console.append(self._tk("console_resumed") + "\n")
                    # Deliberately NOT re-enabling the
                    # fields here -- fields unlock only after Reset.
                    # Resuming is still not a fresh launch, so they stay
                    # locked.
                    continue
                if item.startswith(_HUD_STATE_PREFIX):
                    self._apply_hud_state(item[len(_HUD_STATE_PREFIX):])
                    continue
                self.console.append(item)
        except queue.Empty:
            pass
        self.after(150, self._poll_queue)

    def _apply_hud_state(self, raw_json):
        """Parses one renderer.py emit_hud_state() JSON payload and
        replaces (never appends to) self.hud_var's content. Malformed/
        truncated JSON is silently skipped rather than raised -- a stray
        parse hiccup on one tick's line must never crash the GUI thread;
        the next tick's line (a few dozen ms later during playback) simply
        supersedes it."""
        try:
            data = json.loads(raw_json)
        except (ValueError, TypeError):
            return
        n = data.get("n", 0)
        # Track the current N for the Start/Resume button
        # -- see __init__'s own doc-comment on _last_hud_n and _poll_queue's
        # __exit__ branch, which is what actually reads this back into the
        # N field once the process ends.
        self._last_hud_n = n
        count = data.get("count", 0)
        rebuild_ms = data.get("rebuild_ms", 0.0)
        running = data.get("running", False)
        tempo_ms = data.get("tempo_ms", 0)
        lines = data.get("lines", [])
        status = (self._tk("hud_status_running", tempo=tempo_ms) if running
                  else self._tk("hud_status_stopped"))
        header = self._tk("hud_header", n=f"{n:,}", count=f"{count:,}",
                         rebuild_ms=f"{rebuild_ms:.1f}", status=status)
        body = "\n".join(str(line) for line in lines)
        self.hud_var.set(header + ("\n" + body if body else ""))
