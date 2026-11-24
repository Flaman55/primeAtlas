"""
test_wslconfig_edit.py -- primeatlas/about/wslconfig_edit.py, how Atlas changes the WSL RAM
and processor limits (memory= and processors= of the [wsl2] section of
%UserProfile%\\.wslconfig).

A. min_limit_gib(windows_ram_bytes): WSL's own default, half the RAM in whole GiB, at least
   MIN_LIMIT_GIB. proposed_limit_gib: Windows RAM minus max(RESERVE_MIN_GIB, RESERVE_SHARE of
   it), rounded to whole GiB, never below min_limit_gib. max_limit_gib: the whole GiB of
   Windows RAM. All three None for unknown RAM. is_risky(gib, ram): above the proposal.
   max_processors(threads): the Windows thread count, None when unknown; MIN_PROCESSORS 1.
B. set_wsl2_keys(text, {"memory": "40GB"}): only memory= of [wsl2] changes, everything else stays byte for
   byte (other keys, other sections, comments, an inline comment after the value, blank lines,
   CRLF or LF line ends). Section and key names in any case. Every memory= line of [wsl2] gets
   the value (a repeated key cannot keep the old one). [wsl2] without memory= gets the line
   after its last key; no [wsl2] gets the section at the end; an empty file becomes the
   section alone. A memory= of another section is never touched. The result reads back
   (system_info.parse_wslconfig) as the new limit.
   B2. The same for processors=, and for both keys at once: each existing line keeps its
   place, missing ones are added after the last key in the order given; {} changes nothing.
C. plan_change(path, values) / apply_change(change): the plan holds the file's text before and
   after and diff_lines() names exactly the removed and added lines. Applying writes the new
   text, keeps a UTF-8 BOM the file had, leaves a backup copy of the old file next to it
   (.wslconfig.bak_<date>_<time>) and no temp file; a missing file is created with no backup;
   a plan with nothing to change writes nothing. A file edited after the plan is not
   overwritten (FileChangedError, file and folder untouched).
D. shutdown_wsl(run): runs `wsl.exe --shutdown` once; True only for exit code 0; a missing
   wsl.exe or a timeout is False.
E. WslLimitRow (primeatlas/about/wsl_limit_row.py) with recorded dialogs and shutdown:
   E1. show(info) puts the file's memory= in GB in the field, else the proposal, and names
       the proposal; unknown Windows RAM leaves both empty.
   E2. Save refuses a value outside WSL's default (half the RAM)..Windows RAM, a non-number
       and an empty field before reading or asking anything.
   E3. Until Windows RAM is known (before show(), or show() with unknown RAM) Save is
       disabled and save() does nothing.
   E4. A file limit that is not whole GB (10.4GB shows 10): Save with 10 is a change and asks.
   E5. Two memory= lines in [wsl2]: the last one is the current limit (WSL reads it so);
       a write sets both.
   E6. A value equal to the file's limit (in any unit) does nothing at all: no dialog, no
       write, no restart.
   E7. A limit above the proposal is warned about first (No by default);
   E8. No to the warning changes nothing and puts the cursor back in the field.
   E9. A new value asks first (file path, changed lines, backup or new-file note); No leaves
       the file; Yes writes it with a backup. A file edited while the question was open is
       kept and an error says so; a file that cannot be written gives an error; a missing
       file is created with no backup.
   E10. A file that cannot be read (a folder in its place, not UTF-8) gives an error and
        nothing more.
   E11. After a write: while a Generation job runs WSL is not restarted and a note names the
        jobs; otherwise it asks to restart WSL: No -> a next-start note; Yes -> one shutdown,
        then the hardware is read again; a failed shutdown -> an error.
   E12. While the restart runs Save is disabled and save() does nothing; it is enabled
        again when the restart ends.
F. The row's processor field (same Save button):
   F1. show(info) puts the file's processors= in the field, else the Windows thread count,
       and a hint names the thread count; unknown threads leave both empty.
   F2. Save refuses a value outside 1..the Windows threads, a non-number and an empty field
       (the error names the processor field) before reading or asking anything.
   F3. A file value above the threads (64 of 16) shows as it is, marked out of range;
       Save refuses it.
   F4. Until the Windows threads are known Save is disabled and save() does nothing.
   F5. Nothing to change (processors= equal to the field, or no processors= and the field
       at all threads, the WSL default; RAM unchanged): no dialog, no write.
   F6. Only the processors changed: one question whose diff names only processors=, one
       backup, the memory= line kept, one restart question.
   F7. Both changed: one question naming both lines, one backup, one restart question.
   F8. A risky RAM limit already in the file and only the processors changed: no warning;
       a risky new RAM limit with the processors changed: the warning first.
   F9. Either field unusable: nothing is asked or written, even when the other changed.

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
    check(we.MIN_PROCESSORS == 1, "the smallest processor limit is 1")
    for threads in (1, 8, 24):
        check(we.max_processors(threads) == threads, f"{threads} threads -> at most {threads}")
    for threads in (None, 0):
        check(we.max_processors(threads) is None, f"threads {threads!r} -> no largest limit")


def _limit(text):
    return system_info.parse_wslconfig(text).memory_bytes


def _mem(text, gib):
    return we.set_wsl2_keys(text, {"memory": f"{gib}GB"})


def _test_set_memory():
    print("\n--- B. set_wsl2_keys (memory) ---")
    check(_mem("[wsl2]\nmemory=48GB\n", 40) == "[wsl2]\nmemory=40GB\n",
          "the value is replaced")
    crlf = "[wsl2]\r\nmemory=48GB\r\nprocessors=8\r\n"
    check(_mem(crlf, 40) == "[wsl2]\r\nmemory=40GB\r\nprocessors=8\r\n",
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
    got = _mem(full, 40)
    check(got == want, f"only memory= of [wsl2] changes, spaces, case and comment kept ({got!r})")
    check(_limit(got) == 40 * GIB, "it reads back as 40 GiB")
    twice = "[wsl2]\nmemory=8GB\nswap=0\nmemory=16GB\n"
    got = _mem(twice, 20)
    check(got == "[wsl2]\nmemory=20GB\nswap=0\nmemory=20GB\n" and _limit(got) == 20 * GIB,
          f"every memory= of [wsl2] gets the value ({got!r})")
    no_key = "[wsl2]\nprocessors=8\nswap=0\n\n[boot]\nsystemd=true\n"
    got = _mem(no_key, 12)
    check(got == "[wsl2]\nprocessors=8\nswap=0\nmemory=12GB\n\n[boot]\nsystemd=true\n",
          f"[wsl2] without memory= gets it after its last key ({got!r})")
    empty_section = "[wsl2]\n[boot]\nsystemd=true\n"
    got = _mem(empty_section, 12)
    check(got == "[wsl2]\nmemory=12GB\n[boot]\nsystemd=true\n",
          f"an empty [wsl2] gets the line right under it ({got!r})")
    other = "[boot]\r\nsystemd=true\r\n"
    got = _mem(other, 12)
    check(got == "[boot]\r\nsystemd=true\r\n\r\n[wsl2]\r\nmemory=12GB\r\n",
          f"no [wsl2] -> the section at the end, same line ends ({got!r})")
    no_end = "[boot]\nsystemd=true"
    got = _mem(no_end, 12)
    check(got == "[boot]\nsystemd=true\n\n[wsl2]\nmemory=12GB\n" and _limit(got) == 12 * GIB,
          f"a last line with no line end still ends before the new section ({got!r})")
    check(_mem("", 7) == "[wsl2]\nmemory=7GB\n", "empty file -> the section alone")
    last = "[wsl2]\nswap=0"
    check(_mem(last, 7) == "[wsl2]\nswap=0\nmemory=7GB\n",
          "a [wsl2] ending the file with no line end gets the line after its last key")
    check(_mem("[wsl2]\nmemory=40GB\n", 40) == "[wsl2]\nmemory=40GB\n",
          "the same value -> the same text")
    commented = "[wsl2]\n# memory=10GB\nmemoryX=3\n"
    got = _mem(commented, 9)
    check(got == "[wsl2]\n# memory=10GB\nmemoryX=3\nmemory=9GB\n",
          f"a commented memory= or a longer key is not the key ({got!r})")


def _test_set_processors():
    print("\n--- B2. set_wsl2_keys (processors, both) ---")
    cpus = system_info.parse_wslconfig
    check(we.set_wsl2_keys("[wsl2]\nprocessors=8\n", {"processors": "20"})
          == "[wsl2]\nprocessors=20\n", "processors= is replaced")
    full = ("[experimental]\r\nprocessors=2\r\n\r\n[wsl2]\r\nmemory=40GB\r\n"
            "  Processors = 12  # half\r\nswap=32GB\r\n")
    got = we.set_wsl2_keys(full, {"processors": "20"})
    check(got == full.replace("Processors = 12", "Processors = 20"),
          f"only processors= of [wsl2] changes, CRLF, spaces, case and comment kept ({got!r})")
    check(cpus(got).processors == 20, "it reads back as 20")
    got = we.set_wsl2_keys("[wsl2]\nmemory=40GB\nswap=0\n", {"processors": "6"})
    check(got == "[wsl2]\nmemory=40GB\nswap=0\nprocessors=6\n",
          f"[wsl2] without processors= gets it after its last key ({got!r})")
    twice = "[wsl2]\nprocessors=4\nprocessors=6\n"
    check(we.set_wsl2_keys(twice, {"processors": "8"}) == "[wsl2]\nprocessors=8\nprocessors=8\n",
          "every processors= of [wsl2] gets the value")
    both = "[wsl2]\nprocessors=4\nswap=0\nmemory=8GB\n"
    got = we.set_wsl2_keys(both, {"memory": "40GB", "processors": "20"})
    check(got == "[wsl2]\nprocessors=20\nswap=0\nmemory=40GB\n",
          f"both keys: each line keeps its place ({got!r})")
    got = we.set_wsl2_keys("[wsl2]\nswap=0\n[boot]\nsystemd=true\n",
                           {"memory": "40GB", "processors": "20"})
    check(got == "[wsl2]\nswap=0\nmemory=40GB\nprocessors=20\n[boot]\nsystemd=true\n",
          f"both missing: added after the last key in the order given ({got!r})")
    got = we.set_wsl2_keys("[wsl2]\nmemory=8GB\n", {"processors": "3", "memory": "9GB"})
    check(got == "[wsl2]\nmemory=9GB\nprocessors=3\n",
          f"one present, one missing ({got!r})")
    check(we.set_wsl2_keys("", {"memory": "8GB", "processors": "4"})
          == "[wsl2]\nmemory=8GB\nprocessors=4\n", "empty file -> the section with both")
    got = we.set_wsl2_keys("[boot]\nsystemd=true\n", {"processors": "4"})
    check(got == "[boot]\nsystemd=true\n\n[wsl2]\nprocessors=4\n",
          f"no [wsl2] -> the section at the end ({got!r})")
    check(we.set_wsl2_keys(both, {}) == both, "{} changes nothing")
    check(we.set_wsl2_keys("[wsl2]\nprocessorsX=3\n# processors=2\n", {"processors": "5"})
          == "[wsl2]\nprocessorsX=3\nprocessors=5\n# processors=2\n",
          "a longer key or a commented processors= is not the key")


def _files(folder):
    return sorted(os.listdir(folder))


def _test_plan_apply():
    print("\n--- C. plan_change / apply_change ---")
    when = datetime(2026, 11, 16, 9, 5, 7)
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, ".wslconfig")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("[wsl2]\r\nmemory=48GB\r\nswap=0\r\n")
        change = we.plan_change(path, {"memory": "40GB"})
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

        same = we.plan_change(path, {"memory": "40GB"})
        check(not same.changed and same.diff_lines() == [], "the same value -> nothing to change")
        check(we.apply_change(same, now=when) is None and len(_files(folder)) == 2,
              "applying no change writes nothing and makes no backup")

        stale = we.plan_change(path, {"memory": "30GB"})
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
        we.apply_change(we.plan_change(path, {"memory": "6GB"}), now=when)
        with open(path, "rb") as f:
            check(f.read() == b"\xef\xbb\xbf[wsl2]\nmemory=6GB\n", "a UTF-8 BOM is kept")

    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, ".wslconfig")
        change = we.plan_change(path, {"memory": "12GB"})
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


def _info(ram_gib, memory_text=None, threads=16, processors=None):
    windows = system_info.WindowsInfo(ram_total=None if ram_gib is None else ram_gib * GIB,
                                      threads=threads)
    text = "[wsl2]\n"
    if memory_text:
        text += f"memory={memory_text}\n"
    if processors is not None:
        text += f"processors={processors}\n"
    return system_info.SystemInfo(windows, None, system_info.parse_wslconfig(text))


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

    def save(self, value=None, cpus=None):
        if value is not None:
            self.row.value_var.set(value)
        if cpus is not None:
            self.row.cpu_var.set(cpus)
        self.row.field.refresh(at_once=True)
        self.row.cpu_field.refresh(at_once=True)
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

            for text in ("10GB", "10240MB", " 10 GB  # mine"):
                _write(path, f"[wsl2]\nmemory={text}\n")
                r = _Row(root, path, answers=[True, True])
                r.row.show(_info(16, text))
                r.save("10")
                check(r.dialogs == [] and r.shutdowns == 0 and r.saved == 0
                      and _read(path) == f"[wsl2]\nmemory={text}\n",
                      f"the file's own limit ({text!r}) -> Save does nothing at all ({r.kinds()})")
            check(len([n for n in os.listdir(folder) if n.startswith(".wslconfig.bak_")]) == 1,
                  "no write -> no new backup")
            _write(path, "[wsl2]\nmemory=10GB\n")

            r = _Row(root, path, answers=[True, True])
            r.row.show(_info(16, "10GB"))
            r.save("9")
            check(r.kinds() == ["ask", "ask"] and r.shutdowns == 1 and r.saved == 1,
                  f"Yes to the restart -> WSL shut down once, then read again ({r.kinds()})")

            r = _Row(root, path, answers=[True, True], shutdown_ok=False)
            r.row.show(_info(16, "9GB"))
            r.save("10")
            check(r.kinds() == ["ask", "ask", "error"] and r.saved == 1,
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
            r = _Row(root, path, answers=[True, True])
            r.row.show(_info(16, "14GB"))
            r.save("14")
            check(r.dialogs == [] and r.shutdowns == 0,
                  f"a risky limit already in the file -> Save does nothing, no warning ({r.kinds()})")

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

        with tempfile.TemporaryDirectory() as folder:
            _test_row_edges(root, folder)
        with tempfile.TemporaryDirectory() as folder:
            _test_processors(root, folder)
    finally:
        root.destroy()


def _test_row_edges(root, folder):
    import threading
    path = os.path.join(folder, ".wslconfig")
    _write(path, "[wsl2]\nmemory=8GB\n")

    # E3: no RAM known yet
    r = _Row(root, path, answers=[True, True])
    check(r.row.save_button.instate(["disabled"]), "E3: Save is disabled before the RAM is read")
    r.save("999")
    check(r.dialogs == [] and _read(path) == "[wsl2]\nmemory=8GB\n",
          f"E3: save() before the RAM is read does nothing ({r.kinds()})")
    r.row.show(_info(None, "8GB"))
    r.save("999")
    check(r.row.save_button.instate(["disabled"]) and r.dialogs == []
          and _read(path) == "[wsl2]\nmemory=8GB\n",
          f"E3: unknown RAM -> Save disabled, save() does nothing ({r.kinds()})")
    r.row.show(_info(16, "8GB"))
    check(not r.row.save_button.instate(["disabled"]), "E3: known RAM -> Save enabled")

    # E4: a limit that is not whole GB
    _write(path, "[wsl2]\nmemory=10.4GB\n")
    r = _Row(root, path, answers=[False])
    r.row.show(_info(16, "10.4GB"))
    check(r.row.value_var.get() == "10", "E4: 10.4GB shows as 10")
    r.save()
    check(r.kinds() == ["ask"] and "+ memory=10GB" in r.dialogs[0][1],
          f"E4: Save with 10 against 10.4GB is a change and asks ({r.kinds()})")

    # E5: two memory= lines, the last one counts
    two = "[wsl2]\nmemory=8GB\nmemory=10GB\n"
    _write(path, two)
    r = _Row(root, path, answers=[True, True])
    r.row.show(_info(16, "10GB"))
    r.save("10")
    check(r.dialogs == [] and _read(path) == two,
          f"E5: the last memory= equals the field -> nothing happens ({r.kinds()})")
    r = _Row(root, path, answers=[True, False])
    r.row.show(_info(16, "10GB"))
    r.save("8")
    check(r.kinds()[:1] == ["ask"] and _read(path) == "[wsl2]\nmemory=8GB\nmemory=8GB\n",
          f"E5: the first line's value is still a change; the write sets both ({r.kinds()})")

    # E8: No to the warning puts the cursor back in the field
    _write(path, "[wsl2]\nmemory=8GB\n")
    r = _Row(root, path, answers=[False])
    r.row.show(_info(16, "8GB"))
    focused = []
    r.row.entry.focus_set = lambda: focused.append(True)
    r.save("15")
    check(r.kinds() == ["warn"] and focused == [True],
          f"E8: No to the warning -> the cursor goes back to the field ({r.kinds()}, {focused})")

    # E10: a file that cannot be read
    with open(path, "wb") as f:
        f.write(b"[wsl2]\nmemory=8GB # \xff\xfe\n")
    r = _Row(root, path, answers=[True, True])
    r.row.show(_info(16, "8GB"))
    r.save("10")
    check(r.kinds() == ["error"] and r.dialogs[0][1].startswith("about.wsl_limit_read_failed")
          and r.saved == 0 and r.shutdowns == 0,
          f"E10: a file that is not UTF-8 -> a read error, nothing more ({r.kinds()})")
    folder_path = os.path.join(folder, "a_folder")
    os.mkdir(folder_path)
    r = _Row(root, folder_path, answers=[True, True])
    r.row.show(_info(16, "8GB"))
    r.save("10")
    check(r.kinds() == ["error"] and r.dialogs[0][1].startswith("about.wsl_limit_read_failed"),
          f"E10: a folder in place of the file -> a read error, nothing more ({r.kinds()})")

    # E12: Save is disabled while the restart runs
    _write(path, "[wsl2]\nmemory=8GB\n")
    r = _Row(root, path, answers=[True, True, True, True])
    r.row.show(_info(16, "8GB"))
    release = threading.Event()
    started = threading.Event()
    runs = []

    def slow_shutdown():
        runs.append(1)
        started.set()
        release.wait(5)
        return True
    r.row.shutdown = slow_shutdown
    r.row.value_var.set("10")
    r.row.field.refresh(at_once=True)
    r.row.save()
    started.wait(5)
    root.update()
    asked = len(r.dialogs)
    check(r.row.save_button.instate(["disabled"]), "E12: Save is disabled while WSL restarts")
    r.row.value_var.set("11")
    r.row.field.refresh(at_once=True)
    r.row.save()
    root.update()
    check(len(r.dialogs) == asked and len(runs) == 1 and _read(path) == "[wsl2]\nmemory=10GB\n",
          f"E12: save() during the restart does nothing ({r.kinds()}, runs {len(runs)})")
    release.set()
    r._settle()
    check(not r.row.save_button.instate(["disabled"]) and r.saved == 1,
          "E12: the restart ends -> Save enabled again, the hardware read again")


def _test_processors(root, folder):
    print("\n--- F. the processor field ---")
    import tkinter.messagebox as messagebox
    errors = []
    messagebox.showerror = lambda *a, **k: errors.append(a)
    path = os.path.join(folder, ".wslconfig")
    base = "[wsl2]\nmemory=8GB\n"

    def backups():
        return [n for n in os.listdir(folder) if n.startswith(".wslconfig.bak_")]

    # F1
    r = _Row(root, path)
    r.row.show(_info(16, "8GB", processors=8))
    check(r.row.cpu_var.get() == "8", "F1: the field shows the file's processors=")
    check(r.row.cpu_hint_label.cget("text") == "about.wsl_cpu_hint|threads=16",
          f"F1: the hint names the threads ({r.row.cpu_hint_label.cget('text')!r})")
    r.row.show(_info(16, "8GB"))
    check(r.row.cpu_var.get() == "16", "F1: no processors= -> all Windows threads")
    r.row.show(_info(16, "8GB", threads=None))
    check(r.row.cpu_var.get() == "" and r.row.cpu_hint_label.cget("text") == "",
          "F1: unknown threads -> empty field, no hint")

    # F4
    _write(path, base)
    r = _Row(root, path, answers=[True, True])
    r.row.show(_info(16, "8GB", threads=None))
    r.save("10", "4")
    check(r.row.save_button.instate(["disabled"]) and r.dialogs == [] and _read(path) == base,
          f"F4: unknown threads -> Save disabled, save() does nothing ({r.kinds()})")
    r.row.show(_info(16, "8GB"))
    check(not r.row.save_button.instate(["disabled"]), "F4: threads known -> Save enabled")

    # F2
    r = _Row(root, path)
    r.row.show(_info(16, "8GB"))
    for bad in ("17", "0", "abc"):
        errors.clear()
        r.dialogs.clear()
        r.save("8", bad)
        check(len(errors) == 1 and r.dialogs == [] and _read(path) == base,
              f"F2: processors {bad!r} is refused before anything is read or asked")
    r.dialogs.clear()
    r.save("8", "")
    check(r.kinds() == ["error"] and r.dialogs[0][1] == "about.wsl_cpu_empty"
          and _read(path) == base, f"F2: an empty processor field is refused by name ({r.dialogs})")

    # F3
    _write(path, base + "processors=64\n")
    r = _Row(root, path, answers=[True, True])
    r.row.show(_info(16, "8GB", processors=64))
    check(r.row.cpu_var.get() == "64" and r.row.cpu_field.problem is not None,
          "F3: 64 of 16 threads shows as it is, marked out of range")
    errors.clear()
    r.save()
    check(len(errors) == 1 and r.dialogs == [] and _read(path) == base + "processors=64\n",
          f"F3: Save refuses it ({r.kinds()})")

    # F5
    for text, processors in ((base + "processors=8\n", 8), (base, None),
                             (base + "processors=many\n", None)):
        _write(path, text)
        r = _Row(root, path, answers=[True, True])
        r.row.show(_info(16, "8GB", processors=processors))
        r.save()
        check(r.dialogs == [] and r.shutdowns == 0 and _read(path) == text,
              f"F5: nothing to change in {text!r} -> nothing happens ({r.kinds()})")
    before = len(backups())

    # F6
    _write(path, base)
    r = _Row(root, path, answers=[False])
    r.row.show(_info(16, "8GB"))
    r.save(None, "12")
    diff = r.dialogs[0][1] if r.dialogs else ""
    check(r.kinds() == ["ask"] and "+ processors=12" in diff and "memory" not in diff,
          f"F6: the question names only processors= ({diff!r})")
    r = _Row(root, path, answers=[True, False])
    r.row.show(_info(16, "8GB"))
    r.save(None, "12")
    check(_read(path) == base + "processors=12\n" and len(backups()) == before + 1
          and r.kinds() == ["ask", "ask", "info"] and r.saved == 1,
          f"F6: Yes -> processors= added, memory= kept, one backup, one restart question "
          f"({r.kinds()})")

    # F7
    for name in backups():
        os.remove(os.path.join(folder, name))
    _write(path, base + "processors=12\n")
    r = _Row(root, path, answers=[True, False])
    r.row.show(_info(16, "8GB", processors=12))
    r.save("10", "6")
    diff = r.dialogs[0][1] if r.dialogs else ""
    check("+ memory=10GB" in diff and "+ processors=6" in diff,
          f"F7: one question names both lines ({diff!r})")
    check(_read(path) == "[wsl2]\nmemory=10GB\nprocessors=6\n" and len(backups()) == 1
          and r.kinds() == ["ask", "ask", "info"],
          f"F7: one write, one backup, one restart question ({r.kinds()})")

    # F8
    _write(path, "[wsl2]\nmemory=14GB\n")
    r = _Row(root, path, answers=[False])
    r.row.show(_info(16, "14GB"))
    r.save(None, "4")
    check(r.kinds() == ["ask"], f"F8: a risky limit already in the file -> no warning ({r.kinds()})")
    r = _Row(root, path, answers=[False])
    r.row.show(_info(16, "14GB"))
    r.save("15", "4")
    check(r.kinds() == ["warn"] and _read(path) == "[wsl2]\nmemory=14GB\n",
          f"F8: a risky new limit -> the warning first ({r.kinds()})")

    # F9
    _write(path, base)
    for ram, cpus in (("abc", "4"), ("10", "abc"), ("", "4"), ("10", "")):
        errors.clear()
        r = _Row(root, path, answers=[True, True])
        r.row.show(_info(16, "8GB"))
        r.save(ram, cpus)
        check(len(errors) + r.kinds().count("error") == 1 and "ask" not in r.kinds()
              and _read(path) == base,
              f"F9: RAM {ram!r}, processors {cpus!r} -> refused, nothing written ({r.kinds()})")


def main():
    _test_proposal()
    _test_set_memory()
    _test_set_processors()
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
