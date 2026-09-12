"""
stdin_commands.py -- background stdin-command-reader thread for
primeatlas/ring_viz/renderer.py's --pipe-stdin-commands live pause/resume
(Faza 13, see PLAN.md). [ADDED Faza 1 of the renderer.py split, see that
file's own module docstring for the overall refactor plan.]
"""

import queue
import sys
import threading


def start_stdin_command_reader():
    """[ADDED Faza 13, see PLAN.md] Background daemon thread that blocks on
    `sys.stdin.readline()` in a loop, pushing each stripped non-empty line
    into a thread-safe queue.Queue the main GLFW loop polls NON-blockingly
    (queue.get_nowait()) once per frame -- same producer/thread-consumer-
    queue shape as generation.py's own LocalLoggedRunner._read_loop, just
    the opposite direction (that one reads the subprocess's stdOUT into a
    queue for Tkinter to drain; this one reads OUR stdIN, fed by
    LocalLoggedRunner.send_line() on the Tkinter side, into a queue this
    same process's own main loop drains).

    When stdin hits EOF (the parent process died, or closed the pipe --
    e.g. Tkinter's own process exiting without an explicit Reset first),
    the special sentinel "__STDIN_CLOSED__" is pushed exactly once so the
    main loop can tell "no command right now" (empty queue) apart from
    "there will never be another command" (must not idle forever).

    Only ever started when --pipe-stdin-commands is passed (see that
    flag's own doc-comment) -- reading stdin at all when it's just an
    inherited console (the flag OFF) would block forever on a real
    terminal with nothing to read, hanging what should be a normal
    Ctrl-C-able CLI run."""
    q = queue.Queue()

    def _loop():
        try:
            for line in sys.stdin:
                cmd = line.strip()
                if cmd:
                    q.put(cmd)
        except Exception:  # noqa: BLE001 -- must never crash this thread silently
            pass
        q.put("__STDIN_CLOSED__")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return q
