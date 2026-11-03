"""
logged_runners.py -- the subprocess runners behind every live console in the app:
WslLoggedRunner (a WSL command tailed through its log/exit files) and LocalLoggedRunner
(a native subprocess read through a pipe). Both put text chunks on an output queue and
finish with an ("__exit__", returncode) sentinel.

No tkinter: exercised directly against plain local commands.
"""
import collections
import os
import subprocess
import threading
import time

from .wsl_command import _popen_kwargs_no_window


class WslLoggedRunner:
    """Runs a WSL command with output redirected to files on disk (build_wsl_logged_
    command()) instead of relying on subprocess.PIPE against wsl.exe's own stdout.

    A pipe-based approach doesn't work reliably here: launching wsl.exe from a
    console-less parent process (this is a windowed tkinter app, not a console app) can
    make Windows/WSL's own console-allocation machinery open a SEPARATE, real terminal
    window that receives the script's actual output, while the pipe this app reads from
    gets nothing and never sees EOF -- so the app never learns the run finished. A
    terminal window shows the script running, but neither the user nor the app itself
    can tell from its own UI whether or when the run finished. Redirecting entirely on
    the Linux side sidesteps that: the log/exit-code
    files are ordinary files on the same Windows drive both Windows and WSL already share,
    tailed directly with plain Python file I/O on a background daemon thread -- no pipe,
    no console, no WSL console-interop quirks anywhere in the actual data path, whatever
    window WSL itself chooses to pop up (or not) along the way.

    `output_queue` receives plain text chunks, then a final ("__exit__", returncode)
    sentinel tuple once the run is done (returncode
    is None if the run never started, or if the wrapper process ended without ever
    writing the exit-code file -- see the grace-period handling in _tail_loop()) -- so
    the GUI polling code (_drain_output_queue) needed no changes to support this class.

    stop() remains best-effort for the reason above (WSL's process-lifecycle model
    doesn't guarantee terminate()ing the Windows-side wrapper kills the Linux process
    underneath) -- this additionally fires a one-shot `wsl.exe -e pkill -f kill_pattern`
    as a second, independent attempt at reaching the actual Linux process tree. Matching
    by substring against the running command line is safe here specifically because the
    GUI only ever allows one instance of a given script to run at a time (see the
    is_running() checks in _on_run_loop/_on_run_constellation) -- kill_pattern is that
    script's own filename, which should not collide with anything else.

    No tkinter dependency -- exercised directly (substituting a plain `bash -c` command
    for the `wsl.exe -e bash -c` form, since this class only cares about the log/exit
    FILES, not what actually wrote them) without a display or a real WSL install."""

    POLL_INTERVAL = 0.2
    EXIT_MARKER_GRACE_SECONDS = 2.0
    TAIL_LINES = 50

    def __init__(self, cmd, log_path, exit_path, output_queue, kill_pattern=None):
        self.cmd = cmd
        self.log_path = log_path
        self.exit_path = exit_path
        self.output_queue = output_queue
        self.kill_pattern = kill_pattern
        self.proc = None
        self._thread = None
        # The last TAIL_LINES output lines, for the close guard's stage label
        # (run_guard.job_stage); written by the tail thread, read by the GUI thread.
        self._tail = collections.deque(maxlen=self.TAIL_LINES)
        self._tail_partial = ""
        self._tail_lock = threading.Lock()

    @property
    def tail_lines(self):
        """Copy of the last output lines, the unfinished last line included."""
        with self._tail_lock:
            return list(self._tail) + ([self._tail_partial] if self._tail_partial else [])

    def _remember_tail(self, chunk):
        with self._tail_lock:
            *complete, self._tail_partial = (self._tail_partial + chunk).split("\n")
            self._tail.extend(complete)

    def start(self):
        self.output_queue.put(f"$ {' '.join(self.cmd)}\n")
        try:
            self.proc = subprocess.Popen(self.cmd, **_popen_kwargs_no_window())
        except OSError as e:
            self.output_queue.put(f"[!] Could not start the process: {e}\n")
            self.output_queue.put(("__exit__", None))
            return
        self._thread = threading.Thread(target=self._tail_loop, daemon=True)
        self._thread.start()

    def _tail_loop(self):
        offset = 0
        grace_deadline = None
        try:
            while True:
                offset = self._drain_new_log_bytes(offset)
                if os.path.exists(self.exit_path):
                    time.sleep(0.1)  # let a just-flushed final write land before the
                                      # last drain, so the tail-end of the script's
                                      # output isn't cut off by a race with echo $? >
                    offset = self._drain_new_log_bytes(offset)
                    returncode = self._read_exit_code()
                    self._cleanup_files()
                    self.output_queue.put(("__exit__", returncode))
                    return
                if self.proc.poll() is not None:
                    # Wrapper process ended but never wrote the exit marker (e.g. wsl.exe
                    # itself failed before reaching the redirect) -- give the filesystem
                    # a brief grace period before giving up, rather than reporting a
                    # false failure on every ordinary run (write latency on the underlying
                    # mount is real).
                    if grace_deadline is None:
                        grace_deadline = time.time() + self.EXIT_MARKER_GRACE_SECONDS
                    elif time.time() > grace_deadline:
                        offset = self._drain_new_log_bytes(offset)
                        self.output_queue.put(
                            "[!] The wsl.exe process exited without writing an exit code.\n")
                        self._cleanup_files()
                        self.output_queue.put(("__exit__", None))
                        return
                time.sleep(self.POLL_INTERVAL)
        except Exception as e:  # noqa: BLE001 -- must never kill this thread silently
            self.output_queue.put(f"[!] Could not read the log: {e}\n")
            self.output_queue.put(("__exit__", None))

    def _drain_new_log_bytes(self, offset):
        if not os.path.exists(self.log_path):
            return offset
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(offset)
                chunk = f.read()
                new_offset = f.tell()
        except OSError:
            return offset
        if chunk:
            self._remember_tail(chunk)
            self.output_queue.put(chunk)
        return new_offset

    def _read_exit_code(self):
        try:
            with open(self.exit_path, encoding="utf-8") as f:
                raw = f.read().strip()
            return int(raw)
        except (OSError, ValueError):
            return None

    def _cleanup_files(self):
        """Best-effort delete of the log/exit files once fully drained and reported --
        keeps .generation_logs/ from growing unbounded across months of runs. The GUI
        already shows the full output live in its own pane, so nothing is lost."""
        for path in (self.log_path, self.exit_path):
            try:
                os.remove(path)
            except OSError:
                pass

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def is_finished(self):
        """True once the tail thread has queued the exit sentinel (or never started), so
        the GUI's next queue drain runs the job's finish callback."""
        return self._thread is None or not self._thread.is_alive()

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass
        if self.kill_pattern:
            try:
                subprocess.Popen(["wsl.exe", "-e", "pkill", "-f", self.kill_pattern],
                                  **_popen_kwargs_no_window())
            except OSError:
                pass


class LocalLoggedRunner:
    """Runs an ordinary LOCAL subprocess (no WSL involved) with its stdout/stderr piped
    directly back to this process, unlike WslLoggedRunner's file-tailing approach. That
    file-tailing dance exists ONLY to work around wsl.exe's own console-allocation
    quirks when launched from a windowed (console-less) parent -- see WslLoggedRunner's
    own docstring. A plain native subprocess (e.g. `sys.executable -m pip install`) has
    none of that: it's a normal child of this same Windows process tree, so a regular
    subprocess.PIPE + line-by-line read on a background thread is both simpler and
    perfectly reliable here.

    Same output contract as WslLoggedRunner (plain text chunks on `output_queue`, then a
    final ("__exit__", returncode) sentinel) so callers that already know how to drain
    that queue (see settings_tab.py's _poll_restore_queue) don't need a second shape to
    handle -- this class is used for exactly one thing so far (the sympy installer, see
    settings_tab.py's _on_install_sympy), but kept generically named/shaped in case a
    future feature needs another local (non-WSL) subprocess with live output.

    No tkinter dependency -- exercised directly against a trivial local command (e.g.
    [sys.executable, "-c", "print('hi')"]) without any WSL install required."""

    def __init__(self, cmd, output_queue, pipe_stdin=False):
        self.cmd = cmd
        self.output_queue = output_queue
        self.proc = None
        self._thread = None
        # Opt-in only -- every existing caller
        # (e.g. settings_tab.py's sympy installer) keeps stdin inherited/
        # default exactly as before. RingsTab is the first caller that
        # needs a way to send commands INTO the running subprocess (see
        # send_line() below) -- visualization/shared/renderer.py's own PAUSE/RESUME
        # protocol reads them off stdin when launched with
        # --pipe-stdin-commands (see build_renderer_argv/rings_tab.py).
        self._pipe_stdin = pipe_stdin

    def start(self):
        self.output_queue.put(f"$ {' '.join(self.cmd)}\n")
        # _popen_kwargs_no_window() already sets stdout=DEVNULL/stderr=DEVNULL (the
        # right default for WslLoggedRunner/env_setup.py's fire-and-forget callers,
        # which don't want piped output at all) -- this class DOES need piped output,
        # so those two keys must be overridden in the dict rather than also passed as
        # separate keyword args to Popen(), which raises "got multiple values for
        # keyword argument 'stdout'" if done that way instead.
        kwargs = _popen_kwargs_no_window()
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.STDOUT
        if self._pipe_stdin:
            kwargs["stdin"] = subprocess.PIPE
        try:
            self.proc = subprocess.Popen(self.cmd, text=True, bufsize=1, **kwargs)
        except OSError as e:
            self.output_queue.put(f"[!] Could not start process: {e}\n")
            self.output_queue.put(("__exit__", None))
            return
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def send_line(self, text):
        """Write one line to the subprocess's
        stdin (only meaningful when started with pipe_stdin=True -- a no-op,
        not an error, otherwise, since a caller checking is_running() first
        has no easy way to know in advance whether stdin was piped). Used by
        RingsTab to send "RESUME" while the renderer is idling in its own
        paused/hidden state -- see that class's own PAUSE/RESUME doc-comment.
        Swallows a broken pipe (process already gone) same as stop() does,
        since the caller's next _poll_queue tick will see the __exit__
        sentinel regardless and react to that instead."""
        if self.proc is None or self.proc.stdin is None:
            return
        try:
            self.proc.stdin.write(text.rstrip("\n") + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def _read_loop(self):
        try:
            for line in self.proc.stdout:
                self.output_queue.put(line)
            self.proc.stdout.close()
            returncode = self.proc.wait()
            self.output_queue.put(("__exit__", returncode))
        except Exception as e:  # noqa: BLE001 -- must never kill this thread silently
            self.output_queue.put(f"[!] Error reading process output: {e}\n")
            self.output_queue.put(("__exit__", None))

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass
