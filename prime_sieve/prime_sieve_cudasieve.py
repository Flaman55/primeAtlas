import bisect
import csv
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time

import window_sharding

VERSION = "v0.1"

# ==========================================================================================
# prime_sieve_cudasieve.py -- "cudasieve mode" (GPU engine, `cudasieve` branch only)
#
# Forked alongside prime_atlas_v2.py/orchestrator_v4.py/settings_tab_v2.py on the
# `cudasieve` branch -- see those files' own header notes. This module does NOT exist on
# main; it is new, not a version bump of any production file.
#
# Modeled on prime_sieve_primesieve.py (SAME folder): like that file, this mode bypasses
# this project's own batched engine/orchestrator machinery entirely and calls a fast,
# purpose-built external sieve directly, then maps its result onto this project's own
# PGS2 on-disk format -- a window written by this mode is byte-for-byte interchangeable
# with one written by any other engine in this folder.
#
# UNLIKE prime_sieve_primesieve.py, this file does NOT link or ctypes-bind a library.
# It shells out to the SEPARATE, already-installed `cudasieve` command-line executable
# as its own OS subprocess and parses its stdout -- see "PROCESS BOUNDARY, NOT LINKING"
# below for why that distinction matters here specifically.
#
# ATTRIBUTION: this file drives CUDASieve, an independent, third-party, GPU-accelerated
# sieve of Eratosthenes by Curtis Seizert -- NOT authored by, or part of, this project.
#   Source:  https://github.com/curtisseizert/CUDASieve
#   License: GNU GPLv3 (see that repository's own `License` file for the exact text)
#
# PROCESS BOUNDARY, NOT LINKING (why this matters for licensing):
#   CUDASieve is GPLv3. This project (PrimeAtlas) is not. Statically or dynamically
#   LINKING CUDASieve's library (libcudasieve.a) into this project's own process would
#   create a single combined binary containing GPL code, which would require the whole
#   combined work to be conveyed under GPL-compatible terms. This file deliberately
#   avoids that: it never links libcudasieve.a, never vendors CUDASieve source into this
#   repository, and only invokes the separately-built, separately-distributed `cudasieve`
#   CLI executable as an independent OS process (subprocess.run), communicating over
#   plain stdout -- the same "mere aggregation via exec" boundary FSF's own GPL FAQ
#   describes as NOT creating a derivative/combined work. PrimeAtlas's own source stays
#   under its own license regardless of whether the user has CUDASieve installed.
#   The user builds/installs `cudasieve` themselves (see settings_tab_v2.py's installer,
#   which fetches it from CUDASieve's own GitHub repo -- never a vendored copy -- and
#   shows its License text for the user to accept before first use, exactly like this
#   project's existing sympy installer shows nothing since sympy is MIT, but unlike that
#   one, this installer's consent step is NOT optional).
#
# KNOWN LIMITATION -- CUDASieve's own CLI documents that its `-p`/`--print` flag "will be
# ignored below 2**40" (see that project's `host::help()`, src/main.cpp) -- i.e. its own
# authors chose not to support printing an actual prime LIST below roughly 1.0995e12.
# This project's floors start at 10**0 and this mode is only useful once it can list
# individual primes, not just a count -- so MIN_PRINTABLE_TOP below refuses anything
# under that documented ceiling with a clear error pointing at primesieve/CPU mode
# instead, rather than silently returning an empty or wrong result.
#   VERIFIED on real hardware (RTX 5070 + WSL2, 2026-08-27, see
#   verify_cudasieve_hardware.py in this same folder): the exact boundary behavior AT
#   2**40, the stdout line format `-p -s` produces, and the documented ~1-in-20000
#   count-off-by-one risk under concurrent GPU load (CUDASieve's own README,
#   "Correctness" section) were all checked against primesieve's own output for
#   [2**40, 2**40+10**6) and a second, unrelated sample at 10**13+10**6 -- exact set
#   match (not just count) on both ranges, zero dropped stdout lines. Re-run
#   verify_cudasieve_hardware.py after any future change to this file's stdout parsing.
# ==========================================================================================


MIN_PRINTABLE_TOP = 2 ** 40  # See "KNOWN LIMITATION" above -- CUDASieve's own -p/--print
                             # flag is documented as ignored below this value.


# ------------------------------------------------------------------------------------------
# PGS2 output format + low-floor splitting -- duplicated verbatim from prime_sieve_v3.py /
# prime_sieve_primesieve.py. Every scanner file in this folder is kept independently
# runnable (no cross-imports between engine files) -- this file follows that same
# established convention.
# ------------------------------------------------------------------------------------------

PGS_MAGIC = b"PGS2"


def encode_varint(value):
    """LEB128 unsigned varint: 7 data bits per byte, MSB = continuation flag. Duplicated
    verbatim from prime_sieve_v3.py / prime_sieve_primesieve.py."""
    if value < 0:
        raise ValueError("encode_varint requires a non-negative value")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def write_prime_window(path, primes, generated_at=None):
    """Writes a sorted list of primes (ints, ascending) to `path` in PGS2 format.
    Duplicated verbatim from prime_sieve_v3.py / prime_sieve_primesieve.py."""
    if generated_at is None:
        generated_at = int(time.time())
    count = len(primes)
    with open(path, "wb") as f:
        f.write(PGS_MAGIC)
        if count == 0:
            f.write(bytes([0]))
            f.write((0).to_bytes(4, "big"))
            f.write(int(generated_at).to_bytes(4, "big"))
            return
        base = primes[0]
        base_bytes = base.to_bytes(max(1, (base.bit_length() + 7) // 8), "big")
        if len(base_bytes) > 255:
            raise ValueError(f"base prime too large for 1-byte length prefix: {base}")
        f.write(bytes([len(base_bytes)]))
        f.write(base_bytes)
        f.write(count.to_bytes(4, "big"))
        f.write(int(generated_at).to_bytes(4, "big"))
        prev = base
        for p in primes[1:]:
            f.write(encode_varint(p - prev))
            prev = p


def format_offset(n):
    """Duplicated verbatim from prime_sieve_v3.py / prime_sieve_primesieve.py."""
    if n == 0:
        return "0"
    if n % 1_000_000 == 0:
        return f"{n // 1_000_000}M"
    if n % 1_000 == 0:
        return f"{n // 1_000}k"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.6f}M".rstrip('0').rstrip('.')
    if n >= 1_000:
        return f"{n / 1_000:.3f}k".rstrip('0').rstrip('.')
    return str(n)


SCAN_METRICS_FILENAME = "last_scan_metrics.json"


def write_scan_metrics_handoff(portal_folder, total_primes_found=None, windows_processed=None,
                                write_files=None):
    """Duplicated from prime_sieve_primesieve.py -- see that file's own docstring for why
    l_final/sieving_primes_count are omitted (this engine has no equivalent diagnostic
    either -- CUDASieve's own sieving-primes count is not exposed by its CLI output in a
    form this module parses)."""
    path = os.path.join(portal_folder, SCAN_METRICS_FILENAME)
    data = {}
    if total_primes_found is not None:
        data["total_primes_found"] = total_primes_found
    if windows_processed is not None:
        data["windows_processed"] = windows_processed
    if write_files is not None:
        data["write_files"] = write_files
    try:
        os.makedirs(portal_folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError as e:
        print(f"[!] WARNING: could not write scan metrics handoff ({e})")


LOW_FLOOR_CUTOFF = 7  # Duplicated from prime_sieve_v3.py -- floors 0-6 are each narrower
                      # than the smallest supported window_m, 10,000,000. Moot in practice
                      # for this engine (MIN_PRINTABLE_TOP already excludes floors this
                      # low), kept only so this function's signature/behavior stays
                      # identical to every other engine file's copy.


def _low_floor_segments(base_power, combined_lo, combined_hi):
    """Duplicated verbatim from prime_sieve_v3.py / prime_sieve_primesieve.py."""
    if base_power >= LOW_FLOOR_CUTOFF or combined_lo != 10 ** base_power:
        return []
    segments = []
    floor = base_power
    while True:
        floor_lo = 10 ** floor
        floor_hi = 10 ** (floor + 1)
        if floor_hi > combined_hi:
            break
        segments.append((floor, floor_lo, floor_hi))
        floor += 1
    return segments


# ------------------------------------------------------------------------------------------
# benchmark_log.csv logging -- schema/writer duplicated from orchestrator_v3.py /
# prime_sieve_primesieve.py's own copy. See that file's header comment for the full
# rationale (every engine writes to the SAME log so the Benchmark tab sees one unified
# history regardless of which engine produced which floor).
# ------------------------------------------------------------------------------------------

BENCHMARK_FIELDNAMES = [
    "run_timestamp_utc", "base_exponent", "target_idx_start", "target_idx_end",
    "windows_written", "total_seconds", "seconds_per_window", "total_primes",
    "avg_primes_per_window", "primes_per_second", "l_final", "sieving_primes_count",
    "max_child_rss_mb", "instance_of_n", "loop_session_seconds", "loop_numbers_per_second",
    "loop_seconds_per_window", "write_files", "base_gen_seconds", "sieve_seconds",
    "write_seconds", "bytes_written", "engine", "numbers_processed",
]


def _ensure_benchmark_log_schema(log_path):
    """Duplicated verbatim from orchestrator_v3.py / prime_sieve_primesieve.py."""
    if not os.path.exists(log_path):
        return
    with open(log_path, newline="") as f:
        reader = csv.DictReader(f)
        existing_fields = reader.fieldnames or []
        rows = list(reader)
    if existing_fields == BENCHMARK_FIELDNAMES:
        return
    if not all(field in BENCHMARK_FIELDNAMES for field in existing_fields):
        return
    tmp_path = f"{log_path}.tmp{os.getpid()}"
    with open(tmp_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in BENCHMARK_FIELDNAMES})
    os.replace(tmp_path, log_path)


def _append_floor_meta_row(portal_folder, base_exponent, row):
    """Duplicated (self-contained, no cross-import) from prime_sieve_primesieve.py -- see
    that file's own docstring for the full rationale."""
    key_fields = ("run_timestamp_utc", "base_exponent", "target_idx_start", "target_idx_end")

    def _key(r):
        return tuple(str(r.get(k, "")) for k in key_fields)

    floor_dir = os.path.join(portal_folder, f"10p{base_exponent}")
    path = os.path.join(floor_dir, "floor_meta.json")
    try:
        rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                rows = list(data.get("benchmark_rows", []))
        if _key(row) in {_key(r) for r in rows}:
            return
        rows.append(dict(row))
        os.makedirs(floor_dir, exist_ok=True)
        tmp_path = f"{path}.tmp{os.getpid()}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"base_exponent": base_exponent, "benchmark_rows": rows}, f,
                      indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        pass


def write_benchmark_row(base_exponent, target_idx_start, target_idx_count, total_seconds,
                         total_primes, windows_written, write_files, portal_folder):
    """Duplicated from prime_sieve_primesieve.py -- see that file's own docstring. Same
    blank-column set (l_final/sieving_primes_count/max_child_rss_mb/instance_of_n/loop_*)
    for the same reason: this engine's own diagnostics don't expose those either."""
    if windows_written <= 0:
        return
    target_idx_end = target_idx_start + target_idx_count - 1
    seconds_per_window = total_seconds / windows_written if windows_written else float("nan")
    primes_per_second = total_primes / total_seconds if total_seconds > 0 else float("nan")
    avg_primes_per_window = total_primes / windows_written if windows_written else float("nan")

    log_path = os.path.join(portal_folder, "benchmark_log.csv")
    try:
        os.makedirs(portal_folder, exist_ok=True)
        _ensure_benchmark_log_schema(log_path)
        is_new = not os.path.exists(log_path)
        with open(log_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES)
            if is_new:
                writer.writeheader()
            row = {
                "engine": "cuda",
                "run_timestamp_utc": datetime.datetime.now(datetime.timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S UTC"),
                "base_exponent": base_exponent,
                "target_idx_start": target_idx_start,
                "target_idx_end": target_idx_end,
                "windows_written": windows_written,
                "total_seconds": f"{total_seconds:.3f}",
                "seconds_per_window": f"{seconds_per_window:.4f}",
                "total_primes": total_primes,
                "avg_primes_per_window": f"{avg_primes_per_window:.1f}",
                "primes_per_second": f"{primes_per_second:.2f}",
                "l_final": "",
                "sieving_primes_count": "",
                "max_child_rss_mb": "",
                "instance_of_n": "",
                "loop_session_seconds": "",
                "loop_numbers_per_second": "",
                "loop_seconds_per_window": "",
                "write_files": "1" if write_files else "0",
            }
            writer.writerow(row)
        print(f"[BENCHMARK] logged to {log_path} (for cross-floor growth analysis)")
        _append_floor_meta_row(portal_folder, base_exponent, row)
    except OSError as e:
        print(f"[BENCHMARK] WARNING: could not write benchmark log ({e})")


# ------------------------------------------------------------------------------------------
# CUDASieve CLI subprocess wrapper -- deliberately NOT ctypes/library binding (see module
# header, "PROCESS BOUNDARY, NOT LINKING"). Everything below shells out to a separately
# installed `cudasieve` executable and parses plain stdout text.
# ------------------------------------------------------------------------------------------

_PRIME_LINE_RE = re.compile(r"^\d+$")

CUDASIEVE_REPO_URL = "https://github.com/curtisseizert/CUDASieve"


def default_install_dir():
    """Where the installer (settings_tab_v2.py, via the --fetch-license/--build CLI modes
    below) clones and builds CUDASieve: a dotfolder under the WSL user's own home
    directory -- deliberately OUTSIDE this git repository (never vendored -- see module
    header) and OUTSIDE CONSTELLATION_PORTAL_DIR (that is data storage, this is a
    third-party tool's own build tree, a different kind of thing entirely)."""
    return os.path.expanduser("~/.primeatlas/cudasieve")


def find_cudasieve_binary():
    """Locates the external `cudasieve` executable: CUDASIEVE_BIN env var first (same as
    this project's own CONSTELLATION_PORTAL_DIR override convention -- an explicit path
    always wins over autodetection), then a plain PATH lookup, then the installer's own
    default_install_dir() (a binary just built there won't be on PATH unless the user
    added it themselves). Returns None, never raises, if it cannot be found -- callers
    decide whether that is fatal (see require_cudasieve_binary())."""
    override = os.environ.get("CUDASIEVE_BIN")
    if override and os.path.isfile(override) and os.access(override, os.X_OK):
        return override
    found = shutil.which("cudasieve")
    if found:
        return found
    default_path = os.path.join(default_install_dir(), "cudasieve")
    if os.path.isfile(default_path) and os.access(default_path, os.X_OK):
        return default_path
    return None


def require_cudasieve_binary():
    """Same as find_cudasieve_binary() but raises a clear, actionable RuntimeError instead
    of returning None -- the one call site every generation entry point below should use,
    so a missing install fails with a message pointing at settings_tab_v2.py's installer
    rather than a bare FileNotFoundError from subprocess."""
    path = find_cudasieve_binary()
    if not path:
        raise RuntimeError(
            "cudasieve executable not found (checked $CUDASIEVE_BIN and $PATH). Install "
            "it first via Settings > Aktualizacje (this branch's CUDASieve installer, "
            "which builds it from https://github.com/curtisseizert/CUDASieve -- GPLv3, "
            "Curtis Seizert -- and requires an Nvidia GPU + the CUDA Toolkit's nvcc). "
            "This project never vendors or links that code -- see this file's own module "
            "header for why.")
    return path


def is_cudasieve_available():
    """Non-raising availability probe for the Settings tab / Quick-gen UI (analogous to
    primeatlas.primality.try_import_sympy() -- callers use this to decide whether to show
    the GPU engine as selectable at all, not to actually run a sieve)."""
    return find_cudasieve_binary() is not None


def generate_primes_in_range(lo, hi, gpu_index=None):
    """Returns a sorted Python list of every prime in the EXCLUSIVE range [lo, hi) (this
    project's own convention) by invoking `cudasieve -b lo -t hi-1 -p -s` as a subprocess
    and parsing its stdout, one prime per line (see module header's KNOWN LIMITATION for
    why hi-1 must be >= MIN_PRINTABLE_TOP).

    -s (silent) suppresses CUDASieve's own progress/diagnostic lines so stdout is (as
    close as its CLI allows to) prime-list-only; -p asks it to print each prime it finds.
    Every non-blank stdout line that is NOT a bare run of digits is treated as diagnostic
    noise that slipped through -s rather than a parse error, and is dropped with a
    printed warning -- VERIFIED on real hardware (RTX 5070 + WSL2, 2026-08-27,
    verify_cudasieve_hardware.py): -s does suppress everything else CUDASieve prints in
    -p mode -- zero dropped-line warnings across both real-hardware test ranges."""
    if hi <= lo:
        return []
    if hi - 1 < MIN_PRINTABLE_TOP:
        raise RuntimeError(
            f"cudasieve mode cannot list individual primes below its own documented "
            f"printable floor (2**40 = {MIN_PRINTABLE_TOP:,}); requested range was "
            f"[{lo:,}, {hi:,}). Use primesieve or Floor/Range/Exploration mode (CPU) for "
            f"floors this low instead -- see this file's module header, KNOWN LIMITATION.")
    binary = require_cudasieve_binary()
    argv = [binary, "-b", str(lo), "-t", str(hi - 1), "-p", "-s"]
    if gpu_index is not None:
        argv += ["-g", str(gpu_index)]
    proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"cudasieve exited with code {proc.returncode} for range [{lo:,}, {hi:,}). "
            f"stderr: {proc.stderr.strip()[:2000]}")
    primes = []
    dropped_lines = 0
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if _PRIME_LINE_RE.match(line):
            primes.append(int(line))
        else:
            dropped_lines += 1
    if dropped_lines:
        print(f"[!] cudasieve mode: dropped {dropped_lines} non-numeric stdout line(s) "
              f"(diagnostic output that slipped through -s -- see module header TODO).")
    # Defensive sanity check: CUDASieve's own README documents a ~1-in-20000 chance of an
    # off-by-one count under concurrent GPU load (its "Correctness" section) -- this can't
    # detect that specific failure mode, but it DOES catch a badly-parsed or truncated
    # output stream, which would otherwise silently write a wrong/incomplete window.
    if primes and any(b <= a for a, b in zip(primes, primes[1:])):
        raise RuntimeError(
            f"cudasieve output for [{lo:,}, {hi:,}) was not strictly increasing after "
            f"parsing -- likely a stdout parsing mismatch, not a real prime list. Refusing "
            f"to write a window from it.")
    return primes


def generate_floor_windows(base_power, target_idx_start, target_idx_count, window_m,
                            write_files=True, portal_folder=None, gpu_index=None):
    """GPU-engine equivalent of prime_sieve_primesieve.py's generate_floor_windows() --
    same combined-range computation, same PGS2 write-tail, same low-floor splitting hook
    (kept for signature parity with every other engine even though MIN_PRINTABLE_TOP
    already excludes the floors _low_floor_segments() would ever fire on), same
    benchmark_log.csv / floor_meta.json / last_scan_metrics.json bookkeeping, same
    window_sharding.py shard_NNNNN layout (task #405, ported in here since it landed
    after this file originally forked) -- a floor generated through this mode is
    indistinguishable on disk from one generated by any
    other engine in this folder. See generate_primes_in_range() for the one real
    difference (a subprocess call instead of a ctypes call or this project's own batched
    engine)."""
    BASE = 10 ** base_power
    combined_lo = BASE + target_idx_start * window_m
    combined_hi = combined_lo + target_idx_count * window_m

    print("=" * 70)
    print(f"[*] PRIME SIEVE -- {VERSION} (cudasieve mode: shells out to the external "
          f"`cudasieve` CLI -- see this file's header for attribution/source: "
          f"github.com/curtisseizert/CUDASieve, GPLv3, not linked into this process)")
    print(f"[*] Combined range: [{combined_lo:,}, {combined_hi:,})  "
          f"size={max(0, combined_hi - combined_lo):,}")
    if not write_files:
        print(f"[*] WRITE_FILES=False -- no PGS2 files will be written this run; only the "
              f"aggregate prime count will be reported.")
    print("=" * 70)

    if combined_hi <= combined_lo:
        print("[*] Nothing to generate (empty range).")
        write_scan_metrics_handoff(portal_folder, total_primes_found=0, windows_processed=0,
                                    write_files=write_files)
        print("=" * 70)
        return

    t_start = time.perf_counter()
    primes = generate_primes_in_range(combined_lo, combined_hi, gpu_index=gpu_index)
    t_gen = time.perf_counter() - t_start
    print(f"[*] cudasieve generated {len(primes):,} primes in {t_gen:.2f}s.")

    generated_at = int(time.time())
    total_primes_found = 0
    windows_processed = 0

    low_floor_segments = _low_floor_segments(base_power, combined_lo, combined_hi)
    if low_floor_segments:
        for floor, floor_lo, floor_hi in low_floor_segments:
            lo_i = bisect.bisect_left(primes, floor_lo)
            hi_i = bisect.bisect_left(primes, floor_hi)
            segment = primes[lo_i:hi_i]
            count = len(segment)
            if write_files:
                # Sharded (see window_sharding.py, task #405) -- a low floor always
                # writes its one window at offset 0, so it always lands in
                # shard_00000.
                folder = os.path.join(portal_folder, f"10p{floor}", "source_primes")
                shard_folder = window_sharding.shard_dir(folder, 0)
                os.makedirs(shard_folder, exist_ok=True)
                path = os.path.join(shard_folder, f"PRIME_WINDOW_10p{floor}_off_0.bin")
                write_prime_window(path, segment, generated_at=generated_at)
            total_primes_found += count
            windows_processed += 1
            print(f"    10p{floor}: {count:,} primes")
        skipped_floor = low_floor_segments[-1][0] + 1
        print(f"[*] Low-floor batch: floor(s) {low_floor_segments[0][0]}-"
              f"{low_floor_segments[-1][0]} written complete -- floor {skipped_floor} "
              f"skipped (not written partially).")
    else:
        # Sharded (see window_sharding.py, task #405): no single directory ever holds
        # more than SHARD_SIZE window files, regardless of floor size -- floor_folder
        # itself is therefore never created/listed directly, only its shard_NNNNN
        # subfolders are.
        floor_folder = os.path.join(portal_folder, f"10p{base_power}", "source_primes")
        window_lo = combined_lo
        while window_lo < combined_hi:
            window_hi = min(window_lo + window_m, combined_hi)
            lo_i = bisect.bisect_left(primes, window_lo)
            hi_i = bisect.bisect_left(primes, window_hi)
            segment = primes[lo_i:hi_i]
            if write_files:
                offset = window_lo - BASE
                target_tag = f"10p{base_power}_off_{format_offset(offset)}"
                window_index = window_sharding.shard_index_for_offset(offset, window_m)
                shard_folder = window_sharding.shard_dir(floor_folder, window_index)
                os.makedirs(shard_folder, exist_ok=True)
                path = os.path.join(shard_folder, f"PRIME_WINDOW_{target_tag}.bin")
                write_prime_window(path, segment, generated_at=generated_at)
            total_primes_found += len(segment)
            windows_processed += 1
            window_lo = window_hi

    print(f"\n[*] TOTAL PRIMES FOUND this run: {total_primes_found:,} across "
          f"{windows_processed} window(s)"
          + ("" if write_files else "  (NO FILES WRITTEN -- count-only mode)"))
    write_scan_metrics_handoff(portal_folder, total_primes_found=total_primes_found,
                                windows_processed=windows_processed, write_files=write_files)
    write_benchmark_row(base_power, target_idx_start, target_idx_count, t_gen,
                         total_primes_found, windows_processed, write_files, portal_folder)
    print("=" * 70)


# ------------------------------------------------------------------------------------------
# Installer CLI modes -- --status / --fetch-license / --build -- called from
# settings_tab_v2.py (Aktualizacje tab) via a WSL subprocess, same as this file's own
# floor-generation CLI below. Kept in THIS file (not split into the Windows-side GUI code)
# so all CUDASieve-specific logic -- including the git clone / make invocation -- lives in
# exactly one place, consistent with this folder's "every engine file stays independently
# runnable" convention (see module header). Deliberately three separate steps, not one
# "--install" that does everything, so the GUI can show the ACTUAL License text (read back
# from the just-cloned repo, not a copy embedded in this project) and get the user's
# explicit consent BEFORE the longer `make` build step ever runs -- see settings_tab_v2.py's
# own installer section for that consent-gate flow.
#
# PARTIALLY VERIFIED on real hardware (RTX 5070 + WSL2): _detect_cuda_dir()/
# _detect_gpu_arch()/_ensure_rdc_flag() each encode a specific failure fixed by hand on
# that machine on 2026-08-23 (see each function's own docstring for the exact error each
# one addresses) -- that manual run is what this automated cmd_build() reproduces. What
# has NOT yet been exercised is cmd_build() itself, as automated code, against a
# completely fresh clone (run_cudasieve_hardware_check.sh, 2026-08-27, found a binary
# already built from that manual run and skipped straight to verification -- see that
# script's own step [1/5]/[2/5]). To close this out for real: `rm -rf
# ~/.primeatlas/cudasieve` then re-run run_cudasieve_hardware_check.sh so steps 2-3
# (clone + build) actually execute.
# ------------------------------------------------------------------------------------------

def cmd_status(install_dir):
    """Prints one JSON line describing whether the pieces this mode needs are present --
    an Nvidia driver (nvidia-smi), the CUDA compiler (nvcc), a cloned repo, and a built,
    executable binary -- so the Settings tab can show a precise status instead of a bare
    yes/no. Mirrors primesieve_query.py's one-JSON-line-on-stdout contract (the blocking
    WSL call pattern prime_atlas_v2.py's run_primesieve_query_wsl() already uses)."""
    binary_path = os.path.join(install_dir, "cudasieve")
    binary_ok = os.path.isfile(binary_path) and os.access(binary_path, os.X_OK)
    result = {
        "ok": True,
        "has_nvidia_smi": shutil.which("nvidia-smi") is not None,
        "has_nvcc": shutil.which("nvcc") is not None,
        "cloned": os.path.isdir(os.path.join(install_dir, ".git")),
        "binary_exists": binary_ok,
        "binary_path": binary_path if binary_ok else None,
        "install_dir": install_dir,
    }
    print(json.dumps(result))


def cmd_fetch_license(install_dir):
    """Clones CUDASieve (or fast-forwards an existing clone) into install_dir, then prints
    the ACTUAL, current text of its own `License` file as one JSON line -- this is what
    settings_tab_v2.py shows the user for consent before --build ever runs, precisely so
    the consent step reflects the real file in the real repository, not a string this
    project would otherwise have to keep in sync by hand. Cloning source code onto disk is
    not itself a use requiring prior consent (equivalent to `git clone` of any public repo)
    -- see module header, "PROCESS BOUNDARY, NOT LINKING" -- the consent gate belongs at
    "before build/before this becomes a usable engine", which is exactly where
    settings_tab_v2.py places it."""
    try:
        os.makedirs(os.path.dirname(install_dir), exist_ok=True)
        if not os.path.isdir(os.path.join(install_dir, ".git")):
            proc = subprocess.run(
                ["git", "clone", "--depth", "1", CUDASIEVE_REPO_URL, install_dir],
                capture_output=True, text=True, timeout=120)
            if proc.returncode != 0:
                print(json.dumps({
                    "ok": False,
                    "error": f"git clone failed: {proc.stderr.strip()[:2000]}"}))
                return
        else:
            subprocess.run(["git", "-C", install_dir, "fetch", "--depth", "1", "origin"],
                            capture_output=True, text=True, timeout=60)
            subprocess.run(["git", "-C", install_dir, "reset", "--hard", "origin/master"],
                            capture_output=True, text=True, timeout=30)
        license_path = os.path.join(install_dir, "License")
        if not os.path.isfile(license_path):
            print(json.dumps({
                "ok": False,
                "error": f"License file not found at {license_path} after clone"}))
            return
        with open(license_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        print(json.dumps({"ok": True, "license_text": text, "install_dir": install_dir}))
    except Exception as e:  # noqa: BLE001 -- must always emit a JSON line, never a
                            # traceback the GUI's blocking-call JSON parser can't read
        print(json.dumps({"ok": False, "error": str(e)}))


def _detect_cuda_dir():
    """Locates the CUDA Toolkit's install root. CUDA_DIR env var wins if set (same override
    convention as every other path-guessing in this project). Otherwise asks `nvcc` itself
    where it lives (nvcc is at <CUDA_DIR>/bin/nvcc) rather than guessing blind, then falls
    back to the handful of locations NVIDIA's own installers actually use. Confirmed on real
    hardware (2026-08-23) that CUDA_DIR must be passed on the `make` command line, NOT as an
    environment variable -- CUDASieve's own makefile has a plain `CUDA_DIR = /opt/cuda`
    assignment, which (per GNU Make's variable-precedence rules) overrides any exported
    environment variable of the same name but is itself overridden by a command-line
    `make CUDA_DIR=...` argument. See cmd_build() below for where this return value is used."""
    override = os.environ.get("CUDA_DIR")
    if override and os.path.isdir(override):
        return override
    nvcc_path = shutil.which("nvcc")
    if nvcc_path:
        candidate = os.path.dirname(os.path.dirname(os.path.realpath(nvcc_path)))
        if os.path.isdir(os.path.join(candidate, "include")):
            return candidate
    for candidate in ("/usr/local/cuda", "/usr/lib/cuda", "/opt/cuda"):
        if os.path.isdir(os.path.join(candidate, "include")):
            return candidate
    return "/usr/local/cuda"  # last-resort guess (same default this project always used) --
                              # `make` fails with its own clear error if this is wrong, same
                              # as before this function existed


def _detect_gpu_arch():
    """Asks nvidia-smi for THIS machine's own GPU compute capability (e.g. "12.0" for
    Blackwell/RTX 50-series) instead of trusting CUDASieve's own makefile default
    (GPU_ARCH=compute_52/GPU_CODE=sm_52,..., hardcoded for Maxwell-era cards circa 2014).
    Confirmed on real hardware (RTX 5070, 2026-08-23) that the hardcoded default fails
    outright on a modern GPU + modern nvcc: "nvcc fatal : Value 'sm_52' is not defined for
    option 'gpu-code'". Returns (gpu_arch, gpu_code) as the two `make`-command-line values
    CUDASieve's makefile expects, or (None, None) if detection isn't possible (caller then
    falls back to CUDASieve's own makefile default and warns, rather than blocking outright
    -- an older GPU might still legitimately need that old default).

    Multi-GPU machines: takes the FIRST device nvidia-smi reports. This project has no
    concept yet of "build for which GPU" beyond generate_primes_in_range()'s own -g/gpu_index
    RUNTIME passthrough -- building for the first device's architecture matches CUDASieve's
    own default GPU-0 assumption."""
    if not shutil.which("nvidia-smi"):
        return None, None
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15, check=False)
    except OSError:
        return None, None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None, None
    first_line = proc.stdout.strip().splitlines()[0].strip()
    match = re.match(r"^(\d+)\.(\d+)$", first_line)
    if not match:
        return None, None
    arch_digits = f"{match.group(1)}{match.group(2)}"
    return f"compute_{arch_digits}", f"sm_{arch_digits}"


_RDC_FLAG = "-rdc=true"
_NVCC_FLAGS_RE = re.compile(r"NVCC_FLAGS\s*=(?:[^\n]*\\\n)*[^\n]*")


def _ensure_rdc_flag(install_dir):
    """Patches CUDASieve's own makefile to add -rdc=true to NVCC_FLAGS. Confirmed necessary
    on real hardware (2026-08-23): modern nvcc (13.x) refuses to link a __global__ function
    template instantiated in one translation unit and called from another under CUDASieve's
    default whole-program compilation mode (link fails with "undefined reference to
    device::makePrimeList_PLout<...>"); -rdc=true (separable compilation) fixes it. Idempotent
    -- checks for the flag before adding it, so repeated --build calls never append it twice.
    Best-effort: if the makefile's NVCC_FLAGS assignment doesn't match the expected shape,
    leaves the file untouched and lets `make` fail with its own error, rather than risk
    corrupting a third-party file this project doesn't own or vendor (see module header,
    "PROCESS BOUNDARY, NOT LINKING")."""
    makefile_path = os.path.join(install_dir, "makefile")
    if not os.path.isfile(makefile_path):
        return
    with open(makefile_path, encoding="utf-8") as f:
        text = f.read()
    if _RDC_FLAG in text:
        return
    match = _NVCC_FLAGS_RE.search(text)
    if not match:
        print("[!] WARNING: could not find NVCC_FLAGS in makefile to patch in -rdc=true -- "
              "if the build fails with 'undefined reference to device::...', add -rdc=true "
              "to NVCC_FLAGS by hand and re-run --build.")
        return
    new_text = text[:match.start()] + match.group(0) + f" {_RDC_FLAG}" + text[match.end():]
    with open(makefile_path, "w", encoding="utf-8") as f:
        f.write(new_text)
    print("[*] Patched makefile: added -rdc=true to NVCC_FLAGS (required for modern nvcc "
          "template linking -- see _ensure_rdc_flag() docstring in this file).")


def _clean_stale_build_artifacts(install_dir, obj_dir):
    """Removes previously-built .o files, the static lib, and the binary before every build.
    Needed because _ensure_rdc_flag() can change NVCC_FLAGS between runs (e.g. the very first
    --build after this function was added) -- object files compiled under the OLD flags
    linked against ones compiled under the NEW flags is exactly the failure mode hit manually
    on real hardware (2026-08-23) before this cleanup step existed. Cheap (a handful of
    files), so it always runs rather than trying to detect whether flags actually changed."""
    for stale_name in ("libcudasieve.a", "cudasieve"):
        stale_path = os.path.join(install_dir, stale_name)
        if os.path.isfile(stale_path):
            os.remove(stale_path)
    if os.path.isdir(obj_dir):
        for name in os.listdir(obj_dir):
            if name.endswith(".o"):
                os.remove(os.path.join(obj_dir, name))


def cmd_build(install_dir):
    """Runs `make` in an ALREADY-CLONED install_dir (see cmd_fetch_license above -- this
    function does not clone) -- plain text progress on stdout, meant to be tailed live by
    WslLoggedRunner (prime_atlas_v2.py) the same way any other long-running Generation-tab
    job is, not captured as one blocking call like --status/--fetch-license.

    Every step below (obj/ directory, CUDA_DIR, GPU_ARCH/GPU_CODE, -rdc=true) mirrors a real
    failure hit and fixed manually, one at a time, on an actual RTX 5070 + WSL2 machine on
    2026-08-23 -- see this function's helpers' own docstrings for the specific error each one
    fixes. Different GPUs will detect different GPU_ARCH/GPU_CODE values; CUDA_DIR is
    autodetected rather than hardcoded so this isn't tied to one machine's install layout."""
    print(f"[*] Building CUDASieve in {install_dir} ...")
    if not os.path.isdir(install_dir):
        print("[!] ERROR: install_dir does not exist -- run --fetch-license first (it "
              "clones the repo); nothing to build here yet.")
        sys.exit(1)

    obj_dir = os.path.join(install_dir, "obj")
    os.makedirs(obj_dir, exist_ok=True)  # git doesn't track empty directories -- a fresh
                                          # clone is missing this, and `make` fails with
                                          # "can't create obj/main.o: No such file or
                                          # directory" otherwise

    _ensure_rdc_flag(install_dir)
    _clean_stale_build_artifacts(install_dir, obj_dir)

    cuda_dir = _detect_cuda_dir()
    gpu_arch, gpu_code = _detect_gpu_arch()

    make_args = ["make", f"CUDA_DIR={cuda_dir}"]
    print(f"[*] CUDA_DIR={cuda_dir}")
    if gpu_arch:
        make_args += [f"GPU_ARCH={gpu_arch}", f"GPU_CODE={gpu_code}"]
        print(f"[*] Detected GPU compute capability -> GPU_ARCH={gpu_arch} "
              f"GPU_CODE={gpu_code}")
    else:
        print("[!] WARNING: could not detect GPU compute capability via nvidia-smi -- "
              "building with CUDASieve's own makefile default (compute_52/sm_52,... , "
              "Maxwell-era, ~2014). This will fail on most GPUs newer than ~2016 ('Value "
              "\"sm_52\" is not defined for option \"gpu-code\"'). Make sure the Nvidia "
              "driver is installed (nvidia-smi should work) and re-run --build.")

    proc = subprocess.run(make_args, cwd=install_dir)
    if proc.returncode != 0:
        print(f"[!] make failed (exit {proc.returncode}) with: {' '.join(make_args)}\n"
              f"    If this is a GPU-architecture error, the detected value "
              f"(GPU_ARCH={gpu_arch}) may not match your actual card -- open "
              f"{install_dir}/makefile and check CUDA_DIR/GPU_ARCH/GPU_CODE by hand against "
              f"CUDASieve's own README, then re-run --build.")
        sys.exit(proc.returncode)
    binary_path = os.path.join(install_dir, "cudasieve")
    if os.path.isfile(binary_path):
        try:
            os.chmod(binary_path, 0o755)
        except OSError:
            pass
        print(f"[*] Build finished: {binary_path}")
        print(f"[*] find_cudasieve_binary() in this file already checks this exact "
              f"location as a fallback -- no PATH/CUDASIEVE_BIN change needed unless you "
              f"want one.")
    else:
        print(f"[!] make reported success but {binary_path} was not produced -- check "
              f"{install_dir}/makefile's own binary output name/location.")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--status", "--fetch-license", "--build"):
        _mode = sys.argv[1]
        _install_dir = sys.argv[2] if len(sys.argv) > 2 else default_install_dir()
        if _mode == "--status":
            cmd_status(_install_dir)
        elif _mode == "--fetch-license":
            cmd_fetch_license(_install_dir)
        elif _mode == "--build":
            cmd_build(_install_dir)
        sys.exit(0)

    print("=" * 70)
    print(f"[*] PRIME SIEVE -- CUDASIEVE MODE (GPU) -- {VERSION}")
    print("    Shells out to the external `cudasieve` CLI -- see this file's module "
          "header for attribution/source (github.com/curtisseizert/CUDASieve, GPLv3, "
          "(C) Curtis Seizert) -- NOT linked into this process.")
    print("=" * 70)

    # CONSTELLATION_PORTAL_DIR -- same override convention as every other engine in this
    # folder (see prime_sieve_primesieve.py's own __main__ block).
    env_override = os.environ.get("CONSTELLATION_PORTAL_DIR")
    if env_override:
        BASE_STORAGE_10PN = env_override
    elif os.name == "nt":
        BASE_STORAGE_10PN = r"C:\CONSTELLATION_PORTAL"
    else:
        BASE_STORAGE_10PN = "/mnt/c/CONSTELLATION_PORTAL"
    print(f"[*] Windows written to: {BASE_STORAGE_10PN}\\10p{{N}}\\source_primes\\")

    # CLI: <base_exponent> <target_idx_start> <target_idx_count> <window_m> [write_files 0/1]
    # -- identical positional contract to prime_sieve_primesieve.py's __main__ block, so
    # the GUI/orchestrator side can dispatch to either engine with the same argv shape.
    if len(sys.argv) > 4:
        base_exponent = int(sys.argv[1])
        target_idx_start = int(sys.argv[2])
        target_idx_count = int(sys.argv[3])
        window_m = int(sys.argv[4])
    else:
        base_exponent = 13
        target_idx_start = 0
        target_idx_count = 1
        window_m = 10 ** 7

    write_files = True
    if len(sys.argv) > 5:
        write_files = bool(int(sys.argv[5]))

    print("Start time:", datetime.datetime.now().strftime("%H:%M:%S"))
    generate_floor_windows(base_exponent, target_idx_start, target_idx_count, window_m,
                            write_files=write_files, portal_folder=BASE_STORAGE_10PN)
