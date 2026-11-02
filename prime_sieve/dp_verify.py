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
streams. Pure Python: orchestrator_v3.py calls reconcile_d() after each batch and the
Storage tab's "Verify P against D" calls verify_floor().
"""
import os
from collections import namedtuple

import prime_sieve_v1
import storage_kinds
import window_sharding

MISMATCH_FILENAME = "DP_MISMATCH.txt"

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


def _update_mismatch_list(portal_folder, base_exponent, tag, line):
    """Drops tag's line from DP_MISMATCH.txt, then adds `line` when it is not None."""
    path = _mismatch_path(portal_folder, base_exponent)
    lines = [ln for ln in _read_mismatch_lines(path) if ln.split(" ", 1)[0] != tag]
    if line is not None:
        lines.append(line)
    _write_mismatch_lines(path, lines)


def reconcile(portal_folder, base_exponent, p_path):
    """Compares the P window at p_path with its D counterpart (see the module docstring)."""
    d_path = counterpart_d_path(p_path)
    if not os.path.exists(p_path):
        return Result("no_p", None)
    if not os.path.exists(d_path):
        return Result("no_d", None)
    with open(d_path, "rb") as f:
        d_data = f.read()
    with open(p_path, "rb") as f:
        p_data = f.read()
    tag = _window_tag(p_path)
    if _without_timestamp(d_data) == _without_timestamp(p_data):
        storage_kinds.add_proven_tags(portal_folder, base_exponent, {tag})
        os.remove(p_path)
        _update_mismatch_list(portal_folder, base_exponent, tag, None)
        return Result("equal", None)
    first = _first_difference(d_path, p_path)
    d_count = prime_sieve_v1.read_prime_window_header(d_path)["count"]
    p_count = prime_sieve_v1.read_prime_window_header(p_path)["count"]
    line = f"{tag} first_difference={first} d_count={d_count} p_count={p_count}"
    print(f"[ERROR] D/P mismatch in {tag}: first differing number {first} "
          f"(D {d_count} primes, P {p_count}); both files kept, listed in "
          f"10p{base_exponent}/{MISMATCH_FILENAME}")
    _update_mismatch_list(portal_folder, base_exponent, tag, line)
    storage_kinds.discard_proven_tag(portal_folder, base_exponent, tag)
    return Result("mismatch", first)


def reconcile_d(portal_folder, base_exponent, d_path):
    """reconcile() for a freshly written D window; "no_p" when it has no P counterpart."""
    p_path = counterpart_p_path(d_path)
    if not os.path.exists(p_path):
        return Result("no_p", None)
    return reconcile(portal_folder, base_exponent, p_path)


def verify_floor(portal_folder, base_exponent):
    """reconcile() over every P window of the floor; {status: count} of the outcomes."""
    summary = {}
    p_dir = storage_kinds.source_dir(portal_folder, base_exponent, storage_kinds.KIND_P)
    for name, path in window_sharding.list_sharded_files(
            p_dir, predicate=lambda n: storage_kinds.is_window_name(n, storage_kinds.KIND_P)):
        status = reconcile(portal_folder, base_exponent, path).status
        summary[status] = summary.get(status, 0) + 1
    return summary
