"""
generation_console.py -- GenerationConsole, a collapsible live-output pane with its own
clear/detach controls, used by both Generation-tab sections (pipeline, k-tuple search).

Detaching opens a larger Toplevel mirroring the SAME live output: append() writes into
every currently-registered mirror (the embedded pane plus an open detached copy, if any),
so neither can ever fall behind the other regardless of which one is visible at the time.
Closing the detached window only removes it from the mirror list -- it never clears or
otherwise affects the embedded pane's content.

extra_controls_builder, if given, is called once each time the detached window opens, with
the window itself as parent, to add extra widgets above the mirrored output (used by the
pipeline section to duplicate its Quick-gen panel so a run can be launched from the
detached window too -- see prime_atlas_v1.py's _build_detached_quick_panel). It may return
a no-argument cleanup callable, invoked when the window closes.
"""
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText


class GenerationConsole:
    def __init__(self, parent, translator, *, height=10, extra_controls_builder=None,
                 window_title=None):
        self.T = translator
        self._parent = parent
        self._extra_controls_builder = extra_controls_builder
        self._window_title = window_title or self.T("gen.detached_window_title")
        self._visible = False
        self._detached_win = None
        self._mirrors = []

        self.toggle_row = ttk.Frame(parent)
        self.toggle_row.pack(fill="x", padx=8, pady=(4, 0))
        self.toggle_btn = ttk.Button(self.toggle_row, text=self.T("gen.terminal_show"),
                                      command=self.toggle)
        self.toggle_btn.pack(side="left")
        self.clear_btn = ttk.Button(self.toggle_row, text=self.T("gen.terminal_clear"),
                                     command=self.clear)
        self.clear_btn.pack(side="left", padx=(6, 0))
        self.detach_btn = ttk.Button(self.toggle_row, text=self.T("gen.terminal_detach"),
                                      command=self.open_detached)
        self.detach_btn.pack(side="left", padx=(6, 0))

        self.text = ScrolledText(parent, height=height, font=("Consolas", 9),
                                  state="disabled", background="#111318",
                                  foreground="#d8d8d8")
        self._mirrors.append(self.text)
        # NOT packed here -- starts collapsed, see show()/hide()/toggle().

    # --- collapse/expand -------------------------------------------------------------

    def show(self):
        if not self._visible:
            self.text.pack(fill="both", expand=True, padx=8, pady=(0, 8))
            self._visible = True
            self.toggle_btn.configure(text=self.T("gen.terminal_hide"))

    def hide(self):
        if self._visible:
            self.text.pack_forget()
            self._visible = False
            self.toggle_btn.configure(text=self.T("gen.terminal_show"))

    def toggle(self):
        self.hide() if self._visible else self.show()

    # --- content -----------------------------------------------------------------

    def clear(self):
        """Clears every currently-registered mirror (embedded pane + detached copy, if
        open). Only ever called explicitly, via the Clear button -- a new run does NOT
        call this (see prime_atlas_v1.py's _on_run_loop/_on_run_constellation, which
        append a separator line instead), so several runs' output can stay stacked in
        the console for comparison until the person clears it themselves."""
        for widget in self._mirrors:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.configure(state="disabled")

    def append(self, text):
        """Writes into every currently-registered mirror. The embedded pane and an open
        detached window always show identical, up-to-date content -- there is only ever
        one write path, so neither can fall behind."""
        for widget in self._mirrors:
            widget.configure(state="normal")
            widget.insert("end", text)
            widget.see("end")
            widget.configure(state="disabled")

    # --- detached window ------------------------------------------------------------

    def open_detached(self):
        """Opens a larger Toplevel with its own copy of the current output (pre-seeded
        from the embedded pane's existing content, then kept in sync going forward) plus,
        if the caller supplied one, extra controls above it. Raises the existing window
        instead of opening a second one if already open."""
        if self._detached_win is not None and self._detached_win.winfo_exists():
            self._detached_win.lift()
            return

        win = tk.Toplevel(self._parent)
        win.title(self._window_title)
        win.geometry("1100x700")

        cleanup = None
        if self._extra_controls_builder is not None:
            cleanup = self._extra_controls_builder(win)

        # Own Clear button -- calls the SAME self.clear() as the embedded pane's, so it
        # empties every registered mirror (this window's copy AND the embedded pane)
        # rather than just the local view, keeping the "never diverge" guarantee from
        # this class's docstring intact even when the clear click happens from here.
        detached_btn_row = ttk.Frame(win)
        detached_btn_row.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Button(detached_btn_row, text=self.T("gen.terminal_clear"),
                   command=self.clear).pack(side="left")

        mirror = ScrolledText(win, font=("Consolas", 10), state="disabled",
                               background="#111318", foreground="#d8d8d8")
        mirror.pack(fill="both", expand=True, padx=8, pady=8)
        mirror.configure(state="normal")
        mirror.insert("end", self.text.get("1.0", "end-1c"))
        mirror.configure(state="disabled")
        self._mirrors.append(mirror)

        def _on_close():
            if mirror in self._mirrors:
                self._mirrors.remove(mirror)
            if cleanup is not None:
                cleanup()
            win.destroy()
            self._detached_win = None

        win.protocol("WM_DELETE_WINDOW", _on_close)
        self._detached_win = win
