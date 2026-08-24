"""
primesieve_calc_tab.py -- standalone libprimesieve calculator sub-tab (Liczby pierwsze
-> primesieve), extracted from prime_atlas_v1.py during the refactor branch's Faza 4
(2026-08-24) -- the phase that shrinks the app shell further, after every OTHER tab was
already split out during Faza 3. Count primes in a range, nth prime, next/prev prime --
entirely independent of anything already in storage (no floor, no PORTAL_FOLDER,
nothing written to disk); the only I/O is a single blocking wsl.exe round trip per
click, via primesieve_query.py (prime_sieve/ folder) -- see build_primesieve_query_argv/
run_primesieve_query_wsl's own docstrings below for that CLI's exact contract.

build_primesieve_query_argv/run_primesieve_query_wsl used to be module-level functions
in prime_atlas_v1.py itself; they move here in full since this calculator sub-tab is
their only caller. run_primesieve_query_wsl() takes an explicit `translator` parameter
instead of reading a bare module global T (same reasoning as generation.py's
build_wsl_logged_command taking an explicit `portal_folder` param -- see that module's
own docstring) so this stays a self-contained, circularity-free leaf module:
prime_atlas_v1.py imports FROM here, never the other way around.

Constructor-injected (same convention as every other extracted tab -- see e.g.
primeatlas/generation_tab.py's own docstring): status_var and totals_progress are the
app's SHARED status bar/progress bar (also used by the primality tab, the search
worker, and the totals-cache scan -- one bar for the whole app, not one per tab), and
translator is the app's Translator instance (bare T(...) calls become self.T(...)
here).

Operation-dependent input fields use the grid()/grid_remove() swap technique the
Quick-gen panel's mode switch established (NOT tkraise -- that approach had a
frame-overlap bug fixed earlier in this project's history), so only one field layout is
ever visible/interactive at a time.
"""
import json
import os
import shlex
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

from .background import PersistentWorker
from .base_tab import BaseTab
from .generation import PRIMESIEVE_QUERY_SCRIPT, windows_path_to_wsl, _eval_quick_number


def build_primesieve_query_argv(op, *args, script_path=None):
    """Returns the LINUX-side argv for primesieve_query.py -- the one-shot calculator CLI
    behind this sub-tab. `op` is one of "count"/"nth"/"next"/"prev" and `args` are that
    operation's positional arguments, all passed through as plain strings (see that
    script's own module header for each operation's exact argument count) -- this
    function does no validation of its own, the query script itself rejects a malformed
    call and reports it as {"ok": false, "error": ...} rather than crashing (see
    run_primesieve_query_wsl())."""
    script = script_path if script_path is not None else PRIMESIEVE_QUERY_SCRIPT
    script_wsl = windows_path_to_wsl(script)
    return ["python3", "-u", script_wsl, op] + [str(a) for a in args]


def run_primesieve_query_wsl(argv, translator, timeout=120):
    """Runs a primesieve_query.py invocation (see build_primesieve_query_argv()) as a
    BLOCKING wsl.exe subprocess call -- deliberately NOT the WslLoggedRunner/file-tailing
    machinery every WSL launch in the Generation tab uses (see that class's own docstring
    for why long-running jobs need it): a single count/nth/next/prev query answers in well
    under a second for any reasonable input and doesn't need a live progress console, so a
    simpler synchronous-capture-output shape fits better here. Callers (this tab's own
    worker thread, see PrimesieveCalcTab._primesieve_calc_job) are still responsible for
    not calling this on the GUI thread directly, since even a "well under a second" WSL
    round-trip is enough to freeze Tk's event loop noticeably.

    `timeout` bounds the whole wsl.exe call, not just the query itself -- count_primes and
    nth_prime are genuine sieve operations (see prime_sieve_primesieve.py's own docstrings
    on those two), so an extreme range/n CAN legitimately take a while; 120s is generous
    for anything a person would plausibly type into this calculator by hand, not a hard
    guarantee.

    `translator` is the app's Translator instance (T(...) in the original module-level
    version -- see this module's own docstring for why it's an explicit parameter here
    instead of a bare global).

    Returns (True, result) on success (result is the int primesieve_query.py reported), or
    (False, error_message) on ANY failure -- a non-zero/JSON-shaped {"ok": false, ...}
    response from the script itself, a WSL/process-launch failure, a timeout, or
    unparseable stdout (e.g. WSL not installed at all, so 'wsl.exe' itself never ran) --
    every failure path funnels through this same two-tuple shape so the GUI side has
    exactly one place that decides how to display an error, not one per failure kind."""
    inner = " ".join(shlex.quote(str(t)) for t in argv)
    cmd = ["wsl.exe", "-e", "bash", "-c", inner]
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired:
        return False, translator("primesieve_calc.error_timeout", timeout=timeout)
    except OSError as e:
        return False, translator("primesieve_calc.error_wsl_launch", error=e)
    stdout = (result.stdout or "").strip()
    last_line = stdout.splitlines()[-1] if stdout else ""
    try:
        payload = json.loads(last_line)
    except (ValueError, IndexError):
        detail = stdout or (result.stderr or "").strip() or translator("primesieve_calc.error_no_output")
        return False, translator("primesieve_calc.error_bad_output", detail=detail[:500])
    if payload.get("ok"):
        return True, payload.get("result")
    return False, payload.get("error", translator("primesieve_calc.error_unknown"))


class PrimesieveCalcTab(BaseTab):
    def __init__(self, parent, status_var, translator, totals_progress):
        super().__init__(parent, translator)
        self.status = status_var
        self.totals_progress = totals_progress
        self._primesieve_calc_busy = False
        self._primesieve_calc_worker = PersistentWorker(
            self, self._primesieve_calc_job, on_result=self._on_primesieve_calc_result)
        self._build_ui()

    def _build_ui(self):
        container = ttk.Frame(self)
        container.pack(fill="x", padx=12, pady=12)

        op_row = ttk.Frame(container)
        op_row.pack(fill="x", pady=(0, 10))
        ttk.Label(op_row, text=self.T("primesieve_calc.field_operation")).pack(side="left")
        # (internal op code, translated display label) pairs -- the combobox itself only
        # ever shows/stores the translated label (ttk.Combobox has no separate
        # value/label concept like a listbox with associated data), so
        # _on_primesieve_calc_operation_changed() maps back to the code via this same
        # list's index (combobox.current()) rather than reverse-parsing display text.
        self._primesieve_calc_ops = [
            ("count", self.T("primesieve_calc.op_count")),
            ("nth", self.T("primesieve_calc.op_nth")),
            ("next", self.T("primesieve_calc.op_next")),
            ("prev", self.T("primesieve_calc.op_prev")),
        ]
        self.primesieve_calc_op_combo = ttk.Combobox(
            op_row, state="readonly", width=32,
            values=[label for _code, label in self._primesieve_calc_ops])
        self.primesieve_calc_op_combo.current(0)
        self.primesieve_calc_op_combo.pack(side="left", padx=(6, 0))
        self.primesieve_calc_op_combo.bind(
            "<<ComboboxSelected>>", self._on_primesieve_calc_operation_changed)

        fields_area = ttk.Frame(container)
        fields_area.pack(fill="x", pady=(0, 10))

        self._primesieve_calc_count_frame = ttk.Frame(fields_area)
        ttk.Label(self._primesieve_calc_count_frame,
                  text=self.T("primesieve_calc.field_lo")).grid(row=0, column=0, sticky="e")
        self.primesieve_calc_lo_entry = ttk.Entry(self._primesieve_calc_count_frame, width=22)
        self.primesieve_calc_lo_entry.grid(row=0, column=1, padx=(6, 16))
        ttk.Label(self._primesieve_calc_count_frame,
                  text=self.T("primesieve_calc.field_hi")).grid(row=0, column=2, sticky="e")
        self.primesieve_calc_hi_entry = ttk.Entry(self._primesieve_calc_count_frame, width=22)
        self.primesieve_calc_hi_entry.grid(row=0, column=3, padx=(6, 0))

        self._primesieve_calc_nth_frame = ttk.Frame(fields_area)
        ttk.Label(self._primesieve_calc_nth_frame,
                  text=self.T("primesieve_calc.field_n")).grid(row=0, column=0, sticky="e")
        self.primesieve_calc_n_entry = ttk.Entry(self._primesieve_calc_nth_frame, width=22)
        self.primesieve_calc_n_entry.grid(row=0, column=1, padx=(6, 16))
        ttk.Label(self._primesieve_calc_nth_frame,
                  text=self.T("primesieve_calc.field_start")).grid(row=0, column=2, sticky="e")
        self.primesieve_calc_start_entry = ttk.Entry(self._primesieve_calc_nth_frame, width=22)
        self.primesieve_calc_start_entry.grid(row=0, column=3, padx=(6, 0))

        self._primesieve_calc_x_frame = ttk.Frame(fields_area)
        ttk.Label(self._primesieve_calc_x_frame,
                  text=self.T("primesieve_calc.field_x")).grid(row=0, column=0, sticky="e")
        self.primesieve_calc_x_entry = ttk.Entry(self._primesieve_calc_x_frame, width=22)
        self.primesieve_calc_x_entry.grid(row=0, column=1, padx=(6, 0))

        # All three placed in the SAME grid cell -- grid_remove() on the two not
        # currently active, grid() on the one that is (see
        # _on_primesieve_calc_operation_changed()). count starts visible, matching the
        # combobox's own default selection (index 0) above.
        self._primesieve_calc_count_frame.grid(row=0, column=0, sticky="w")
        self._primesieve_calc_nth_frame.grid(row=0, column=0, sticky="w")
        self._primesieve_calc_x_frame.grid(row=0, column=0, sticky="w")
        self._primesieve_calc_nth_frame.grid_remove()
        self._primesieve_calc_x_frame.grid_remove()

        button_row = ttk.Frame(container)
        button_row.pack(fill="x", pady=(0, 10))
        self.primesieve_calc_button = ttk.Button(
            button_row, text=self.T("primesieve_calc.compute_button"),
            command=self._on_primesieve_calc_compute)
        self.primesieve_calc_button.pack(side="left")

        result_row = ttk.Frame(container)
        result_row.pack(fill="x")
        self.primesieve_calc_result_var = tk.StringVar(value="")
        ttk.Label(result_row, textvariable=self.primesieve_calc_result_var,
                  font=("Consolas", 11, "bold"), wraplength=700, justify="left").pack(
            side="left", anchor="w")
        self.primesieve_calc_copy_button = ttk.Button(
            result_row, text=self.T("primesieve_calc.copy_button"),
            command=self._on_primesieve_calc_copy_result, state="disabled")
        self.primesieve_calc_copy_button.pack(side="left", padx=(10, 0))
        self._primesieve_calc_last_result = None  # raw int, for the Copy button -- None
                                                     # whenever the result label isn't
                                                     # currently showing a successful
                                                     # numeric result

    def _on_primesieve_calc_operation_changed(self, _event=None):
        code = self._primesieve_calc_ops[self.primesieve_calc_op_combo.current()][0]
        self._primesieve_calc_count_frame.grid_remove()
        self._primesieve_calc_nth_frame.grid_remove()
        self._primesieve_calc_x_frame.grid_remove()
        if code == "count":
            self._primesieve_calc_count_frame.grid()
        elif code == "nth":
            self._primesieve_calc_nth_frame.grid()
        else:  # next / prev share the same single-field layout
            self._primesieve_calc_x_frame.grid()

    def _on_primesieve_calc_compute(self):
        """Validates the active operation's fields CLIENT-SIDE first (same rules
        primesieve_query.py itself enforces -- n>0, x>2 for prev, hi>lo for count -- see
        that script's own docstring) so an obviously-bad input gets an immediate
        messagebox instead of paying for a WSL round trip just to have it rejected there
        anyway. A value primesieve_query.py could STILL reject for some other reason
        (e.g. asking libprimesieve for something past its own uint64 ceiling) is left to
        come back as a normal error result -- this is a fast local sanity check, not a
        full re-implementation of the backend's own validation."""
        if self._primesieve_calc_busy:
            return
        code = self._primesieve_calc_ops[self.primesieve_calc_op_combo.current()][0]
        try:
            if code == "count":
                lo = _eval_quick_number(self.primesieve_calc_lo_entry.get())
                hi = _eval_quick_number(self.primesieve_calc_hi_entry.get())
                if lo is None or hi is None:
                    raise ValueError(self.T("primesieve_calc.error_count_fields_int"))
                if hi <= lo:
                    raise ValueError(self.T("primesieve_calc.error_hi_le_lo"))
                args = (lo, hi)
            elif code == "nth":
                n = _eval_quick_number(self.primesieve_calc_n_entry.get())
                if n is None or n <= 0:
                    raise ValueError(self.T("primesieve_calc.error_n_positive"))
                start_raw = self.primesieve_calc_start_entry.get().strip()
                if start_raw:
                    start = _eval_quick_number(start_raw)
                    if start is None or start < 0:
                        raise ValueError(self.T("primesieve_calc.error_start_nonneg"))
                else:
                    start = 0
                args = (n, start)
            else:  # next / prev
                x = _eval_quick_number(self.primesieve_calc_x_entry.get())
                if x is None:
                    raise ValueError(self.T("primesieve_calc.error_field_int",
                                             field=self.T("primesieve_calc.field_x")))
                if code == "prev" and x <= 2:
                    raise ValueError(self.T("primesieve_calc.error_prev_too_small"))
                args = (x,)
        except ValueError as e:
            messagebox.showerror(self.T("primesieve_calc.error_dialog_title"), str(e))
            return

        self._primesieve_calc_busy = True
        self.primesieve_calc_button.configure(state="disabled")
        self.primesieve_calc_copy_button.configure(state="disabled")
        self._primesieve_calc_last_result = None
        self._start_busy_progress()
        self.status.set(self.T("primesieve_calc.status_computing"))
        self._primesieve_calc_worker.submit({"code": code, "args": args})

    def _primesieve_calc_job(self, job, report_progress):
        """Runs on PersistentWorker's own daemon thread; _primesieve_calc_busy blocking
        new requests from the GUI side means only one query is ever in flight. An
        exception raised here (e.g. run_primesieve_query_wsl() itself failing
        unexpectedly) is caught by PersistentWorker's own last-resort net."""
        code, args = job["code"], job["args"]
        argv = build_primesieve_query_argv(code, *args)
        ok, payload = run_primesieve_query_wsl(argv, self.T)
        return code, args, ok, payload

    def _on_primesieve_calc_result(self, payload, error):
        """Main-thread callback for _primesieve_calc_job -- same 150ms-poll-driven
        timing as before, just delivered via PersistentWorker instead of a bespoke
        queue.Queue + self.after() pair."""
        self._primesieve_calc_busy = False
        self.primesieve_calc_button.configure(state="normal")
        self._stop_busy_progress()
        if error is not None:
            self.status.set(self.T("primesieve_calc.status_error"))
            messagebox.showerror(self.T("primesieve_calc.error_dialog_title"), str(error))
            return
        code, args, ok, result_payload = payload
        if not ok:
            self.status.set(self.T("primesieve_calc.status_error"))
            messagebox.showerror(self.T("primesieve_calc.error_dialog_title"), result_payload)
            return
        self.status.set(self.T("primesieve_calc.status_done"))
        self._primesieve_calc_last_result = result_payload
        self.primesieve_calc_copy_button.configure(state="normal")
        if code == "count":
            lo, hi = args
            text = self.T("primesieve_calc.result_count", lo=f"{lo:,}", hi=f"{hi:,}",
                           count=f"{result_payload:,}")
        elif code == "nth":
            n, start = args
            text = self.T("primesieve_calc.result_nth", n=f"{n:,}", start=f"{start:,}",
                           value=f"{result_payload:,}")
        elif code == "next":
            (x,) = args
            text = self.T("primesieve_calc.result_next", x=f"{x:,}", value=f"{result_payload:,}")
        else:
            (x,) = args
            text = self.T("primesieve_calc.result_prev", x=f"{x:,}", value=f"{result_payload:,}")
        self.primesieve_calc_result_var.set(text)

    def _on_primesieve_calc_copy_result(self):
        if self._primesieve_calc_last_result is None:
            return
        self._copy_to_clipboard(str(self._primesieve_calc_last_result))
