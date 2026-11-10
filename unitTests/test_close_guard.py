"""
test_close_guard.py -- primeatlas/generation/close_guard.py (CLOSE_GUARD_PLAN.md
sections 1 and 3): closing the main window with no job closes at once; with a job a
Yes/No dialog (default No) lists each job with its stage, No keeps everything running;
Yes stops every job through the Generation tab's save-point stop, shows a Stopping window
with the live stage until every runner has finished, saves each stopped job's console
text to .generation_logs/closed_<job>_<UTC>.log and only then closes; "Close now" hard
stops what is left and closes; a second close request while stopping is ignored. Every
dialog string exists in both locales.

The Generation tab is a duck-typed fake (runners, consoles, stop_job_for_close), so no
WSL is needed; tkinter needs a display.

Usage:
    python unitTests/test_close_guard.py
"""
import glob
import json
import os
import shutil
import sys
import tempfile
import tkinter as tk

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def T(key, **kwargs):
    return key + (json.dumps(kwargs, sort_keys=True) if kwargs else "")


class FakeRunner:
    def __init__(self, tail):
        self.tail_lines = list(tail)
        self.running = True
        self.hard_stopped = False

    def is_running(self):
        return self.running

    def is_finished(self):
        return not self.running

    def stop(self):
        self.hard_stopped = True
        self.running = False


class FakeConsole:
    def __init__(self, text):
        self.text = text

    def get_text(self):
        return self.text


class FakeGenTab:
    def __init__(self, portal):
        self.portal = portal
        self._loop_runner = None
        self._const_runner = None
        self._ktuple_runner = None
        self._verify_runner = None
        self.loop_console = FakeConsole("loop console text\n")
        self.const_console = FakeConsole("const console text\n")
        self.ktuple_console = FakeConsole("ktuple console text\n")
        self.verify_console = FakeConsole("verify console text\n")
        self.loop_run_info = {"engine": "pt1"}
        self.stopped = []

    def _get_portal_folder(self):
        return self.portal

    def stop_job_for_close(self, key):
        self.stopped.append(key)

    def job_settled(self, key):
        runner = {"generation": self._loop_runner, "constellation": self._const_runner,
                  "ktuple": self._ktuple_runner, "verify": self._verify_runner}[key]
        return runner is None or runner.is_finished()


def pump(root, rounds=5):
    for _ in range(rounds):
        root.update()


def main():
    from primeatlas.generation import close_guard

    root = tk.Tk()
    root.withdraw()
    tmp = tempfile.mkdtemp(prefix="primeatlas_close_guard_test_")
    try:
        # 1) no job: closes at once, no dialog
        tab = FakeGenTab(tmp)
        closed, asked = [], []
        result = close_guard.request_close(root, tab, T, close_app=lambda: closed.append(1),
                                           ask=lambda title, msg: asked.append(msg) or True)
        check(result == "closed" and closed == [1] and asked == [],
              f"no job -> closed without a dialog ({result})")

        # 2) job running, answer No: nothing changes
        tab = FakeGenTab(tmp)
        tab._loop_runner = FakeRunner(["[+] Progress: 42.10% (421/1000 chunks) | time: 3s"])
        tab._const_runner = FakeRunner(["[CONSTELLATIONS v2] window 12 of 400"])
        closed, asked = [], []
        result = close_guard.request_close(root, tab, T, close_app=lambda: closed.append(1),
                                           ask=lambda title, msg: asked.append(msg) or False)
        check(result == "kept" and closed == [] and tab.stopped == [],
              f"answer No -> kept, nothing stopped ({result})")
        msg = asked[0] if asked else ""
        check("close.job_generation" in msg and "close.job_constellation" in msg,
              "dialog lists both running jobs")
        check("close.stage_sieving" in msg and "42.10%" in msg, "dialog shows the sieving stage")
        check("close.question" in msg and "close.kept_note" in msg,
              "dialog asks and says what is kept")
        check("close.v5_sieve_note" not in msg, "no v5 note for a pt1 run")

        tab.loop_run_info = {"engine": "v5"}
        asked = []
        close_guard.request_close(root, tab, T, close_app=lambda: None,
                                  ask=lambda title, msg: asked.append(msg) or False)
        check(asked and "close.v5_sieve_note" in asked[0], "v5 in the sieve stage adds the v5 note")
        tab.loop_run_info = {"engine": "v6"}
        asked = []
        close_guard.request_close(root, tab, T, close_app=lambda: None,
                                  ask=lambda title, msg: asked.append(msg) or False)
        check(asked and "close.v5_sieve_note" in asked[0],
              "v6 (also writes after sieving) adds the same note")
        tab.loop_run_info = {"engine": "v5"}
        sieve_tail = tab._loop_runner.tail_lines
        tab._loop_runner.tail_lines = [
            "[*] Counting the primes of the written windows (10 headers, 4 threads)..."]
        asked = []
        close_guard.request_close(root, tab, T, close_app=lambda: None,
                                  ask=lambda title, msg: asked.append(msg) or False)
        check(asked and "close.v5_sieve_note" not in asked[0],
              "v5 past the sieve stage (counting) has no v5 note")
        tab._loop_runner.tail_lines = sieve_tail

        # default answer is No in the real dialog
        seen = {}
        real_ask = close_guard.messagebox.askyesno
        close_guard.messagebox.askyesno = lambda *a, **k: seen.update(k) or False
        try:
            close_guard.request_close(root, tab, T, close_app=lambda: None)
        finally:
            close_guard.messagebox.askyesno = real_ask
        check(seen.get("default") == "no", f"real dialog defaults to No ({seen})")

        # 3) answer Yes: save point stop, Stopping window, logs, then close
        tab = FakeGenTab(tmp)
        tab._loop_runner = FakeRunner(["[*] Counting the primes of the written windows (9 "
                                       "headers, 2 threads)..."])
        tab._ktuple_runner = FakeRunner(["[KTUPLE] batch 3"])
        closed = []
        result = close_guard.request_close(root, tab, T, close_app=lambda: closed.append(1),
                                           ask=lambda title, msg: True, poll_ms=20)
        check(result == "stopping", f"answer Yes -> stopping ({result})")
        check(sorted(tab.stopped) == ["generation", "ktuple"],
              f"every running job got the save-point stop ({tab.stopped})")
        pump(root)
        win = close_guard.active_stopping_window()
        check(win is not None, "a Stopping window is shown")
        check(win is not None and "close.stage_counting" in win.status_text(),
              "Stopping window shows the live stage")
        check(closed == [], "app still open while jobs are stopping")

        again = close_guard.request_close(root, tab, T, close_app=lambda: closed.append(2),
                                          ask=lambda title, msg: True)
        check(again == "stopping" and closed == [], "second close request while stopping ignored")

        tab._loop_runner.running = False
        tab._ktuple_runner.running = False
        for _ in range(20):
            pump(root, 2)
            root.after(25)
            if closed:
                break
        check(closed == [1], f"app closes after every runner finished ({closed})")
        logs = sorted(glob.glob(os.path.join(tmp, ".generation_logs", "closed_*.log")))
        names = [os.path.basename(p) for p in logs]
        check(any(n.startswith("closed_generation_") for n in names)
              and any(n.startswith("closed_ktuple_") for n in names),
              f"console logs saved per stopped job ({names})")
        gen_log = [p for p in logs if os.path.basename(p).startswith("closed_generation_")]
        if gen_log:
            with open(gen_log[0], encoding="utf-8") as f:
                check(f.read() == "loop console text\n", "saved log holds the console text")
        check(close_guard.active_stopping_window() is None, "Stopping window gone after close")

        # 4) Close now: hard stop of what is left, then close
        tab = FakeGenTab(tmp)
        tab._loop_runner = FakeRunner(["[+] Progress: 1.00% (1/100 chunks)"])
        closed = []
        close_guard.request_close(root, tab, T, close_app=lambda: closed.append(1),
                                  ask=lambda title, msg: True, poll_ms=20)
        pump(root)
        win = close_guard.active_stopping_window()
        if win is not None:
            win.close_now()
        pump(root)
        check(tab._loop_runner.hard_stopped and closed == [1], "Close now hard stops and closes")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        root.destroy()

    for lang in ("en", "pl"):
        with open(os.path.join(_REPO_ROOT, "primeatlas", "core", "locales",
                               f"strings_{lang}.json"), encoding="utf-8") as f:
            strings = json.load(f)
        missing = [k for k in close_guard.STRING_KEYS if k not in strings]
        check(not missing, f"strings_{lang}.json has every close-guard key (missing {missing})")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
