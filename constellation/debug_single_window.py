"""
debug_single_window.py -- standalone, minimal diagnostic for isolating WHERE the
floor-25-scale crash (see constellation_finder_v1.py's own module docstring, and its
process_floor()/max_windows docstring) actually happens.

Reads exactly ONE window file, in COMPLETE isolation from the rest of process_floor()'s
own state -- no 545,000-entry shard walk, no WINDOW_INDEX.tsv, no pattern matching, no
peek into a neighboring window. Two outcomes:

  - If THIS crashes the WSL process too (same "Proces wsl.exe zakonczyl sie bez
    zapisania kodu wyjscia" signature), the problem is specific to this ONE file's own
    size/content -- worth inspecting that file directly (size, header, byte contents).
  - If it succeeds cleanly, the problem is something about the ACCUMULATED state from
    a full process_floor() run instead (e.g. holding the whole floor's 545,000-entry
    window list + WINDOW_INDEX.tsv cache in memory before ever touching a single
    window's actual content -- constellation_finder_v1.py's own DIAG lines already
    showed a real ~200MB jump during exactly that phase on floor 25).

Added 2026-09-13 after a real crash log pinpointed the death to somewhere between
"reading window 1" and that window's own per-step summary -- this script is the fast,
surgical follow-up: rather than waiting through another full 5000-window batch just to
retest the SAME single file, it tests just that file, in a few seconds.

Usage (run directly inside WSL):
    python3 debug_single_window.py <portal_folder> <base_exponent> <filename>

    portal_folder: the WSL-side path (e.g. /mnt/h/Goldbach)
    base_exponent: the floor number (e.g. 25)
    filename: exactly as printed in a constellation_finder_v1.py log line, e.g.
              PRIME_WINDOW_10p25_off_2345678901237987900M.bin -- this script finds it
              itself among the floor's shard_NNNNN subfolders (window_sharding.py), no
              need to work out which shard by hand.

Or from Windows, via wsl.exe (mirroring how the GUI itself launches constellation_
finder_v1.py):
    wsl.exe -e bash -c "python3 -u '/mnt/f/OneDrive/Desktop/AI Agent Ollama/primeAtlas/constellation/debug_single_window.py' /mnt/h/Goldbach 25 PRIME_WINDOW_10p25_off_2345678901237987900M.bin"

Prints size, header, and full-decode timing/counts, with process diagnostics (RSS,
open FDs) and an explicit fsync after every line, same reasoning as constellation_
finder_v1.py's own DIAG lines: if the WHOLE VM dies mid-run, a write() that already
returned inside the VM can still be sitting in a dirty page not yet physically synced
to the real Windows-side log file -- fsync forces that now, so as much as possible
survives on disk even if this script itself is what dies.
"""
import sys
import os
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "..", "prime_sieve"))
import prime_sieve_v1  # noqa: E402
import window_sharding  # noqa: E402

try:
    import resource  # POSIX-only -- see constellation_finder_v1.py's own import guard
except ImportError:
    resource = None


def _diag():
    if resource is None:
        return "rss=n/a open_fds=n/a (non-POSIX)"
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    try:
        open_fds = len(os.listdir("/proc/self/fd"))
    except OSError:
        open_fds = -1
    return f"rss={rss_mb:.1f}MB open_fds={open_fds}"


def _log(msg):
    print(f"[DEBUG_SINGLE_WINDOW] {msg} | {_diag()}")
    try:
        sys.stdout.flush()
        os.fsync(sys.stdout.fileno())
    except OSError:
        pass  # best-effort -- must never crash the probe over a diagnostic nicety


def main():
    if len(sys.argv) != 4:
        print("Usage: python3 debug_single_window.py <portal_folder> <base_exponent> <filename>")
        return 1
    portal_folder, base_exponent, filename = sys.argv[1], sys.argv[2], sys.argv[3]
    _log(f"start -- portal={portal_folder!r} floor=10^{base_exponent} filename={filename!r}")

    source_dir = os.path.join(portal_folder, f"10p{base_exponent}", "source_primes")
    t_find0 = time.time()
    path = None
    for _shard_name, shard_path in window_sharding.iter_shard_dirs(source_dir):
        candidate = os.path.join(shard_path, filename)
        if os.path.exists(candidate):
            path = candidate
            break
    _log(f"shard search done in {time.time()-t_find0:.2f}s")

    if path is None:
        _log(f"FILE NOT FOUND under {source_dir} (searched every shard_NNNNN subfolder)")
        return 1
    _log(f"found at {path!r}")

    size_bytes = os.path.getsize(path)
    _log(f"file size={size_bytes:,} bytes")

    t0 = time.time()
    header = prime_sieve_v1.read_prime_window_header(path)
    _log(f"header read in {time.time()-t0:.3f}s: {header}")

    t1 = time.time()
    primes = prime_sieve_v1.read_prime_window(path)
    _log(f"full decode done in {time.time()-t1:.3f}s: {len(primes):,} primes decoded, "
         f"first={primes[0] if primes else None}, last={primes[-1] if primes else None}")

    _log("SUCCESS -- this file decoded cleanly in complete isolation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
