"""
test_delete_benchmarks.py -- Settings > Backup "Delete benchmarks": clears every row of the
storage's benchmark_log.csv and nothing else.

A. delete_manager.count_benchmark_rows: no file, header only, rows, a quoted field holding a
   line break (one row).
B. delete_manager.clear_benchmark_log: the header line stays byte for byte, every row goes;
   the floors, their floor_meta.json and sieving-prime cache, and the totals cache stay; no
   file -> nothing created, no error; an empty file stays empty; a failed replace -> an
   error, the log unchanged, no temp file left; PortalWiper.execute() still clears the log.
C. DeleteSection._on_delete_benchmarks_clicked on a stub tab: no rows -> one info, no
   question; "No" -> the log unchanged, no reload; "Yes" -> the log cleared, the Benchmark
   tab reloaded once, a done message naming the row count; a failed clear -> a warning and
   no reload.
D. The strings exist in English and Polish with the same placeholders.

Usage:
    python unitTests/test_delete_benchmarks.py
"""
import json
import os
import re
import shutil
import sys
import tempfile
from unittest import mock

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []

HEADER = "timestamp,engine,base_exponent,total_seconds\n"
ROWS = ("2026-11-10T10:00:00,v7.2,18,577.0\n"
        "2026-11-10T10:10:00,v7.2,18,55.1\n"
        '2026-11-10T10:20:00,"v6\nsplit",19,12.0\n')
KEYS = ("settings.delete_benchmarks_frame", "settings.delete_benchmarks_hint",
        "settings.delete_benchmarks_button", "settings.delete_benchmarks_empty",
        "settings.delete_benchmarks_confirm", "settings.delete_benchmarks_done",
        "settings.delete_benchmarks_error")


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _seed(portal):
    """A storage with a log of 3 rows, one floor and the caches around it."""
    _write(os.path.join(portal, "benchmark_log.csv"), HEADER + ROWS)
    _write(os.path.join(portal, "10p18", "source_primes", "PRIME_WINDOW_10p18_off_0.bin"), "x")
    _write(os.path.join(portal, "10p18", "floor_meta.json"), "{}")
    _write(os.path.join(portal, "10p18", "sieving_primes_count_cache.json"), '{"1000": 168}')
    _write(os.path.join(portal, ".portal_totals_cache.json"), "{}")


def _files(portal):
    out = set()
    for root, _dirs, names in os.walk(portal):
        out.update(os.path.relpath(os.path.join(root, n), portal) for n in names)
    return out


def part_a(tmp):
    from primeatlas.settings import delete_manager as dm
    portal = os.path.join(tmp, "a")
    os.makedirs(portal)
    check(dm.count_benchmark_rows(portal) == 0, "no log: 0 rows")
    _write(os.path.join(portal, "benchmark_log.csv"), HEADER)
    check(dm.count_benchmark_rows(portal) == 0, "header only: 0 rows")
    _write(os.path.join(portal, "benchmark_log.csv"), HEADER + ROWS)
    check(dm.count_benchmark_rows(portal) == 3,
          "3 rows, one with a quoted line break, count as 3")


def part_b(tmp):
    from primeatlas.settings import delete_manager as dm
    portal = os.path.join(tmp, "b")
    _seed(portal)
    before = _files(portal)
    check(dm.clear_benchmark_log(portal) is None, "clear: no error")
    check(_read(os.path.join(portal, "benchmark_log.csv")) == HEADER,
          "clear: the header line stays byte for byte, every row is gone")
    check(_files(portal) == before, "clear: no file added or removed (floors, caches stay)")
    check(_read(os.path.join(portal, "10p18", "sieving_primes_count_cache.json"))
          == '{"1000": 168}', "clear: the floor's sieving-prime cache is untouched")

    empty_dir = os.path.join(tmp, "b_none")
    os.makedirs(empty_dir)
    check(dm.clear_benchmark_log(empty_dir) is None and not os.listdir(empty_dir),
          "no log: no error and nothing created")
    _write(os.path.join(empty_dir, "benchmark_log.csv"), "")
    check(dm.clear_benchmark_log(empty_dir) is None
          and _read(os.path.join(empty_dir, "benchmark_log.csv")) == "",
          "an empty log stays empty")

    locked = os.path.join(tmp, "b_locked")
    _seed(locked)
    with mock.patch.object(dm.os, "replace", side_effect=OSError("locked")):
        error = dm.clear_benchmark_log(locked)
    check(isinstance(error, str) and "locked" in error, f"failed replace: an error ({error!r})")
    check(_read(os.path.join(locked, "benchmark_log.csv")) == HEADER + ROWS,
          "failed replace: the log is unchanged")
    check(not [n for n in os.listdir(locked) if ".tmp" in n], "failed replace: no temp file left")

    full = os.path.join(tmp, "b_full")
    _seed(full)
    _deleted, errors = dm.PortalWiper(full).execute()
    check(not errors and _read(os.path.join(full, "benchmark_log.csv")) == HEADER,
          "PortalWiper.execute() still leaves only the header")


class _StubTab:
    """The parts of SettingsTab that DeleteSection's benchmark delete uses."""

    def __init__(self, portal):
        self.reloads = 0
        self.logged = []
        self.wsl = {"get_portal_folder": lambda: portal,
                    "reload_benchmark_log": self._reload}

    def _reload(self):
        self.reloads += 1

    def T(self, key, **kwargs):
        return key + (json.dumps(kwargs, sort_keys=True) if kwargs else "")

    def _restore_log(self, text):
        self.logged.append(text)


def _click(tab, answer):
    from primeatlas.settings import delete_section
    calls = []
    box = mock.MagicMock()
    box.askyesno.side_effect = lambda *a, **k: calls.append(("ask", a)) or answer
    box.showinfo.side_effect = lambda *a, **k: calls.append(("info", a))
    box.showwarning.side_effect = lambda *a, **k: calls.append(("warning", a))
    with mock.patch.object(delete_section, "messagebox", box):
        delete_section.DeleteSection._on_delete_benchmarks_clicked(tab)
    return calls


def part_c(tmp):
    from primeatlas.settings import delete_manager as dm
    portal = os.path.join(tmp, "c")
    os.makedirs(portal)
    _write(os.path.join(portal, "benchmark_log.csv"), HEADER)
    tab = _StubTab(portal)
    calls = _click(tab, True)
    check([c[0] for c in calls] == ["info"]
          and calls[0][1][1] == "settings.delete_benchmarks_empty" and tab.reloads == 0,
          f"no rows: one info, no question, no reload ({calls})")

    _seed(portal)
    calls = _click(tab, False)
    check([c[0] for c in calls] == ["ask"]
          and _read(os.path.join(portal, "benchmark_log.csv")) == HEADER + ROWS
          and tab.reloads == 0, f"No: the log unchanged, no reload ({calls})")
    check('"rows": 3' in calls[0][1][1] and json.dumps(portal)[1:-1] in calls[0][1][1],
          "the question names the row count and the storage folder")

    calls = _click(tab, True)
    check([c[0] for c in calls] == ["ask", "info"]
          and _read(os.path.join(portal, "benchmark_log.csv")) == HEADER and tab.reloads == 1,
          f"Yes: the log cleared, the Benchmark tab reloaded once ({calls})")
    check(calls[1][1][1].startswith("settings.delete_benchmarks_done")
          and '"rows": 3' in calls[1][1][1], "the done message names the row count")

    _seed(portal)
    with mock.patch.object(dm.os, "replace", side_effect=OSError("locked")):
        calls = _click(tab, True)
    check([c[0] for c in calls] == ["ask", "warning"] and tab.reloads == 1,
          f"failed clear: a warning, no reload ({calls})")


def part_d():
    locales = os.path.join(_REPO_ROOT, "primeatlas", "core", "locales")
    with open(os.path.join(locales, "strings_en.json"), encoding="utf-8") as f:
        en = json.load(f)
    with open(os.path.join(locales, "strings_pl.json"), encoding="utf-8") as f:
        pl = json.load(f)
    for key in KEYS:
        check(key in en and key in pl, f"{key} in English and Polish")
        if key in en and key in pl:
            check(set(re.findall(r"{(\w+)}", en[key])) == set(re.findall(r"{(\w+)}", pl[key])),
                  f"{key}: same placeholders")


def main():
    tmp = tempfile.mkdtemp(prefix="primeatlas_delete_benchmarks_test_")
    try:
        part_a(tmp)
        part_b(tmp)
        part_c(tmp)
        part_d()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if failures:
        print(f"\n{len(failures)} FAILED")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
