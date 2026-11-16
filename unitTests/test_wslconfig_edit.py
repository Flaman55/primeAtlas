"""
test_wslconfig_edit.py -- primeatlas/about/wslconfig_edit.py, how Atlas changes the WSL RAM
limit (memory= of the [wsl2] section of %UserProfile%\\.wslconfig).

A. proposed_limit_gib(windows_ram_bytes): Windows RAM minus max(RESERVE_MIN_GIB, RESERVE_SHARE
   of it), rounded to whole GiB, at least MIN_LIMIT_GIB; None for unknown RAM.
   max_limit_gib(windows_ram_bytes): the whole GiB of Windows RAM (at least MIN_LIMIT_GIB);
   None for unknown RAM.
B. set_wsl2_memory(text, gib): only memory= of [wsl2] changes, everything else stays byte for
   byte (other keys, other sections, comments, an inline comment after the value, blank lines,
   CRLF or LF line ends). Section and key names in any case. Every memory= line of [wsl2] gets
   the value (a repeated key cannot keep the old one). [wsl2] without memory= gets the line
   after its last key; no [wsl2] gets the section at the end; an empty file becomes the
   section alone. A memory= of another section is never touched. The result reads back
   (system_info.parse_wslconfig) as the new limit.
C. plan_change(path, gib) / apply_change(change): the plan holds the file's text before and
   after and diff_lines() names exactly the removed and added lines. Applying writes the new
   text, keeps a UTF-8 BOM the file had, leaves a backup copy of the old file next to it
   (.wslconfig.bak_<date>_<time>) and no temp file; a missing file is created with no backup;
   a plan with nothing to change writes nothing. A file edited after the plan is not
   overwritten (FileChangedError, file and folder untouched).
D. shutdown_wsl(run): runs `wsl.exe --shutdown` once; True only for exit code 0; a missing
   wsl.exe or a timeout is False.
E. WslLimitRow (primeatlas/about/wsl_limit_row.py) with recorded dialogs and shutdown:
   show(info) puts the file's memory= in GB in the field, else the proposal, and names the
   proposal; unknown Windows RAM leaves both empty. Save refuses a value outside 1..Windows
   RAM, a non-number and an empty field before reading or asking anything. A new value asks
   first (file path, changed lines, backup or new-file note); No leaves the file. Yes writes
   it, then asks to restart WSL: No -> a next-start note; Yes -> one shutdown, then the
   hardware is read again; a failed shutdown -> an error. The value already in the file skips
   the write question. A running Generation job: the file is written, WSL is not restarted
   and a note names the jobs. A file edited while the question was open is kept and an error
   says so; a file that cannot be written gives an error. A missing file is created with no
   backup.

Usage:
    python unitTests/test_wslconfig_edit.py
"""
import os
import subprocess
import sys
import tempfile
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.about import system_info  # noqa: E402
from primeatlas.about import wslconfig_edit as we  # noqa: E402

failures = []
GIB = 1024 ** 3


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_proposal():
    print("\n--- A. proposed and largest limit ---")
    check(we.RESERVE_SHARE == 0.25 and we.RESERVE_MIN_GIB == 3 and we.WSL_DEFAULT_SHARE == 0.5,
          "reserve 25 %, at least 3 GiB; WSL's own default is half the RAM")
    for ram, want in ((64 * GIB, 32), (16 * GIB, 8), (int(15.9 * GIB), 8), (int(7.9 * GIB), 4),
                      (3 * GIB, 2), (GIB, 1), (GIB // 2, 1)):
        got = we.min_limit_gib(ram)
        check(got == want, f"smallest limit (WSL default) for {ram / GIB:.2f} GiB -> {want} (got {got})")
    for ram, want in ((64 * GIB, 48), (16 * GIB, 12), (12 * GIB, 9), (8 * GIB, 5),
                      (int(63.9 * GIB), 48), (int(7.9 * GIB), 5), (6 * GIB, 3), (4 * GIB, 2),
                      (2 * GIB, 1), (GIB // 2, 1)):
        got = we.proposed_limit_gib(ram)
        check(got == want, f"proposal for {ram / GIB:.2f} GiB -> {want} GiB (got {got})")
    for ram in (16 * GIB, 4 * GIB, 3 * GIB, int(7.9 * GIB), GIB // 2):
        low, mid, high = we.min_limit_gib(ram), we.proposed_limit_gib(ram), we.max_limit_gib(ram)
        check(low <= mid <= high, f"{ram / GIB:.2f} GiB: smallest <= proposal <= largest "
                                  f"({low}, {mid}, {high})")
    for ram in (None, 0):
        check(we.proposed_limit_gib(ram) is None and we.max_limit_gib(ram) is None
              and we.min_limit_gib(ram) is None,
              f"RAM {ram!r} -> no proposal, no smallest or largest limit")
    for ram, want in ((64 * GIB, 64), (int(63.9 * GIB), 63), (GIB // 2, 1)):
        check(we.max_limit_gib(ram) == want, f"largest limit for {ram / GIB:.2f} GiB -> {want}")
    for gib, risky in ((8, False), (12, False), (13, True), (16, True)):
        check(we.is_risky(gib, 16 * GIB) is risky, f"16 GiB RAM, limit {gib} -> risky {risky}")
    check(we.is_risky(64, None) is False, "unknown RAM -> nothing to compare, not risky")


def _limit(text):
    return system_info.parse_wslconfig(text).memory_bytes


def _test_set_memory():
    print("\n--- B. set_wsl2_memory ---")
    check(we.set_wsl2_memory("[wsl2]\nmemory=48GB\n", 40) == "[wsl2]\nmemory=40GB\n",
          "the value is replaced")
    crlf = "[wsl2]\r\nmemory=48GB\r\nprocessors=8\r\n"
    check(we.set_wsl2_memory(crlf, 40) == "[wsl2]\r\nmemory=40GB\r\nprocessors=8\r\n",
          "CRLF line ends kept")
    full = ("# my settings\n"
            "[experimental]\n"
            "memory=99GB\n"
            "autoMemoryReclaim=gradual\n"
            "\n"
            "[WSL2]\n"
            "  Memory = 48GB   # half of it\n"
            "swap=0\n"
            "; old: memory=30GB\n"
            "\n"
            "[boot]\n"
            "systemd=true\n")
    want = full.replace("  Memory = 48GB   # half of it", "  Memory = 40GB   # half of it")
    got = we.set_wsl2_memory(full, 40)
    check(got == want, f"only memory= of [wsl2] changes, spaces, case and comment kept ({got!r})")
    check(_limit(got) == 40 * GIB, "it reads back as 40 GiB")
    twice = "[wsl2]\nmemory=8GB\nswap=0\nmemory=16GB\n"
    got = we.set_wsl2_memory(twice, 20)
    check(got == "[wsl2]\nmemory=20GB\nswap=0\nmemory=20GB\n" and _limit(got) == 20 * GIB,
          f"every memory= of [wsl2] gets the value ({got!r})")
    no_key = "[wsl2]\nprocessors=8\nswap=0\n\n[boot]\nsystemd=true\n"
    got = we.set_wsl2_memory(no_key, 12)
    check(got == "[wsl2]\nprocessors=8\nswap=0\nmemory=12GB\n\n[boot]\nsystemd=true\n",
          f"[wsl2] without memory= gets it after its last key ({got!r})")
    empty_section = "[wsl2]\n[boot]\nsystemd=true\n"
    got = we.set_wsl2_memory(empty_section, 12)
    check(got == "[wsl2]\nmemory=12GB\n[boot]\nsystemd=true\n",
          f"an empty [wsl2] gets the line right under it ({got!r})")
    other = "[boot]\r\nsystemd=true\r\n"
    got = we.set_wsl2_memory(other, 12)
    check(got == "[boot]\r\nsystemd=true\r\n\r\n[wsl2]\r\nmemory=12GB\r\n",
          f"no [wsl2] -> the section at the end, same line ends ({got!r})")
    no_end = "[boot]\nsystemd=true"
    got = we.set_wsl2_memory(no_end, 12)
    check(got == "[boot]\nsystemd=true\n\n[wsl2]\nmemory=12GB\n" and _limit(got) == 12 * GIB,
          f"a last line with no line end still ends before the new section ({got!r})")
    check(we.set_wsl2_memory("", 7) == "[wsl2]\nmemory=7GB\n", "empty file -> the section alone")
    last = "[wsl2]\nswap=0"
    check(we.set_wsl2_memory(last, 7) == "[wsl2]\nswap=0\nmemory=7GB\n",
          "a [wsl2] ending the file with no line end gets the line after its last key")
    check(we.set_wsl2_memory("[wsl2]\nmemory=40GB\n", 40) == "[wsl2]\nmemory=40GB\n",
          "the same value -> the same text")
    commented = "[wsl2]\n# memory=10GB\nmemoryX=3\n"
    got = we.set_wsl2_memory(commented, 9)
    check(got == "[wsl2]\n# memory=10GB\nmemoryX=3\nmemory=9GB\n",
          f"a commented memory= or a longer key is not the key ({got!r})")


def _files(folder):
    return sorted(os.listdir(folder))


def _test_plan_apply():
    print("\n--- C. plan_change / apply_change ---")
    when = datetime(2026, 11, 16, 9, 5, 7)
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, ".wslconfig")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("[wsl2]\r\nmemory=48GB\r\nswap=0\r\n")
        change = we.plan_change(path, 40)
        check(change.existed and change.changed, "an existing file with another value -> a change")
        check(change.diff_lines() == ["- memory=48GB", "+ memory=40GB"],
              f"the diff names the old and the new line ({change.diff_lines()})")
        backup = we.apply_change(change, now=when)
        check(backup == path + ".bak_2026-11-16_090507", f"backup named by date and time ({backup})")
        with open(path, "rb") as f:
            check(f.read() == b"[wsl2]\r\nmemory=40GB\r\nswap=0\r\n", "the new text is written")
        with open(backup, "rb") as f:
            check(f.read() == b"[wsl2]\r\nmemory=48GB\r\nswap=0\r\n", "the backup holds the old text")
        check(_files(folder) == [".wslconfig", ".wslconfig.bak_2026-11-16_090507"],
              f"no temp file left ({_files(folder)})")

        same = we.plan_change(path, 40)
        check(not same.changed and same.diff_lines() == [], "the same value -> nothing to change")
        check(we.apply_change(same, now=when) is None and len(_files(folder)) == 2,
              "applying no change writes nothing and makes no backup")

        stale = we.plan_change(path, 30)
        with open(path, "w", encoding="utf-8") as f:
            f.write("[wsl2]\nmemory=20GB\n")
        try:
            we.apply_change(stale, now=datetime(2026, 11, 16, 10, 0, 0))
            raised = False
        except we.FileChangedError:
            raised = True
        with open(path, encoding="utf-8") as f:
            kept = f.read()
        check(raised and kept == "[wsl2]\nmemory=20GB\n" and len(_files(folder)) == 2,
              "a file edited after the plan is not overwritten, no backup made")

    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, ".wslconfig")
        with open(path, "wb") as f:
            f.write(b"\xef\xbb\xbf[wsl2]\nmemory=8GB\n")
        we.apply_change(we.plan_change(path, 6), now=when)
        with open(path, "rb") as f:
            check(f.read() == b"\xef\xbb\xbf[wsl2]\nmemory=6GB\n", "a UTF-8 BOM is kept")

    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, ".wslconfig")
        change = we.plan_change(path, 12)
        check(not change.existed and change.changed
              and change.diff_lines() == ["+ [wsl2]", "+ memory=12GB"],
              f"a missing file -> created, the diff adds the section ({change.diff_lines()})")
        check(we.apply_change(change, now=when) is None, "a new file has no backup")
        with open(path, encoding="utf-8") as f:
            check(f.read() == "[wsl2]\nmemory=12GB\n", "the new file holds the section")
        check(_files(folder) == [".wslconfig"], f"only the file ({_files(folder)})")


def _test_shutdown():
    print("\n--- D. shutdown_wsl ---")
    calls = []

    def fake(code=None, error=None):
        def run(argv, **kwargs):
            calls.append(argv)
            if error is not None:
                raise error
            return subprocess.CompletedProcess(argv, code)
        return run
    check(we.shutdown_wsl(run=fake(0)) is True, "exit 0 -> True")
    check(calls == [["wsl.exe", "--shutdown"]], f"one wsl.exe --shutdown call ({calls})")
    check(we.shutdown_wsl(run=fake(1)) is False, "exit 1 -> False")
    check(we.shutdown_wsl(run=fake(error=OSError("no wsl"))) is False, "no wsl.exe -> False")
    check(we.shutdown_wsl(run=fake(error=subprocess.TimeoutExpired("wsl.exe", 1))) is False,
          "timeout -> False")


def _fake_T(key, **kwargs):
    return key + "".join(f"|{k}={kwargs[k]}" for k in sorted(kwargs))


def _info(ram_gib, memory_text=None):
    windows = system_info.WindowsInfo(ram_total=None if ram_gib is None else ram_gib * GIB)
    cfg = (system_info.parse_wslconfig(f"[wsl2]\nmemory={memory_text}\n") if memory_text
           else system_info.WslConfig())
    return system_info.SystemInfo(windows, None, cfg)


class _Row:
    """A WslLimitRow on its own Tk root with recorded dialogs and shutdown."""

    def __init__(self, root, path, answers=(), jobs=(), shutdown_ok=True):
        from primeatlas.about.wsl_limit_row import WslLimitRow
        self.root = root
        self.dialogs = []
        self.answers = list(answers)
        self.shutdowns = 0
        self.saved = 0
        self.row = WslLimitRow(root, _fake_T, running_jobs=lambda: list(jobs), path=path,
                               on_saved=self._saved)
        self.row.pack()
        self.row.ask = self._ask
        self.row.warn = lambda title, text: self._ask(title, text, "warn")
        self.row.info = lambda title, text: self.dialogs.append(("info", text))
        self.row.error = lambda title, text: self.dialogs.append(("error", text))

        def shutdown():
            self.shutdowns += 1
            return shutdown_ok
        self.row.shutdown = shutdown

    def _ask(self, title, text, kind="ask"):
        self.dialogs.append((kind, text))
        if not self.answers:
            return False  # a question the scenario did not expect; its kinds() check fails
        answer = self.answers.pop(0)
        return answer() if callable(answer) else answer

    def _saved(self):
        self.saved += 1

    def save(self, value=None):
        if value is not None:
            self.row.value_var.set(value)
        self.row.field.refresh(at_once=True)
        self.row.save()
        self._settle()

    def _settle(self):
        import time
        end = time.time() + 3
        while time.time() < end:
            self.root.update()
            time.sleep(0.02)
            if not self.row.tk.call("after", "info"):
                break
        self.root.update()

    def kinds(self):
        return [kind for kind, _text in self.dialogs]


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def _test_row():
    print("\n--- E. WslLimitRow ---")
    import tkinter as tk
    import tkinter.messagebox as messagebox
    errors = []
    messagebox.showerror = lambda *a, **k: errors.append(a)
    root = tk.Tk()
    root.withdraw()
    try:
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, ".wslconfig")
            _write(path, "[wsl2]\nmemory=8GB\n")

            r = _Row(root, path)
            r.row.show(_info(16, "8GB"))
            check(r.row.value_var.get() == "8", "the field shows the file's memory= in GB")
            check(r.row.proposal_label.cget("text") == "about.wsl_limit_proposal|gib=12|minimum=3"
                  "|share=25", f"the proposal for 16 GiB ({r.row.proposal_label.cget('text')})")
            r.row.show(_info(16))
            check(r.row.value_var.get() == "12", "no memory= in the file -> the proposal")
            r.row.show(_info(None))
            check(r.row.value_var.get() == "" and r.row.proposal_label.cget("text") == "",
                  "unknown Windows RAM -> no proposal, empty field")

            r.row.show(_info(16, "8GB"))
            for bad in ("17", "7", "0", "abc"):
                errors.clear()
                r.dialogs.clear()
                r.save(bad)
                check(len(errors) == 1 and r.dialogs == [] and _read(path) == "[wsl2]\nmemory=8GB\n",
                      f"field {bad!r} is refused before anything is read or asked")
            r.dialogs.clear()
            r.save("")
            check(r.kinds() == ["error"] and _read(path) == "[wsl2]\nmemory=8GB\n",
                  "an empty field is refused")

            r = _Row(root, path, answers=[False])
            r.row.show(_info(16, "8GB"))
            r.save("10")
            check(r.kinds() == ["ask"] and _read(path) == "[wsl2]\nmemory=8GB\n" and r.saved == 0,
                  "No to the change -> the file stays, nothing more is asked")
            text = r.dialogs[0][1]
            check("- memory=8GB" in text and "+ memory=10GB" in text and path in text
                  and "about.wsl_limit_backup_note" in text,
                  f"the question names the file, the changed lines and the backup ({text!r})")

            r = _Row(root, path, answers=[True, False])
            r.row.show(_info(16, "8GB"))
            r.save("10")
            backups = [n for n in os.listdir(folder) if n.startswith(".wslconfig.bak_")]
            check(_read(path) == "[wsl2]\nmemory=10GB\n" and len(backups) == 1,
                  f"Yes -> the file holds the new limit, one backup ({backups})")
            check(r.kinds() == ["ask", "ask", "info"] and r.shutdowns == 0 and r.saved == 1,
                  f"then a restart question; No -> a next-start note, no shutdown ({r.kinds()})")
            check(r.dialogs[1][1] == "about.wsl_limit_restart_question"
                  and r.dialogs[2][1] == "about.wsl_limit_next_start", "the restart texts")

            r = _Row(root, path, answers=[True])
            r.row.show(_info(16, "10GB"))
            r.save("10")
            check(r.kinds() == ["ask"] and r.dialogs[0][1] == "about.wsl_limit_restart_question",
                  "the value already in the file -> no write question, only the restart one")
            check(r.shutdowns == 1 and r.saved == 1,
                  f"Yes -> WSL shut down once, then read again ({r.shutdowns}, {r.saved})")
            check(len([n for n in os.listdir(folder) if n.startswith(".wslconfig.bak_")]) == 1,
                  "no write -> no new backup")

            r = _Row(root, path, answers=[True], shutdown_ok=False)
            r.row.show(_info(16, "10GB"))
            r.save("10")
            check(r.kinds() == ["ask", "error"] and r.saved == 1,
                  f"a failed shutdown -> an error, still read again ({r.kinds()})")

            jobs = [("generation", object()), ("verify", object())]
            r = _Row(root, path, answers=[True], jobs=jobs)
            r.row.show(_info(16, "10GB"))
            r.save("11")
            check(_read(path) == "[wsl2]\nmemory=11GB\n", "a running job does not stop the write")
            check(r.kinds() == ["ask", "info"] and r.shutdowns == 0 and r.saved == 1,
                  f"a running job -> no restart question, no shutdown ({r.kinds()})")
            check("close.job_name_generation" in r.dialogs[1][1]
                  and "close.job_name_verify" in r.dialogs[1][1]
                  and r.dialogs[1][1].startswith("about.wsl_limit_run_active"),
                  f"the note names the running jobs ({r.dialogs[1][1]!r})")

            def edit_meanwhile():
                _write(path, "[wsl2]\nmemory=2GB\n")
                return True
            r = _Row(root, path, answers=[edit_meanwhile])
            r.row.show(_info(16, "11GB"))
            r.save("12")
            check(_read(path) == "[wsl2]\nmemory=2GB\n" and r.kinds() == ["ask", "error"]
                  and r.dialogs[1][1].startswith("about.wsl_limit_file_changed") and r.saved == 0,
                  f"a file edited during the question is kept, an error says so ({r.kinds()})")

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, ".wslconfig")
            _write(path, "[wsl2]\nmemory=8GB\n")
            for value in ("8", "12"):
                r = _Row(root, path, answers=[False])
                r.row.show(_info(16, "8GB" if value == "12" else "9GB"))
                r.save(value)
                check("warn" not in r.kinds(), f"limit {value} of 16 GiB (not above the proposal) "
                                               f"-> no warning ({r.kinds()})")
            for value in ("13", "16"):
                r = _Row(root, path, answers=[False])
                r.row.show(_info(16, "8GB"))
                r.save(value)
                check(r.kinds() == ["warn"] and _read(path) == "[wsl2]\nmemory=8GB\n"
                      and r.saved == 0 and r.shutdowns == 0,
                      f"limit {value} of 16 GiB, No to the warning -> nothing else asked or "
                      f"written ({r.kinds()})")
                left = 16 - int(value)
                check(r.dialogs[0][1] == f"about.wsl_limit_risky|gib={value}|left={left}|reserve=4",
                      f"the warning names the limit, what Windows keeps and the reserve "
                      f"({r.dialogs[0][1]!r})")
            r = _Row(root, path, answers=[True, True, False])
            r.row.show(_info(16, "8GB"))
            r.save("14")
            check(r.kinds() == ["warn", "ask", "ask", "info"]
                  and _read(path) == "[wsl2]\nmemory=14GB\n",
                  f"Yes to the warning -> the usual change question, then written ({r.kinds()})")
            r = _Row(root, path, answers=[False])
            r.row.show(_info(16, "14GB"))
            r.save("14")
            check(r.kinds() == ["warn"] and r.shutdowns == 0,
                  f"a risky limit already in the file still warns before a restart ({r.kinds()})")
            r = _Row(root, path, answers=[True, True])
            r.row.show(_info(16, "14GB"))
            r.save("14")
            check(r.kinds() == ["warn", "ask"] and r.shutdowns == 1,
                  f"Yes to it -> the restart question, WSL shut down ({r.kinds()})")

            from primeatlas.about import wsl_limit_row
            calls = []
            real_ask = messagebox.askyesno
            messagebox.askyesno = lambda *a, **k: calls.append((a, k)) or False
            try:
                answer = wsl_limit_row.WslLimitRow(root, _fake_T).warn("t", "x")
            finally:
                messagebox.askyesno = real_ask
            check(answer is False and len(calls) == 1
                  and calls[0][1].get("icon") == messagebox.WARNING
                  and calls[0][1].get("default") == messagebox.NO,
                  f"the real warning is a Yes/No with the warning icon, No by default ({calls})")

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, ".wslconfig")
            r = _Row(root, path, answers=[True, False])
            r.row.show(_info(16))
            r.save()
            check(_read(path) == "[wsl2]\nmemory=12GB\n" and "about.wsl_limit_new_file_note"
                  in r.dialogs[0][1], "no file -> created with the proposal, the question says so")
            check(os.listdir(folder) == [".wslconfig"], "a new file leaves no backup")

            blocked = os.path.join(folder, "missing_folder", ".wslconfig")
            r = _Row(root, blocked, answers=[True])
            r.row.show(_info(16))
            r.save()
            check(r.kinds() == ["ask", "error"]
                  and r.dialogs[1][1].startswith("about.wsl_limit_write_failed") and r.saved == 0,
                  f"a file that cannot be written -> an error, nothing more ({r.kinds()})")
    finally:
        root.destroy()


def main():
    _test_proposal()
    _test_set_memory()
    _test_plan_apply()
    _test_shutdown()
    _test_row()
    print()
    if failures:
        print(f"{len(failures)} FAILED")
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
