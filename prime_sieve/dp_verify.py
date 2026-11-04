"""
dp_verify.py -- a D window proves or refutes the P window of the same offset.

A P window (pt1's BPSW output, see storage_kinds.py) is a probable prime list; once a D
window exists for the same offset, the two are compared:

  - equal: the P file is removed and the D window is listed as D/P in
    10p{N}/DP_PROVEN.txt (storage_kinds.py): the range is proven by D and still counts
    as present in the P store;
  - different: both files stay, an ERROR line names the window and the smallest number
    that is in only one of the two lists, and the window is listed in
    10p{N}/DP_MISMATCH.txt, and a D/P entry of the window is dropped. A difference is a
    BPSW counterexample or a bug in one of the engines, so it is never resolved
    automatically.

A later equal comparison of a listed window removes its line. The comparison is
idempotent: a run interrupted between writing D and removing P redoes it next time.

Two PGS2 files hold the same primes exactly when their bytes agree outside the 4-byte
generation timestamp, so the common case compares bytes; only a mismatch decodes the gap
streams. A batch compares its windows in a thread pool (every comparison only reads) and
then writes DP_PROVEN.txt and DP_MISMATCH.txt once, before it removes the proven P files:
rewriting the lists per window costs time quadratic in the floor's window count. Pure
Python: orchestrator_v3.py calls reconcile_many() after each batch and the Storage tab's
"Verify P against D" calls verify_floor().
"""
import os
import time
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import prime_sieve_v1
import storage_kinds
import window_sharding

MISMATCH_FILENAME = "DP_MISMATCH.txt"
PROGRESS_PREFIX = "[*] D proves P:"
# Threads comparing windows: each comparison waits on two file reads (WSL /mnt latency),
# so they overlap well past the core count; 8 matches the v6 writer's default (arbitrary).
DEFAULT_WORKERS = 8
_PROGRESS_SECONDS = 2.0

Result = namedtuple("Result", "status first_difference")
# status: "equal", "mismatch", "no_d" (P without D), "no_p" (D without P)


def counterpart_p_path(d_path):
    shard_dir, name = os.path.split(d_path)
    shard = os.path.basename(shard_dir)
    floor_dir = os.path.dirname(os.path.dirname(shard_dir))
    p_name = name[:-len(".bin")] + "_P.bin"
    return os.path.join(floor_dir, storage_kinds.SOURCE_DIRNAMES[storage_kinds.KIND_P], shard, p_name)


def counterpart_d_path(p_path):
    shard_dir, name = os.path.split(p_path)
    shard = os.path.basename(shard_dir)
    floor_dir = os.path.dirname(os.path.dirname(shard_dir))
    d_name = name[:-len("_P.bin")] + ".bin"
    return os.path.join(floor_dir, storage_kinds.SOURCE_DIRNAMES[storage_kinds.KIND_D], shard, d_name)


def _without_timestamp(data):
    """PGS2 bytes with generated_at cut out (magic, 1-byte base length L, L base bytes,
    4-byte count, 4-byte generated_at, gap stream)."""
    at = 4 + 1 + data[4] + 4
    return data[:at] + data[at + 4:]


def _first_difference(d_path, p_path):
    """Smallest number present in exactly one of the two windows (None if none)."""
    d = prime_sieve_v1.read_prime_window(d_path)
    p = prime_sieve_v1.read_prime_window(p_path)
    i = j = 0
    while i < len(d) and j < len(p):
        if d[i] == p[j]:
            i += 1
            j += 1
        else:
            return min(d[i], p[j])
    if i < len(d):
        return d[i]
    if j < len(p):
        return p[j]
    return None


def _window_tag(path):
    return storage_kinds.window_tag(os.path.basename(path))


def _mismatch_path(portal_folder, base_exponent):
    return os.path.join(portal_folder, f"10p{base_exponent}", MISMATCH_FILENAME)


def _read_mismatch_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [line for line in f.read().splitlines() if line.strip()]


def _write_mismatch_lines(path, lines):
    if not lines:
        if os.path.exists(path):
            os.remove(path)
        return
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def _compare(p_path):
    """(status, tag, mismatch) of the P window at p_path against its D counterpart, where
    mismatch is (first difference, D count, P count) for a differing pair; reads only, so
    comparisons of different windows run in parallel."""
    p_data = _read(p_path)
    if p_data is None:
        return "no_p", None, None
    d_path = counterpart_d_path(p_path)
    d_data = _read(d_path)
    if d_data is None:
        return "no_d", None, None
    tag = _window_tag(p_path)
    if _without_timestamp(d_data) == _without_timestamp(p_data):
        return "equal", tag, None
    return "mismatch", tag, (_first_difference(d_path, p_path),
                             prime_sieve_v1.read_prime_window_header(d_path)["count"],
                             prime_sieve_v1.read_prime_window_header(p_path)["count"])


def _apply(portal_folder, base_exponent, outcomes):
    """Writes the outcomes [((status, tag, mismatch), p_path), ...] of a batch: each list
    once, then the proven P files removed, so an interruption leaves at worst a P window
    that is compared again."""
    equal = [(tag, p) for (status, tag, _m), p in outcomes if status == "equal"]
    mismatches = [(tag, m) for (status, tag, m), _p in outcomes if status == "mismatch"]
    if not equal and not mismatches:
        return
    new_lines = []
    for tag, (first, d_count, p_count) in mismatches:
        print(f"[ERROR] D/P mismatch in {tag}: first differing number {first} "
              f"(D {d_count} primes, P {p_count}); both files kept, listed in "
              f"10p{base_exponent}/{MISMATCH_FILENAME}")
        new_lines.append(f"{tag} first_difference={first} d_count={d_count} p_count={p_count}")
    proven = {tag for tag, _p in equal}
    refuted = {tag for tag, _m in mismatches}
    storage_kinds.update_proven_tags(portal_folder, base_exponent, add=proven, discard=refuted)
    path = _mismatch_path(portal_folder, base_exponent)
    kept = [ln for ln in _read_mismatch_lines(path) if ln.split(" ", 1)[0] not in proven | refuted]
    _write_mismatch_lines(path, kept + new_lines)
    for _tag, p_path in equal:
        os.remove(p_path)


def reconcile(portal_folder, base_exponent, p_path):
    """Compares the P window at p_path with its D counterpart (see the module docstring)."""
    outcome = _compare(p_path)
    _apply(portal_folder, base_exponent, [(outcome, p_path)])
    status, _tag, mismatch = outcome
    return Result(status, mismatch[0] if mismatch else None)


def reconcile_d(portal_folder, base_exponent, d_path):
    """reconcile() for a freshly written D window; "no_p" when it has no P counterpart."""
    return reconcile(portal_folder, base_exponent, counterpart_p_path(d_path))


def reconcile_many(portal_folder, base_exponent, p_paths, workers=DEFAULT_WORKERS,
                   progress=print):
    """reconcile() over every path of p_paths, compared by `workers` threads (each pair is
    two file reads, latency-bound on WSL's /mnt drives); DP_PROVEN.txt and
    DP_MISMATCH.txt are written once for the whole batch. Progress lines go to `progress`
    (None: silent). Returns {status: count}."""
    p_paths = list(p_paths)
    outcomes = [None] * len(p_paths)
    total = len(p_paths)
    t_start = last = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(_compare, p): i for i, p in enumerate(p_paths)}
        for done, future in enumerate(as_completed(futures), 1):
            outcomes[futures[future]] = future.result()
            now = time.perf_counter()
            if progress is not None and (done == total or now - last >= _PROGRESS_SECONDS):
                last = now
                progress(f"{PROGRESS_PREFIX} {done}/{total} ({100 * done / total:.1f}%) | "
                         f"time: {now - t_start:.1f}s")
    _apply(portal_folder, base_exponent, list(zip(outcomes, p_paths)))
    summary = {}
    for status, _tag, _line in outcomes:
        summary[status] = summary.get(status, 0) + 1
    return summary


def verify_floor(portal_folder, base_exponent, workers=DEFAULT_WORKERS, progress=None):
    """reconcile_many() over every P window of the floor; {status: count} of the outcomes."""
    p_dir = storage_kinds.source_dir(portal_folder, base_exponent, storage_kinds.KIND_P)
    paths = [path for _name, path in window_sharding.list_sharded_files(
        p_dir, predicate=lambda n: storage_kinds.is_window_name(n, storage_kinds.KIND_P))]
    return reconcile_many(portal_folder, base_exponent, paths, workers, progress)
