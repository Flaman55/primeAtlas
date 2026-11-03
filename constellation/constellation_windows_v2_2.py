"""
constellation_windows_v2_2.py -- the source windows of a floor: the cached WINDOW_INDEX.tsv
(filename -> base_prime), the base_prime-ordered window list, and the list of floors that
have any source window at all.
"""
import os
import time

import constellation_dynamic_v2_2 as _dyn  # first: puts ../prime_sieve on sys.path
import constellation_const_v2_2 as _const
import prime_sieve_v1  # noqa: E402
import window_sharding  # noqa: E402
from constellation_diag_v2_2 import _proc_diag  # noqa: E402


def _window_index_path(base_exponent):
    folder = os.path.join(_dyn.PORTAL_FOLDER, f"10p{base_exponent}", "constellations")
    return os.path.join(folder, _const.WINDOW_INDEX_FILENAME)


def _read_window_index(base_exponent):
    """Returns {filename: base_prime_or_None} from the cached per-floor window index (see
    list_source_windows()'s docstring), or {} if no index exists yet."""
    path = _window_index_path(base_exponent)
    if not os.path.exists(path):
        return {}
    index = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            name, _, base_prime_str = line.partition("\t")
            index[name] = int(base_prime_str) if base_prime_str else None
    return index


def _write_window_index(base_exponent, index):
    path = _window_index_path(base_exponent)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        for name, base_prime in index.items():
            f.write(f"{name}\t{'' if base_prime is None else base_prime}\n")
    os.replace(tmp_path, path)


def list_source_windows(base_exponent):
    """Returns [(filename, path, base_prime), ...] for every PRIME_WINDOW_*.bin under
    10p{base_exponent}/source_primes/, ordered ascending by base_prime (from each file's
    header -- robust regardless of filename shorthand).

    SHARDING: source_primes/ is sharded into shard_NNNNN subfolders (see
    window_sharding.py): WSL's filesystem interop with the Windows-side mount degrades
    badly (the process dies silently, no Python traceback) once a directory holds
    roughly 100k entries. window_sharding.list_sharded_files() walks each shard
    subfolder (at most SHARD_SIZE entries each) instead of listing source_dir directly.

    WINDOW_INDEX.tsv cache: sorting needs every window's base_prime, which otherwise
    means opening every source window's header on every call -- hundreds of thousands
    of file opens on a large floor before any matching starts. Source windows are
    written once and never rewritten (unlike hit files), so a filename's base_prime is
    cached indefinitely: a call only reads the headers of files new since the index was
    last written and drops entries whose file is gone, making the per-call cost
    O(files added since last run)."""
    t0 = time.time()
    source_dir = os.path.join(_dyn.PORTAL_FOLDER, f"10p{base_exponent}", "source_primes")
    sharded_files = window_sharding.list_sharded_files(
        source_dir,
        predicate=lambda name: name.startswith("PRIME_WINDOW_") and name.endswith(".bin"))
    if not sharded_files:
        return []
    paths_by_name = dict(sharded_files)
    names_on_disk = sorted(paths_by_name.keys())
    if _const.CONSTELLATION_DIAG_ENABLED:
        print(f"[CONSTELLATIONS v2] DIAG: shard walk found {len(names_on_disk):,} window(s) "
              f"for 10^{base_exponent} in {time.time()-t0:.2f}s | {_proc_diag()}")

    names_on_disk_set = set(names_on_disk)
    index = {name: base_prime for name, base_prime in _read_window_index(base_exponent).items()
              if name in names_on_disk_set}
    new_names = [name for name in names_on_disk if name not in index]
    if new_names:
        t1 = time.time()
        for name in new_names:
            header = prime_sieve_v1.read_prime_window_header(paths_by_name[name])
            index[name] = header["base_prime"]
        _write_window_index(base_exponent, index)
        if _const.CONSTELLATION_DIAG_ENABLED:
            print(f"[CONSTELLATIONS v2] DIAG: read {len(new_names):,} fresh header(s) "
                  f"({len(names_on_disk) - len(new_names):,} served from WINDOW_INDEX.tsv "
                  f"cache) in {time.time()-t1:.2f}s | {_proc_diag()}")

    entries = [(name, paths_by_name[name], index[name]) for name in names_on_disk]
    entries.sort(key=lambda e: (e[2] is None, e[2] if e[2] is not None else 0, e[0]))
    if _const.CONSTELLATION_DIAG_ENABLED:
        print(f"[CONSTELLATIONS v2] DIAG: list_source_windows(10^{base_exponent}) done in "
              f"{time.time()-t0:.2f}s total | {_proc_diag()}")
    return entries


def list_floors_with_data():
    """Returns sorted base_exponent ints for every 10p{N} folder under _dyn.PORTAL_FOLDER that
    actually has at least one PGS2 source window. Floor folders can exist as empty
    source_primes/constellations placeholders ahead of the scanner actually reaching
    them, so folder presence alone doesn't mean there's anything to process.

    A cheap directory-listing existence check, NOT a call into list_source_windows():
    on a floor not indexed yet that would read every window header, a cost
    process_floor() already pays once.

    source_primes/ directly contains only shard_NNNNN subfolders (see
    window_sharding.py), so "has_window" is checked one level down, inside the first
    existing shard subfolder (any floor with data has a non-empty shard_00000) -- a
    bounded listdir, not a full window_sharding.list_sharded_files() walk."""
    if not os.path.isdir(_dyn.PORTAL_FOLDER):
        return []
    result = []
    for name in os.listdir(_dyn.PORTAL_FOLDER):
        if name.startswith("10p") and name[3:].isdigit():
            base_exponent = int(name[3:])
            source_dir = os.path.join(_dyn.PORTAL_FOLDER, name, "source_primes")
            if not os.path.isdir(source_dir):
                continue
            has_window = False
            for _shard_name, shard_path in window_sharding.iter_shard_dirs(source_dir):
                if any(fn.startswith("PRIME_WINDOW_") and fn.endswith(".bin")
                       for fn in os.listdir(shard_path)):
                    has_window = True
                    break
            if has_window:
                result.append(base_exponent)
    return sorted(result)
