"""
pseudosquares_native.py -- Pseudosquares mode: runs the Pseudosquares Prime Sieve program
itself (J. P. Sorenson's algorithm, implemented by Kim Walisch), which outputs only proven
primes and reaches 10^33, past primesieve's 2^64.

The timed part is the program's process alone, from its start to its exit, so the logged
speed is the program's own; nothing of Atlas runs inside it (native_tool_run.py).
- count: `pseudosquares_prime_sieve START STOP [--threads=N]` -- finds the primes of the
  range and reports their number, writing nothing; the sieve-phase work of an Atlas engine,
  so the row goes on the sieve charts. Threads: the program's own choice (Auto, 0 here) or
  the N asked for, which it caps at the CPU cores; the row logs the count it reports.
- print: `pseudosquares_prime_sieve START STOP --print` into
  portal/pseudosquares/10p<N>/<start>_<stop>.txt -- every prime as the program's own text,
  one per line, NOT the Atlas storage format; a whole run, on the whole-run chart. The
  program prints on one thread (pseudosquares_const.PRINT_THREADS).
The range never leaves its floor (rows are per floor) and never passes the program's 10^33
stop. Both log one benchmark_log.csv row (engine ENGINE_PSEUDOSQUARES_COUNT /
ENGINE_PSEUDOSQUARES_PRINT, engine_version = program version plus the build's commit).

ATTRIBUTION: Pseudosquares Prime Sieve is an independent open-source program by Kim Walisch
(BSD 2-Clause License), https://github.com/kimwalisch/Pseudosquares-Prime-Sieve -- built
inside WSL by pseudosquares_install.py, not part of this project.

Run inside WSL:
    python3 pseudosquares_native.py <base_exponent> <target_idx_start> <target_idx_count>
                                    <window_m> <print|count> [threads, 0 = Auto]
"""
import os
import re
import shutil
import subprocess
import sys

import native_tool_run
import pseudosquares_const as const
from benchmark_log_schema import ENGINE_PSEUDOSQUARES_COUNT, ENGINE_PSEUDOSQUARES_PRINT

MODES = native_tool_run.MODES
ENGINES = {"print": ENGINE_PSEUDOSQUARES_PRINT, "count": ENGINE_PSEUDOSQUARES_COUNT}


def default_install_dir():
    return os.path.join(os.path.expanduser("~"), const.INSTALL_DIR_REL)


def native_range(base_exponent, target_idx_start, target_idx_count, window_m):
    """[lo, hi) of the request: hi clamped to the floor's end and to the program's stop.
    ValueError for a floor past MAX_FLOOR or a range with no numbers."""
    if base_exponent > const.MAX_FLOOR:
        raise ValueError(f"floor {base_exponent} is past the program's stop "
                         f"{const.MAX_STOP} (last floor {const.MAX_FLOOR})")
    lo = 10 ** base_exponent + target_idx_start * window_m
    hi = min(lo + target_idx_count * window_m, 10 ** (base_exponent + 1), const.MAX_STOP + 1)
    if hi <= lo:
        raise ValueError("empty range")
    return lo, hi


def argv(mode, lo, hi, threads, binary):
    """The program's command line for [lo, hi); its stop is inclusive. `threads` 0 = the
    program's own choice; print takes no thread count (it prints on one thread)."""
    cmd = [binary, str(lo), str(hi - 1)]
    if mode == "print":
        return cmd + ["--print"]
    return cmd + ([f"--threads={threads}"] if threads > 0 else [])


def print_path(portal_folder, base_exponent, lo, hi):
    return os.path.join(portal_folder, "pseudosquares", f"10p{base_exponent}",
                        f"{lo}_{hi - 1}.txt")


def parse_count_report(text):
    """{threads, seconds, primes} from the program's count output."""
    def grab(pattern, cast):
        m = re.search(pattern, text, re.M)
        return cast(m.group(1)) if m else None
    return {"threads": grab(r"^Threads: (\d+)", int),
            "seconds": grab(r"^Seconds: ([\d.]+)", float),
            "primes": grab(r"^Primes: (\d+)", int)}


def parse_version(text):
    m = re.search(r"pseudosquares_prime_sieve (\d+(?:\.\d+)*)", text)
    return m.group(1) if m else ""


def engine_version(version, commit):
    """"1.2 (fccb96e)": the program's version and the commit it was built from."""
    return f"{version} ({commit})" if version and commit else version


def find_binary(install_dir=None):
    """The program: $PSEUDOSQUARES_BIN, then the installer's build, then PATH; None if
    none is there."""
    def runnable(path):
        return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)
    override = os.environ.get(const.BINARY_ENV)
    if runnable(override):
        return override
    built = os.path.join(install_dir or default_install_dir(), const.BUILD_DIR_NAME,
                         const.BINARY_NAME)
    if runnable(built):
        return built
    return shutil.which(const.BINARY_NAME)


def build_commit(binary, install_dir=None):
    """Short commit of the install's clone when `binary` is its build, else None (a
    binary from elsewhere has no known source)."""
    install_dir = install_dir or default_install_dir()
    built = os.path.join(install_dir, const.BUILD_DIR_NAME, const.BINARY_NAME)
    if not binary or os.path.realpath(binary) != os.path.realpath(built):
        return None
    return head_commit(install_dir)


def head_commit(install_dir):
    """Short (7-digit) commit checked out in the clone at `install_dir`; None if none."""
    proc = subprocess.run(["git", "-C", install_dir, "rev-parse", "--short=7", "HEAD"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def benchmark_row(mode, base_exponent, target_idx_start, target_idx_count, window_m,
                  wall_seconds, primes, threads, version, bytes_written, max_rss_mb):
    """The log row of one native run (native_tool_run.benchmark_row)."""
    lo, hi = native_range(base_exponent, target_idx_start, target_idx_count, window_m)
    return native_tool_run.benchmark_row(
        mode, ENGINES[mode], base_exponent, target_idx_start, target_idx_count, lo, hi,
        wall_seconds, primes, threads, version, bytes_written, max_rss_mb,
        write_threads=const.PRINT_THREADS)


def run(mode, base_exponent, target_idx_start, target_idx_count, window_m, portal_folder,
        threads=0):
    """One native run; logs and returns its row."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    lo, hi = native_range(base_exponent, target_idx_start, target_idx_count, window_m)
    binary = find_binary()
    if binary is None:
        print("[!] pseudosquares_prime_sieve not found; install it in Settings > Updates "
              "(Pseudosquares Prime Sieve)")
        sys.exit(2)
    version = engine_version(
        parse_version(subprocess.run([binary, "--version"], capture_output=True,
                                     text=True).stdout),
        build_commit(binary))
    cmd = argv(mode, lo, hi, threads, binary)
    print(f"[*] Pseudosquares Prime Sieve {version} (native, Kim Walisch, BSD 2-Clause, "
          f"{const.REPO_URL}): {' '.join(cmd)}")
    print(f"[*] Range: [{lo:,}, {hi:,})  size={hi - lo:,}")
    out_path = None
    if mode == "print":
        out_path = print_path(portal_folder, base_exponent, lo, hi)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        print(f"[*] Text output (the program's format, not Atlas storage): {out_path}")
    returncode, wall, out = native_tool_run.run_timed(cmd, out_path)
    if returncode != 0:
        print(f"[!] pseudosquares_prime_sieve exited with code {returncode}; no row logged")
        if out:
            print(out.decode("utf-8", "replace")[-2000:])
        sys.exit(returncode or 1)
    if mode == "count":
        report = parse_count_report(out.decode("utf-8", "replace"))
        primes, used_threads, bytes_written = report["primes"], report["threads"], None
        print(f"[*] The program's own time: {report['seconds']} s, threads: {used_threads}")
    else:
        primes, used_threads = native_tool_run.count_lines(out_path), const.PRINT_THREADS
        bytes_written = os.path.getsize(out_path)
        print(f"[*] {bytes_written:,} bytes of text, threads: {used_threads} (--print)")
    print(f"[BENCHMARK] {primes:,} primes, wall {wall:.3f} s, "
          f"{(hi - lo) / wall / 1e6:,.1f} M numbers/s")
    row = benchmark_row(mode, base_exponent, target_idx_start, target_idx_count, window_m,
                        wall, primes, used_threads, version, bytes_written,
                        native_tool_run.child_rss_mb())
    native_tool_run.append_row(portal_folder, row)
    return row


if __name__ == "__main__":
    if len(sys.argv) not in (6, 7) or sys.argv[5] not in MODES:
        sys.exit(__doc__)
    portal = os.environ.get("CONSTELLATION_PORTAL_DIR") or "/mnt/c/CONSTELLATION_PORTAL"
    run(sys.argv[5], int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]),
        portal, threads=int(sys.argv[6]) if len(sys.argv) == 7 else 0)
