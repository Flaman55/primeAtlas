"""
rings_tab.py -- RingsTab(BaseTab), the "Ring visualization" tab (Faza 3, see PLAN.md
at the repo root for the full phased rollout this belongs to). Launches the Faza 0-2
GPU renderer (primeatlas/ring_viz/renderer.py) as a separate native Windows subprocess
against the app's own currently-configured magazyn, given a target N.

WHY A SUBPROCESS, NOT EMBEDDED IN THIS WINDOW: GL's own event loop does not compose
with Tkinter's mainloop() -- see primeatlas/ring_viz/__init__.py's own docstring for
the full reasoning; already settled in PLAN.md's "Window embedding" design decision
before any of this tab's own code was written.

WHY LocalLoggedRunner AND NOT WslLoggedRunner: renderer.py is a plain native Windows
Python script (moderngl+glfw, no WSL involved anywhere) -- LocalLoggedRunner
(primeatlas/generation.py) already exists for exactly this "ordinary local subprocess,
live stdout capture on a background thread" shape (its only prior caller is the sympy
installer in settings_tab.py). PLAN.md's own point 5 said to reuse "the existing
WSL/GenerationConsole subprocess-management pattern" -- LocalLoggedRunner turned out to
be the closer fit once it was clear this specific launch is native, not WSL; GenerationConsole
(the collapsible live-output pane widget) is still reused as-is for the actual UI, since it
has no WSL-specific assumption baked in at all.

renderer.py's own print() calls (loading progress, the per-N-change rebuild line, see
that module's own docstring) already write to stdout -- LocalLoggedRunner's queue-based
capture surfaces those as real, user-visible progress text in this tab's console pane,
not just the GL window's own title bar (which nothing outside that window can see).

get_portal_folder is a deferred callable (same dependency-injection pattern as every
other extracted tab -- see research_goldbach_tab.py's own docstring), read fresh at
launch time rather than captured once, so a Settings-tab storage-path change takes
effect on the NEXT launch without this tab needing its own change-notification wiring.
"""
import os
import queue
import sys
import tkinter as tk
from tkinter import ttk, messagebox

from .base_tab import BaseTab
from .generation import LocalLoggedRunner, _eval_quick_number
from .generation_console import GenerationConsole
from . import storage

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
RENDERER_SCRIPT = os.path.join(_THIS_DIR, "ring_viz", "renderer.py")


def build_renderer_argv(portal_folder, upto, python_executable=None):
    """Builds the argv for launching renderer.py against a real magazyn.

    Uses `python_executable` (defaults to sys.executable -- THIS SAME Python
    interpreter PrimeAtlas itself is currently running under) rather than a
    bare "python" resolved from PATH, so the launch can never accidentally
    pick a different, possibly moderngl/glfw-less Python install if more
    than one exists on the machine.

    Deliberately launches RENDERER_SCRIPT as a PLAIN SCRIPT PATH argument
    (`[exe, RENDERER_SCRIPT, ...]`), never `-m primeatlas.ring_viz.renderer`
    -- see renderer.py's own module docstring for exactly why that matters
    (its internal sys.path fix for the prime_sieve/ sibling directory runs
    too late to help a `-m`/dotted-import invocation, which imports the
    primeatlas package first)."""
    exe = python_executable or sys.executable
    return [exe, RENDERER_SCRIPT, "--source", "magazyn",
            "--portal-folder", portal_folder, "--upto", str(upto)]


class RingsTab(BaseTab):
    def __init__(self, parent, get_portal_folder, status_var, translator, totals_progress):
        super().__init__(parent, translator)
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self.totals_progress = totals_progress
        self._runner = None
        self._queue = None
        self._build_ui()

    def _build_ui(self):
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=12, pady=12)

        intro = ttk.Label(container, text=self.T("rings.intro"), wraplength=760, justify="left")
        intro.pack(anchor="w", pady=(0, 10))

        field_row = ttk.Frame(container)
        field_row.pack(fill="x", pady=(0, 6))
        ttk.Label(field_row, text=self.T("rings.field_n")).pack(side="left")
        self.n_entry = ttk.Entry(field_row, width=28)
        self.n_entry.pack(side="left", padx=(6, 10))
        self.n_hint_var = tk.StringVar(value="")
        ttk.Label(field_row, textvariable=self.n_hint_var, foreground="#888888").pack(side="left")
        self.n_entry.bind("<KeyRelease>", self._on_n_changed)

        button_row = ttk.Frame(container)
        button_row.pack(fill="x", pady=(0, 10))
        self.open_button = ttk.Button(button_row, text=self.T("rings.open_button"),
                                       command=self._on_open)
        self.open_button.pack(side="left")
        self.stop_button = ttk.Button(button_row, text=self.T("rings.stop_button"),
                                       command=self._on_stop, state="disabled")
        self.stop_button.pack(side="left", padx=(6, 0))

        self.console = GenerationConsole(container, self.T, height=14,
                                          window_title=self.T("rings.console_title"))

    def _on_n_changed(self, _event=None):
        """Live floor hint next to the N field -- purely informational (which
        10p{N} floor this N would fall in, via the SAME digit_count_floor()
        the Primes tab's own search box uses -- see PLAN.md point 4), never
        blocks typing on an invalid/incomplete value."""
        raw = self.n_entry.get().strip()
        if not raw:
            self.n_hint_var.set("")
            return
        n = _eval_quick_number(raw)
        if n is None or n < 0:
            self.n_hint_var.set(self.T("rings.hint_invalid"))
            return
        floor = storage.digit_count_floor(n) if n > 0 else 0
        self.n_hint_var.set(self.T("rings.hint_floor", floor=floor))

    def _on_open(self):
        if self._runner is not None and self._runner.is_running():
            return
        raw = self.n_entry.get().strip()
        n = _eval_quick_number(raw) if raw else None
        if n is None or n < 2:
            messagebox.showerror(self.T("rings.error_dialog_title"), self.T("rings.error_n_invalid"))
            return
        portal_folder = self._get_portal_folder()
        if not portal_folder or not os.path.isdir(portal_folder):
            messagebox.showerror(self.T("rings.error_dialog_title"), self.T("rings.error_no_portal"))
            return

        argv = build_renderer_argv(portal_folder, n)
        q = queue.Queue()
        runner = LocalLoggedRunner(argv, q)
        self._runner = runner
        self._queue = q
        self.open_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.console.show()
        self.console.append(self.T("rings.console_launching", n=f"{n:,}") + "\n")
        self.status.set(self.T("rings.status_launching"))
        runner.start()
        self._poll_queue()

    def _on_stop(self):
        """Best-effort: closes the GL window's own process. The user can also
        just close the GL window directly (Esc, or the window's own close
        control) -- either path ends up here via _poll_queue's own
        __exit__ handling, since LocalLoggedRunner's queue reports the
        process ending either way, not just when THIS button caused it."""
        if self._runner is not None:
            self._runner.stop()

    def _poll_queue(self):
        if self._queue is None:
            return
        try:
            while True:
                item = self._queue.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__exit__":
                    code = item[1]
                    self.open_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    if code == 0:
                        self.console.append(self.T("rings.console_closed_ok") + "\n")
                        self.status.set(self.T("rings.status_closed"))
                    else:
                        self.console.append(self.T("rings.console_closed_error", code=code) + "\n")
                        self.status.set(self.T("rings.status_error"))
                    self._runner = None
                    self._queue = None
                    return
                self.console.append(item)
        except queue.Empty:
            pass
        self.after(150, self._poll_queue)
