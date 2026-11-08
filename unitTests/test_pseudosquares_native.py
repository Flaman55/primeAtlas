"""
test_pseudosquares_native.py -- Pseudosquares mode runs Kim Walisch's Pseudosquares Prime
Sieve program itself, so its benchmark row is that program's own speed.

A. Pure: the range of (floor, start, count, window_m), clamped to the floor's end and to the
   program's 10^33 stop, every floor up to 32 accepted, 33 and up refused; the argv of both
   modes (count: [START, STOP] plus --threads=N when a thread count is set, print: --print,
   never --threads); the text file path of a print run; parsing the program's count report
   and --version; the engine version naming the pinned build; the log row of each mode:
   engine tag, threads as reported, no Atlas windows, count = sieve time, print = loop time
   on 1 thread; the binary lookup order (env override, install dir, PATH).
B. The GUI-side argv of the runner: positional floor/start/count/window_m/mode/threads.
C. (WSL only, program installed) a count run and a print run over the same range of floor
   20: the count equals the lines the print run wrote, the print file holds the program's
   own text; primesieve's count of a floor-18 range (under its 2^64 stop) agrees.

Usage:
    python unitTests/test_pseudosquares_native.py      (A, B; C runs only under WSL)
"""
import csv
import os
import shutil
import subprocess
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []
W = 10_000_000

COUNT_REPORT = """Sieving primes inside [10000000000000000000000000, 10000000000000000010000000]
Thread dist: 416667
Threads: 24

Sieve size: 262144 bytes
delta: 4194304
s: 63959939 (max sieving prime)
p: 227 (pseudosquare prime)
Lp: 190621428905186449 (pseudosquare)

Primes: 173428
Seconds: 0.397
"""
VERSION_TEXT = """pseudosquares_prime_sieve 1.2, <https://github.com/kimwalisch/Pseudosquares-Prime-Sieve>
Copyright (C) 2026 Kim Walisch
BSD 2-Clause License <https://opensource.org/licenses/BSD-2-Clause>
"""


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False


def part_a():
    import benchmark_log_schema as schema
    import pseudosquares_const as const
    import pseudosquares_native as pss

    check(pss.native_range(20, 0, 2, W) == (10 ** 20, 10 ** 20 + 2 * W),
          "range: floor start plus start/count windows, hi exclusive")
    check(pss.native_range(20, 3, 1, W) == (10 ** 20 + 3 * W, 10 ** 20 + 4 * W),
          "range: start index moves lo by whole windows")
    check(pss.native_range(3, 0, 1, W) == (1000, 10_000),
          "range: a low floor ends at its own end, not one window further")
    lo, hi = pss.native_range(32, 0, 10 ** 30, W)
    check((lo, hi) == (10 ** 32, 10 ** 33), "range: floor 32 ends at the program's 10^33 stop")
    lo, hi = pss.native_range(32, 9 * 10 ** 25 - 1, 5, W)
    check(hi == 10 ** 33 and hi - lo == W, "range: the last window of floor 32 is clamped, not dropped")
    check(const.MAX_FLOOR == 32, "MAX_FLOOR: 32 is the last floor under 10^33")
    check(raises(lambda: pss.native_range(33, 0, 1, W)), "range: floor 33 refused")
    check(raises(lambda: pss.native_range(20, 0, 0, W)), "range: zero windows refused")
    check(raises(lambda: pss.native_range(3, 1, 1, W)), "range: a start past the floor's end refused")
    check(pss.native_range(0, 0, 1, W) == (1, 10), "range: floor 0 is [1, 10)")

    b = "/x/pseudosquares_prime_sieve"
    check(pss.argv("count", 100, 200, 0, b) == [b, "100", "199"],
          "argv count, Auto threads: [START, STOP] inclusive, no thread flag")
    check(pss.argv("count", 100, 200, 6, b) == [b, "100", "199", "--threads=6"],
          "argv count, 6 threads: --threads=6")
    check(pss.argv("print", 100, 200, 6, b) == [b, "100", "199", "--print"],
          "argv print: --print, no thread flag (the program prints on one thread)")
    big = 10 ** 32 + 5
    check(pss.argv("count", big, big + 10, 0, b)[1:3] == [str(big), str(big + 9)],
          "argv: numbers past 2^64 written in full")
    check(pss.print_path("/p", 25, 10 ** 25, 10 ** 25 + W) == os.path.join(
        "/p", "pseudosquares", "10p25", f"{10 ** 25}_{10 ** 25 + W - 1}.txt"),
          "print path: portal/pseudosquares/10p<N>/<start>_<stop>.txt")

    report = pss.parse_count_report(COUNT_REPORT)
    check(report == {"threads": 24, "seconds": 0.397, "primes": 173428},
          "count report: threads, seconds, primes")
    check(pss.parse_count_report("garbage") == {"threads": None, "seconds": None, "primes": None},
          "count report: missing fields are None")
    check(pss.parse_version(VERSION_TEXT) == "1.2", "version: parsed from --version")
    check(pss.parse_version("") == "", "version: empty when absent")
    check(pss.engine_version("1.2", "fccb96e") == "1.2 (fccb96e)",
          "engine version: program version plus the build's commit")
    check(pss.engine_version("1.2", None) == "1.2", "engine version: no commit, version only")
    check(pss.engine_version("", None) == "", "engine version: empty when unknown")

    count = pss.benchmark_row("count", 25, 0, 1, W, wall_seconds=0.4, primes=173428,
                              threads=24, version="1.2 (fccb96e)", bytes_written=None,
                              max_rss_mb=512.0)
    check(count["engine"] == schema.ENGINE_PSEUDOSQUARES_COUNT == "pseudosquares_count",
          "count row: engine pseudosquares_count")
    check(count["engine_version"] == "1.2 (fccb96e)" and count["threads"] == "24",
          "count row: version and the threads the program reported")
    check(count["sieve_seconds"] == "0.400" and count["total_seconds"] == "0.400",
          "count row: wall time is total and sieve time")
    check(count["loop_session_seconds"] == "" and count["write_threads"] == "",
          "count row: no loop time, no write threads")
    check(count["windows_written"] == 0 and count["numbers_processed"] == W,
          "count row: no Atlas windows, numbers of the range")
    check(count["run_purpose"] == schema.RUN_PURPOSE_BENCHMARK, "count row: a benchmark run")
    check(count["max_child_rss_mb"] == "512.0", "count row: the program's peak RAM")

    printed = pss.benchmark_row("print", 25, 0, 1, W, wall_seconds=2.0, primes=173428,
                                threads=const.PRINT_THREADS, version="1.2", bytes_written=4567,
                                max_rss_mb=None)
    check(printed["engine"] == schema.ENGINE_PSEUDOSQUARES_PRINT == "pseudosquares_print",
          "print row: engine pseudosquares_print")
    check(printed["loop_session_seconds"] == "2.000" and printed["sieve_seconds"] == "",
          "print row: wall time is loop time, no sieve time")
    check(printed["loop_numbers_per_second"] == f"{W / 2.0:.2f}", "print row: numbers per second")
    check(printed["threads"] == "1" and printed["write_threads"] == "1",
          "print row: 1 thread, 1 write thread")
    check(printed["bytes_written"] == 4567, "print row: text bytes")
    check(printed["run_purpose"] == schema.RUN_PURPOSE_BENCHMARK,
          "print row: a benchmark run (the program's own format, not Atlas storage)")

    tmp = tempfile.mkdtemp()
    saved = {k: os.environ.get(k) for k in (const.BINARY_ENV, "PATH")}
    try:
        def make(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("")
            os.chmod(path, 0o755)
        install = os.path.join(tmp, "install")
        built = os.path.join(install, const.BUILD_DIR_NAME, const.BINARY_NAME)
        override = os.path.join(tmp, "own", const.BINARY_NAME)
        on_path = os.path.join(tmp, "bin", const.BINARY_NAME)
        os.environ.pop(const.BINARY_ENV, None)
        os.environ["PATH"] = os.path.join(tmp, "empty")
        check(pss.find_binary(install) is None, "binary: none installed -> None")
        if os.name != "nt":
            make(on_path)
            os.environ["PATH"] = os.path.dirname(on_path)
            check(pss.find_binary(install) == on_path, "binary: found on PATH")
            make(built)
            check(pss.find_binary(install) == built, "binary: the install's build wins over PATH")
            make(override)
            os.environ[const.BINARY_ENV] = override
            check(pss.find_binary(install) == override, "binary: the env override wins")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp)


def part_b():
    from primeatlas.generation.engine_argv import build_pseudosquares_native_argv
    argv = build_pseudosquares_native_argv(25, 3, 2, W, "count", 8,
                                           script_path=r"C:\r\prime_sieve\pseudosquares_native.py")
    check(argv == ["python3", "-u", "/mnt/c/r/prime_sieve/pseudosquares_native.py",
                   "25", "3", "2", str(W), "count", "8"],
          "GUI argv: floor, start, count, window_m, mode, threads (0 = Auto)")


def part_c():
    if os.name == "nt" or "microsoft" not in os.uname().release.lower():
        print("SKIPPED (WSL-only): part C")
        return
    import native_tool_run
    import pseudosquares_native as pss
    if pss.find_binary() is None:
        print("SKIPPED (program not installed): part C")
        return
    tmp = tempfile.mkdtemp()
    try:
        w = 1_000_000
        count = pss.run("count", 20, 0, 2, w, tmp, threads=2)
        printed = pss.run("print", 20, 0, 2, w, tmp)
        lo, hi = pss.native_range(20, 0, 2, w)
        path = pss.print_path(tmp, 20, lo, hi)
        check(os.path.isfile(path), "print run: text file written")
        check(count["total_primes"] == printed["total_primes"] == native_tool_run.count_lines(path),
              f"count == printed lines ({count['total_primes']})")
        check(count["threads"] == "2", "count run: the thread count asked for")
        with open(path) as f:
            first = int(f.readline())
        check(lo <= first < hi, "print file: the program's own one-prime-per-line text")
        with open(os.path.join(tmp, "benchmark_log.csv"), newline="") as f:
            rows = list(csv.DictReader(f))
        check([r["engine"] for r in rows] == ["pseudosquares_count", "pseudosquares_print"],
              "log: one row per run")
        if shutil.which("primesieve"):
            low = pss.run("count", 18, 0, 1, w, tmp)
            lo18, hi18 = pss.native_range(18, 0, 1, w)
            ps = subprocess.run(["primesieve", str(lo18), str(hi18 - 1), "--count", "--quiet"],
                                capture_output=True, text=True)
            check(ps.returncode == 0 and int(ps.stdout.split()[-1]) == low["total_primes"],
                  f"primesieve's count of a floor-18 range agrees ({low['total_primes']})")
    finally:
        shutil.rmtree(tmp)


def main():
    part_a()
    part_b()
    part_c()
    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
